"""
IP/VPS 溯源 — 统一编排引擎
"""
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from hunter_tool import hunter_search
from threatbook_tool import ThreatBookClient, get_authenticated_client
from whois_tool import whois_istero

load_dotenv()

logger = logging.getLogger("Agent.Orchestrator")

def get_reports_dir() -> Path:
    path = Path.cwd() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path

CLOUD_PROVIDER_ASN: Dict[str, List[int]] = {
    "腾讯云": [45090, 132203, 135897, 137696, 138392, 139007, 140339, 140340, 140341],
    "阿里云": [45062, 37963, 45102, 4837, 58519, 58461, 132208, 134763, 138964],
    "百度智能云": [55967, 38365, 55960, 56047, 56048, 137690],
    "华为云": [136907, 136941, 137990, 138308, 139607, 140220, 141207],
    "AWS 中国": [9607, 39111, 10252, 10126],
    "Azure 中国": [13238, 134109],
}

CLOUD_PROVIDER_KEYWORDS: Dict[str, List[str]] = {
    "腾讯云": ["tencent", "tencentcloud", "腾讯云"],
    "阿里云": ["alibaba", "aliyun", "阿里云"],
    "百度智能云": ["baidu", "baiducloud", "百度云"],
    "华为云": ["huawei", "huaweicloud", "华为云"],
    "AWS 中国": ["amazon", "aws"],
    "Azure 中国": ["microsoft", "azure"],
}


def _extract_asn_from_hunter(data: Dict) -> Optional[int]:
    arr = (
        data.get("data", {}).get("arr", [])
        if isinstance(data.get("data"), dict)
        else []
    )
    for item in arr:
        asn = item.get("asn") or item.get("as_number")
        if asn:
            try:
                return int(asn)
            except (ValueError, TypeError):
                pass
    return None


def _extract_isp_from_hunter(data: Dict) -> Optional[str]:
    arr = (
        data.get("data", {}).get("arr", [])
        if isinstance(data.get("data"), dict)
        else []
    )
    for item in arr:
        isp = item.get("isp") or item.get("company")
        if isp:
            return str(isp)
    return None


def _query_ipinfo(ip: str) -> Dict[str, Any]:
    url = f"https://ipinfo.io/{ip}/json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "data": data}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "ipinfo.io 请求超时"}
    except Exception as e:
        return {"success": False, "error": f"ipinfo.io 请求异常: {str(e)}"}


def _parse_asn_from_org(org: str) -> Optional[int]:
    if not org:
        return None
    match = re.search(r"AS(\d+)", org)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def _is_ip(target: str) -> bool:
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target))


def _is_domain(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", target))


def _timed(func, *args, **kwargs) -> Tuple[Any, float]:
    start = time.time()
    result = func(*args, **kwargs)
    return result, time.time() - start


def _fmt_time(seconds: float) -> str:
    return f"{seconds:.1f}s"


def run_phase1_whois(target: str) -> Dict[str, Any]:
    if _is_ip(target):
        result, elapsed = _timed(_query_ipinfo, target)
        return {
            "step": "IP 归属查询 (ipinfo.io)",
            "target": target,
            "success": result.get("success", False),
            "data": result.get("data", result),
            "error": result.get("error"),
            "elapsed": _fmt_time(elapsed),
        }
    result, elapsed = _timed(whois_istero, target)
    return {
        "step": "WHOIS 查询",
        "target": target,
        "success": result.get("success", False),
        "data": result.get("data", result),
        "error": result.get("error"),
        "elapsed": _fmt_time(elapsed),
    }


def run_phase1_hunter(target: str) -> Dict[str, Any]:
    query = f'ip="{target}"' if _is_ip(target) else f'domain="{target}"'
    result, elapsed = _timed(hunter_search, query, page_size=10)
    return {
        "step": "Hunter 资产测绘",
        "target": target,
        "success": result.get("success", False),
        "data": result.get("data", result),
        "error": result.get("error"),
        "secondary_query_triggered": result.get("secondary_query_triggered", False),
        "secondary_data": result.get("secondary_data"),
        "elapsed": _fmt_time(elapsed),
    }


def run_phase1_threatbook(target: str) -> Dict[str, Any]:
    if not _is_ip(target):
        return {
            "step": "微步安全情报",
            "target": target,
            "success": False,
            "data": None,
            "error": "微步查询仅支持 IP 地址",
            "elapsed": "0.0s",
        }

    try:
        client = get_authenticated_client(use_saved=True)
        result, elapsed = _timed(client.query_all, target)
        return {
            "step": "微步安全情报",
            "target": target,
            "success": result.get("success", False) if isinstance(result, dict) else False,
            "data": result,
            "error": result.get("error") if isinstance(result, dict) else None,
            "elapsed": _fmt_time(elapsed),
        }
    except RuntimeError as e:
        return {
            "step": "微步安全情报",
            "target": target,
            "success": False,
            "data": None,
            "error": str(e),
            "elapsed": "0.0s",
        }


def run_phase1_basic_info(target: str) -> Dict[str, Any]:
    steps = []

    whois_result = run_phase1_whois(target)
    steps.append(whois_result)

    hunter_result = run_phase1_hunter(target)
    steps.append(hunter_result)

    domain_relation = {"step": "域名关联分析", "target": target, "success": False, "data": {}, "elapsed": "0.0s"}
    if hunter_result.get("success"):
        arr = (
            hunter_result["data"].get("data", {}).get("arr", [])
            if isinstance(hunter_result["data"].get("data"), dict)
            else []
        )
        domains_found = set()
        for item in arr:
            domain = item.get("domain") or item.get("host")
            if domain:
                domains_found.add(domain)
        if domains_found:
            domain_relation["success"] = True
            domain_relation["data"] = {"domains": sorted(domains_found)}
    steps.append(domain_relation)

    threatbook_result = run_phase1_threatbook(target)
    steps.append(threatbook_result)

    success_count = sum(1 for s in steps if s.get("success"))
    return {
        "phase": "phase1_basic_info",
        "phase_name": "基础信息收集",
        "target": target,
        "steps": steps,
        "summary": f"{success_count}/{len(steps)} 步骤成功",
    }


def _parse_ipinfo_data(whois_data: Dict) -> Tuple[Optional[int], Optional[str]]:
    data = whois_data.get("data", {})
    if not data:
        return None, None
    org = data.get("org", "")
    asn = _parse_asn_from_org(org)
    isp = org
    return asn, isp


def run_phase2_cloud_platform(
    hunter_data: Dict,
    threatbook_data: Optional[Dict] = None,
    whois_data: Optional[Dict] = None,
) -> Dict[str, Any]:
    asn = _extract_asn_from_hunter(hunter_data.get("data", {}))
    isp = _extract_isp_from_hunter(hunter_data.get("data", {}))

    threatbook_isp = None
    if threatbook_data:
        intelligence = threatbook_data.get("data", {}).get("intelligence", {})
        if isinstance(intelligence, dict):
            threatbook_isp = intelligence.get("data", {}).get("isp") if isinstance(intelligence.get("data"), dict) else None

    ipinfo_asn, ipinfo_isp = None, None
    if whois_data and whois_data.get("step") == "IP 归属查询 (ipinfo.io)":
        ipinfo_asn, ipinfo_isp = _parse_ipinfo_data(whois_data)

    asn = asn or ipinfo_asn
    isp_source = isp or ipinfo_isp or threatbook_isp or ""

    candidates = []

    if asn:
        for provider, asn_list in CLOUD_PROVIDER_ASN.items():
            if asn in asn_list:
                candidates.append({"provider": provider, "method": f"ASN {asn} 匹配", "confidence": "高"})

    isp_lower = isp_source.lower()
    if isp_lower:
        for provider, keywords in CLOUD_PROVIDER_KEYWORDS.items():
            if any(kw.lower() in isp_lower for kw in keywords):
                if not any(c["provider"] == provider for c in candidates):
                    candidates.append({"provider": provider, "method": f"ISP 关键词 '{isp_source}' 匹配", "confidence": "中"})

    unidentified = bool(asn) and not candidates

    return {
        "phase": "phase2_cloud_platform",
        "phase_name": "云平台层溯源",
        "asn": asn,
        "isp": isp_source,
        "candidates": candidates,
        "unidentified": unidentified,
        "summary": candidates[0]["provider"] if candidates else ("未匹配已知云厂商" if not unidentified else "未知 ASN"),
    }


def run_full_trace(target: str) -> Dict[str, Any]:
    start_time = time.time()
    target = target.strip()

    if not _is_ip(target) and not _is_domain(target):
        return {"error": f"无法识别输入: {target}，请输入 IP 地址或域名"}

    trace_result = {
        "target": target,
        "type": "IP" if _is_ip(target) else "Domain",
        "trace_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "phases": [],
    }

    phase1 = run_phase1_basic_info(target)
    trace_result["phases"].append(phase1)

    hunter_step = next((s for s in phase1.get("steps", []) if s["step"] == "Hunter 资产测绘"), {})
    whois_step = next((s for s in phase1.get("steps", []) if s["step"] in ("WHOIS 查询", "IP 归属查询 (ipinfo.io)")), {})
    threatbook_step = next((s for s in phase1.get("steps", []) if s["step"] == "微步安全情报"), {})
    phase2 = run_phase2_cloud_platform(
        hunter_step,
        threatbook_step.get("data") if threatbook_step.get("success") else None,
        whois_step if whois_step.get("success") else None,
    )
    trace_result["phases"].append(phase2)

    trace_result["elapsed"] = f"{time.time() - start_time:.1f}s"

    phase1_ok = phase1.get("summary", "")
    phase2_ok = phase2.get("summary", "")
    trace_result["summary"] = f"{phase1_ok} | 云平台: {phase2_ok}"

    return trace_result


def print_trace_report(result: Dict[str, Any]):
    print()
    print("=" * 70)
    print(f"  IP/VPS 溯源报告 — {result.get('target', '')}")
    print(f"  时间: {result.get('trace_time', '')}  |  耗时: {result.get('elapsed', '')}")
    print("=" * 70)

    for phase in result.get("phases", []):
        print()
        print(f"■ [{phase.get('phase_name', '')}]")
        print("-" * 70)

        if phase.get("phase") == "phase1_basic_info":
            for step in phase.get("steps", []):
                icon = "[OK]" if step.get("success") else "[FAIL]"
                print(f"  {icon} {step['step']}  ({step.get('elapsed', '')})")
                if step.get("error"):
                    print(f"     错误: {step['error']}")
                if step.get("success"):
                    _print_step_summary(step)
        elif phase.get("phase") == "phase2_cloud_platform":
            candidates = phase.get("candidates", [])
            if candidates:
                for c in candidates:
                    print(f"  [OK] {c['provider']} ({c['method']}, 置信度: {c['confidence']})")
            else:
                print(f"  - 未识别云厂商 (ASN: {phase.get('asn', 'N/A')}, ISP: {phase.get('isp', 'N/A')})")

    print()
    print(f"  汇总: {result.get('summary', '')}")
    print("=" * 70)

    info = extract_report_info(result)
    print_extracted_info(info)


def extract_report_info(report: dict) -> dict:
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
        arr = []
        inner = hunter_data.get("data") if isinstance(hunter_data.get("data"), dict) else hunter_data
        arr = inner.get("arr", []) if isinstance(inner, dict) else []
        for asset in arr:
            port = asset.get("port", "")
            protocol = asset.get("protocol", "")
            web_title = asset.get("web_title", "").strip()
            if web_title:
                extracted["web_titles"].append({
                    "port": port,
                    "protocol": protocol,
                    "web_title": web_title,
                })

    extracted["domains"] = sorted(set(extracted["domains"]))
    return extracted


def print_extracted_info(info: dict):
    print()
    print("■ 提取信息 — 域名 / Web标题 / 历史DNS")
    print("-" * 70)

    domains = info.get("domains", [])
    print(f"\n  域名 ({len(domains)}个):" if domains else "\n  域名: (无)")
    for d in domains:
        print(f"    - {d}")

    titles = info.get("web_titles", [])
    print(f"\n  Web Title ({len(titles)}条):" if titles else "\n  Web Title: (无)")
    for t in titles:
        print(f"    [{t['port']}/{t['protocol']}] {t['web_title']}")

    hd = info.get("history_dns")
    print()
    if hd is None:
        print("  历史DNS: (无数据)")
    elif hd.get("error"):
        err = hd.get("error", "未知错误")
        code = hd.get("response_code", "")
        print(f"  历史DNS: (无数据 - {err}{f' (code: {code})' if code else ''})")
    else:
        items = hd.get("items", []) if isinstance(hd, dict) else []
        print(f"  历史DNS ({len(items)}条):" if items else "  历史DNS: (无记录)")
        for item in items:
            ioc = item.get("ioc", "")
            ft = item.get("findTime", "")
            print(f"    - {ioc} ({ft})")

    print()


def _print_step_summary(step: Dict[str, Any]):
    step_name = step["step"]
    data = step.get("data", {})

    if step_name == "IP 归属查询 (ipinfo.io)":
        if isinstance(data, dict):
            org = data.get("org", "")
            city = data.get("city", "")
            region = data.get("region", "")
            country = data.get("country", "")
            timezone = data.get("timezone", "")
            parts = []
            if org: parts.append(f"ISP/ASN: {org}")
            if city and region: parts.append(f"{city}, {region}, {country}")
            elif city: parts.append(f"{city}, {country}")
            if timezone: parts.append(f"时区: {timezone}")
            if parts:
                print(f"     {', '.join(parts)}")

    elif step_name == "WHOIS 查询":
        if isinstance(data, dict):
            registrar = data.get("registrar") or data.get("registrar_name", "")
            org = data.get("registrant_org") or data.get("org", "")
            email = data.get("registrant_email") or data.get("email", "")
            parts = []
            if org: parts.append(f"注册组织: {org}")
            if email: parts.append(f"邮箱: {email}")
            if registrar: parts.append(f"注册商: {registrar}")
            if parts:
                print(f"     {', '.join(parts)}")

    elif step_name == "Hunter 资产测绘":
        arr = []
        raw = data
        if isinstance(raw, dict):
            inner = raw.get("data") if isinstance(raw.get("data"), dict) else raw
            arr = inner.get("arr", []) if isinstance(inner, dict) else []
        print(f"     发现 {len(arr)} 条资产记录")
        if step.get("secondary_query_triggered"):
            print(f"     → 触发 Blog 二次查询")

    elif step_name == "域名关联分析":
        domains = data.get("domains", [])
        print(f"     关联域名: {', '.join(domains[:5])}" + (f" ...等 {len(domains)} 个" if len(domains) > 5 else ""))

    elif step_name == "微步安全情报":
        if isinstance(data, dict):
            s = data.get("_summary")
            if s:
                print(f"     情报: ✓{s.get('success',0)} ✗{s.get('failed',0)} (共 {s.get('total',0)} 接口)")

