import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import DbSession, client_ip, require_permission
from app.models import AuditLog, Role, User
from app.schemas.auth import RoleOut, UserOut, UserUpdate
from app.schemas.core import AuditLogOut
from app.services import audit
from app.services.catalog import ROLE_ADMIN

router = APIRouter(prefix="/api/v1/admin", tags=["administração"])

UsersAdmin = Annotated[User, Depends(require_permission("admin:users"))]
AuditAdmin = Annotated[User, Depends(require_permission("admin:audit"))]


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: UsersAdmin) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)))


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession, _: UsersAdmin) -> list[Role]:
    return list(db.scalars(select(Role).order_by(Role.name)))


def _active_admin_count(db: DbSession) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .join(Role)
            .where(Role.name == ROLE_ADMIN, User.is_active)
        )
        or 0
    )


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, request: Request, db: DbSession, admin: UsersAdmin
) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")

    changes: dict[str, object] = {}
    new_role = target.role
    if payload.role is not None and payload.role != target.role.name:
        found = db.scalar(select(Role).where(Role.name == payload.role))
        if found is None:
            raise HTTPException(422, "Papel inexistente.")
        new_role = found
        changes["role"] = {"from": target.role.name, "to": found.name}
    new_active = target.is_active if payload.is_active is None else payload.is_active
    if new_active != target.is_active:
        changes["is_active"] = {"from": target.is_active, "to": new_active}

    # Nunca deixar o sistema sem administrador ativo.
    loses_admin = (
        target.role.name == ROLE_ADMIN
        and target.is_active
        and (new_role.name != ROLE_ADMIN or not new_active)
    )
    if loses_admin and _active_admin_count(db) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "É necessário manter ao menos um administrador ativo."
        )

    if changes:
        target.role = new_role
        target.is_active = new_active
        audit.record(
            db,
            "admin.user_updated",
            user_id=admin.id,
            entity_type="user",
            entity_id=target.id,
            details=changes,
            ip_address=client_ip(request),
        )
        db.commit()
        db.refresh(target)
    return target


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    db: DbSession,
    _: AuditAdmin,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: str | None = None,
) -> list[AuditLog]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit)))
