"""Lote de candles em colunas numpy: formato comum a todos os conectores."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
import numpy.typing as npt

from app.market.timeframes import from_epoch
from app.models.enums import Timeframe

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class CandleBatch:
    """Candles ordenados por tempo. `ts` é a abertura do candle (epoch em segundos, UTC)."""

    ts: IntArray
    open: FloatArray
    high: FloatArray
    low: FloatArray
    close: FloatArray
    volume: FloatArray
    spread: FloatArray  # NaN quando desconhecido

    def __len__(self) -> int:
        return int(self.ts.shape[0])

    @classmethod
    def empty(cls) -> "CandleBatch":
        f = np.empty(0, dtype=np.float64)
        return cls(np.empty(0, dtype=np.int64), f, f, f, f, f, f)

    @classmethod
    def concat(cls, batches: list["CandleBatch"]) -> "CandleBatch":
        batches = [b for b in batches if len(b)]
        if not batches:
            return cls.empty()
        return cls(
            *(
                np.concatenate([getattr(b, name) for b in batches])
                for name in ("ts", "open", "high", "low", "close", "volume", "spread")
            )
        )

    def select(self, mask: BoolArray | IntArray) -> "CandleBatch":
        """Seleciona linhas por máscara booleana ou por índices."""
        return CandleBatch(
            self.ts[mask],
            self.open[mask],
            self.high[mask],
            self.low[mask],
            self.close[mask],
            self.volume[mask],
            self.spread[mask],
        )

    def to_rows(self, symbol_id: UUID, timeframe: Timeframe) -> list[dict[str, Any]]:
        spread = [None if np.isnan(s) else float(s) for s in self.spread]
        return [
            {
                "symbol_id": symbol_id,
                "timeframe": timeframe,
                "ts": from_epoch(int(self.ts[i])),
                "open": float(self.open[i]),
                "high": float(self.high[i]),
                "low": float(self.low[i]),
                "close": float(self.close[i]),
                "volume": float(self.volume[i]),
                "spread": spread[i],
            }
            for i in range(len(self))
        ]
