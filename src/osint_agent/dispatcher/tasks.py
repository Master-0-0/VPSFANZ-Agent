import logging
import re
from typing import List, Optional

from .config import Config
from .llm import LLMClient
from .prompting import get_prompt
from ..graph.models import Intent, Project, ProjectStatus
from ..tools.registry import call_tool, list_tools_prompt

logger = logging.getLogger("osint_agent.tasks")


def build_task_vars(project: Project, task_type: str, **extra) -> dict:
    hints_text = "\n".join("- %s" % h.content for h in project.hints) if project.hints else "无"
    facts_text = "\n".join("  - [%s] %s" % (f.id[:8], f.description) for f in project.facts) if project.facts else "  - 暂无"

    open_intents_text = "\n".join(
        "  - [%s] %s" % (i.id[:8], i.description) for i in project.open_intents
    ) if project.open_intents else "  - 无开放意图"

    tools_text = list_tools_prompt() if task_type in ("explore", "reason") else ""

    vars_dict = {
        "origin": project.origin,
        "goal": project.goal,
        "hints": hints_text,
        "facts": facts_text,
        "open_intents": open_intents_text,
        "graph_yaml": project.graph_yaml(),
        "max_intents": "3",
        "tools": tools_text,
    }
    vars_dict.update(extra)
    return vars_dict


class TaskResult:
    def __init__(self, status: str, message: str = ""):
        self.status = status
        self.message = message


def _split_prompt(prompt: str):
    lines = prompt.split("\n", 1)
    if len(lines) >= 2:
        return lines[0].strip(), lines[1].strip()
    return prompt, prompt


class BootstrapTask:
    def __init__(self, config: Config):
        self.config = config

    async def execute(self, project: Project, llm: LLMClient) -> TaskResult:
        vars_dict = build_task_vars(project, "bootstrap")
        prompt = get_prompt("bootstrap", vars_dict, self.config.runtime.prompt_group)

        if prompt is None:
            system_prompt = "你是一个 OSINT 情报分析专家。请根据起点和目标提供初始分析。"
            user_prompt = "起点: %s\n目标: %s\n用户提示: %s" % (project.origin, project.goal, vars_dict["hints"])
        else:
            system_prompt, user_prompt = _split_prompt(prompt)

        result = llm.send_json(system_prompt, user_prompt)
        return _handle_result(project, result, "bootstrap")


class ReasonTask:
    def __init__(self, config: Config):
        self.config = config

    async def execute(self, project: Project, llm: LLMClient) -> TaskResult:
        max_intents = self.config.tasks.reason.max_intents
        vars_dict = build_task_vars(project, "reason", max_intents=str(max_intents))
        prompt = get_prompt("reason", vars_dict, self.config.runtime.prompt_group)

        if prompt is None:
            system_prompt = "你是一个 OSINT 情报分析专家。请阅读图状态并判断进度。"
            user_prompt = "起点: %s\n目标: %s\n\n当前图状态:\n%s\n用户提示:\n%s" % (
                project.origin, project.goal, project.graph_yaml(), vars_dict["hints"],
            )
        else:
            system_prompt, user_prompt = _split_prompt(prompt)

        result = llm.send_json(system_prompt, user_prompt)
        return _handle_result(project, result, "reason")


class ExploreTask:
    def __init__(self, config: Config):
        self.config = config

    async def execute(self, project: Project, intent: Intent, llm: LLMClient) -> TaskResult:
        project.claim_intent(intent.id)

        vars_dict = build_task_vars(
            project, "explore",
            intent_description=intent.description,
            intent_id=intent.id,
        )
        prompt = get_prompt("explore", vars_dict, self.config.runtime.prompt_group)

        tool_context = await self._execute_auto_tools(intent.description, llm)

        if prompt is None:
            system_prompt = "你是一个 OSINT 情报分析专家，可以综合分析情报。"
            user_prompt = "起点: %s\n目标: %s\n\n当前图:\n%s\n\n探索方向: %s\n\n%s\n\n%s" % (
                project.origin, project.goal, project.graph_yaml(),
                intent.description, vars_dict["tools"], tool_context,
            )
        else:
            system_prompt, user_prompt = _split_prompt(prompt)
            user_prompt += "\n\n" + tool_context

        result = llm.send_json(system_prompt, user_prompt)
        result = await self._handle_tool_calls(result, llm, system_prompt, user_prompt)
        return _handle_result(project, result, "explore", intent)

    async def _execute_auto_tools(self, intent_description: str, llm: LLMClient) -> str:
        parts = []

        keywords_list = self._generate_search_keywords(intent_description, llm)
        search_query = keywords_list[0] if keywords_list else intent_description

        logger.info("=== Bing 搜索调用 ===")
        logger.info("  Intent: %s", intent_description)
        logger.info("  关键词: %s", search_query)

        sr = call_tool("web_search", {"query": search_query, "num_results": 8})
        results_data = sr.get("result", sr)
        parts.append("## 自动搜索: %s" % search_query)
        results_list = results_data.get("results", []) if isinstance(results_data, dict) else []
        for i, r in enumerate(results_list, 1):
            parts.append("  [%d] %s" % (i, r.get("title", "")))
            parts.append("      URL: %s" % r.get("url", ""))
            parts.append("      摘要: %s" % r.get("snippet", ""))
        if not results_list:
            parts.append("  (无搜索结果)")
        return "\n".join(parts)

    @staticmethod
    def _generate_search_keywords(intent_description: str, llm: LLMClient) -> List[str]:
        """调用 LLM 将 intent 描述转换为搜索引擎友好的关键词"""
        system_prompt = (
            "你是一个搜索关键词提取专家。"
            "将下面的调查目标转化为搜索引擎友好的关键词查询。\n"
            "要求：\n"
            "- 提取关键实体词（域名、IP、人名、代号、平台名等），去除中文虚词和解释性文字\n"
            "- 多个关键词用空格分隔\n"
            "- 需要精确匹配的词用双引号括起来，例如 \"abc123\"\n"
            "- **必须保留所有具体的域名、IP 地址、用户名、邮箱等标识符**\n"
            "- **禁止将具体标识符替换为通用词汇**（如将 120.27.154.229 替换为 服务器IP）\n"
            "- 如果 Intent 中出现了具体域名或 IP，它必须作为精确匹配引号词出现在关键词中\n"
            "- 输出最多3条不同的关键词组合，每行一条\n"
            "- 不要输出任何其他内容，只输出关键词行"
        )
        content = llm.send(system_prompt, intent_description, max_tokens=512)
        if content:
            lines = [l.strip() for l in content.strip().split('\n') if l.strip()]
            lines = [re.sub(r'^[\d\.\-\*\s]+', '', l) for l in lines]
            lines = [l for l in lines if l]
            if lines:
                return lines[:3]
        return [intent_description]

    async def _handle_tool_calls(
        self, result: Optional[dict], llm: LLMClient,
        system_prompt: str, user_prompt: str,
    ) -> Optional[dict]:
        if result is None:
            return result

        data = result.get("data", {}) or {}
        tool_calls = data.get("tool_calls")
        if not tool_calls:
            return result

        tool_results = []
        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            params = tc.get("params", {})
            tr = call_tool(tool_name, params)
            tool_results.append({
                "tool": tool_name,
                "params": params,
                "result": tr,
            })

        tool_context = "\n\n===== 工具调用结果 =====\n"
        for tr in tool_results:
            tool_context += "工具: %s\n参数: %s\n结果: %s\n\n" % (
                tr["tool"], tr["params"], tr["result"],
            )
        tool_context += "请基于以上工具结果，给出最终的情报发现。"

        user_prompt_with_tools = user_prompt + tool_context
        final_result = llm.send_json(system_prompt, user_prompt_with_tools)
        if final_result:
            return final_result

        data["description"] = data.get("description") or str(tool_results)
        return result


def _handle_result(project: Project, result: Optional[dict], task_type: str, intent: Intent = None) -> TaskResult:
    if result is None:
        msg = "LLM 返回格式错误"
        if intent:
            project.fail_intent(intent.id)
        return TaskResult("continue", msg)

    if not result.get("accepted"):
        reason = result.get("reason", "未知原因")
        if intent:
            project.fail_intent(intent.id)
        return TaskResult("continue", reason)

    data = result.get("data", {}) or {}

    if data.get("complete"):
        project.status = ProjectStatus.completed
        return TaskResult("complete", data["complete"].get("description", ""))

    if task_type == "explore" and data.get("description"):
        project.add_fact(
            description=data["description"],
            source="explore:%s" % intent.id if intent else "explore",
        )
        if intent:
            project.complete_intent(intent.id)

    if task_type in ("bootstrap", "reason") and data.get("facts"):
        for f_data in data["facts"]:
            project.add_fact(
                description=f_data["description"],
                source=task_type,
            )

    if data.get("intents"):
        for i_data in data["intents"]:
            project.add_intent(description=i_data["description"])

    return TaskResult("continue", "")
