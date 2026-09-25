"""In-memory lead store. Same interface as a Postgres-backed repository would have,
so swapping storage never touches the agent or the API layer."""
from __future__ import annotations

import uuid

from app.models import Lead


class LeadStore:
    def __init__(self):
        self._leads: dict[str, Lead] = {}

    def create(self, source: str) -> Lead:
        lead = Lead(id=uuid.uuid4().hex[:8], source=source)
        self._leads[lead.id] = lead
        return lead

    def get(self, lead_id: str) -> Lead | None:
        return self._leads.get(lead_id)

    def list(self) -> list[Lead]:
        return list(self._leads.values())
