import { ComingSoon } from "@/components/ui";

export const metadata = { title: "Gráficos" };

export default function Page() {
  return (
    <ComingSoon
      title="Gráficos"
      sprint={7}
      features={[
        "Candlesticks com Lightweight Charts",
        "Seletor de ativos e timeframes (M1 a W1)",
        "Indicadores técnicos",
        "Marcação de BOS, CHoCH, FVG e Order Blocks",
        "Zonas de suporte, resistência e liquidez",
        "Visualização de operações virtuais",
      ]}
    />
  );
}
