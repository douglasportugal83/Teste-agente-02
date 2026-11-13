// Teste ponta a ponta (navegador real) do fluxo da Sprint 1.
// Pré-requisitos: API e frontend no ar, banco recém-migrado (sem usuários) e Playwright instalado.
//   node e2e/smoke.mjs [url-do-frontend] [pasta-de-screenshots]
import assert from "node:assert/strict";
import { createRequire } from "node:module";

// require() encontra também uma instalação global do Playwright (NODE_PATH).
const { chromium } = createRequire(import.meta.url)("playwright");

const BASE = process.argv[2] ?? "http://localhost:3000";
const SHOTS = process.argv[3] ?? null;
const email = `e2e-${Date.now()}@example.com`;
const password = "Senha-forte-123";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const problems = [];
page.on("console", (m) => m.type() === "error" && problems.push(m.text()));
page.on("pageerror", (e) => problems.push(String(e)));
const shot = async (name, options = {}) =>
  SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true, ...options });

try {
  // Rota protegida sem sessão redireciona para o login.
  await page.goto(`${BASE}/dashboard`);
  await page.waitForURL("**/login");

  // Senha fraca é recusada pela API com mensagem compreensível.
  await page.goto(`${BASE}/register`);
  await page.getByLabel("Nome").fill("Admin E2E");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill("somenteletras");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.getByRole("alert").filter({ hasText: "letras e números" }).waitFor();
  await shot("01-register-error");

  // Cadastro válido entra direto no painel.
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.waitForURL("**/dashboard");
  await page.getByText("MODO SIMULAÇÃO").waitFor();
  await page.getByText("13 ativos monitorados").waitFor();
  await page.getByText("Tempo real").waitFor(); // WebSocket autenticado
  for (const text of ["XAUUSD", "NAS100", "BTCUSD", "EURUSD", "Pausado", "1 não lido"]) {
    assert.ok(await page.getByText(text, { exact: true }).first().isVisible(), `faltou ${text}`);
  }
  assert.match(await page.getByText("Patrimônio fictício").locator("..").innerText(), /100\.000,00/);
  await shot("02-dashboard");

  await page.getByRole("button", { name: "Marcar como lido" }).click();
  await page.getByText("1 não lido").waitFor({ state: "detached" });

  // A sessão sobrevive a um recarregamento.
  await page.reload();
  await page.getByText("13 ativos monitorados").waitFor();

  // Navegação pelas oito telas.
  for (const name of ["Gráficos", "Estratégias", "Robô Simulador", "Backtesting", "Inteligência Artificial"]) {
    await page.getByRole("link", { name }).click();
    await page.getByRole("heading", { name, level: 1 }).waitFor();
  }
  await page.getByRole("link", { name: "Gestão de Risco" }).click();
  await page.getByText("Drawdown máximo (%)").waitFor();
  await shot("03-risk");

  await page.getByRole("link", { name: "Administração" }).click();
  await page.getByRole("cell", { name: "user.registered" }).waitFor();
  await page.getByText(email).first().waitFor();
  assert.equal(await page.getByLabel(`Papel de ${email}`).inputValue(), "admin");
  // O último administrador não pode ser rebaixado: a API recusa e a tela mostra o motivo.
  await page.getByLabel(`Papel de ${email}`).selectOption("trader");
  await page.getByRole("alert").filter({ hasText: "ao menos um administrador" }).waitFor();
  assert.equal(await page.getByLabel(`Papel de ${email}`).inputValue(), "admin");
  await shot("04-admin");

  // Sair, errar a senha, entrar de novo.
  await page.getByRole("button", { name: "Sair" }).click();
  await page.waitForURL("**/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill("senha-errada-1");
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("alert").filter({ hasText: "E-mail ou senha incorretos" }).waitFor();
  await page.getByLabel("Senha").fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.waitForURL("**/dashboard");

  // Layout em celular: sem rolagem horizontal e menu recolhível funcional.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByText("13 ativos monitorados").waitFor();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  assert.ok(overflow <= 0, `rolagem horizontal de ${overflow}px no celular`);
  await page.getByRole("button", { name: "Menu" }).click();
  await page.getByRole("link", { name: "Backtesting" }).click();
  await page.getByRole("heading", { name: "Backtesting", level: 1 }).waitFor();
  await page.goto(`${BASE}/dashboard`);
  await page.getByText("13 ativos monitorados").waitFor();
  await shot("05-dashboard-mobile");

  // Erros 4xx esperados (senha fraca, senha errada, rebaixamento) aparecem no console como falha de rede.
  const unexpected = problems.filter((p) => !/status of (401|409|422)/.test(p));
  assert.deepEqual(unexpected, [], "erros no console do navegador");
  console.log("E2E OK");
} finally {
  await browser.close();
}
