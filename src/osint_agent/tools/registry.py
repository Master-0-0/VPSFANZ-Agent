from typing import Callable, Dict, Optional

TOOL_REGISTRY: Dict[str, dict] = {}


def tool(name: str, description: str):
    def decorator(fn: Callable) -> Callable:
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "fn": fn,
        }
        return fn
    return decorator


def list_tools() -> list:
    result = []
    for name, entry in TOOL_REGISTRY.items():
        result.append({"name": name, "description": entry["description"]})
    return result


def list_tools_prompt() -> str:
    lines = ["可用工具:"]
    for name, entry in TOOL_REGISTRY.items():
        lines.append("  - %s: %s" % (name, entry["description"]))
    lines.append(
        '调用格式: {"tool": "工具名", "params": {"参数名": "值"}}'
    )
    return "\n".join(lines)


def call_tool(name: str, params: Optional[Dict] = None) -> dict:
    if params is None:
        params = {}
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return {"error": "未知工具: %s" % name}
    try:
        result = entry["fn"](**params)
        return {"success": True, "result": result}
    except Exception as e:
        return {"error": str(e)}


import osint_agent.tools.web_search  # noqa
