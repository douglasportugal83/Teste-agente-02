"""Executa o motor do terminal em tempo real, numa thread dentro da API."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from app.binary.engine import BinaryEngine, EngineConfig

logger = logging.getLogger("traderai.terminal")

WARMUP_STEP_SECONDS = 0.5


class TerminalService:
    """Mantém um `BinaryEngine` andando no relógio de parede e publica o último snapshot.

    Ao iniciar, simula `warmup_seconds` de passado em ritmo acelerado para a tela não nascer
    vazia. Esse histórico é tão sintético quanto o restante — e se perde ao reiniciar a API.
    """

    def __init__(
        self,
        config: EngineConfig | None = None,
        warmup_seconds: float = 3600.0,
        tick_seconds: float = 0.25,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._tick = tick_seconds
        self._engine = BinaryEngine(config, start_time=clock() - warmup_seconds)
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def warm_up(self) -> None:
        """Avança o motor até o presente (o relógio continua andando durante o cálculo)."""
        engine = self._engine
        while not self._stop.is_set():
            target = self._clock()
            if engine.t + WARMUP_STEP_SECONDS > target:
                break
            engine.step(engine.t + WARMUP_STEP_SECONDS)
        self.advance()

    def advance(self) -> None:
        self._engine.step(self._clock())
        snapshot = self._engine.snapshot()
        with self._lock:
            self._snapshot = snapshot

    def snapshot(self) -> dict[str, Any] | None:
        """Último estado publicado; `None` enquanto o aquecimento não terminou."""
        with self._lock:
            return self._snapshot

    def _loop(self) -> None:
        try:
            self.warm_up()
            while not self._stop.wait(self._tick):
                self.advance()
        except Exception:
            logger.exception("terminal_engine_crashed")
            with self._lock:
                self._snapshot = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="terminal-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


_service: TerminalService | None = None


def set_terminal_service(service: TerminalService | None) -> None:
    global _service
    _service = service


def get_terminal_service() -> TerminalService | None:
    return _service
