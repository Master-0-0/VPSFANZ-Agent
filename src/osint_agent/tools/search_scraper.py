"""无头浏览器搜索爬虫 — 搜索 Bing、访问结果页面、提取摘要。"""

import asyncio
import base64
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, unquote, quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser


@dataclass
class SearchResult:
    """单条搜索结果的数据结构"""
    title: str
    url: str
    snippet: str


@dataclass
class SearchResponse:
    """一次搜索的完整响应结构"""
    query: str
    engine: str
    results: List[SearchResult] = field(default_factory=list)

    def to_dict(self):
        return {
            "query": self.query,
            "engine": self.engine,
            "results": [asdict(r) for r in self.results],
        }


ENGINE_CONFIG = {
    "bing": {
        "homepage": "https://cn.bing.com",
        "search_url": "https://cn.bing.com/search?q={query}",
        "result_selector": "li.b_algo",
        "title_selector": "h2 a",
        "link_selector": "h2 a",
        "snippet_selector": ".b_caption p",
        "next_page_selector": "a.sb_pagN",
    },
}


def _decode_bing_url(url: str) -> str:
    if "/ck/a" not in url:
        return url
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        encoded = qs.get("u", [None])[0]
        if encoded:
            if encoded.startswith("a1"):
                encoded = encoded[2:]
            padding = 4 - len(encoded) % 4
            if padding != 4:
                encoded += "=" * padding
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            decoded = unquote(decoded)
            if decoded.startswith("http://") or decoded.startswith("https://"):
                return decoded
    except Exception:
        pass
    return url


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


class SearchScraper:
    """无头浏览器搜索爬虫，支持搜索引擎查询和页面内容提取。"""

    def __init__(
        self,
        engine: str = "bing",
        headless: bool = True,
        timeout: int = 30000,
        user_agent: Optional[str] = None,
    ):
        if engine not in ENGINE_CONFIG:
            raise ValueError(f"不支持的搜索引擎: {engine}。可选: {list(ENGINE_CONFIG)}")
        self.engine = engine
        self.config = ENGINE_CONFIG[engine]
        self.headless = headless
        self.timeout = timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self._browser

    async def _new_page(self) -> Page:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1920, "height": 1080},
        )
        return await context.new_page()

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> SearchResponse:
        """执行搜索并返回结构化结果。"""
        page = await self._new_page()
        response = SearchResponse(query=query, engine=self.engine)

        try:
            url = self.config["search_url"].format(query=quote(query))
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
            await self._dismiss_cookie_banner(page)
            results = await self._parse_search_results(page)

            for i, r in enumerate(results):
                if i >= max_results:
                    break
                response.results.append(r)

            return response
        finally:
            await page.context.close()

    async def _parse_search_results(self, page: Page) -> List[SearchResult]:
        html = await page.content()
        soup = BeautifulSoup(html, "lxml")
        items = soup.select(self.config["result_selector"])
        results: List[SearchResult] = []
        seen = set()

        for item in items:
            title_el = item.select_one(self.config["title_selector"])
            link_el = item.select_one(self.config["link_selector"])
            snippet_el = item.select_one(self.config["snippet_selector"])

            title = _clean_text(title_el.get_text()) if title_el else ""
            raw_url = link_el.get("href", "") if link_el else ""
            url = _decode_bing_url(raw_url)
            snippet = _clean_text(snippet_el.get_text()) if snippet_el else ""

            if not title or not url:
                continue
            if url in seen:
                continue
            seen.add(url)

            results.append(SearchResult(title=title, url=url, snippet=snippet))
        return results

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        try:
            reject_btn = page.locator("#bnp_btn_reject, #bnp_btn_secondary")
            if await reject_btn.count() > 0:
                await reject_btn.first.click(timeout=2000)
        except Exception:
            pass

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
