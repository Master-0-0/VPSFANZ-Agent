import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class IntentStatus(str, Enum):
    pending = "pending"
    claimed = "claimed"
    completed = "completed"
    failed = "failed"


class ProjectStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str
    source: str = ""
    confidence: float = 1.0
    metadata: Dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Intent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str
    from_fact_id: str = ""
    status: IntentStatus = IntentStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Hint(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    origin: str
    goal: str
    status: ProjectStatus = ProjectStatus.running
    facts: List[Fact] = Field(default_factory=list)
    intents: List[Intent] = Field(default_factory=list)
    hints: List[Hint] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def open_intents(self) -> List[Intent]:
        return [i for i in self.intents if i.status == IntentStatus.pending]

    @property
    def completed_intents(self) -> List[Intent]:
        return [i for i in self.intents if i.status == IntentStatus.completed]

    @property
    def failed_intents(self) -> List[Intent]:
        return [i for i in self.intents if i.status == IntentStatus.failed]

    def add_fact(self, description: str, source: str = "", confidence: float = 1.0, metadata: Optional[Dict] = None) -> Fact:
        fact = Fact(
            description=description,
            source=source,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.facts.append(fact)
        self.updated_at = datetime.now(timezone.utc)
        return fact

    def add_intent(self, description: str, from_fact_id: str = "") -> Intent:
        intent = Intent(description=description, from_fact_id=from_fact_id)
        self.intents.append(intent)
        self.updated_at = datetime.now(timezone.utc)
        return intent

    def add_hint(self, content: str) -> Hint:
        hint = Hint(content=content)
        self.hints.append(hint)
        self.updated_at = datetime.now(timezone.utc)
        return hint

    def claim_intent(self, intent_id: str) -> Optional[Intent]:
        for i in self.intents:
            if i.id == intent_id and i.status == IntentStatus.pending:
                i.status = IntentStatus.claimed
                self.updated_at = datetime.now(timezone.utc)
                return i
        return None

    def complete_intent(self, intent_id: str) -> Optional[Intent]:
        for i in self.intents:
            if i.id == intent_id and i.status == IntentStatus.claimed:
                i.status = IntentStatus.completed
                self.updated_at = datetime.now(timezone.utc)
                return i
        return None

    def fail_intent(self, intent_id: str) -> Optional[Intent]:
        for i in self.intents:
            if i.id == intent_id:
                i.status = IntentStatus.failed
                self.updated_at = datetime.now(timezone.utc)
                return i
        return None

    def graph_yaml(self) -> str:
        lines = ["graph:"]
        for f in self.facts:
            lines.append("  - fact: %s" % f.id)
            lines.append("    description: %s" % f.description)
        for i in self.intents:
            lines.append("  - intent: %s" % i.id)
            lines.append("    description: %s" % i.description)
            lines.append("    from: %s" % i.from_fact_id)
            lines.append("    status: %s" % i.status.value)
        return "\n".join(lines)
