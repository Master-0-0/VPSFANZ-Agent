import asyncio
import threading
from typing import Callable, Optional

import typer

from .dispatcher.config import Config
from .dispatcher.llm import LLMClient
from .dispatcher.logging import get_logger, setup_logging
from .dispatcher.loop import Dispatcher
from .graph.export import export_json, export_mermaid, export_yaml
from .graph.models import Project, ProjectStatus
from .graph.store import ProjectStore

logger = get_logger("cli")

app = typer.Typer(
    name="osint-agent",
    help="OSINT 情报查询 Agent — 基于 Fact-Intent Graph 的节点拓展引擎",
)


def _load_config(config_path: Optional[str]) -> Config:
    return Config.load(config_path) if config_path else Config.load()


def _get_store(config: Config) -> ProjectStore:
    return ProjectStore(db_path=config.store.db_path)


def _run_async(coro):
    """运行异步协程，附带 Windows overlapped 错误静音处理"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # 静默 ProactorEventLoop 关闭时的 "Cancelling an overlapped future failed"
    orig_handler = loop.get_exception_handler()
    def _handler(loop_, context):
        msg = context.get("message", "")
        exc = context.get("exception", None)
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 6:
            return
        if "Cancelling an overlapped future" in msg:
            return
        if orig_handler:
            orig_handler(loop_, context)
        else:
            loop_.default_exception_handler(context)
    loop.set_exception_handler(_handler)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_event_printer(
    interactive: bool,
    loop_count_ref: list,
    verbose: bool = False,
    publish_event: Optional[Callable] = None,
):
    def printer(event: str, data: dict):
        if publish_event:
            try:
                publish_event(event, data)
            except Exception:
                pass
        if event == "loop_start":
            loop_count_ref[0] = data["loop"]
            typer.echo("\n%s" % ("=" * 50))
            typer.echo("  OODA 循环 #%d" % data["loop"])
            typer.echo("%s" % ("=" * 50))
        elif event == "task_decided":
            task = data["task"]
            labels = {"bootstrap": "Bootstrap 初始分析", "reason": "Reason 进度评估", "explore": "Explore 探索执行"}
            typer.echo("  [%s]" % labels.get(task, task))
        elif event == "task_result":
            result = data.get("result")
            project = data.get("project")
            if result:
                if result.status == "complete":
                    typer.echo("  [完成] %s" % result.message)
                elif result.message:
                    typer.echo("  [!] %s" % result.message)
            if verbose:
                typer.echo("\n--- 详情 ---")
                typer.echo("  Facts: %d | Intents: %d (%d open) | Hints: %d" % (
                    len(project.facts), len(project.intents),
                    len(project.open_intents), len(project.hints),
                ))
                if project.facts:
                    last = project.facts[-1]
                    typer.echo("  最新 Fact [%s..]:" % last.id[:8])
                    for line in last.description.strip().split("\n"):
                        typer.echo("    | %s" % line)
            if interactive:
                typer.echo("\n--- 当前图状态 ---")
                typer.echo(project.graph_yaml())
                typer.echo("-------------------")
        elif event == "complete":
            typer.echo("\n[目标已达成]")
        elif event == "step_wait":
            typer.echo("\n--- 循环 #%d 暂停 (分步模式) ---" % data["loop"])
            typer.echo("  Facts: %d | Intents: %d (%d open)" % (
                len(data["project"].facts), len(data["project"].intents),
                len(data["project"].open_intents),
            ))

    return printer


@app.command()
def run(
    keyword: str = typer.Argument(..., help="搜索起点（关键词/人名/公司等）"),
    goal: str = typer.Option("", "--goal", "-g", help="情报目标"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider (deepseek/openai/ollama)"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="模型名称"),
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API Key"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="交互模式（每轮显示图状态）"),
    step: bool = typer.Option(False, "--step", "-s", help="分步模式（每轮暂停等待确认）"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
    web: bool = typer.Option(False, "--web", "-w", help="启动 Web UI"),
    port: int = typer.Option(8080, "--port", help="Web UI 端口（--web 时生效）"),
):
    """运行一次 OSINT 情报查询"""
    setup_logging(verbose=verbose)
    config = _load_config(config_path)

    if provider:
        config.llm.provider = provider
    if model:
        config.llm.model = model
    if api_key:
        config.llm.api_key = api_key

    base_url, resolved_key, resolved_model = config.resolve_llm_config()
    if not resolved_key:
        typer.echo("错误: 未设置 API Key。通过 --api-key、环境变量或 config.yaml 设置。")
        raise typer.Exit(1)

    project = Project(origin=keyword, goal=goal)
    store = _get_store(config)
    store.create_project(project)

    typer.echo("项目已创建: %s" % project.id)
    typer.echo("  起点: %s" % keyword)
    typer.echo("  目标: %s" % goal)
    typer.echo("  LLM:  %s / %s" % (config.llm.provider, resolved_model))
    typer.echo("  Verbose: %s" % verbose)
    if web:
        typer.echo("  Web UI: http://localhost:%d" % port)
    logger.info("Project created: id=%s provider=%s model=%s",
                project.id, config.llm.provider, resolved_model)

    llm = LLMClient(base_url=base_url, api_key=resolved_key, model=resolved_model)
    dispatcher = Dispatcher(config, store, llm)

    publish_event = None
    if web:
        try:
            from .server.app import app as web_app
            from .server.events import bus
            import uvicorn
            web_project_id = project.id
            def _publish(event, data):
                try:
                    bus.publish(web_project_id, event, data)
                except Exception:
                    pass
            publish_event = _publish
            server_thread = threading.Thread(
                target=uvicorn.run,
                args=(web_app,),
                kwargs={"host": "0.0.0.0", "port": port, "log_level": "info"},
                daemon=True,
            )
            server_thread.start()
        except ImportError:
            typer.echo("警告: 缺少 fastapi/uvicorn，请安装: pip install fastapi uvicorn")

    loop_count_ref = [0]
    try:
        project = _run_async(
            dispatcher.run(
                project,
                on_event=_make_event_printer(interactive, loop_count_ref, verbose, publish_event),
                step_mode=step,
            )
        )
    except KeyboardInterrupt:
        saved = store.get_project(project.id)
        if saved:
            saved.status = ProjectStatus.failed
            store.save_project(saved)
            project = saved
        else:
            project.status = ProjectStatus.failed
            store.save_project(project)
        typer.echo("\n用户中断，项目状态已保存。可通过以下命令继续：")
        typer.echo("  osint-agent resume %s" % project.id)
        return

    typer.echo("\n%s" % ("=" * 50))
    typer.echo("  项目完成: %s" % project.id)
    typer.echo("  状态: %s" % project.status.value)
    typer.echo("  Facts: %d" % len(project.facts))
    typer.echo("  Intents: %d (%d open)" % (len(project.intents), len(project.open_intents)))
    typer.echo("%s" % ("=" * 50))
    logger.info("Project done: id=%s status=%s facts=%d",
                project.id, project.status.value, len(project.facts))

    if web:
        typer.echo("\n服务器运行中: http://localhost:%d" % port)
        typer.echo("按 Enter 关闭服务器...")
        input()


@app.command()
def list_projects(
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """列出所有项目"""
    config = _load_config(config_path)
    store = _get_store(config)
    projects = store.list_projects()
    if not projects:
        typer.echo("暂无项目")
        return
    typer.echo("  %-14s %-10s %-20s -> %s" % ("ID", "状态", "起点", "目标"))
    typer.echo("  %s" % ("-" * 70))
    for p in projects:
        typer.echo("  %-14s %-10s %-20s -> %s" % (p.id[:12], p.status.value, p.origin[:18], p.goal[:40]))


@app.command()
def graph(
    project_id: str = typer.Argument(..., help="项目 ID"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """查看项目的图状态"""
    config = _load_config(config_path)
    store = _get_store(config)
    project = store.get_project(project_id)
    if project is None:
        typer.echo("项目不存在: %s" % project_id)
        raise typer.Exit(1)
    typer.echo("项目: %s" % project.id)
    typer.echo("起点: %s" % project.origin)
    typer.echo("目标: %s" % project.goal)
    typer.echo("状态: %s" % project.status.value)
    typer.echo("Facts: %d  Intents: %d  Hints: %d" % (
        len(project.facts), len(project.intents), len(project.hints)))
    typer.echo("")
    typer.echo(project.graph_yaml())
    if project.hints:
        typer.echo("\nhints:")
        for h in project.hints:
            typer.echo("  - %s" % h.content)


@app.command()
def hint(
    content: str = typer.Argument(..., help="提示内容"),
    project_id: str = typer.Option("", "--project-id", "-p", help="项目 ID"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """向项目中注入提示"""
    config = _load_config(config_path)
    store = _get_store(config)
    project = store.get_project(project_id)
    if project is None:
        typer.echo("项目不存在: %s" % project_id)
        raise typer.Exit(1)
    project.add_hint(content)
    store.save_project(project)
    typer.echo("Hint 已注入: %s" % content)
    logger.info("Hint injected: project=%s content=%s", project_id, content)


@app.command()
def resume(
    project_id: str = typer.Argument(..., help="项目 ID"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
    interactive: bool = typer.Option(False, "--interactive", "-i"),
    step: bool = typer.Option(False, "--step", "-s", help="分步模式"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
):
    """从之前保存的项目继续"""
    setup_logging(verbose=verbose)
    config = _load_config(config_path)
    store = _get_store(config)
    project = store.get_project(project_id)
    if project is None:
        typer.echo("项目不存在: %s" % project_id)
        raise typer.Exit(1)

    if project.status != ProjectStatus.running:
        typer.echo("项目已处于 %s 状态，无法继续" % project.status.value)
        return

    base_url, api_key, model = config.resolve_llm_config()
    if not api_key:
        typer.echo("错误: 未设置 API Key")
        raise typer.Exit(1)

    llm = LLMClient(base_url=base_url, api_key=api_key, model=model)
    dispatcher = Dispatcher(config, store, llm)

    typer.echo("继续项目: %s" % project.id)
    typer.echo("  起点: %s" % project.origin)
    typer.echo("  目标: %s" % project.goal)
    typer.echo("  Facts: %d" % len(project.facts))
    typer.echo("  Intents: %d" % len(project.intents))

    loop_count_ref = [0]
    try:
        project = _run_async(
            dispatcher.run(
                project,
                on_event=_make_event_printer(interactive, loop_count_ref, verbose),
                step_mode=step,
            )
        )
    except KeyboardInterrupt:
        saved = store.get_project(project.id)
        if saved:
            saved.status = ProjectStatus.failed
            store.save_project(saved)
        else:
            project.status = ProjectStatus.failed
            store.save_project(project)
        typer.echo("\n用户中断。")
        return

    typer.echo("\n%s" % ("=" * 50))
    typer.echo("  项目完成: %s" % project.id)
    typer.echo("  状态: %s" % project.status.value)
    typer.echo("  Facts: %d" % len(project.facts))
    typer.echo("  Intents: %d (%d open)" % (len(project.intents), len(project.open_intents)))
    typer.echo("%s" % ("=" * 50))


@app.command()
def export(
    project_id: str = typer.Argument(..., help="项目 ID"),
    fmt: str = typer.Option("yaml", "--format", "-f", help="导出格式: json / yaml / mermaid"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="输出文件路径（默认输出到终端）"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """导出项目的图数据"""
    config = _load_config(config_path)
    store = _get_store(config)
    project = store.get_project(project_id)
    if project is None:
        typer.echo("项目不存在: %s" % project_id)
        raise typer.Exit(1)

    if fmt == "json":
        content = export_json(project)
    elif fmt == "mermaid":
        content = export_mermaid(project)
    else:
        content = export_yaml(project)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(content)
        typer.echo("已导出到: %s" % output)
        logger.info("Exported project %s to %s (format=%s)", project_id, output, fmt)
    else:
        typer.echo(content)


@app.command()
def show_config(
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
):
    """查看当前配置"""
    cfg = _load_config(config_path)
    typer.echo(cfg.model_dump_json(indent=2))


@app.command()
def delete(
    project_id: str = typer.Argument(..., help="项目 ID"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c"),
    force: bool = typer.Option(False, "--force", "-f", help="确认删除"),
):
    """删除指定的项目"""
    if not force:
        typer.echo("使用 --force 确认删除")
        return
    config = _load_config(config_path)
    store = _get_store(config)
    project = store.get_project(project_id)
    if project is None:
        typer.echo("项目不存在: %s" % project_id)
        raise typer.Exit(1)
    store.delete_project(project_id)
    typer.echo("项目已删除: %s" % project_id)
    logger.info("Deleted project: %s", project_id)


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", help="Web UI 端口"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="配置文件路径"),
):
    """启动 Web UI（无需运行 agent，查看已有项目）"""
    setup_logging(verbose=False)
    typer.echo("启动 Web UI: http://localhost:%d" % port)
    typer.echo("按 Ctrl+C 停止")
    try:
        from .server.app import app as web_app
        import uvicorn
        uvicorn.run(web_app, host="0.0.0.0", port=port, log_level="info")
    except ImportError:
        typer.echo("错误: 请先安装依赖: pip install fastapi uvicorn")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
