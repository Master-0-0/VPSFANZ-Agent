import json
import subprocess
import sys
import urllib.parse
from typing import List, Optional

import typer

app = typer.Typer(
    name="vpsctl",
    help="VPS 工具集 — 统一管理 ipvps 与 osint-agent",
    no_args_is_help=True,
)


def _run_cli(cmd: List[str]) -> int:
    try:
        proc = subprocess.run(cmd)
    except FileNotFoundError:
        typer.echo(
            f"错误: 未找到 '{cmd[0]}' 命令。请先安装对应的 CLI 工具。",
            err=True,
        )
        raise typer.Exit(1)
    return proc.returncode


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def ipvps(ctx: typer.Context):
    """透传调用 ipvps 命令"""
    if not ctx.args:
        _run_cli(["ipvps", "--help"])
        return
    sys.exit(_run_cli(["ipvps"] + ctx.args))


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def osint(ctx: typer.Context):
    """透传调用 osint-agent 命令"""
    if not ctx.args:
        _run_cli(["osint-agent", "--help"])
        return
    sys.exit(_run_cli(["osint-agent"] + ctx.args))


@app.command()
def pipeline(
    target: str = typer.Argument(..., help="目标 IP 地址或域名"),
    goal: str = typer.Option(
        "找出安全相关人员情报",
        "--goal", "-g",
        help="OSINT 情报目标",
    ),
    web: bool = typer.Option(True, "--web/--no-web", help="启动 Web UI"),
    port: int = typer.Option(8080, "--port", help="Web UI 端口"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="osint-agent 详细输出"),
    step: bool = typer.Option(False, "--step", "-s", help="osint-agent 分步模式"),
):
    """执行 IP 溯源 → OSINT 情报查询 自动化管道"""
    typer.echo("=" * 60)
    typer.echo("  vpsctl pipeline — 自动化溯源分析管道")
    typer.echo("=" * 60)
    typer.echo(f"  目标 IP: {target}")
    typer.echo(f"  情报目标: {goal}")
    typer.echo()

    typer.echo("◆ 步骤1: IP/VPS 溯源")
    typer.echo("-" * 40)
    try:
        proc = subprocess.run(
            ["ipvps", "trace", target, "--json", "--no-save"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        typer.echo("错误: 未找到 'ipvps' 命令。请先执行: pip install -e ip-vps-demo/", err=True)
        raise typer.Exit(1)
    except subprocess.CalledProcessError:
        typer.echo("错误: 溯源步骤失败，管道终止。", err=True)
        raise typer.Exit(1)

    try:
        trace_result = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        typer.echo("错误: 无法解析 ipvps 输出", err=True)
        raise typer.Exit(1)

    typer.echo()
    typer.echo("◆ 步骤2: 提取信息")
    typer.echo("-" * 40)
    info = _extract_info(trace_result)
    _print_extracted(info)

    typer.echo()
    typer.echo("◆ 步骤3: 编码并传递给 osint-agent")
    typer.echo("-" * 40)
    text = _format_extracted(info)
    encoded = urllib.parse.quote(text)

    osint_args = [
        "osint-agent", "run", encoded,
        "--goal", goal,
        "-i",
    ]
    if verbose:
        osint_args.append("-v")
    if step:
        osint_args.append("-s")
    if web:
        osint_args += ["--web", "--port", str(port)]

    typer.echo(f"  调用: osint-agent run <encoded> --goal {goal} ...")
    typer.echo()
    sys.exit(_run_cli(osint_args))


def _extract_info(report: dict) -> dict:
    extracted = {
        "target": report.get("target", ""),
        "trace_time": report.get("trace_time", ""),
        "domains": [],
        "web_titles": [],
        "history_dns": None,
    }
    phases = report.get("phases", [])
    phase1 = next((p for p in phases if p.get("phase") == "phase1_basic_info"), {})
    steps = phase1.get("steps", [])

    domain_step = next((s for s in steps if s["step"] == "域名关联分析"), {})
    if domain_step.get("success"):
        extracted["domains"].extend(domain_step["data"].get("domains", []))

    tb_step = next((s for s in steps if s["step"] == "微步安全情报"), {})
    tb_data = tb_step.get("data", {}) if isinstance(tb_step.get("data"), dict) else {}
    cd = tb_data.get("current_domains", {})
    if cd.get("success"):
        items = cd.get("data", {}).get("items", [])
        for item in items:
            ioc = item.get("ioc", "").strip()
            if ioc and ioc not in extracted["domains"]:
                extracted["domains"].append(ioc)

    hd = tb_data.get("history_domains", {})
    if hd.get("success"):
        extracted["history_dns"] = hd.get("data", {})
    else:
        extracted["history_dns"] = {"error": hd.get("error", "无数据"), "response_code": hd.get("response_code")}

    hunter_step = next((s for s in steps if s["step"] == "Hunter 资产测绘"), {})
    hunter_data = hunter_step.get("data", {})
    if isinstance(hunter_data, dict):
        inner = hunter_data.get("data") if isinstance(hunter_data.get("data"), dict) else hunter_data
        arr = inner.get("arr", []) if isinstance(inner, dict) else []
        for asset in arr:
            port = asset.get("port", "")
            protocol = asset.get("protocol", "")
            web_title = asset.get("web_title", "").strip()
            if web_title:
                extracted["web_titles"].append({"port": port, "protocol": protocol, "web_title": web_title})

    extracted["domains"] = sorted(set(extracted["domains"]))
    return extracted


def _format_extracted(info: dict) -> str:
    lines = []
    domains = info.get("domains", [])
    if domains:
        lines.append(f"域名 ({len(domains)}个):")
        for d in domains:
            lines.append(f"    - {d}")
    else:
        lines.append("域名: (无)")

    titles = info.get("web_titles", [])
    if titles:
        lines.append(f"Web Title ({len(titles)}条):")
        for t in titles:
            lines.append(f"    [{t['port']}/{t['protocol']}] {t['web_title']}")
    else:
        lines.append("Web Title: (无)")

    hd = info.get("history_dns")
    if hd is None:
        lines.append("历史DNS: (无数据)")
    elif hd.get("error"):
        err = hd.get("error", "未知错误")
        code = hd.get("response_code", "")
        code_str = f" (code: {code})" if code else ""
        lines.append(f"历史DNS: (无数据 - {err}{code_str})")
    else:
        items = hd.get("items", []) if isinstance(hd, dict) else []
        if items:
            lines.append(f"历史DNS ({len(items)}条):")
            for item in items:
                ioc = item.get("ioc", "")
                ft = item.get("findTime", "")
                lines.append(f"    - {ioc} ({ft})")
        else:
            lines.append("历史DNS: (无记录)")
    return "\n".join(lines)


def _print_extracted(info: dict):
    domains = info.get("domains", [])
    print(f"  域名: {len(domains)} 个")
    for d in domains[:5]:
        print(f"    - {d}")
    if len(domains) > 5:
        print(f"    ... 等 {len(domains)} 个")

    titles = info.get("web_titles", [])
    print(f"  Web Title: {len(titles)} 条")
    for t in titles[:3]:
        print(f"    [{t['port']}/{t['protocol']}] {t['web_title']}")
    if len(titles) > 3:
        print(f"    ... 等 {len(titles)} 条")

    hd = info.get("history_dns")
    if hd is None:
        print("  历史DNS: (无数据)")
    elif hd.get("error"):
        print(f"  历史DNS: (无数据 - {hd['error']})")
    else:
        items = hd.get("items", [])
        print(f"  历史DNS: {len(items)} 条" if items else "  历史DNS: (无记录)")


if __name__ == "__main__":
    app()
