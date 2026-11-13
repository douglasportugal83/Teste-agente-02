"""Motor do terminal: mundo sintético + robô "direcional tardio" em mercados binários.

O mundo
-------
* **Spot** BTC/USD: passeio log-normal com volatilidade estocástica (regimes calmos/agitados).
* **Perp**: spot mais uma base (basis) que oscila em torno de um pequeno prêmio.
* **Oráculo**: republica o spot em degraus, com atraso — é ele que define a referência de
  abertura e o resultado de cada mercado.
* **Mercados** "BTC Sobe/Desce" de 5 e 15 minutos, alinhados ao relógio. Cada cota paga $1 se
  o lado acertar. O livro cota uma probabilidade implícita que persegue o modelo **com atraso**
  (`book_lag_seconds`).

O robô
------
Observa os últimos minutos de cada mercado e compra o lado líder (P do modelo alta) quando a
oferta está abaixo da probabilidade do modelo; carrega até a liquidação.

Importante: o lucro simulado nasce da hipótese de que o livro reage mais devagar que o modelo.
Isso é uma premissa do mundo sintético, não uma evidência de que a estratégia funcione em
mercados reais.

O motor é determinístico: mesma semente e mesma sequência de `step(now)` → mesmo resultado.
"""

import math
import random
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.binary.model import SECONDS_PER_YEAR, prob_up, reach_usd

UP = "UP"
DOWN = "DOWN"
SIDE_LABEL = {UP: "SOBE", DOWN: "DESCE"}
TICK = 0.01  # passo de preço das cotas, em dólares
BOOK_LEVELS = 4


@dataclass(frozen=True)
class EngineConfig:
    seed: int = 7
    start_price: float = 87_000.0
    annual_vol: float = 0.55
    durations: tuple[int, ...] = (300, 900)
    # --- robô ---
    watch_seconds: float = 240.0  # só observa/compra nesta janela final
    min_leader_p: float = 0.80  # o líder precisa ter pelo menos esta P do modelo
    min_edge: float = 0.01  # vantagem mínima (P do modelo − oferta), no vencimento
    edge_decay_seconds: float = 45.0  # quanto mais longe do fim, mais vantagem é exigida
    max_ask: float = 0.98
    max_stake_per_market: float = 600.0
    median_chunk_usd: float = 14.0
    # --- mundo ---
    book_lag_seconds: float = 2.5
    half_spread: float = 0.005
    oracle_interval: float = 1.0
    oracle_latency: tuple[float, float] = (0.35, 1.1)


@dataclass
class Fill:
    seq: int
    ts: float
    market_id: str
    label: str
    side: str
    kind: str  # ENTRY | ADD | HEDGE | FLIP
    price: float
    usd: float
    shares: float
    p_model: float
    edge: float
    t_left: float
    d: float  # spot − referência no momento da compra
    pnl: float | None = None  # preenchido na liquidação

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": round(self.ts, 3),
            "market": self.label,
            "side": self.side,
            "kind": self.kind,
            "price": self.price,
            "usd": round(self.usd, 2),
            "shares": round(self.shares, 2),
            "p_model": round(self.p_model, 4),
            "edge": round(self.edge, 4),
            "t_left": round(self.t_left, 1),
            "d": round(self.d, 2),
            "pnl": None if self.pnl is None else round(self.pnl, 2),
        }


@dataclass
class Market:
    id: str
    label: str
    duration: int
    start: float
    end: float
    reference: float
    implied: float = 0.5  # P(sobe) implícita no livro
    p_up: float = 0.5
    shares: dict[str, float] = field(default_factory=lambda: {UP: 0.0, DOWN: 0.0})
    cost: dict[str, float] = field(default_factory=lambda: {UP: 0.0, DOWN: 0.0})
    fills: list[Fill] = field(default_factory=list)
    ask_sizes: dict[str, list[float]] = field(default_factory=dict)
    bid_sizes: dict[str, list[float]] = field(default_factory=dict)
    best_ask: dict[str, float] = field(default_factory=dict)
    next_action_at: float = 0.0
    first_entry_left: float | None = None
    leader: str = UP
    flips_late: int = 0
    path: list[tuple[float, float, float]] = field(default_factory=list)
    last_path_at: float = -1.0

    @property
    def stake(self) -> float:
        return self.cost[UP] + self.cost[DOWN]


def _ceil_tick(value: float) -> float:
    return round(min(0.99, max(TICK, math.ceil(round(value / TICK, 6)) * TICK)), 2)


class BinaryEngine:
    def __init__(self, config: EngineConfig | None = None, start_time: float = 0.0) -> None:
        self.config = config or EngineConfig()
        self.rng = random.Random(self.config.seed)  # noqa: S311 — simulação, não criptografia
        self.t = start_time
        self.started_at = start_time
        self.spot = self.config.start_price
        self.base_sigma = self.config.annual_vol / math.sqrt(SECONDS_PER_YEAR)
        self._log_vol = 0.0
        self._model_var = self.base_sigma**2
        self._basis = 0.00005
        self.perp = self.spot * (1 + self._basis)
        self.oracle = self.spot
        self.oracle_source_ts = start_time
        self._next_oracle = start_time
        self._spot_trail: deque[tuple[float, float]] = deque(maxlen=64)

        self.markets: dict[int, Market] = {}
        self.fills: deque[Fill] = deque(maxlen=20_000)
        self.settled: deque[dict[str, Any]] = deque(maxlen=500)
        self.first_entries: deque[float] = deque(maxlen=2_000)
        self.realized_pnl = 0.0
        self.total_fills = 0
        self.markets_traded = 0
        self.markets_won = 0

        self.candles: deque[list[float]] = deque(maxlen=90)  # [minuto, o, h, l, c]
        self.feed_series: deque[tuple[float, float, float, float]] = deque(maxlen=240)
        self._next_feed_sample = start_time
        self.inputs: deque[tuple[float, ...]] = deque(maxlen=90)
        self._next_input_sample = start_time
        self.late_hist = [0.0] * 24  # dólares comprados por faixa de 10 s até o vencimento

        self.wire: deque[dict[str, Any]] = deque(maxlen=40)
        self.wire_seq = 0
        self.wire_bytes = 0
        self._wire_times: deque[float] = deque(maxlen=4_000)
        self.events: deque[dict[str, Any]] = deque(maxlen=24)
        self._stats_cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------ mundo
    @property
    def model_sigma(self) -> float:
        return math.sqrt(self._model_var)

    def step(self, now: float) -> None:
        dt = now - self.t
        if dt <= 0:
            return
        self.t = now
        rng = self.rng

        # Volatilidade estocástica: log do multiplicador reverte à média.
        self._log_vol += -0.02 * self._log_vol * dt + 0.06 * math.sqrt(dt) * rng.gauss(0, 1)
        self._log_vol = max(-1.0, min(1.2, self._log_vol))
        sigma = self.base_sigma * math.exp(self._log_vol)
        log_return = sigma * math.sqrt(dt) * rng.gauss(0, 1)
        self.spot *= math.exp(log_return)

        # O modelo não conhece a volatilidade verdadeira: estima por média móvel exponencial.
        alpha = 1 - math.exp(-dt / 120.0)
        self._model_var += (log_return**2 / dt - self._model_var) * alpha
        self._model_var = max(self._model_var, (0.5 * self.base_sigma) ** 2)

        self._basis += (0.00005 - self._basis) * 0.05 * dt + 0.00002 * math.sqrt(dt) * rng.gauss(
            0, 1
        )
        self.perp = self.spot * (1 + self._basis)
        self._spot_trail.append((now, self.spot))
        self._update_oracle(now)
        self._update_candles(now)

        if now >= self._next_feed_sample:
            self.feed_series.append((now, self.spot, self.perp, self.oracle))
            self._next_feed_sample = now + 0.5

        for duration in self.config.durations:
            market = self.markets.get(duration)
            if market is not None and now >= market.end:
                self._settle(market)
                market = None
            if market is None:
                market = self._open_market(duration, now)
            self._update_market(market, now, dt)

        self._sample_inputs(now)

    def _update_oracle(self, now: float) -> None:
        if now < self._next_oracle:
            return
        lo, hi = self.config.oracle_latency
        source_ts = now - self.rng.uniform(lo, hi)
        price = self._spot_trail[0][1]
        for ts, value in self._spot_trail:
            if ts > source_ts:
                break
            price = value
        self.oracle = price
        self.oracle_source_ts = min(source_ts, now)
        self._next_oracle = now + self.config.oracle_interval * self.rng.uniform(0.7, 1.3)
        self._emit("oracle", "oracle_update", {"px": round(price, 2)})

    def _update_candles(self, now: float) -> None:
        minute = math.floor(now / 60) * 60.0
        if not self.candles or self.candles[-1][0] != minute:
            self.candles.append([minute, self.spot, self.spot, self.spot, self.spot])
            return
        candle = self.candles[-1]
        candle[2] = max(candle[2], self.spot)
        candle[3] = min(candle[3], self.spot)
        candle[4] = self.spot

    # --------------------------------------------------------------- mercados
    def _open_market(self, duration: int, now: float) -> Market:
        start = math.floor(now / duration) * float(duration)
        label = f"BTC {duration // 60}M"
        market = Market(
            id=f"BTC-{duration // 60}M-{int(start)}",
            label=label,
            duration=duration,
            start=start,
            end=start + duration,
            reference=self.oracle,
        )
        for side in (UP, DOWN):
            market.ask_sizes[side] = [self._level_size() for _ in range(BOOK_LEVELS)]
            market.bid_sizes[side] = [self._level_size() for _ in range(BOOK_LEVELS)]
        self._requote(market)
        self.markets[duration] = market
        self._emit("market", "new_market", {"m": market.id, "ref": round(market.reference, 2)})
        return market

    def _level_size(self) -> float:
        return round(self.rng.uniform(150, 4_500), 2)

    def _requote(self, market: Market) -> None:
        for side, implied in ((UP, market.implied), (DOWN, 1 - market.implied)):
            ask = _ceil_tick(implied + self.config.half_spread)
            if market.best_ask.get(side) != ask:
                market.best_ask[side] = ask
                # Mudou o melhor preço: a fila daquele nível é outra.
                market.ask_sizes[side][0] = self._level_size()
                market.bid_sizes[side][0] = self._level_size()

    def _update_market(self, market: Market, now: float, dt: float) -> None:
        left = market.end - now
        market.p_up = prob_up(self.spot, market.reference, left, self.model_sigma)

        lag = 1 - math.exp(-dt / self.config.book_lag_seconds)
        noise = 0.004 * math.sqrt(dt) * self.rng.gauss(0, 1)
        market.implied = min(
            0.995, max(0.005, market.implied + (market.p_up - market.implied) * lag + noise)
        )
        previous_ask = dict(market.best_ask)
        self._requote(market)
        if market.best_ask != previous_ask and self.rng.random() < 0.6:
            self._emit(
                "book",
                "price_change",
                {"m": market.label, "up": market.best_ask[UP], "down": market.best_ask[DOWN]},
            )

        leader = UP if market.p_up >= 0.5 else DOWN
        if leader != market.leader:
            market.leader = leader
            if left <= 60:
                market.flips_late += 1
        if now - market.last_path_at >= 1.0:
            market.path.append(
                (
                    round(now - market.start, 1),
                    round(self.spot - market.reference, 2),
                    round(market.p_up, 4),
                )
            )
            market.last_path_at = now

        if 1.0 < left <= self.config.watch_seconds and now >= market.next_action_at:
            self._maybe_buy(market, now, left)

    def _maybe_buy(self, market: Market, now: float, left: float) -> None:
        cfg = self.config
        side = market.leader
        p_side = market.p_up if side == UP else 1 - market.p_up
        ask = market.best_ask[side]
        edge = p_side - ask
        required = cfg.min_edge * (1 + left / cfg.edge_decay_seconds)
        room = cfg.max_stake_per_market - market.stake
        if p_side < cfg.min_leader_p or ask > cfg.max_ask or edge < required or room < 1.0:
            return

        level_shares = market.ask_sizes[side][0]
        usd = cfg.median_chunk_usd * math.exp(0.9 * self.rng.gauss(0, 1))
        usd = min(usd, 250.0, room, level_shares * ask)
        if usd < 1.0:
            return
        shares = usd / ask

        other = DOWN if side == UP else UP
        if market.stake == 0:
            kind = "ENTRY"
            market.first_entry_left = left
            self.first_entries.append(left)
        elif market.shares[side] >= market.shares[other]:
            kind = "ADD"
        else:
            kind = "FLIP" if p_side >= 0.9 else "HEDGE"

        self.total_fills += 1
        fill = Fill(
            seq=self.total_fills,
            ts=now,
            market_id=market.id,
            label=market.label,
            side=side,
            kind=kind,
            price=ask,
            usd=usd,
            shares=shares,
            p_model=p_side,
            edge=edge,
            t_left=left,
            d=self.spot - market.reference,
        )
        market.shares[side] += shares
        market.cost[side] += usd
        market.fills.append(fill)
        self.fills.append(fill)
        self._stats_cache = None
        bucket = min(len(self.late_hist) - 1, int(left // 10))
        self.late_hist[bucket] += usd

        market.ask_sizes[side][0] -= shares
        if market.ask_sizes[side][0] < 1.0:  # nível esgotado: o seguinte assume
            market.ask_sizes[side] = market.ask_sizes[side][1:] + [self._level_size()]
        market.next_action_at = now + self.rng.uniform(0.4, 2.5)

        self._emit(
            "user",
            "fill",
            {"m": market.label, "side": side, "px": ask, "usd": round(usd, 2), "kind": kind},
        )
        self._event(
            kind,
            f"{market.label} · T-{left:.0f}s · compra {SIDE_LABEL[side]} @ ${ask:.2f} · "
            f"${usd:.2f} · P modelo {p_side:.3f}",
        )

    def _settle(self, market: Market) -> None:
        outcome = UP if self.oracle >= market.reference else DOWN
        self._emit("market", "market_resolved", {"m": market.id, "outcome": outcome})
        if market.stake <= 0:
            return
        pnl = 0.0
        for fill in market.fills:
            fill.pnl = (fill.shares if fill.side == outcome else 0.0) - fill.usd
            pnl += fill.pnl
        self.realized_pnl += pnl
        self.markets_traded += 1
        if pnl > 0:
            self.markets_won += 1
        self._stats_cache = None
        self.settled.append(
            {
                "id": market.id,
                "label": market.label,
                "end": market.end,
                "outcome": outcome,
                "stake": round(market.stake, 2),
                "pnl": round(pnl, 2),
                "up_shares": round(market.shares[UP], 2),
                "down_shares": round(market.shares[DOWN], 2),
                "fills": len(market.fills),
            }
        )
        self._event(
            "SETTLED",
            f"{market.label} liquidado · resultado {SIDE_LABEL[outcome]} · "
            f"investido ${market.stake:.2f} · {'+' if pnl >= 0 else '−'}${abs(pnl):.2f}",
            tone="up" if pnl >= 0 else "down",
        )

    # ------------------------------------------------------------ telemetria
    def _emit(self, channel: str, kind: str, payload: dict[str, Any]) -> None:
        self.wire_seq += 1
        body = ", ".join(f'"{key}": {value!r}' for key, value in payload.items()).replace("'", '"')
        self.wire_bytes += len(body) + len(kind) + 24
        self._wire_times.append(self.t)
        self.wire.append(
            {
                "seq": self.wire_seq,
                "ts": round(self.t, 3),
                "ch": channel,
                "type": kind,
                "body": body,
            }
        )

    def _event(self, kind: str, text: str, tone: str = "info") -> None:
        self.events.append({"ts": round(self.t, 3), "kind": kind, "text": text, "tone": tone})

    def _sample_inputs(self, now: float) -> None:
        if now < self._next_input_sample:
            return
        self._next_input_sample = now + 1.0
        market = self.markets[self.config.durations[0]]
        left = market.end - now
        side = market.leader
        p_side = market.p_up if side == UP else 1 - market.p_up
        ask = market.best_ask[side]
        self.inputs.append(
            (
                round(self.spot - market.reference, 2),
                round(reach_usd(self.spot, left, self.model_sigma), 2),
                round(left, 1),
                round(market.p_up, 4),
                ask,
                round(p_side - ask, 4),
            )
        )

    def _stats(self) -> dict[str, Any]:
        if self._stats_cache is not None:
            return self._stats_cache
        fills = list(self.fills)
        sizes = [f.usd for f in fills]
        count = len(fills)
        self._stats_cache = {
            "realized_pnl": round(self.realized_pnl, 2),
            "fills_total": self.total_fills,
            "markets_traded": self.markets_traded,
            "win_rate": (self.markets_won / self.markets_traded) if self.markets_traded else None,
            "avg_usd": round(statistics.fmean(sizes), 2) if sizes else None,
            "median_usd": round(statistics.median(sizes), 2) if sizes else None,
            "first_entry_median_s": (
                round(statistics.median(self.first_entries), 0) if self.first_entries else None
            ),
            "share_buys_ge_80": (sum(f.price >= 0.80 for f in fills) / count) if count else None,
            "share_buys_last_minute": (
                (sum(f.t_left <= 60 for f in fills) / count) if count else None
            ),
            "avg_edge": round(statistics.fmean(f.edge for f in fills), 4) if count else None,
        }
        return self._stats_cache

    def _market_view(self, market: Market) -> dict[str, Any]:
        left = max(0.0, market.end - self.t)
        side = market.leader
        other = DOWN if side == UP else UP
        p_side = market.p_up if side == UP else 1 - market.p_up
        ask = market.best_ask[side]
        watching = left <= self.config.watch_seconds
        return {
            "id": market.id,
            "label": market.label,
            "duration": market.duration,
            "start": market.start,
            "end": market.end,
            "seconds_left": round(left, 2),
            "reference": round(market.reference, 2),
            "p_up": round(market.p_up, 4),
            "implied_up": round(market.implied, 4),
            "leader": side,
            "p_leader": round(p_side, 4),
            "ask_leader": ask,
            "edge": round(p_side - ask, 4),
            "state": "trading" if market.stake > 0 else ("watching" if watching else "idle"),
            "flip_risk": round(min(10.0, 20.0 * (1 - p_side)), 1),
            "flips_late": market.flips_late,
            "reach_usd": round(reach_usd(self.spot, left, self.model_sigma), 2),
            "book": {
                "side": side,
                "asks": [
                    [round(ask + i * TICK, 2), size]
                    for i, size in enumerate(market.ask_sizes[side])
                    if ask + i * TICK <= 0.995
                ],
                "bids": [
                    [round(ask - (i + 1) * TICK, 2), size]
                    for i, size in enumerate(market.bid_sizes[side])
                    if ask - (i + 1) * TICK >= 0.005
                ],
            },
            "position": {
                "up_shares": round(market.shares[UP], 2),
                "down_shares": round(market.shares[DOWN], 2),
                "stake": round(market.stake, 2),
                "net_side": side if market.shares[side] >= market.shares[other] else other,
                "net_shares": round(abs(market.shares[UP] - market.shares[DOWN]), 2),
            },
            "first_entry_left": market.first_entry_left,
            "path": market.path,
            "fills": [
                {
                    "t_left": round(f.t_left, 1),
                    "d": round(f.d, 2),
                    "usd": round(f.usd, 2),
                    "side": f.side,
                }
                for f in market.fills
            ],
        }

    def snapshot(self) -> dict[str, Any]:
        """Estado completo, serializável em JSON, para a tela do terminal."""
        now = self.t
        hours = max((now - self.started_at) / 3600, 1e-9)
        stats = dict(self._stats())
        stats["trades_24h"] = sum(1 for f in self.fills if f.ts >= now - 86_400)
        stats["pnl_per_hour"] = round(self.realized_pnl / hours, 2)
        stats["open_stake"] = round(sum(m.stake for m in self.markets.values()), 2)
        stats["session_seconds"] = round(now - self.started_at, 1)
        while self._wire_times and self._wire_times[0] < now - 5:
            self._wire_times.popleft()
        primary = self.markets.get(self.config.durations[0])
        first = self.candles[0][1] if self.candles else self.spot
        return {
            "ts": round(now, 3),
            "simulated": True,
            "strategy": {
                "name": "Direcional tardio · carrega até a liquidação",
                "watch_seconds": self.config.watch_seconds,
                "min_leader_p": self.config.min_leader_p,
                "min_edge": self.config.min_edge,
                "max_ask": self.config.max_ask,
                "max_stake_per_market": self.config.max_stake_per_market,
                "book_lag_seconds": self.config.book_lag_seconds,
            },
            "spot": {
                "price": round(self.spot, 2),
                "perp": round(self.perp, 2),
                "oracle": round(self.oracle, 2),
                "change_pct": round((self.spot / first - 1) * 100, 3),
                "oracle_age_ms": round((now - self.oracle_source_ts) * 1000),
                "spot_oracle_bp": round((self.spot / self.oracle - 1) * 10_000, 2),
                "basis_bp": round(self._basis * 10_000, 2),
                "sigma_usd": round(self.spot * self.model_sigma, 3),
            },
            "candles": [[c[0], *(round(v, 2) for v in c[1:])] for c in self.candles],
            "feeds": [
                [round(t, 1), round(s, 2), round(p, 2), round(o, 2)]
                for t, s, p, o in self.feed_series
            ],
            "market": self._market_view(primary) if primary else None,
            "markets": [
                {
                    "label": m.label,
                    "seconds_left": round(max(0.0, m.end - now), 1),
                    "p_up": round(m.p_up, 4),
                    "leader": m.leader,
                    "stake": round(m.stake, 2),
                }
                for m in self.markets.values()
            ],
            "stats": stats,
            "inputs": [list(row) for row in self.inputs],
            "late_hist": [round(v, 2) for v in self.late_hist],
            "tape": [f.as_dict() for f in list(self.fills)[-40:]][::-1],
            "settled": list(self.settled)[-12:][::-1],
            "wire": list(self.wire)[-22:],
            "wire_stats": {
                "msgs_per_s": round(len(self._wire_times) / 5, 1),
                "seq": self.wire_seq,
                "bytes": self.wire_bytes,
            },
            "events": list(self.events)[-14:][::-1],
        }
