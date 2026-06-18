import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .models import Project, Fact, Intent, Hint, IntentStatus, ProjectStatus


class ProjectStore:
    def __init__(self, db_path="~/.osint-agent/projects.db"):
        db_path = Path(db_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                origin TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT DEFAULT '',
                confidence REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS intents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                description TEXT NOT NULL,
                from_fact_id TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS hints (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
        """)

    def create_project(self, project: Project) -> Project:
        with self._lock:
            self._db.execute(
                "INSERT INTO projects (id, origin, goal, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project.id, project.origin, project.goal, project.status.value,
                 project.created_at.isoformat(), project.updated_at.isoformat()),
            )
            self._db.commit()
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                return None
            project = self._row_to_project(row)
            self._load_relations(project)
        return project

    def list_projects(self) -> list:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
            projects = []
            for row in rows:
                p = self._row_to_project(row)
                self._load_relations(p)
                projects.append(p)
        return projects

    def save_project(self, project: Project) -> Project:
        from datetime import datetime, timezone
        with self._lock:
            project.updated_at = datetime.now(timezone.utc)
            self._db.execute(
                "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
                (project.status.value, project.updated_at.isoformat(), project.id),
            )
            self._save_relations(project)
            self._db.commit()
        return project

    def delete_project(self, project_id: str):
        with self._lock:
            for table in ["hints", "intents", "facts"]:
                self._db.execute("DELETE FROM %s WHERE project_id = ?" % table, (project_id,))
            self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self._db.commit()

    def _row_to_project(self, row) -> Project:
        from datetime import datetime
        return Project(
            id=row["id"],
            origin=row["origin"],
            goal=row["goal"],
            status=ProjectStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _load_relations(self, project: Project):
        rows = self._db.execute(
            "SELECT * FROM facts WHERE project_id = ? ORDER BY created_at",
            (project.id,),
        ).fetchall()
        facts = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"]) if isinstance(d["metadata"], str) else d["metadata"]
            facts.append(Fact(**d))
        project.facts = facts

        project.intents = [
            Intent(**dict(r)) for r in self._db.execute(
                "SELECT * FROM intents WHERE project_id = ? ORDER BY created_at",
                (project.id,),
            ).fetchall()
        ]
        project.hints = [
            Hint(**dict(r)) for r in self._db.execute(
                "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at",
                (project.id,),
            ).fetchall()
        ]

    def _save_relations(self, project: Project):
        self._db.execute("DELETE FROM facts WHERE project_id = ?", (project.id,))
        self._db.execute("DELETE FROM intents WHERE project_id = ?", (project.id,))
        self._db.execute("DELETE FROM hints WHERE project_id = ?", (project.id,))
        for f in project.facts:
            self._db.execute(
                "INSERT INTO facts (id, project_id, description, source, confidence, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f.id, project.id, f.description, f.source, f.confidence,
                 json.dumps(f.metadata), f.created_at.isoformat()),
            )
        for i in project.intents:
            self._db.execute(
                "INSERT INTO intents (id, project_id, description, from_fact_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (i.id, project.id, i.description, i.from_fact_id, i.status.value, i.created_at.isoformat()),
            )
        for h in project.hints:
            self._db.execute(
                "INSERT INTO hints (id, project_id, content, created_at) VALUES (?, ?, ?, ?)",
                (h.id, project.id, h.content, h.created_at.isoformat()),
            )

    def close(self):
        self._db.close()
