"""WebSocket de status: heartbeat autenticado, base para os fluxos em tempo real."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.api.deps import user_from_token
from app.api.routes.health import build_system_info
from app.db.session import get_sessionmaker

router = APIRouter()
logger = logging.getLogger("traderai.ws")

HEARTBEAT_SECONDS = 5.0
AUTH_TIMEOUT_SECONDS = 10.0


@router.websocket("/ws/status")
async def status_stream(websocket: WebSocket) -> None:
    """O cliente envia {"type": "auth", "token": "<jwt>"} como primeira mensagem.

    O token não vai na URL para não aparecer em logs de acesso ou proxies.
    """
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_SECONDS)
        token = message.get("token") if isinstance(message, dict) else None
        with get_sessionmaker()() as db:
            user = user_from_token(db, token if isinstance(token, str) else None)
        if user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        while True:
            info = build_system_info()
            await websocket.send_json({"type": "status", **info.model_dump(mode="json")})
            await asyncio.sleep(HEARTBEAT_SECONDS)
    except (WebSocketDisconnect, TimeoutError):
        return
    except ValueError:  # primeira mensagem não era JSON válido
        await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
