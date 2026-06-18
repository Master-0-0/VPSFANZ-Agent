import asyncio
from typing import Callable, Optional

from .config import Config
from .llm import LLMClient
from .logging import get_logger
from .tasks import BootstrapTask, ExploreTask, ReasonTask, TaskResult
from ..graph.models import Project, ProjectStatus
from ..graph.store import ProjectStore

logger = get_logger("loop")


class Dispatcher:
    def __init__(self, config: Config, store: ProjectStore, llm: LLMClient):
        self.config = config
        self.store = store
        self.llm = llm
        self.bootstrap = BootstrapTask(config)
        self.reason = ReasonTask(config)
        self.explore = ExploreTask(config)
        self._reason_failures = 0
        self._max_reason_failures = 5

    async def run(
        self,
        project: Project,
        on_event: Optional[Callable] = None,
        step_mode: bool = False,
    ) -> Project:
        loop_count = 0
        max_loops = self.config.runtime.max_loops

        logger.info("Dispatcher started: origin=%s goal=%s max_loops=%d",
                    project.origin, project.goal, max_loops)

        while project.status == ProjectStatus.running and loop_count < max_loops:
            loop_count += 1
            project = self.store.get_project(project.id)

            if on_event:
                on_event("loop_start", {"loop": loop_count, "project": project})

            if step_mode:
                if on_event:
                    on_event("step_wait", {"loop": loop_count, "project": project})
                await asyncio.get_event_loop().run_in_executor(None, input, "  按 Enter 继续执行当前循环...")

            task_type = self._decide_task(project)
            logger.info("Loop #%d: task=%s facts=%d intents=%d open=%d",
                        loop_count, task_type, len(project.facts),
                        len(project.intents), len(project.open_intents))

            if on_event:
                on_event("task_decided", {"task": task_type, "project": project})

            # guard: reason 连续失败超过上限，强行注入通用 intent 打破死循环
            if task_type == "reason" and self._reason_failures >= self._max_reason_failures:
                logger.warning("Reason failed %d times consecutively, injecting fallback intents",
                               self._reason_failures)
                for desc in [
                    f"在主流搜索引擎中搜索 '{project.origin}' 的相关信息",
                    f"搜索 '{project.origin}' 在 GitHub、知乎等平台的关联账号",
                ]:
                    project.add_intent(description=desc)
                self._reason_failures = 0
                self.store.save_project(project)
                task_type = "explore"
                if on_event:
                    on_event("task_decided", {"task": task_type, "project": project})

            result = None
            try:
                if task_type == "bootstrap":
                    result = await self.bootstrap.execute(project, self.llm)
                elif task_type == "explore":
                    intent = project.open_intents[0] if project.open_intents else None
                    if intent:
                        result = await self.explore.execute(project, intent, self.llm)
                    else:
                        result = TaskResult("continue", "无开放意图")
                elif task_type == "reason":
                    result = await self.reason.execute(project, self.llm)
            except Exception as e:
                logger.exception("Task %s failed", task_type)
                result = TaskResult("continue", "任务异常: %s" % str(e))

            # track consecutive reason failures
            if task_type == "reason" and result and result.status == "continue":
                self._reason_failures += 1
            elif result and result.status == "continue" and result.message:
                # non-reason continue with a message -> likely a partial failure
                if task_type == "explore" and result.message:
                    self._reason_failures += 1
                else:
                    self._reason_failures = 0
            else:
                self._reason_failures = 0

            self.store.save_project(project)

            if on_event:
                on_event("task_result", {"task": task_type, "result": result, "project": project})

            if result and result.status == "complete":
                self.store.save_project(project)
                logger.info("Goal achieved: %s", result.message)
                if on_event:
                    on_event("complete", {"message": result.message, "project": project})
                break

        if loop_count >= max_loops:
            logger.warning("Max loops (%d) reached", max_loops)
            project.status = ProjectStatus.completed
            self.store.save_project(project)

        project = self.store.get_project(project.id)
        logger.info("Dispatcher finished: status=%s facts=%d intents=%d",
                    project.status.value, len(project.facts), len(project.intents))
        return project

    def _decide_task(self, project: Project) -> str:
        if not project.facts and not project.intents:
            return "bootstrap"
        if project.open_intents:
            return "explore"
        return "reason"
