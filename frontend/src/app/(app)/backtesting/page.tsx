import { ComingSoon } from "@/components/ui";

export const metadata = { title: "Backtesting" };

export default function Page() {
  return (
    <ComingSoon
      title="Backtesting"
      sprint={4}
      features={[
        "Seleção de ativos, estratégias e períodos",
        "Custos: spread, slippage, comissões e latência",
        "Treino/validação e walk-forward",
        "Métricas: retorno, drawdown, profit factor, Sharpe",
        "Curva de patrimônio e relatórios detalhados",
      ]}
    />
  );
}
