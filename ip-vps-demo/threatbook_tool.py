"""
微步在线 (ThreatBook) 威胁情报查询工具
- IP威胁情报标签查询
- 近期/历史DNS解析记录查询
- 用户评论区查询
- OAuth本地扫码认证（自动获取Cookie和Token）
- 需要微步在线账号认证信息
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
import requests

load_dotenv()

logger = logging.getLogger("Agent.Tools.ThreatBook")

THREATBOOK_BASE_URL = "https://x.threatbook.com/v5"
THREATBOOK_API_ENDPOINTS = {
    "intelligence": "/node/query/threatbook/intelligence",
    "current_domains": "/node/query/ip/current/domains",
    "history_domains": "/node/query/ip/history/domains",
    "comments": "/node/user/note/list",
}


class ThreatBookClient:
    """微步在线威胁情报查询客户端"""

    def __init__(
        self,
        csrf_token: str = "",
        xx_csrf: str = "",
        cookie: str = "",
        user_id: str = "undefined",
    ):
        self.session = requests.Session()
        self.csrf_token = csrf_token
        self.xx_csrf = xx_csrf
        self.cookie = cookie
        self.user_id = user_id
        self.base_url = THREATBOOK_BASE_URL

        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,zh-TW;q=0.8,zh-HK;q=0.7,en-US;q=0.6,en;q=0.5",
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })

    def _set_auth_headers(self, referer: str = ""):
        if self.csrf_token:
            self.session.headers["X-csrf-token"] = self.csrf_token
        if self.xx_csrf:
            self.session.headers["xx-csrf"] = self.xx_csrf
        self.session.headers["user-id"] = self.user_id
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
        if referer:
            self.session.headers["Referer"] = referer

    def _request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{THREATBOOK_API_ENDPOINTS[endpoint]}"

        resource = (params or {}).get("resource", "")
        if endpoint == "intelligence":
            referer = f"https://x.threatbook.com/v5/ip/{resource}"
        elif endpoint in ("current_domains", "history_domains"):
            referer = f"https://x.threatbook.com/v5/ip/{resource}"
        elif endpoint == "comments":
            referer = f"https://x.threatbook.com/v5/ip/{resource}"
        else:
            referer = "https://x.threatbook.com/"

        self._set_auth_headers(referer=referer)

        logger.info(f"[threatbook] 调用 {endpoint} — params: {params}")

        RESPONSE_CODE_MEANING = {
            0: "成功",
            -1: "参数错误",
            -2: "内部错误",
            -3: "FORBIDDEN - 无权限/未登录/需要会员",
            -4: "频率限制",
            -5: "资源不存在",
            -6: "认证过期",
            -7: "IP被封禁",
        }

        try:
            resp = self.session.get(url, params=params, timeout=30)
            data = resp.json()

            response_code = data.get("response_code")
            if response_code == 0:
                return {"success": True, "data": data.get("data", {})}
            else:
                error_msg = data.get("verbose_msg", "未知错误")
                meaning = RESPONSE_CODE_MEANING.get(response_code, f"未知响应码({response_code})")

                detail_error = f"{error_msg} (code: {response_code} - {meaning})"

                if response_code == -3:
                    detail_error += " [建议: 检查Cookie是否有效，或该接口可能需要会员权限]"
                elif response_code == -6:
                    detail_error += " [建议: 重新执行 oauth_login_playwright() 登录获取新凭证]"

                return {
                    "success": False,
                    "error": error_msg,
                    "detail": detail_error,
                    "response_code": response_code,
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "API 请求超时(30s)", "response_code": None}
        except requests.exceptions.HTTPError as e:
            http_code = e.response.status_code if e.response is not None else "N/A"
            return {
                "success": False,
                "error": f"HTTP 错误 {http_code}: {e}",
                "response_code": f"http_{http_code}",
            }
        except Exception as e:
            return {"success": False, "error": f"请求异常: {str(e)}", "response_code": None}

    def get_intelligence(self, ip: str) -> Dict[str, Any]:
        return self._request("intelligence", {"resource": ip})

    def get_current_domains(self, ip: str) -> Dict[str, Any]:
        return self._request("current_domains", {"resource": ip})

    def get_history_domains(self, ip: str) -> Dict[str, Any]:
        return self._request("history_domains", {"resource": ip})

    def get_comments(self, ip: str, page_num: int = 1) -> Dict[str, Any]:
        return self._request("comments", {"resource": ip, "pageNum": page_num})

    def query_all(self, ip: str) -> Dict[str, Any]:
        results = {
            "ip": ip,
            "_query_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "intelligence": self.get_intelligence(ip),
            "current_domains": self.get_current_domains(ip),
            "history_domains": self.get_history_domains(ip),
            "comments": self.get_comments(ip),
        }

        endpoint_names = {
            "intelligence": "情报标签",
            "current_domains": "近期DNS",
            "history_domains": "历史DNS",
            "comments": "评论区",
        }
        summary = {"total": 4, "success": 0, "failed": 0, "details": []}
        for key in ["intelligence", "current_domains", "history_domains", "comments"]:
            r = results[key]
            status = "[OK]" if r.get("success") else "[FAIL]"
            if r.get("success"):
                summary["success"] += 1
            else:
                summary["failed"] += 1
            detail = f"{status} {endpoint_names[key]}"
            if not r.get("success"):
                detail += f" — {r.get('error', '未知错误')}"
                if r.get("detail"):
                    detail += f"\n   └─ {r['detail']}"
            summary["details"].append(detail)

        results["_summary"] = summary
        return results


def threatbook_query(
    ip: str,
    query_type: str = "all",
    csrf_token: str = "",
    xx_csrf: str = "",
    cookie: str = "",
) -> Dict[str, Any]:
    client = ThreatBookClient(
        csrf_token=csrf_token,
        xx_csrf=xx_csrf,
        cookie=cookie,
    )

    if query_type == "all":
        return client.query_all(ip)
    elif query_type == "intelligence":
        return client.get_intelligence(ip)
    elif query_type == "current_domains":
        return client.get_current_domains(ip)
    elif query_type == "history_domains":
        return client.get_history_domains(ip)
    elif query_type == "comments":
        return client.get_comments(ip)
    else:
        return {"error": f"不支持的查询类型: {query_type}"}


OAUTH_LOGIN_URL = "https://passport.threatbook.cn/oauth"
THREATBOOK_MAIN_URL = "https://x.threatbook.com"
AUTH_SAVE_PATH = str(Path.home() / ".ipvps" / "auth.json")
_OLD_AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".threatbook_auth.json")


def save_auth_credentials(cookie: str, csrf_token: str, xx_csrf: str) -> str:
    Path(AUTH_SAVE_PATH).parent.mkdir(parents=True, exist_ok=True)
    auth_data = {
        "cookie": cookie,
        "csrf_token": csrf_token,
        "xx_csrf": xx_csrf,
        "save_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(AUTH_SAVE_PATH, "w", encoding="utf-8") as f:
        json.dump(auth_data, f, ensure_ascii=False, indent=2)
    logger.info(f"[oauth] 认证凭证已保存到 {AUTH_SAVE_PATH}")
    return AUTH_SAVE_PATH


def load_auth_credentials() -> Optional[Dict[str, str]]:
    for path in (AUTH_SAVE_PATH, _OLD_AUTH_PATH):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[oauth] 加载认证凭证失败 ({path}): {e}")
    return None


def oauth_login_playwright(
    headless: bool = False,
    timeout: int = 300,
    save: bool = True,
) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    result = {"success": False, "error": None}

    PASSPORT_BASE = "https://passport.threatbook.cn"
    OAUTH_URL = f"{PASSPORT_BASE}/oauth"
    CSRF_TOKEN_API = f"{PASSPORT_BASE}/userApi/user/getCsrfToken"

    print("=" * 60)
    print("=== 微步在线 OAuth 扫码登录 (完整认证链路) ===")
    print("=" * 60)
    print(f"正在启动浏览器...")
    print(f"请使用微信扫描页面上的二维码登录")
    print(f"超时时间: {timeout} 秒")
    print("-" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        auth_info = {
            "jwt_token": "",
            "csrf_token": "",
            "xx_csrf": "",
            "cookie": "",
        }

        try:
            print("\n[Step 1/5] 打开登录页面...")
            page.goto(OAUTH_URL, wait_until="networkidle", timeout=30000)
            print("         二维码已加载")

            print("-" * 60)
            print("!!! 请现在使用微信扫描浏览器中的二维码 !!!")
            print("-" * 60)

            print("\n[Step 2/5] 等待微信扫码...")
            start_time = time.time()
            jwt_token = None
            scan_success = False
            last_url = ""
            debug_counter = 0

            while time.time() - start_time < timeout:
                current_url = page.url

                debug_counter += 1
                if debug_counter % 20 == 0:
                    print(f"         [等待中] 当前URL: {current_url[:80]}...")

                if "/oauthResult" in current_url and "code=" in current_url:
                    print("         [检测A] URL 变化 → /oauthResult?code=xxx")
                    scan_success = True
                    break

                if "x.threatbook.com" in current_url and "passport" not in current_url:
                    print("         [检测B] 已直接跳转到主站 x.threatbook.com")
                    scan_success = True
                    break

                try:
                    early_jwt = page.evaluate("""() => {
                        if (window.__PRELOADED_STATE__ &&
                            window.__PRELOADED_STATE__.checkData &&
                            window.__PRELOADED_STATE__.checkData.data) {
                            return window.__PRELOADED_STATE__.checkData.data;
                        }
                        return null;
                    }""")
                    if early_jwt and len(early_jwt) > 20:
                        print("         [检测C] 在当前页面发现 __PRELOADED_STATE__!")
                        jwt_token = early_jwt
                        auth_info["jwt_token"] = jwt_token
                        scan_success = True
                        break
                except Exception:
                    pass

                try:
                    page_text = page.text_content("body") or ""
                    if "扫描成功" in page_text or "scan success" in page_text.lower():
                        print("         [检测D] 页面显示 '扫描成功'")
                        time.sleep(1)
                        scan_success = True
                        break
                except Exception:
                    pass

                last_url = current_url
                time.sleep(0.5)

            if not scan_success:
                result["error"] = f"等待扫码超时 ({timeout}秒)"
                print(f"\n[错误] {result['error']}")
                print(f"         最后URL: {last_url}")
                return result

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                print("         (页面加载未完全完成，继续处理)")

            print("[Step 3/5] 提取 JWT Token...")

            if not jwt_token:
                current_url = page.url

                if "x.threatbook.com" in current_url and "passport" not in current_url:
                    print("         已在主站，尝试从 Cookie 提取认证信息...")
                    all_cookies = context.cookies()
                    for c in all_cookies:
                        if c["name"] == "rememberme":
                            parts = c["value"].split("|")
                            if parts:
                                auth_info["xx_csrf"] = parts[0]
                                print(f"         从 rememberme 获取 xx_csrf: {parts[0][:20]}...")
                            break

                    print("         尝试通过 Passport 获取真正的 csrf_token...")
                    try:
                        page.goto(f"{PASSPORT_BASE}/oauth",
                                  wait_until="networkidle", timeout=15000)
                        time.sleep(2)

                        csrf_result = page.evaluate("""async () => {
                            try {
                                const resp = await fetch(
                                    'https://passport.threatbook.cn/userApi/user/getCsrfToken',
                                    {
                                        method: 'GET',
                                        headers: { 'csrfHeader': 'x', 'Accept': '*/*' },
                                        credentials: 'include'
                                    }
                                );
                                return await resp.json();
                            } catch(e) {
                                return { error: e.message };
                            }
                        }""")

                        if csrf_result.get("response_code") == 0 and csrf_result.get("data"):
                            auth_info["csrf_token"] = csrf_result["data"]
                            jwt_token = "obtained_csrf_via_passport"
                            print(f"         [成功] csrf_token: {auth_info['csrf_token']}")
                        else:
                            print(f"         getCsrfToken 返回: {csrf_result}")
                    except Exception as e:
                        print(f"         Passport 方式失败: {e}")

                    if not auth_info.get("csrf_token") or auth_info["csrf_token"].startswith("vt_"):
                        print("         尝试从主站页面获取 csrf_token...")
                        try:
                            page.goto("https://x.threatbook.com/v5/ip/120.27.154.229",
                                      wait_until="networkidle", timeout=15000)
                            time.sleep(2)
                            main_csrf = page.evaluate("""() => {
                                if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.csrfToken) {
                                    return window.__INITIAL_STATE__.csrfToken;
                                }
                                if (window.csrfToken) return window.csrfToken;
                                const m = document.querySelector('meta[name="csrf-token"]');
                                if (m) return m.content;
                                const cm = document.cookie.match(/csrfToken=([^;]+)/);
                                if (cm) return cm[1];
                                return null;
                            }""")
                            if main_csrf and not main_csrf.startswith("vt_"):
                                auth_info["csrf_token"] = main_csrf
                                jwt_token = "obtained_csrf_from_main"
                                print(f"         [成功] csrf_token(主站): {main_csrf}")
                            elif main_csrf:
                                print(f"         主站 csrf_token 仍是 vt_ 前缀: {main_csrf[:20]}...")
                        except Exception as e:
                            print(f"         主站方式失败: {e}")

                else:
                    try:
                        preloaded = page.evaluate("""() => {
                            if (window.__PRELOADED_STATE__ &&
                                window.__PRELOADED_STATE__.checkData &&
                                window.__PRELOADED_STATE__.checkData.data) {
                                return window.__PRELOADED_STATE__.checkData.data;
                            }
                            return null;
                        }""")
                        if preloaded:
                            jwt_token = preloaded
                            auth_info["jwt_token"] = jwt_token
                            print(f"         JWT Token: {jwt_token[:50]}...")
                    except Exception as e:
                        print(f"         JS提取失败: {e}")

                    if not jwt_token:
                        try:
                            content = page.content()
                            match = re.search(
                                r'"checkData"\s*:\s*\{\s*"data"\s*:\s*"([^"]+)"',
                                content
                            )
                            if match:
                                jwt_token = match.group(1)
                                auth_info["jwt_token"] = jwt_token
                                print(f"         JWT Token (正则): {jwt_token[:50]}...")
                        except Exception as e:
                            print(f"         正则提取失败: {e}")

            else:
                print("         JWT Token 已在 Step 2 中获取")

            SKIP_GETCSRF_TOKEN = ("skipped_already_on_main_site", "obtained_csrf_via_passport", "obtained_csrf_from_main")

            if not jwt_token:
                result["error"] = "无法从 oauthResult 页面提取 JWT Token"
                print(f"\n[错误] {result['error']}")
                return result
            elif jwt_token in SKIP_GETCSRF_TOKEN:
                print(f"         [跳过] csrf_token 已通过其他方式获取")

            if jwt_token and jwt_token not in SKIP_GETCSRF_TOKEN:
                print("[Step 4/5] 调用 getCsrfToken 接口...")

                csrf_resp = page.evaluate("""async (token) => {
                    const resp = await fetch('https://passport.threatbook.cn/userApi/user/getCsrfToken?token=' + token, {
                        method: 'GET',
                        headers: {
                            'csrfHeader': 'x',
                            'Accept': '*/*'
                        }
                    });
                    return await resp.json();
                }""", jwt_token)

                if csrf_resp.get("response_code") == 0:
                    auth_info["csrf_token"] = csrf_resp.get("data", "")
                    print(f"         CSRF Token: {auth_info['csrf_token']}")
                else:
                    print(f"         getCsrfToken 返回异常: {csrf_resp}")
            else:
                print("[Step 4/5] [跳过] 已在主站，从 Cookie 提取认证信息")

            print("[Step 5/5] 等待登录完成并提取认证信息...")

            jump_start = time.time()
            main_page_reached = False

            while time.time() - jump_start < 30:
                current_url = page.url
                if "x.threatbook.com" in current_url and "passport" not in current_url:
                    main_page_reached = True
                    break
                time.sleep(0.5)

            if not main_page_reached:
                print("         未检测到自动跳转，手动访问主站...")
                try:
                    page.goto("https://x.threatbook.com/v5/ip/120.27.154.229",
                              wait_until="networkidle", timeout=20000)
                except Exception as e:
                    print(f"         跳转警告: {e}")

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                print("         (网络加载未完全完成，继续提取 cookie)")

            all_cookies = context.cookies()
            cookie_parts = []
            for c in all_cookies:
                domain = c.get("domain", "")
                if "threatbook" in domain or "threatbook.cn" in domain:
                    cookie_parts.append(f"{c['name']}={c['value']}")

            auth_info["cookie"] = "; ".join(cookie_parts)

            for c in all_cookies:
                name = c["name"]
                value = c["value"]
                if name == "csrfToken":
                    if value and not auth_info["csrf_token"]:
                        auth_info["csrf_token"] = value
                elif name == "xx-csrf":
                    auth_info["xx_csrf"] = value
                elif name == "rememberme":
                    parts = value.split("|")
                    if parts and not auth_info["xx_csrf"]:
                        auth_info["xx_csrf"] = parts[0]

            if not auth_info["csrf_token"]:
                try:
                    page_csrf = page.evaluate("""() => {
                        if (window.csrfToken) return window.csrfToken;
                        const meta = document.querySelector('meta[name="csrf-token"]');
                        if (meta) return meta.content;
                        const match = document.cookie.match(/csrfToken=([^;]+)/);
                        if (match) return match[1];
                        return null;
                    }""")
                    if page_csrf:
                        auth_info["csrf_token"] = page_csrf
                except Exception:
                    pass

            print("\n" + "=" * 60)
            print("=== 认证信息提取完成 ===")
            print("=" * 60)
            print(f"  JWT Token : {auth_info['jwt_token'][:40]}..." if len(auth_info.get('jwt_token','')) > 40 else f"  JWT Token : {auth_info.get('jwt_token', '(空)')}")
            print(f"  CSRF Token: {auth_info.get('csrf_token', '(未获取)')}")
            print(f"  XX-CSRF   : {auth_info.get('xx_csrf', '(未获取)')}")
            print(f"  Cookie 数量: {len(cookie_parts)} 个")
            print("=" * 60)

            missing = []
            if not auth_info["csrf_token"]:
                missing.append("csrf_token")
            if not auth_info["xx_csrf"]:
                missing.append("xx_csrf")
            if not auth_info["cookie"]:
                missing.append("cookie")

            if missing:
                print(f"\n[警告] 以下字段未获取到: {', '.join(missing)}")
                print("部分接口可能无法使用，建议重新登录或检查网络")

            if save and auth_info["cookie"]:
                save_path = save_auth_credentials(
                    auth_info["cookie"],
                    auth_info["csrf_token"],
                    auth_info["xx_csrf"],
                )
                print(f"\n认证凭证已保存到: {save_path}")

            result.update({
                "success": True,
                "jwt_token": auth_info["jwt_token"],
                "csrf_token": auth_info["csrf_token"],
                "xx_csrf": auth_info["xx_csrf"],
                "cookie": auth_info["cookie"],
            })

        except Exception as e:
            result["error"] = f"OAuth登录过程出错: {str(e)}"
            logger.error(f"[oauth] {result['error']}")
            print(f"\n[错误] {result['error']}")
            import traceback
            traceback.print_exc()

        finally:
            time.sleep(2)
            browser.close()

    return result


def get_authenticated_client(
    use_saved: bool = True,
    relogin_if_expired: bool = False,
) -> ThreatBookClient:
    env_csrf = os.environ.get("THREATBOOK_CSRF_TOKEN", "")
    env_xx_csrf = os.environ.get("THREATBOOK_XX_CSRF", "")
    env_cookie = os.environ.get("THREATBOOK_COOKIE", "")
    if env_csrf and env_xx_csrf and env_cookie:
        logger.info("[oauth] 使用 .env 中的认证信息")
        return ThreatBookClient(
            csrf_token=env_csrf,
            xx_csrf=env_xx_csrf,
            cookie=env_cookie,
        )

    if use_saved:
        saved = load_auth_credentials()
        if saved:
            csrf = saved.get("csrf_token", "")
            xx_csrf = saved.get("xx_csrf", "")
            cookie = saved.get("cookie", "")
            if csrf and xx_csrf and cookie:
                logger.info("[oauth] 使用已保存的认证信息")
                return ThreatBookClient(
                    csrf_token=csrf,
                    xx_csrf=xx_csrf,
                    cookie=cookie,
                )

    if relogin_if_expired:
        print("未找到有效的认证信息，需要进行OAuth登录...")
        auth_result = oauth_login_playwright()
        if auth_result.get("success"):
            return ThreatBookClient(
                csrf_token=auth_result["csrf_token"],
                xx_csrf=auth_result["xx_csrf"],
                cookie=auth_result["cookie"],
            )

    raise RuntimeError(
        "未找到认证信息。请先调用 oauth_login_playwright() 进行登录，"
        "或手动提供 cookie/csrf_token 参数，"
        "或在 .env 文件中配置 THREATBOOK_CSRF_TOKEN / THREATBOOK_XX_CSRF / THREATBOOK_COOKIE。"
    )