"""Bing Web Search — 通过无头浏览器 (Playwright) 搜索 Bing，免费无需 API Key"""

import asyncio
import atexit
import logging
import threading
from typing import Any, Dict, Optional

from .registry import tool
from .search_scraper import SearchScraper

logger = logging.getLogger("Agent.Tools.BingSearch")

_event_loop: Optional[asyncio.AbstractEventLoop] = None
_scraper: Optional[SearchScraper] = None
_loop_lock = threading.Lock()


def _get_or_create_loop() -> asyncio.AbstractEventLoop:
    global _event_loop
    with _loop_lock:
        if _event_loop is None or _event_loop.is_closed():
            _event_loop = asyncio.new_event_loop()
            thread = threading.Thread(target=_event_loop.run_forever, daemon=True)
            thread.start()
    return _event_loop


async def _do_search(query: str, max_results: int) -> Dict[str, Any]:
    global _scraper
    if _scraper is None:
        _scraper = SearchScraper(engine="bing", headless=True)
    resp = await _scraper.search(query=query, max_results=max_results)
    return resp.to_dict()


@tool("web_search", "执行网络搜索，返回相关结果列表（含标题、URL、摘要）")
def web_search(query: str, num_results: int = 5) -> dict:
    """使用无头浏览器搜索 Bing，返回结构化搜索结果。"""
    logger.info("*** web_search(query=\"%s\", num_results=%d) ***", query, num_results)
    loop = _get_or_create_loop()
    try:
        future = asyncio.run_coroutine_threadsafe(
            _do_search(query, num_results),
            loop,
        )
        result = future.result(timeout=120)
        return result
    except Exception as e:
        logger.error("搜索失败: %s", e)
        return {"query": query, "results": [], "error": str(e)}


def cleanup():
    global _scraper, _event_loop
    if _scraper is not None:
        async def _close():
            await _scraper.close()
        if _event_loop and not _event_loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(_close(), _event_loop)
                future.result(timeout=10)
            except Exception:
                pass
        _scraper = None
    if _event_loop and not _event_loop.is_closed():
        _event_loop.call_soon_threadsafe(_event_loop.stop)
        _event_loop = None


atexit.register(cleanup)
