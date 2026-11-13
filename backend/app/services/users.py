"""Cadastro e autenticação de usuários."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.base import utcnow
from app.models import Alert, RiskRule, Role, SimulationAccount, User
from app.models.enums import AlertSeverity, SimulationStatus
from app.services import audit
from app.services.catalog import DEFAULT_RISK_RULES, ROLE_ADMIN, ROLE_TRADER

# Hash usado para igualar o tempo de resposta quando o e-mail não existe.
_DUMMY_HASH = hash_password("traderai-dummy-password")


class EmailAlreadyRegisteredError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def register_user(
    db: Session, *, email: str, password: str, full_name: str | None, ip_address: str | None = None
) -> User:
    email = normalize_email(email)
    if get_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError

    # O primeiro usuário do sistema torna-se administrador; os demais, traders.
    is_first = db.scalar(select(func.count()).select_from(User)) == 0
    role = db.scalar(select(Role).where(Role.name == (ROLE_ADMIN if is_first else ROLE_TRADER)))
    if role is None:
        raise RuntimeError("Papéis não inicializados: execute as migrations e o seed.")

    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role_id=role.id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # corrida entre dois cadastros com o mesmo e-mail
        db.rollback()
        raise EmailAlreadyRegisteredError from exc

    _provision_workspace(db, user)
    audit.record(
        db,
        "user.registered",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"role": role.name},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(user)
    return user


def _provision_workspace(db: Session, user: User) -> None:
    """Cria a conta de simulação, regras de risco padrão e o alerta de boas-vindas."""
    settings = get_settings()
    balance = Decimal(str(settings.default_simulation_balance))
    account = SimulationAccount(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Conta de simulação principal",
        currency=settings.default_simulation_currency,
        initial_balance=balance,
        balance=balance,
        equity=balance,
        peak_equity=balance,
        status=SimulationStatus.PAUSED,
        status_reason="Simulador ainda não iniciado.",
    )
    db.add(account)
    db.flush()
    for rule_type, value, description in DEFAULT_RISK_RULES:
        db.add(
            RiskRule(
                user_id=user.id,
                account_id=account.id,
                rule_type=rule_type,
                value=value,
                description=description,
            )
        )
    db.add(
        Alert(
            user_id=user.id,
            severity=AlertSeverity.INFO,
            category="system",
            title="Bem-vindo ao TraderAI Pro",
            message=(
                "Sua conta de simulação foi criada com capital fictício. "
                "Nenhuma ordem real é enviada por esta plataforma."
            ),
        )
    )


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = get_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    user.last_login_at = utcnow()
    return user
