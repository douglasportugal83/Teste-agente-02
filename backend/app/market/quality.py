"""Validação de candles recebidos e avaliação de qualidade de uma série.

`validate_batch` decide o que pode ser gravado: linhas inválidas são REJEITADAS e contadas,
nunca corrigidas em silêncio. `assess_quality` descreve uma série já armazenada.
"""

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.market.candles import BoolArray, CandleBatch
from app.market.timeframes import TIMEFRAME_SECONDS, bucket_origin, from_epoch, to_epoch
from app.models.enums import Timeframe

DAY = 86_400
# Limiar alto de propósito: volatilidade varia muito entre sessões e regimes, e um limiar
# baixo marcaria movimentos legítimos como erro.
OUTLIER_SIGMAS = 25.0
MAX_EXAMPLES = 5


@dataclass
class ValidationResult:
    batch: CandleBatch  # somente linhas válidas, ordenadas e sem duplicatas
    rows_read: int
    rejected: dict[str, int] = field(default_factory=dict)

    @property
    def rows_rejected(self) -> int:
        return sum(self.rejected.values())


def validate_batch(
    batch: CandleBatch, timeframe: Timeframe, now: datetime | None = None
) -> ValidationResult:
    n = len(batch)
    rejected: dict[str, int] = {}
    keep = np.ones(n, dtype=bool)

    def reject(reason: str, bad: BoolArray) -> None:
        nonlocal keep
        newly = bad & keep
        if newly.any():
            rejected[reason] = int(newly.sum())
            keep &= ~bad

    prices = np.stack([batch.open, batch.high, batch.low, batch.close])
    reject("valor_nao_numerico", ~np.isfinite(prices).all(axis=0) | ~np.isfinite(batch.volume))
    with np.errstate(invalid="ignore"):
        reject("preco_nao_positivo", (prices <= 0).any(axis=0))
        reject(
            "ohlc_inconsistente",
            (batch.high < np.maximum(batch.open, batch.close))
            | (batch.low > np.minimum(batch.open, batch.close)),
        )
        reject("volume_negativo", batch.volume < 0)
    size, origin = TIMEFRAME_SECONDS[timeframe], bucket_origin(timeframe)
    reject("horario_desalinhado", (batch.ts - origin) % size != 0)
    if now is not None:
        # Candle ainda em formação (ou no futuro) causaria look-ahead.
        reject("candle_nao_fechado", batch.ts + size > to_epoch(now))

    valid = batch.select(keep)
    order = np.argsort(valid.ts, kind="stable")
    valid = valid.select(order)
    if len(valid):
        # Em duplicatas de horário, prevalece a última linha recebida.
        last_of_run = np.append(valid.ts[1:] != valid.ts[:-1], True)
        duplicates = int((~last_of_run).sum())
        if duplicates:
            rejected["horario_duplicado"] = duplicates
            valid = valid.select(last_of_run)
    return ValidationResult(batch=valid, rows_read=n, rejected=rejected)


@dataclass
class QualityIssue:
    code: str
    severity: str  # info | warning | critical
    message: str
    count: int
    examples: list[datetime] = field(default_factory=list)


@dataclass
class QualityReport:
    candles: int
    first_ts: datetime | None
    last_ts: datetime | None
    expected_candles: int
    completeness_pct: float
    is_stale: bool
    last_candle_age_seconds: int | None
    score: int  # 0–100
    issues: list[QualityIssue]


def _expected_mask(ts: np.ndarray, always_open: bool) -> BoolArray:
    """Horários em que se espera candle. Mercados não 24/7: sem sábado e domingo (UTC)."""
    if always_open:
        return np.ones(ts.shape, dtype=bool)
    weekday = (ts // DAY + 3) % 7  # 0 = segunda
    return np.asarray(weekday < 5)


def assess_quality(
    batch: CandleBatch, timeframe: Timeframe, *, always_open: bool, now: datetime
) -> QualityReport:
    n = len(batch)
    size = TIMEFRAME_SECONDS[timeframe]
    if n == 0:
        issue = QualityIssue("sem_dados", "critical", "Não há candles armazenados.", 0)
        return QualityReport(0, None, None, 0, 0.0, True, None, 0, [issue])

    issues: list[QualityIssue] = []
    ts = batch.ts

    def examples(idx: np.ndarray) -> list[datetime]:
        return [from_epoch(int(t)) for t in ts[idx][:MAX_EXAMPLES]]

    # Lacunas: candles esperados e ausentes entre o primeiro e o último.
    grid = np.arange(ts[0], ts[-1] + size, size)
    grid = grid[_expected_mask(grid, always_open or timeframe is Timeframe.W1)]
    expected = int(grid.size)
    missing = np.setdiff1d(grid, ts, assume_unique=True)
    completeness = 100.0 * (expected - missing.size) / expected if expected else 100.0
    if missing.size:
        ratio = missing.size / expected
        severity = "critical" if ratio > 0.05 else "warning" if ratio > 0.005 else "info"
        issues.append(
            QualityIssue(
                "lacunas",
                severity,
                f"{missing.size} candle(s) ausente(s) de {expected} esperados "
                "(feriados e pausas de mercado contam como lacuna).",
                int(missing.size),
                [from_epoch(int(t)) for t in missing[:MAX_EXAMPLES]],
            )
        )

    # Variações anômalas: retorno muito acima da dispersão robusta (MAD) da série.
    if n > 30:
        returns = np.diff(np.log(batch.close))
        mad = float(np.median(np.abs(returns - np.median(returns))))
        if mad > 0:
            outliers = np.flatnonzero(np.abs(returns) > OUTLIER_SIGMAS * 1.4826 * mad) + 1
            if outliers.size:
                issues.append(
                    QualityIssue(
                        "variacao_anomala",
                        "warning",
                        f"{outliers.size} candle(s) com variação acima de "
                        f"{OUTLIER_SIGMAS:.0f} desvios robustos; pode ser erro de dado "
                        "ou evento real.",
                        int(outliers.size),
                        examples(outliers),
                    )
                )

    flat = np.flatnonzero((batch.high == batch.low) & (batch.volume == 0))
    if flat.size > 0.02 * n:
        issues.append(
            QualityIssue(
                "candles_sem_negociacao",
                "warning",
                f"{flat.size} candle(s) sem variação e sem volume.",
                int(flat.size),
                examples(flat),
            )
        )
    if float(np.nanmax(batch.volume)) == 0.0:
        issues.append(
            QualityIssue(
                "sem_volume",
                "info",
                "A fonte não fornece volume; indicadores baseados em volume ficam indisponíveis.",
                n,
            )
        )

    # Dado atrasado: o último candle fechado deveria ser recente (folga para fim de semana).
    age = to_epoch(now) - int(ts[-1]) - size
    tolerance = 3 * size + (0 if always_open else 3 * DAY)
    is_stale = age > tolerance
    if is_stale:
        issues.append(
            QualityIssue(
                "dados_atrasados",
                "critical",
                f"O último candle fechou há {age // 3600} h; a série não está atualizada.",
                1,
                [from_epoch(int(ts[-1]))],
            )
        )

    penalty = {"info": 0, "warning": 10, "critical": 30}
    score = 100 - sum(penalty[i.severity] for i in issues) - round(100.0 - completeness)
    return QualityReport(
        candles=n,
        first_ts=from_epoch(int(ts[0])),
        last_ts=from_epoch(int(ts[-1])),
        expected_candles=expected,
        completeness_pct=round(completeness, 2),
        is_stale=is_stale,
        last_candle_age_seconds=max(age, 0),
        score=max(0, min(100, score)),
        issues=issues,
    )
