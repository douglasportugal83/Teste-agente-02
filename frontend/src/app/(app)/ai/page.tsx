import { ComingSoon } from "@/components/ui";

export const metadata = { title: "Inteligência Artificial" };

export default function Page() {
  return (
    <ComingSoon
      title="Inteligência Artificial"
      sprint={6}
      features={[
        "Chat com IA (modelo de linguagem opcional)",
        "Análises explicadas com os dados que as sustentam",
        "Comparação entre estratégias",
        "Identificação de regimes de mercado",
        "Resumos automáticos",
      ]}
    />
  );
}
