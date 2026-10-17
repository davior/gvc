"""SQLModel tables.

Every table must be imported here: Alembic's autogenerate only sees what is registered
on `SQLModel.metadata` at import time, so a table missing from this list produces an
empty migration and a silent schema drift.
"""

from app.models.assistant import AssistantSession, AssistantTurn
from app.models.generation import Generation
from app.models.project import Project, ProjectVersion
from app.models.provider import AIProvider
from app.models.render import RenderJob
from app.models.usage import UsageEvent
from app.models.user import User

__all__ = ["AIProvider", "AssistantSession", "AssistantTurn", "Generation", "Project", "ProjectVersion", "RenderJob", "UsageEvent", "User"]
