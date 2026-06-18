"""共享依赖 — 避免 app / routes 循环导入"""

from ..graph.store import ProjectStore

_store: ProjectStore = None


def init_store(db_path: str = None):
    global _store
    _store = ProjectStore(db_path=db_path) if db_path else ProjectStore()


def get_store() -> ProjectStore:
    global _store
    if _store is None:
        _store = ProjectStore()
    return _store


def close_store():
    global _store
    if _store:
        try:
            _store.close()
        except Exception:
            pass
        _store = None
