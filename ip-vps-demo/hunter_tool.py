import base64
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict

from dotenv import load_dotenv
import requests

load_dotenv()

logger = logging.getLogger("Agent.Tools.Hunter")

HUNTER_API_BASE = "https://hunter.qianxin.com/openApi/search"


def _do_hunter_request(
    search: str,
    api_key: str,
    is_web: int,
    page: int,
    page_size: int,
    start_time: str,
    end_time: str,
    status_code: str,
) -> Dict[str, Any]:
    search_b64 = base64.b64encode(search.encode("utf-8")).decode("utf-8")

    params: Dict[str, Any] = {
        "api-key": api_key,
        "search": search_b64,
        "page": page,
        "page_size": page_size,
        "is_web": is_web,
    }
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if status_code:
        params["status_code"] = status_code

    try:
        resp = requests.get(HUNTER_API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "data": data}
    except requests.exceptions.Timeout:
        return {"error": "Hunter API 请求超时"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"Hunter API HTTP 错误: {e}", "response_text": resp.text[:500]}
    except Exception as e:
        return {"error": f"Hunter API 请求异常: {str(e)}"}


def hunter_search(
    search: str,
    api_key: str = "",
    is_web: int = 3,
    page: int = 1,
    page_size: int = 10,
    start_time: str = "",
    end_time: str = "",
    status_code: str = "",
) -> Dict[str, Any]:
    logger.info(f"[hunter_search] 调用 — search: {search}, is_web: {is_web}, page: {page}, page_size: {page_size}")
    api_key = api_key or os.environ.get("HUNTER_API_KEY", "")
    if not api_key:
        return {"error": "未提供 Hunter API Key，请设置 HUNTER_API_KEY 环境变量或传入 api_key 参数"}

    result = _do_hunter_request(search, api_key, is_web, page, page_size, start_time, end_time, status_code)

    ip_match = re.search(r'ip\s*=\s*"([^"]+)"', search)
    domain_match = re.search(r'domain\s*=\s*"([^"]+)"', search)

    if (ip_match or domain_match) and result.get("success"):
        data = result.get("data", {})
        arr = data.get("data", {}).get("arr", []) if isinstance(data.get("data"), dict) else []

        has_blog_title = any(
            item.get("web_title", "") and "'s Blog" in item.get("web_title", "")
            for item in arr
        )

        if has_blog_title:
            if ip_match:
                ip_addr = ip_match.group(1)
            elif arr:
                ip_addr = arr[0].get("ip", "")
            else:
                ip_addr = ""

            logger.info(f"[hunter_search] 检测到 {ip_addr or domain_match.group(1)} 存在 Blog 标题，触发二次查询")
            target_year = datetime.now().year - 2
            new_start_time = f"{target_year}-01-01 00:00:00"

            second_query = (
                f'ip="{ip_addr}" &&'
                '(body="安全" or body="CTF" or body="渗透" or body="测试" or body="内网" or body="github.com")'
            )

            logger.info(f"[hunter_search] 二次查询 — search: {second_query}, start_time: {new_start_time}")
            second_result = _do_hunter_request(
                second_query, api_key, is_web, page, page_size, new_start_time, end_time, status_code
            )

            return {
                "success": True,
                "data": data,
                "secondary_query_triggered": True,
                "secondary_reason": "检测到标题包含 \"'s Blog\"",
                "secondary_query": second_query,
                "secondary_start_time": new_start_time,
                "secondary_data": second_result.get("data") if second_result.get("success") else second_result,
            }

    return result
