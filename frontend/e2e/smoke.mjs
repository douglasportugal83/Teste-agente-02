// Teste ponta a ponta (navegador real) dos fluxos das Sprints 1 e 2 e do Terminal ao vivo.
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
  for (const text of ["Pausado", "1 não lido"]) {
    assert.ok(await page.getByText(text, { exact: true }).first().isVisible(), `faltou ${text}`);
  }
  assert.match(await page.getByText("Patrimônio fictício").locator("..").innerText(), /100\.000,00/);

  // Cotações sintéticas: o histórico inicial carrega em segundo plano (~20 s) e o painel
  // se atualiza sozinho a cada 30 s.
  const eurusd = page.getByRole("row", { name: /EURUSD/ });
  await eurusd.getByText(/^\d,\d{5}$/).waitFor({ timeout: 120_000 });
  await page.getByText("não são cotações reais").waitFor();
  for (const symbol of ["XAUUSD", "NAS100", "BTCUSD", "USDJPY"]) {
    await page.getByRole("rowheader", { name: symbol }).waitFor();
  }
  await page.getByText("Conectado").nth(1).waitFor({ timeout: 60_000 }); // banco + fonte sintética
  await shot("02-dashboard");

  await page.getByRole("button", { name: "Marcar como lido" }).click();
  await page.getByText("1 não lido").waitFor({ state: "detached" });

  // A sessão sobrevive a um recarregamento.
  await page.reload();
  await page.getByText("13 ativos monitorados").waitFor();

  // Navegação pelas oito telas.
  // Gráficos: candles reais do banco, troca de timeframe e de ativo, painel de qualidade.
  await page.getByRole("link", { name: "Gráficos", exact: true }).click();
  await page.locator("canvas").first().waitFor();
  await page.getByText("Nota 100/100").waitFor();
  await page.getByText("Dados sintéticos gerados pelo sistema").waitFor();
  const requested = (pattern) => page.waitForResponse((r) => pattern.test(r.url()) && r.ok());
  let response = requested(/market\/candles.*timeframe=D1/);
  await page.getByRole("button", { name: "D1", exact: true }).click();
  let body = await (await response).json();
  assert.ok(body.candles.length > 500, "D1 deveria ter anos de histórico");
  assert.ok(body.candles.every((c) => c.t % 86400 === 0), "candles D1 alinhados à meia-noite UTC");
  const btc = await page.locator("option", { hasText: "BTCUSD" }).first().getAttribute("value");
  response = requested(new RegExp(`market/candles.*${btc}`));
  await page.getByLabel("Ativo").selectOption(btc);
  body = await (await response).json();
  assert.equal(body.symbol, "BTCUSD");
  await page.getByText("Nota 100/100").waitFor();
  await page.locator("canvas").first().waitFor();
  await shot("03-charts");

  for (const name of ["Estratégias", "Robô Simulador", "Backtesting", "Inteligência Artificial"]) {
    await page.getByRole("link", { name }).click();
    await page.getByRole("heading", { name, level: 1 }).waitFor();
  }
  await page.getByRole("link", { name: "Gestão de Risco" }).click();
  await page.getByText("Drawdown máximo (%)").waitFor();
  await shot("04-risk");

  await page.getByRole("link", { name: "Administração" }).click();
  await page.getByRole("cell", { name: "user.registered" }).waitFor();
  await page.getByText(email).first().waitFor();
  assert.equal(await page.getByLabel(`Papel de ${email}`).inputValue(), "admin");
  // O último administrador não pode ser rebaixado: a API recusa e a tela mostra o motivo.
  await page.getByLabel(`Papel de ${email}`).selectOption("trader");
  await page.getByRole("alert").filter({ hasText: "ao menos um administrador" }).waitFor();
  assert.equal(await page.getByLabel(`Papel de ${email}`).inputValue(), "admin");

  // Fontes de dados: sincronização manual e importação de CSV com linha inválida.
  await page.getByRole("button", { name: "Sincronizar agora" }).click();
  await page.getByRole("status").filter({ hasText: "Sincronização concluída" }).waitFor();
  const csv = [
    "time,open,high,low,close,volume",
    "2026-03-02 10:00,1.1000,1.1010,1.0990,1.1005,150",
    "2026-03-02 11:00,1.1005,1.1020,1.1000,1.1015,180",
    "2026-03-02 12:00,1.1015,1.1000,1.1010,1.1025,90", // máxima abaixo do fechamento
  ].join("\n");
  await page.getByLabel("Arquivo").setInputFiles({
    name: "eurusd_h1.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await page.getByLabel("Símbolo").fill("eurusd");
  await page.getByRole("button", { name: "Importar" }).click();
  const report = page.getByRole("status").filter({ hasText: "EURUSD H1" });
  await report.getByText("2 de 3 linha(s) importada(s)").waitFor();
  await report.getByText("1 rejeitada(s): Máxima/mínima incoerente").waitFor();
  await page.getByRole("cell", { name: "Arquivos importados (CSV)" }).first().waitFor();
  await page.getByRole("cell", { name: "market.import" }).waitFor();
  await shot("05-admin");

  // A série importada fica disponível nos gráficos, identificada pela fonte.
  await page.getByRole("link", { name: "Gráficos", exact: true }).click();
  const imported = await page.locator("option", { hasText: "EURUSD · CSV" }).getAttribute("value");
  response = requested(new RegExp(`market/candles.*${imported}`));
  await page.getByLabel("Ativo").selectOption(imported);
  body = await (await response).json();
  assert.deepEqual(body.candles.map((c) => c.c), [1.1005, 1.1015]);
  assert.equal(body.is_synthetic, false);
  await page.getByText("Atrasada").waitFor(); // histórico antigo é sinalizado como desatualizado
  await page.getByRole("link", { name: "Administração" }).click();
  await page.getByRole("cell", { name: "user.registered" }).waitFor();

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
  await shot("06-dashboard-mobile");

  // Terminal ao vivo: o motor aquece, o fluxo chega pelo WebSocket e o relógio anda.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("link", { name: "Terminal ao vivo" }).click();
  await page.waitForURL("**/terminal");
  await page.getByRole("heading", { name: "Casca do modelo" }).waitFor({ timeout: 60_000 });
  await page.getByText("Simulação ao vivo").waitFor();
  const clockText = () => page.getByText(/^\d\d:\d\d:\d\d UTC$/).textContent();
  const before = await clockText();
  await page.waitForTimeout(1500);
  assert.notEqual(await clockText(), before, "o relógio do terminal não avançou");
  await page.getByRole("table").getByRole("row").nth(1).waitFor(); // a fita já tem execuções
  await shot("07-terminal");
  await page.setViewportSize({ width: 390, height: 844 });
  const terminalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  assert.ok(terminalOverflow <= 0, `rolagem horizontal de ${terminalOverflow}px no terminal`);
  await page.getByRole("link", { name: "Voltar ao painel" }).click();
  await page.waitForURL("**/dashboard");

  // Erros 4xx esperados (senha fraca, senha errada, rebaixamento) aparecem no console como falha de rede.
  const unexpected = problems.filter((p) => !/status of (401|409|422)/.test(p));
  assert.deepEqual(unexpected, [], "erros no console do navegador");
  console.log("E2E OK");
} finally {
  await browser.close();
}
