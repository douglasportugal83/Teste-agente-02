export function money(value: number, currency: string): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(value);
}

export function signedPercent(value: number): string {
  const formatted = new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "exceptZero",
  }).format(value);
  return `${formatted}%`;
}

export function dateTime(iso: string | null): string {
  if (!iso) return "—";
  // A API devolve UTC; sem sufixo de fuso o navegador interpretaria como horário local.
  const normalized = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(normalized),
  );
}

export const CATEGORY_LABELS: Record<string, string> = {
  metals: "Metais",
  indices: "Índices",
  crypto: "Criptomoedas",
  forex: "Forex",
  other: "Outros",
};

export const STATUS_LABELS: Record<string, string> = {
  connected: "Conectado",
  disconnected: "Desconectado",
  error: "Erro",
  not_configured: "Não configurado",
  running: "Em execução",
  paused: "Pausado",
  blocked: "Bloqueado por risco",
  stopped: "Interrompido",
};

export const RISK_RULE_LABELS: Record<string, string> = {
  max_daily_loss: "Perda diária máxima",
  max_exposure_per_symbol: "Exposição máxima por ativo (%)",
  max_open_positions: "Posições simultâneas",
  max_correlated_positions: "Posições correlacionadas",
  risk_per_trade_pct: "Risco por operação (%)",
  max_drawdown_pct: "Drawdown máximo (%)",
  max_volatility_atr_pct: "Volatilidade máxima (ATR %)",
};

export function price(value: number, digits: number): string {
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export const SOURCE_KIND_LABELS: Record<string, string> = {
  synthetic: "sintético",
  mt5: "MT5",
  csv: "CSV",
  parquet: "Parquet",
};

export const REJECTION_LABELS: Record<string, string> = {
  valor_nao_numerico: "Valor não numérico",
  preco_nao_positivo: "Preço zero ou negativo",
  ohlc_inconsistente: "Máxima/mínima incoerente",
  volume_negativo: "Volume negativo",
  horario_desalinhado: "Horário fora da grade do timeframe",
  candle_nao_fechado: "Candle ainda não fechado ou no futuro",
  horario_duplicado: "Horário duplicado",
};
