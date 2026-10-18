"""Admin activity log (audit_logs). Call record() before the caller's commit."""
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession


def record(
    db: AsyncSession,
    actor: dict | str,
    action: str,
    entity_type: str,
    entity_id: Any,
    details: Optional[dict] = None,
) -> None:
    from app.modules.audit.models import AuditLog

    actor_id = actor.get("user_id") if isinstance(actor, dict) else str(actor)
    db.add(AuditLog(
        actor=str(actor_id or "system")[:255],
        action=action[:100],
        entity_type=entity_type[:50],
        entity_id=str(entity_id)[:255],
        action_metadata=details or None,
    ))
