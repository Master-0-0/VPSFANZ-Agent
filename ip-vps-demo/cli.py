"""
IP/VPS 溯源工具集 — 命令行入口
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from orchestrator import (
    extract_report_info,
    get_reports_dir,
    print_extracted_info,
    print_trace_report,
    run_full_trace,
)
from threatbook_tool import load_auth_credentials, oauth_login_playwright

load_dotenv()

app = typer.Typer(
    name="ipvps",
    help="IP/VPS 溯源工具集 — 基础信息收集 + 云厂商识别",
    no_args_is_help=True,
)
auth_app = typer.Typer(help="微步认证管理")
report_app = typer.Typer(help="报告管理")
app.add_typer(auth_app, name="auth")
app.add_typer(report_app, name="report")


def _save_report(result: dict, no_save: bool = False) -> Optional[str]:
    if no_save:
        return None
    reports_dir = get_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_safe = result.get("target", "unknown").replace(".", "_")
    path = reports_dir / f"trace_{target_safe}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(path)


@app.command()
def trace(
    target: str = typer.Argument(..., help="目标 IP 地址或域名"),
    phase: int = typer.Option(0, "--phase", "-p", help="仅显示指定阶段: 1=基础信息, 2=云平台"),
    json_output: bool = typer.Option(False, "--json", "-j", help="以 JSON 格式输出"),
    no_save: bool = typer.Option(False, "--no-save", help="不保存报告文件"),
):
    """执行 IP/VPS 完整溯源流程"""
    result = run_full_trace(target)

    if "error" in result:
        typer.echo(f"错误: {result['error']}", err=True)
        raise typer.Exit(1)

    if phase == 1:
        result["phases"] = [result["phases"][0]]
    elif phase == 2:
        if len(result["phases"]) >= 2:
            result["phases"] = [result["phases"][1]]
        else:
            typer.echo("错误: 缺少阶段1数据，无法单独显示阶段2", err=True)
            raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_trace_report(result)

    report_path = _save_report(result, no_save)
    if report_path:
        typer.echo(f"  [REPORT] 报告已保存: {report_path}")

        info = extract_report_info(result)
        extracted_path = report_path.replace(".json", "_extracted.json")
        with open(extracted_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)


@auth_app.command()
def login(
    timeout: int = typer.Option(300, "--timeout", "-t", help="扫码等待超时秒数"),
):
    """OAuth 扫码登录微步在线"""
    auth_result = oauth_login_playwright(headless=False, timeout=timeout)
    if auth_result.get("success"):
        typer.echo("登录成功！认证信息已保存")
    else:
        typer.echo(f"登录失败: {auth_result.get('error', '未知错误')}", err=True)
        raise typer.Exit(1)


@auth_app.command()
def status():
    """查看所有 API 认证状态"""
    typer.echo()
    typer.echo("  -- API 认证状态 --")

    for key in ["HUNTER_API_KEY", "ISTERO_API_TOKEN"]:
        val = os.environ.get(key, "")
        if val:
            masked = val[:8] + "..." if len(val) > 12 else val
            typer.echo(f"  [OK] {key}={masked}")
        else:
            typer.echo(f"  [..] {key}=(未配置)")

    typer.echo()
    typer.echo("  -- 微步在线认证 --")

    env_csrf = os.environ.get("THREATBOOK_CSRF_TOKEN", "")
    env_xx = os.environ.get("THREATBOOK_XX_CSRF", "")
    env_cookie = os.environ.get("THREATBOOK_COOKIE", "")
    if env_csrf and env_xx and env_cookie:
        typer.echo(f"  [OK] .env 认证信息已配置 (csrf: {env_csrf[:8]}...)")
    else:
        typer.echo(f"  [..] .env 认证信息不完整")

    saved = load_auth_credentials()
    if saved:
        save_time = saved.get("save_time", "未知")
        typer.echo(f"  [OK] 本地保存的认证信息 (保存时间: {save_time})")
    else:
        typer.echo(f"  [..] 无本地保存的认证信息")


@report_app.command()
def list():
    """列出所有历史报告"""
    reports_dir = get_reports_dir()
    if not reports_dir.exists():
        typer.echo("暂无报告")
        return

    files = sorted(reports_dir.glob("trace_*.json"), reverse=True)
    if not files:
        typer.echo("暂无报告")
        return

    typer.echo()
    typer.echo(f"  报告目录: {reports_dir}")
    typer.echo()
    for f in files:
        name = f.stem.replace("trace_", "", 1)
        size = f.stat().st_size
        try:
            with open(f, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            target = meta.get("target", "?")
            elapsed = meta.get("elapsed", "?")
            summary = meta.get("summary", "")
            typer.echo(f"  {name}  [{target}]  {elapsed}  {size} bytes")
            if summary:
                typer.echo(f"    {summary}")
        except Exception:
            typer.echo(f"  {name}  {size} bytes (无法解析)")


@report_app.command()
def view(
    report_id: str = typer.Argument(..., help="报告ID，如 20260618_133830"),
):
    """查看指定报告详情"""
    reports_dir = get_reports_dir()
    candidates = list(reports_dir.glob(f"trace_{report_id}*"))
    if not candidates:
        typer.echo(f"未找到报告: {report_id}", err=True)
        raise typer.Exit(1)

    path = candidates[0]
    try:
        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
        print_trace_report(result)
    except Exception as e:
        typer.echo(f"读取报告失败: {e}", err=True)
        raise typer.Exit(1)


@report_app.command()
def delete(
    report_id: str = typer.Argument(..., help="报告ID，如 20260618_133830"),
    force: bool = typer.Option(False, "--force", "-f", help="直接删除，无需确认"),
):
    """删除指定报告"""
    reports_dir = get_reports_dir()
    candidates = list(reports_dir.glob(f"trace_{report_id}*"))
    if not candidates:
        typer.echo(f"未找到报告: {report_id}", err=True)
        raise typer.Exit(1)

    for path in candidates:
        if not force:
            typer.confirm(f"确认删除 {path.name}?", abort=True)
        path.unlink()
        typer.echo(f"已删除: {path.name}")


@app.command()
def config():
    """查看配置路径信息"""
    typer.echo()
    typer.echo("  -- 配置路径 --")
    typer.echo(f"  报告目录:     {get_reports_dir()}")
    typer.echo(f"  认证文件:     {Path.home() / '.ipvps' / 'auth.json'}")
    typer.echo(f"  环境配置:     {Path.cwd() / '.env'}")
    typer.echo()


if __name__ == "__main__":
    app()
