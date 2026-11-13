from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import audit, users
from app.services.rate_limit import FailureLimiter

router = APIRouter(prefix="/api/v1/auth", tags=["autenticação"])

_settings = get_settings()
login_limiter = FailureLimiter(_settings.login_max_failures, _settings.login_failure_window_seconds)


def _issue_token(db: Session, email: str, password: str, ip: str | None) -> TokenResponse:
    key = f"{users.normalize_email(email)}|{ip}"
    if login_limiter.is_blocked(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login. Tente novamente mais tarde.",
        )
    user = users.authenticate(db, email=email, password=password)
    if user is None:
        login_limiter.register_failure(key)
        # O e-mail é registrado para auditoria; a senha informada nunca é registrada.
        audit.record(
            db,
            "auth.login_failed",
            details={"email": users.normalize_email(email)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_limiter.reset(key)
    audit.record(db, "auth.login", user_id=user.id, ip_address=ip)
    db.commit()
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: DbSession) -> UserOut:
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cadastro desabilitado.")
    try:
        user = users.register_user(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            ip_address=client_ip(request),
        )
    except users.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado.") from exc
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    return _issue_token(db, payload.email, payload.password, client_ip(request))


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession
) -> TokenResponse:
    """Fluxo OAuth2 password, usado pelo botão Authorize do Swagger UI."""
    return _issue_token(db, form.username, form.password, client_ip(request))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
