"""Modelo de probabilidade do mercado binário "fecha acima/abaixo da referência"."""

import math

SECONDS_PER_YEAR = 365.25 * 24 * 3600
MIN_HORIZON_SECONDS = 0.5


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_up(
    spot: float, reference: float, seconds_left: float, sigma_per_sqrt_second: float
) -> float:
    """P(preço no vencimento >= referência), supondo passeio log-normal sem tendência.

    `sigma_per_sqrt_second` é o desvio-padrão do log-retorno em um segundo. O horizonte tem um
    piso para a probabilidade não degenerar em 0/1 por divisão por zero no último instante.
    """
    if spot <= 0 or reference <= 0:
        raise ValueError("preços devem ser positivos")
    if sigma_per_sqrt_second <= 0:
        raise ValueError("volatilidade deve ser positiva")
    horizon = max(seconds_left, MIN_HORIZON_SECONDS)
    z = math.log(spot / reference) / (sigma_per_sqrt_second * math.sqrt(horizon))
    return normal_cdf(z)


def reach_usd(spot: float, seconds_left: float, sigma_per_sqrt_second: float) -> float:
    """Alcance de 1 desvio-padrão do preço, em dólares, até o vencimento (σ·√t)."""
    return spot * sigma_per_sqrt_second * math.sqrt(max(seconds_left, 0.0))
