# TraderAI Pro

Plataforma modular de análise multiativos, backtesting e **simulação** de estratégias de trading.

> **Somente simulação.** O sistema não envia ordens reais e não contém código de execução em
> contas financeiras. Resultados simulados ou históricos não garantem resultados futuros. Nada
> aqui constitui recomendação de investimento.

## Estado atual — Sprints 1 e 2 concluídas

| Entregue e validado | Ainda não existe (sprints seguintes) |
|---|---|
| API FastAPI com autenticação JWT, papéis e permissões | Motor de estratégias em plugins (Sprint 3) |
| Banco PostgreSQL com 17 tabelas e migrations Alembic | Backtesting (Sprint 4) |
| Isolamento por usuário e trilha de auditoria | Paper trading e aplicação das regras de risco (Sprint 5) |
| Gerador de candles sintéticos, atualizado em segundo plano | Motor de IA (Sprint 6) |
| Importação de históricos CSV e Parquet com validação | Indicadores e marcações no gráfico (Sprint 7) |
| Avaliação de qualidade dos dados (lacunas, anomalias, atraso) | |
| Painel: cotações, gráfico de candles, administração de fontes | |

**Conector MT5:** o código de leitura e a ponte estão escritos e testados contra um terminal
*simulado*. **Não foram executados contra um terminal MetaTrader 5 real**, porque a biblioteca
oficial só existe para Windows. Trate-o como não validado até a primeira execução real
(ver [Ponte MetaTrader 5](#ponte-metatrader-5-somente-leitura)).

As telas Estratégias, Robô Simulador, Backtesting e IA existem na navegação, mas apenas descrevem
o que virá — não exibem dados fictícios para parecer prontas.

## Arquitetura

```
frontend/  Next.js 16 + React 19 + TypeScript + Tailwind 4 + Lightweight Charts  → Vercel
backend/   FastAPI + SQLAlchemy 2 + Alembic + numpy/pandas (Python 3.11+)        → serviço Python
banco      PostgreSQL 16 (local, Docker ou Supabase)
ponte MT5  processo separado, na máquina Windows do terminal → grava no mesmo banco
```

```
backend/app
├── core/       configuração (.env), segurança (bcrypt, JWT), logs JSON com redação de segredos
├── db/         base declarativa, engine e sessão
├── models/     17 tabelas (usuários, mercado, estratégias, backtests, simulação, risco, auditoria)
├── schemas/    contratos Pydantic da API
├── services/   cadastro, seed, auditoria, limite de tentativas de login
├── market/     dados de mercado
│   ├── connectors/   base (contrato somente leitura), synthetic, file_import, mt5
│   ├── quality.py    validação de entrada e avaliação de qualidade
│   ├── service.py    ingestão idempotente, sincronização incremental, consultas
│   ├── worker.py     atualizador em segundo plano da fonte sintética
│   └── mt5_bridge.py ponte MT5 → banco (processo à parte)
└── api/        rotas HTTP e WebSocket, autenticação/autorização
```

### Decisões arquiteturais

- **Simulação imposta em três camadas.** `TRADING_MODE` só aceita `simulation`; o banco tem
  `CHECK` que proíbe conta não virtual e fonte de dados com escrita; testes falham se surgir
  rota de execução real ou se a API importar o pacote `MetaTrader5`.
- **Conectores com contrato somente leitura.** A interface `MarketDataConnector` tem apenas
  `discover_symbols` e `fetch_candles`. No MT5, todo acesso à biblioteca passa por um proxy
  (`ReadOnlyMT5`) que só libera oito funções de consulta; `order_send`, `positions_get` etc.
  levantam erro. É uma trava contra descuido, complementada por varredura estática do código
  nos testes — não uma sandbox.
- **Sem look-ahead na origem.** Conectores só devolvem candles *fechados*; a validação rejeita
  qualquer candle ainda em formação ou no futuro antes de gravar.
- **Dados inválidos são rejeitados, nunca corrigidos em silêncio.** Cada linha recusada é
  contada por motivo e reportada (OHLC incoerente, preço não positivo, horário fora da grade,
  duplicata, valor não numérico).
- **Tudo em UTC.** Arquivos importados e o MT5 informam o fuso de origem; a conversão usa a base
  IANA e respeita horário de verão. Horário local inexistente ou ambíguo vira erro.
- **Sintético coerente entre timeframes.** Todos os timeframes são agregados da mesma série M1,
  gerada de forma determinística por bloco: o mesmo pedido devolve sempre os mesmos candles e
  um candle fechado nunca muda depois.
- **Ingestão idempotente** (`INSERT … ON CONFLICT DO UPDATE` na chave `símbolo, timeframe,
  horário`): reimportar ou ressincronizar não duplica.
- **Autenticação própria (JWT + bcrypt) em vez de Supabase Auth**, para rodar sem serviço
  externo. O banco funciona no Supabase apontando `DATABASE_URL`.
- **O primeiro usuário cadastrado vira administrador**; o sistema recusa rebaixar ou desativar
  o último administrador ativo.

## Como rodar

### Opção A — Docker Compose

```bash
cp .env.example .env        # preencha POSTGRES_PASSWORD e JWT_SECRET
docker compose up --build
```

Frontend em http://localhost:3000, API em http://localhost:8000.

### Opção B — local, sem Docker

Requisitos: Python 3.11+, Node 20+, PostgreSQL 14+.

```bash
# banco
createuser traderai --pwprompt && createdb traderai --owner traderai

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # preencha JWT_SECRET e confira DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# frontend (outro terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Abra http://localhost:3000 e crie a primeira conta (será o administrador). Ao iniciar, a API
carrega em segundo plano o histórico sintético dos 13 ativos (≈224 mil candles, cerca de 20 s);
as cotações aparecem no painel em seguida e passam a ser atualizadas a cada 20 s.

### Usando Supabase como banco

Copie a connection string do projeto (Settings → Database) para `DATABASE_URL` e rode
`alembic upgrade head`. Prefixos `postgres://` e `postgresql://` são aceitos.

## Dados de mercado

### Dados sintéticos

**Não são cotações reais** — a interface avisa isso onde eles aparecem. Servem para desenvolver
e testar sem fonte externa. O modelo é um passeio aleatório com regimes (tendência, lateral,
volatilidade elevada) e sazonalidade de sessão. Simplificação: mercados que não são 24/7 fecham
sábado e domingo inteiros em UTC; feriados não são modelados.

Histórico inicial por timeframe: M1 3 dias, M5 10 dias, M15 30 dias, M30 60 dias, H1 180 dias,
H4 1 ano, D1 3 anos, W1 5 anos. Períodos maiores podem ser gerados por
`POST /api/v1/admin/data-sources/{id}/backfill`.

### Importação de CSV e Parquet

Em **Administração → Fontes de dados → Importar histórico**, ou por
`POST /api/v1/admin/market/import`. Limite de 50 MB por arquivo.

- Colunas: data/hora (`time`, `date`, `datetime`, `timestamp` ou `date` + `time`), `open`,
  `high`, `low`, `close` e, opcionalmente, `volume`/`tickvol` e `spread`.
- Separador detectado automaticamente (vírgula, ponto e vírgula, tabulação).
- A exportação de barras do MetaTrader 5 (`<DATE> <TIME> <OPEN> …`) é aceita como está.
- Data/hora em texto ou epoch (segundos ou milissegundos). Informe o **fuso dos horários do
  arquivo**; exportações do MT5 usam o horário do servidor da corretora.

A resposta traz linhas lidas, importadas, rejeitadas por motivo e a avaliação de qualidade.

### Ponte MetaTrader 5 (somente leitura)

A biblioteca oficial `MetaTrader5` só existe para Windows e precisa do terminal na mesma
máquina. Por isso a leitura é feita por um processo separado, que grava no mesmo banco da API:

```powershell
# na máquina Windows com o terminal MT5 instalado e aberto
cd backend
pip install -e ".[mt5]"
copy .env.example .env      # DATABASE_URL do banco da API e MT5_SERVER_TIMEZONE
python -m app.market.mt5_bridge --once                  # uma sincronização, para testar
python -m app.market.mt5_bridge --interval 30           # contínuo, reconecta sozinho
python -m app.market.mt5_bridge --timeframes H1,D1      # restringe os timeframes
```

- Sem `MT5_LOGIN`, usa a conta já aberta no terminal. Se preencher, use a **senha de
  investidor** (somente leitura) — ela, por si só, impede negociação naquela sessão.
- **`MT5_SERVER_TIMEZONE` precisa estar correto.** O MT5 entrega horários no fuso do servidor
  da corretora; com o fuso errado, todos os candles ficam deslocados. Confirme com a corretora
  (muitas usam `Europe/Athens`).
- Todos os símbolos do terminal são registrados; só os do catálogo padrão (inclusive variações
  como `EURUSD.m` ou `USTEC`) começam monitorados. Os demais podem ser ativados por
  `PATCH /api/v1/admin/symbols/{id}`.
- Candles D1/W1 do servidor são rotulados pelo dia/semana UTC mais próximo.
- Em falha, a fonte aparece com erro no painel, os administradores recebem um alerta e a ponte
  tenta de novo com espera crescente (5 s a 5 min).

**Antes de confiar nesses dados**, rode `--once` e compare alguns candles com o gráfico do
terminal: esse caminho ainda não foi exercitado com um terminal real.

### Qualidade dos dados

`GET /api/v1/market/quality` (e o painel na tela Gráficos) informa completude, lacunas,
variações anômalas (limiar de 25 desvios robustos), candles sem negociação, ausência de volume
e atraso da série, com uma nota de 0 a 100. Feriados aparecem como lacuna, pois não há
calendário de mercado.

## Documentação da API

Com o backend no ar: Swagger em `/docs`, ReDoc em `/redoc`, esquema em `/openapi.json`.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health`, `/health/ready` | Liveness e readiness (verifica o banco) |
| GET | `/api/v1/system/info` | Versão, ambiente e modo de operação |
| POST | `/api/v1/auth/register`, `/api/v1/auth/login` | Cadastro e login |
| GET | `/api/v1/auth/me` | Usuário autenticado |
| GET | `/api/v1/dashboard/overview` | Dados da Visão Geral |
| GET | `/api/v1/symbols`, `/api/v1/data-sources` | Catálogo de ativos e fontes |
| GET | `/api/v1/market/candles` | Candles fechados de um símbolo e timeframe |
| GET | `/api/v1/market/quotes` | Último preço e variação dos ativos monitorados |
| GET | `/api/v1/market/quality`, `/api/v1/market/coverage` | Qualidade e cobertura das séries |
| POST | `/api/v1/admin/market/import` | Importa CSV/Parquet |
| POST | `/api/v1/admin/data-sources/{id}/sync`, `/backfill` | Sincroniza ou gera histórico (sintético) |
| PATCH | `/api/v1/admin/symbols/{id}` | Liga/desliga o monitoramento de um símbolo |
| GET/POST | `/api/v1/alerts`, `/api/v1/alerts/{id}/read` | Alertas do usuário |
| GET | `/api/v1/simulation/accounts`, `/api/v1/risk/rules` | Conta fictícia e limites de risco |
| GET/PATCH | `/api/v1/admin/users`, `/roles`, `/audit-logs` | Administração (papel `admin`) |
| WS | `/ws/status` | Heartbeat; primeira mensagem `{"type":"auth","token":"…"}` |

## Testes

```bash
cd backend
ruff check . && ruff format --check . && mypy app
pytest                                   # SQLite em memória, sem dependências externas
TEST_DATABASE_URL=postgresql+psycopg://traderai:SENHA@localhost:5432/traderai_test pytest --cov=app
```

Com `TEST_DATABASE_URL` apontando para um PostgreSQL **de teste** (o esquema `public` é
recriado), a suíte inteira roda nele e inclui o teste das migrations.

```bash
cd frontend
npm run lint && npm run typecheck && npm run build
node e2e/smoke.mjs          # ponta a ponta no navegador; exige Playwright, API e frontend no ar
                            # e banco recém-migrado (sem usuários)
```

O que a suíte cobre:

- **Unitários:** hash, JWT, redação de logs, configuração, gerador sintético (determinismo,
  coerência entre timeframes, ausência de look-ahead e de repintura), validação e qualidade,
  leitura de arquivos e conversão de fusos.
- **Integração:** fluxos HTTP e WebSocket, permissões, isolamento entre usuários, constraints e
  migrations, sincronização incremental, importação ponta a ponta, ponte MT5 com terminal
  simulado (incluindo queda e reconexão).
- **Desempenho:** latência do painel, geração de 1 ano de M1, gravação de 50 mil candles.

O CI (`.github/workflows/ci.yml`) executa tudo exceto o teste de navegador.

## Segurança

- Senhas com bcrypt (pré-hash SHA-256); nunca retornadas pela API.
- Logs JSON com redação automática de chaves sensíveis; só o caminho da requisição é registrado.
- Login com resposta idêntica para e-mail inexistente e senha errada, e bloqueio temporário após
  5 falhas por e-mail e IP.
- Em `ENVIRONMENT=production` a API recusa iniciar com `JWT_SECRET` ausente ou curto.
- Segredos só em variáveis de ambiente; a senha do MT5 nunca é gravada no banco nem em logs.
- Uploads limitados em tamanho e lidos apenas como dados tabulares.

## Pendências conhecidas

- **Conector MT5 não validado com terminal real** (ver acima).
- **Docker e CI não foram executados** no ambiente de desenvolvimento (sem daemon Docker).
- Sem calendário de mercado: feriados e pregões reduzidos contam como lacuna, e o sintético
  ignora feriados e a abertura de domingo à noite.
- O atualizador sintético roda dentro do processo da API; com vários workers do uvicorn, cada um
  repete o trabalho (sem corromper dados). Para escalar, movê-lo para um processo próprio.
- Importação e geração de histórico são síncronas, com limites por requisição (50 MB e 600 mil
  candles); não há fila de tarefas.
- A cobertura (`/market/coverage`) faz uma agregação sobre toda a tabela de candles; com dezenas
  de milhões de linhas precisará de uma tabela-resumo.
- Supabase Auth e políticas RLS no PostgreSQL não implementados.
- Token de acesso no `localStorage`, sem refresh nem revogação (sessão de 60 minutos).
- Limite de tentativas de login em memória, por processo.
- Sem recuperação de senha nem verificação de e-mail.
- As regras de risco estão armazenadas, mas nada as aplica até a Sprint 5.
- Frontend sem testes unitários; a verificação é lint, tipagem, build e o teste de navegador.

## Roteiro

1. **Fundação** — concluída
2. **Dados de mercado** — concluída (MT5 pendente de validação em terminal real)
3. Estratégias: estrutura de plugins e primeiras estratégias verificáveis
4. Backtesting: motor, métricas e relatórios
5. Paper trading: execução virtual, risco e monitoramento
6. Inteligência artificial: explicações, regimes e comparação
7. Dashboard avançado: indicadores, marcações e configurações
8. Testes e publicação
