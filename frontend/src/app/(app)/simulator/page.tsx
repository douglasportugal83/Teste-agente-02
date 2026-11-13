import { ComingSoon } from "@/components/ui";

export const metadata = { title: "Robô Simulador" };

export default function Page() {
  return (
    <ComingSoon
      title="Robô Simulador"
      sprint={5}
      features={[
        "Status em execução/pausado e interrupção imediata",
        "Operações virtuais abertas",
        "Histórico de operações fictícias",
        "Estratégia utilizada e motivo de cada decisão",
        "Logs de eventos",
      ]}
    />
  );
}
