from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.core.serializers import model_to_dict
from app.modules.riders.service import RiderService

router = APIRouter()


def _with_document_link(row: dict) -> dict:
    """id_document_url stores a private storage path; hand out a short-lived link instead."""
    from app.modules.uploads.router import signed_url

    path = row.get("id_document_url")
    if path and not str(path).startswith("http"):
        row["id_document_url"] = signed_url("rider-documents", path)
    return row


def _serialize(entity):
    if entity is None:
        return None
    if isinstance(entity, list):
        return [_with_document_link(model_to_dict(item)) for item in entity]
    return _with_document_link(model_to_dict(entity))


@router.get("", status_code=status.HTTP_200_OK)
async def list_riders(
    rider_status: Optional[str] = Query(None, description="online, offline, busy"),
    vehicle_type: Optional[str] = Query(None, description="motorcycle, bicycle, car"),
    approval_status: Optional[str] = Query(None, description="pending, approved, rejected"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Admin: list riders. Filter by status or vehicle type."""
    riders = await RiderService.get_all_riders(db, rider_status=rider_status, vehicle_type=vehicle_type, approval_status=approval_status)
    from sqlalchemy.future import select
    from app.modules.users.models import UserProfile

    ids = [r.id for r in riders]
    profiles = {}
    if ids:
        res = await db.execute(select(UserProfile).where(UserProfile.user_id.in_(ids)))
        profiles = {p.user_id: p for p in res.scalars().all()}
        from sqlalchemy import text
        email_rows = await db.execute(
            text("select id::text, email from auth.users where id::text = any(:ids)"), {"ids": ids}
        )
        emails = dict(email_rows.all())
    data = []
    for r in riders:
        row = _with_document_link(model_to_dict(r))
        profile = profiles.get(r.id)
        row["full_name"] = profile.full_name if profile else None
        row["phone"] = profile.phone if profile else None
        row["avatar_url"] = profile.avatar_url if profile else None
        row["email"] = emails.get(r.id) if ids else None
        data.append(row)
    return {"success": True, "message": "Riders retrieved successfully", "data": data}


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_my_rider(db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("rider"))):
    """Rider: own profile plus earnings computed from completed deliveries."""
    rider = await RiderService.get_or_create_for_user(db, current_user["user_id"])
    await db.commit()
    earnings = await RiderService.get_earnings(db, current_user["user_id"])
    return {"success": True, "message": "Rider retrieved", "data": {**_serialize(rider), **earnings}}


@router.get("/me/deliveries", status_code=status.HTTP_200_OK)
async def get_my_deliveries(db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("rider"))):
    """Rider: Get all deliveries assigned to the current rider."""
    deliveries = await RiderService.get_deliveries(db, current_user["user_id"])
    return {"success": True, "message": "Rider deliveries retrieved", "data": _serialize(deliveries)}


@router.patch("/me/status", status_code=status.HTTP_200_OK)
async def update_rider_status(
    payload: Optional[dict] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("rider")),
):
    """Rider: Set online/offline, or toggle when no status is sent."""
    rider = await RiderService.update_status(db, current_user["user_id"], (payload or {}).get("status"))
    return {"success": True, "message": f"Rider is now {rider.status}", "data": _serialize(rider)}


@router.patch("/me", status_code=status.HTTP_200_OK)
async def update_my_rider(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("rider"))):
    """Rider: update vehicle type/plate or ID document (upload the image first, then send its URL)."""
    rider = await RiderService.update_me(db, current_user["user_id"], payload)
    return {"success": True, "message": "Rider details updated", "data": _serialize(rider)}


@router.post("/broadcast", status_code=status.HTTP_200_OK)
async def broadcast_to_riders(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: message riders in-app and by email. audience: approved (default) | online | pending | all."""
    audience = str(payload.get("audience") or "approved")
    riders = await RiderService.get_all_riders(
        db,
        rider_status="online" if audience == "online" else None,
        approval_status=None if audience == "all" else ("approved" if audience == "online" else audience),
    )
    sent = await RiderService.message(db, [r.id for r in riders], payload.get("title"), payload.get("body"), current_user["user_id"])
    return {"success": True, "message": f"Message sent to {sent} rider(s)", "data": {"sent": sent}}


@router.post("/{rider_id}/message", status_code=status.HTTP_200_OK)
async def message_rider(rider_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: send one rider a message (in-app + email)."""
    await RiderService.get_by_id(db, rider_id)
    await RiderService.message(db, [rider_id], payload.get("title"), payload.get("body"), current_user["user_id"])
    return {"success": True, "message": "Message sent", "data": None}


@router.patch("/{rider_id}/review", status_code=status.HTTP_200_OK)
async def review_rider(rider_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: approve or reject a rider's onboarding. Body: {decision: approve|reject, note?}."""
    rider = await RiderService.review(db, rider_id, str(payload.get("decision") or ""), payload.get("note"), current_user["user_id"])
    return {"success": True, "message": f"Rider {rider.approval_status}", "data": _serialize(rider)}


@router.get("/{rider_id}", status_code=status.HTTP_200_OK)
async def get_rider(
    rider_id: str = Path(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single rider's profile by ID."""
    roles = current_user.get("roles") or []
    if rider_id != current_user["user_id"] and "admin" not in roles and "super_admin" not in roles:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this rider")
    rider = await RiderService.get_by_id(db, rider_id)
    return {"success": True, "message": "Rider retrieved", "data": _serialize(rider)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rider_profile(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("rider"))):
    """Register the authenticated user as a rider on the platform."""
    rider = await RiderService.create_rider(db, current_user["user_id"], payload)
    return {"success": True, "message": "Rider registered successfully", "data": _serialize(rider)}


@router.patch("/{rider_id}/deactivate", status_code=status.HTTP_200_OK)
@router.delete("/{rider_id}", status_code=status.HTTP_200_OK)
async def deactivate_rider(rider_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: Soft-deactivate a rider account."""
    await RiderService.deactivate(db, rider_id)
    return {"success": True, "message": "Rider deactivated", "data": None}
