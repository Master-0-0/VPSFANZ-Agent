import json
from datetime import datetime
from typing import Optional

from .models import Project


def export_json(project: Project, indent: int = 2) -> str:
    def _serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "model_dump"):
            return _convert(obj.model_dump())
        return str(obj)

    def _convert(d):
        if isinstance(d, dict):
            return {k: _convert(v) for k, v in d.items()}
        if isinstance(d, list):
            return [_convert(i) for i in d]
        if isinstance(d, datetime):
            return d.isoformat()
        return d

    data = _convert(project.model_dump())
    return json.dumps(data, ensure_ascii=False, indent=indent)


def export_yaml(project: Project) -> str:
    lines = []
    lines.append("project:")
    lines.append("  id: %s" % project.id)
    lines.append("  origin: %s" % project.origin)
    lines.append("  goal: %s" % project.goal)
    lines.append("  status: %s" % project.status.value)
    lines.append("  created_at: %s" % project.created_at.isoformat())
    lines.append("  updated_at: %s" % project.updated_at.isoformat())

    lines.append("")
    lines.append("facts:")
    for f in project.facts:
        lines.append("  - id: %s" % f.id)
        lines.append("    description: %s" % f.description)
        lines.append("    source: %s" % f.source)
        lines.append("    confidence: %s" % f.confidence)
        lines.append("    created_at: %s" % f.created_at.isoformat())

    lines.append("")
    lines.append("intents:")
    for i in project.intents:
        lines.append("  - id: %s" % i.id)
        lines.append("    description: %s" % i.description)
        lines.append("    from_fact_id: %s" % i.from_fact_id)
        lines.append("    status: %s" % i.status.value)
        lines.append("    created_at: %s" % i.created_at.isoformat())

    if project.hints:
        lines.append("")
        lines.append("hints:")
        for h in project.hints:
            lines.append("  - id: %s" % h.id)
            lines.append("    content: %s" % h.content)
            lines.append("    created_at: %s" % h.created_at.isoformat())

    return "\n".join(lines)


def export_mermaid(project: Project) -> str:
    lines = ["graph TD"]
    lines.append("  classDef fact fill:#e1f5fe,stroke:#0288d1;")
    lines.append("  classDef intent fill:#fff3e0,stroke:#f57c00;")
    lines.append("  classDef goal fill:#e8f5e9,stroke:#388e3c;")

    goal_id = "G_%s" % project.id[:8]
    lines.append("  %s[\"目标: %s\"]" % (goal_id, _escape_mermaid(project.goal)))
    lines.append("  class %s goal;" % goal_id)

    origin_id = "O_%s" % project.id[:8]
    lines.append("  %s[\"起点: %s\"]" % (origin_id, _escape_mermaid(project.origin)))

    for f in project.facts:
        fid = "F_%s" % f.id
        desc = _escape_mermaid(f.description[:60])
        lines.append("  %s[\"%s\"]" % (fid, desc))
        lines.append("  class %s fact;" % fid)

    for i in project.intents:
        iid = "I_%s" % i.id
        desc = _escape_mermaid(i.description[:50])
        lines.append("  %s(\"%s\")" % (iid, desc))
        lines.append("  class %s intent;" % iid)

        from_id = "F_%s" % i.from_fact_id if i.from_fact_id else origin_id
        lines.append("  %s --> %s" % (from_id, iid))

    for f in project.facts:
        fid = "F_%s" % f.id
        lines.append("  %s --> %s" % (fid, goal_id))

    return "\n".join(lines)


def _escape_mermaid(text: str) -> str:
    return text.replace('"', "'").replace("(", "[").replace(")", "]")
