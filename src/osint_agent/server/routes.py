import asyncio
import json
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from .dependencies import get_store
from .events import bus
from ..graph.export import export_json

router = APIRouter()


@router.get("/")
async def index():
    return FileResponse(str(__import__("pathlib").Path(__file__).parent / "static" / "index.html"))


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

@router.get("/api/projects")
async def list_projects():
    store = get_store()
    projects = store.list_projects()
    return [
        {
            "id": p.id,
            "origin": p.origin,
            "goal": p.goal,
            "status": p.status.value,
            "facts": len(p.facts),
            "intents": len(p.intents),
            "open_intents": len(p.open_intents),
            "completed_intents": len(p.completed_intents),
            "failed_intents": len(p.failed_intents),
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    store = get_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return _project_detail(project)


@router.get("/api/projects/{project_id}/graph")
async def get_graph(project_id: str):
    store = get_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")

    nodes = []
    edges = []

    goal = project.goal
    goal_id = f"goal_{project.id[:8]}"
    nodes.append({
        "id": goal_id,
        "label": f"目标: {goal[:30]}..." if len(goal) > 30 else f"目标: {goal}",
        "type": "goal",
        "title": goal,
    })

    origin = project.origin
    origin_id = f"origin_{project.id[:8]}"
    nodes.append({
        "id": origin_id,
        "label": f"起点: {origin[:30]}..." if len(origin) > 30 else f"起点: {origin}",
        "type": "origin",
        "title": origin,
    })

    for f in project.facts:
        fid = f"fact_{f.id}"
        desc = f.description
        desc_short = desc[:30] + "..." if len(desc) > 30 else desc
        nodes.append({
            "id": fid,
            "label": desc_short,
            "type": "fact",
            "title": desc,
            "source": f.source,
            "confidence": f.confidence,
            "created_at": f.created_at.isoformat(),
        })
        edges.append({"from": origin_id, "to": fid})

    for i in project.intents:
        iid = f"intent_{i.id}"
        desc = i.description
        desc_short = desc[:30] + "..." if len(desc) > 30 else desc
        nodes.append({
            "id": iid,
            "label": desc_short,
            "type": "intent",
            "status": i.status.value,
            "title": desc,
            "created_at": i.created_at.isoformat(),
        })
        src = f"fact_{i.from_fact_id}" if i.from_fact_id else origin_id
        edges.append({"from": src, "to": iid})

    for f in project.facts:
        edges.append({"from": f"fact_{f.id}", "to": goal_id})

    return {"nodes": nodes, "edges": edges}


@router.get("/api/projects/{project_id}/export")
async def export_project(project_id: str, fmt: str = Query("json")):
    store = get_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if fmt == "json":
        return json.loads(export_json(project))
    raise HTTPException(400, f"Unsupported format: {fmt}")


# ---------------------------------------------------------------------------
# SSE real-time events
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/events")
async def project_events(project_id: str, request: Request):
    q = bus.subscribe(project_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"
        finally:
            bus.unsubscribe(project_id, q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _project_detail(project):
    return {
        "id": project.id,
        "origin": project.origin,
        "goal": project.goal,
        "status": project.status.value,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "facts": [
            {
                "id": f.id,
                "description": f.description,
                "source": f.source,
                "confidence": f.confidence,
                "created_at": f.created_at.isoformat(),
            }
            for f in project.facts
        ],
        "intents": [
            {
                "id": i.id,
                "description": i.description,
                "from_fact_id": i.from_fact_id,
                "status": i.status.value,
                "created_at": i.created_at.isoformat(),
            }
            for i in project.intents
        ],
        "hints": [
            {
                "id": h.id,
                "content": h.content,
                "created_at": h.created_at.isoformat(),
            }
            for h in project.hints
        ],
    }
