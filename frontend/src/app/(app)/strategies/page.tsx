import { ComingSoon } from "@/components/ui";

export const metadata = { title: "Estratégias" };

export default function Page() {
  return (
    <ComingSoon
      title="Estratégias"
      sprint={3}
      features={[
        "Biblioteca de estratégias em plugins",
        "Configuração individual de parâmetros",
        "Ativação para simulação",
        "Comparação de resultados",
        "Histórico de versões",
      ]}
    />
  );
}
