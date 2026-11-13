"""Terminal do robô de mercados binários simulados: snapshot REST e fluxo WebSocket."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from app.api.deps import require_permission, user_from_token
from app.binary.service import get_terminal_service
from app.db.session import get_sessionmaker
from app.models import User

router = APIRouter(tags=["terminal"])

PERMISSION = "dashboard:read"
STREAM_INTERVAL_SECONDS = 0.25
AUTH_TIMEOUT_SECONDS = 10.0

TerminalUser = Annotated[User, Depends(require_permission(PERMISSION))]


@router.get(
    "/api/v1/terminal/snapshot",
    summary="Estado atual do terminal (mundo sintético e robô simulado)",
)
def terminal_snapshot(_: TerminalUser) -> dict[str, Any]:
    service = get_terminal_service()
    if service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "O motor do terminal está desligado (TERMINAL_ENGINE_ENABLED=false).",
        )
    snapshot = service.snapshot()
    if snapshot is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "O motor do terminal ainda está aquecendo. Tente novamente em instantes.",
            headers={"Retry-After": "2"},
        )
    return snapshot


@router.websocket("/ws/terminal")
async def terminal_stream(websocket: WebSocket) -> None:
    """Primeira mensagem do cliente: {"type": "auth", "token": "<jwt>"} (como em /ws/status)."""
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_SECONDS)
        token = message.get("token") if isinstance(message, dict) else None
        with get_sessionmaker()() as db:
            user = user_from_token(db, token if isinstance(token, str) else None)
            allowed = user is not None and PERMISSION in (user.role.permissions or [])
        if not allowed:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        last_ts: float | None = None
        while True:
            service = get_terminal_service()
            snapshot = service.snapshot() if service is not None else None
            if service is None:
                await websocket.send_json({"type": "disabled"})
                await websocket.close()
                return
            if snapshot is None:
                await websocket.send_json({"type": "warming"})
            elif snapshot["ts"] != last_ts:
                last_ts = snapshot["ts"]
                await websocket.send_json({"type": "snapshot", "data": snapshot})
            await asyncio.sleep(STREAM_INTERVAL_SECONDS)
    except (WebSocketDisconnect, TimeoutError):
        return
    except ValueError:  # primeira mensagem não era JSON válido
        await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
