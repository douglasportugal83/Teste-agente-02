"""Leitura de históricos em CSV e Parquet para um CandleBatch.

Aceita cabeçalhos comuns (time/date/datetime/timestamp, open/high/low/close, volume) e o
formato de exportação do MetaTrader 5 (<DATE> <TIME> <OPEN> ... <TICKVOL> <VOL> <SPREAD>).
"""

import io
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from app.market.candles import CandleBatch


class ImportFormatError(ValueError):
    """Arquivo ilegível ou sem as colunas necessárias."""


_ALIASES: dict[str, tuple[str, ...]] = {
    "datetime": ("datetime", "timestamp", "time", "date", "ts", "data", "datahora"),
    "open": ("open", "o", "abertura"),
    "high": ("high", "h", "max", "maxima"),
    "low": ("low", "l", "min", "minima"),
    "close": ("close", "c", "fechamento", "last"),
    "volume": ("volume", "tickvol", "tick_volume", "vol"),
    "spread": ("spread",),
}


def _normalize(name: object) -> str:
    return re.sub(r"[^a-z_]", "", str(name).strip().lower().replace(" ", "_"))


def _read_frame(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith((".parquet", ".pq")):
            return pd.read_parquet(io.BytesIO(content))
        if lower.endswith((".csv", ".txt", ".tsv")):
            # sep=None faz o pandas detectar vírgula, ponto e vírgula ou tabulação.
            return pd.read_csv(io.BytesIO(content), sep=None, engine="python")
    except Exception as exc:  # pandas/pyarrow levantam tipos variados para arquivo corrompido
        raise ImportFormatError(f"Não foi possível ler o arquivo: {exc}") from exc
    raise ImportFormatError("Formato não suportado: use .csv ou .parquet.")


def _to_utc_epoch(series: pd.Series, source_tz: str) -> np.ndarray:
    try:
        zone = ZoneInfo(source_tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ImportFormatError(f"Fuso horário desconhecido: {source_tz}") from exc

    if pd.api.types.is_numeric_dtype(series):
        # Epoch em segundos ou milissegundos (sempre UTC).
        values = series.astype("float64")
        if float(values.abs().max()) > 1e11:
            values = values / 1000.0
        parsed = pd.to_datetime(values, unit="s", utc=True, errors="coerce")
    else:
        text = series.astype(str).str.strip().str.replace(".", "-", regex=False)
        parsed = pd.to_datetime(text, errors="coerce", format="mixed")
        if parsed.dt.tz is None:
            # Horários locais inexistentes/ambíguos na virada do horário de verão viram NaT
            # e são rejeitados, em vez de serem deslocados em silêncio.
            parsed = parsed.dt.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
        parsed = parsed.dt.tz_convert("UTC")
    if parsed.isna().any():
        raise ImportFormatError(
            f"{int(parsed.isna().sum())} linha(s) com data/hora inválida, inexistente ou ambígua "
            f"no fuso {source_tz}."
        )
    epoch = parsed.astype("datetime64[s, UTC]").astype("int64")
    return np.asarray(epoch, dtype=np.int64)


def parse_candle_file(content: bytes, filename: str, source_tz: str = "UTC") -> CandleBatch:
    frame = _read_frame(content, filename)
    if frame.empty:
        raise ImportFormatError("O arquivo não contém linhas.")
    frame.columns = [_normalize(c) for c in frame.columns]

    # Exportação do MT5 traz data e hora em colunas separadas.
    if "date" in frame.columns and "time" in frame.columns:
        frame["datetime"] = frame["date"].astype(str) + " " + frame["time"].astype(str)
        frame = frame.drop(columns=["date", "time"])

    columns: dict[str, str] = {}
    for target, aliases in _ALIASES.items():
        found = next((a for a in aliases if a in frame.columns), None)
        if found is not None:
            columns[target] = found
    missing = [c for c in ("datetime", "open", "high", "low", "close") if c not in columns]
    if missing:
        raise ImportFormatError(
            f"Colunas obrigatórias ausentes: {', '.join(missing)}. "
            f"Colunas encontradas: {', '.join(map(str, frame.columns))}."
        )

    def numeric(target: str) -> np.ndarray:
        if target not in columns:
            return np.full(len(frame), np.nan if target == "spread" else 0.0)
        values = pd.to_numeric(frame[columns[target]], errors="coerce")
        return np.asarray(values, dtype=np.float64)

    return CandleBatch(
        ts=_to_utc_epoch(frame[columns["datetime"]], source_tz),
        open=numeric("open"),
        high=numeric("high"),
        low=numeric("low"),
        close=numeric("close"),
        volume=numeric("volume"),
        spread=numeric("spread"),
    )
