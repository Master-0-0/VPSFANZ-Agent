import logging
import os
from typing import Any, Dict

from dotenv import load_dotenv
import requests

load_dotenv()

logger = logging.getLogger("Agent.Tools.Whois")

WHOIS_ISTERO_API = "https://api.istero.com/resource/v2/whois/query"


def whois_istero(
    domain: str,
    token: str = "",
) -> Dict[str, Any]:
    token = token or os.environ.get("ISTERO_API_TOKEN", "")
    if not token:
        return {"error": "未提供 ISAS API Token，请设置 ISTERO_API_TOKEN 环境变量或传入 token 参数"}

    logger.info(f"[whois_istero] 调用 — domain: {domain}")

    headers = {"Authorization": f"Bearer {token}"}
    params = {"domain": domain}

    try:
        resp = requests.get(WHOIS_ISTERO_API, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
    except requests.exceptions.Timeout:
        return {"error": "ISAS Whois API 请求超时"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"ISAS Whois API HTTP 错误: {e}", "response_text": resp.text[:500]}
    except Exception as e:
        return {"error": f"ISAS Whois API 请求异常: {str(e)}"}

    if body.get("code") != 200:
        return {"error": f"ISAS Whois API 返回异常: code={body.get('code')}, message={body.get('message')}"}

    return {"success": True, "data": body.get("data", {})}
