"""SSE 事件总线 — 支持 Dispatcher → 前端实时推送

publish 是同步的，通过 call_soon_threadsafe 跨线程推送到对应事件循环。
"""

import asyncio
import json
from typing import Any, Dict, List, Tuple


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}

    def subscribe(self, project_id: str) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(project_id, []).append((q, loop))
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue):
        subs = self._subscribers.get(project_id, [])
        self._subscribers[project_id] = [(sq, sl) for sq, sl in subs if sq is not q]

    def publish(self, project_id: str, event: str, data: Any):
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        subs = self._subscribers.get(project_id, [])
        if not subs:
            return
        for q, loop in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, payload)
            except Exception:
                pass

    def cleanup_project(self, project_id: str):
        self._subscribers.pop(project_id, None)


bus = EventBus()
