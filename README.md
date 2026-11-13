# TraderAI Pro

Plataforma modular de análise multiativos, backtesting e **simulação** de estratégias de trading.

> **Somente simulação.** O sistema não envia ordens reais e não contém código de execução em
> contas financeiras. Resultados simulados ou históricos não garantem resultados futuros. Nada
> aqui constitui recomendação de investimento.

## Estado atual — Sprint 1 (Fundação) concluída

| Entregue e validado | Ainda não existe (sprints seguintes) |
|---|---|
| API FastAPI com autenticação JWT, papéis e permissões | Candles sintéticos, importação CSV/Parquet, conector MT5 (Sprint 2) |
| Banco PostgreSQL com as 17 tabelas, migrations Alembic | Motor de estratégias em plugins (Sprint 3) |
| Isolamento de dados por usuário e trilha de auditoria | Backtesting (Sprint 4) |
| Painel Next.js: login, cadastro, Visão Geral, Gestão de Risco (leitura), Administração | Paper trading e aplicação das regras de risco (Sprint 5) |
| WebSocket de status autenticado com reconexão | Motor de IA (Sprint 6), gráficos Lightweight Charts (Sprint 7) |

As telas Gráficos, Estratégias, Robô Simulador, Backtesting e IA existem na navegação, mas apenas
descrevem o que virá — não exibem dados fictícios para parecer prontas.

## Arquitetura

```
frontend/  Next.js 16 + React 19 + TypeScript + Tailwind 4   → Vercel
backend/   FastAPI + SQLAlchemy 2 + Alembic (Python 3.11+)   → serviço Python separado (Docker)
banco      PostgreSQL 16 (local, Docker ou Supabase)
```

```
backend/app
├── core/       configuração (.env), segurança (bcrypt, JWT), logs JSON com redação de segredos
├── db/         base declarativa, engine e sessão
├── models/     17 tabelas (usuários, mercado, estratégias, backtests, simulação, risco, auditoria)
├── schemas/    contratos Pydantic da API
├── services/   regras de negócio: cadastro, seed, auditoria, limite de tentativas de login
└── api/        rotas HTTP e WebSocket, dependências de autenticação/autorização
```

### Decisões arquiteturais

- **Simulação imposta em três camadas.** `TRADING_MODE` só aceita `simulation` (outro valor impede
  a API de iniciar); o banco tem `CHECK` que proíbe conta não virtual e fonte de dados com escrita;
  um teste falha se surgir rota de execução real ou se o pacote `MetaTrader5` for importado pela API.
- **Autenticação própria (JWT + bcrypt) em vez de Supabase Auth.** Permite rodar e testar tudo
  localmente, sem serviço externo. O banco é PostgreSQL padrão e funciona no Supabase bastando
  apontar `DATABASE_URL`. A adoção do Supabase Auth fica registrada como pendência.
- **Isolamento entre usuários na camada de aplicação.** Toda consulta de dado pessoal filtra por
  `user_id`; acessar recurso alheio devolve 404. RLS no PostgreSQL é uma segunda barreira pendente.
- **Enums como `VARCHAR` + `CHECK`**, não tipos nativos: adicionar um valor é uma migration simples.
- **`market_candles` com chave primária composta** `(symbol_id, timeframe, ts)`: impede duplicatas
  e já é o índice das consultas por intervalo.
- **O conector MT5 será um processo separado** (Sprint 2), pois o terminal só roda em Windows e não
  em funções serverless. A API nunca importa a biblioteca do MT5.
- **O primeiro usuário cadastrado vira administrador**; os seguintes, `trader`. O sistema recusa
  rebaixar ou desativar o último administrador ativo.

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

Abra http://localhost:3000 e crie a primeira conta (será o administrador).

### Usando Supabase como banco

Copie a connection string do projeto (Settings → Database) para `DATABASE_URL` e rode
`alembic upgrade head`. Prefixos `postgres://` e `postgresql://` são aceitos.

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

Com `TEST_DATABASE_URL` apontando para um PostgreSQL **de teste** (o esquema `public` é recriado),
a suíte inteira roda nele e inclui o teste que aplica as migrations, compara com os modelos e
reverte.

```bash
cd frontend
npm run lint && npm run typecheck && npm run build
node e2e/smoke.mjs          # ponta a ponta no navegador; exige Playwright, API e frontend no ar
                            # e banco sem usuários
```

Cobertura da suíte: unitários (hash, JWT, redação de logs, configuração), integração (fluxos HTTP,
WebSocket, permissões, isolamento, constraints do banco, migrations) e desempenho (latência do
painel, inserção e consulta de 20 mil candles). O CI (`.github/workflows/ci.yml`) executa tudo
exceto o teste de navegador.

## Segurança

- Senhas com bcrypt (pré-hash SHA-256, sem truncamento em 72 bytes); nunca retornadas pela API.
- Logs estruturados em JSON com redação automática de chaves sensíveis; apenas o caminho da
  requisição é registrado. Um teste verifica que senha e token não chegam aos logs nem à auditoria.
- Login com resposta idêntica para e-mail inexistente e senha errada, e bloqueio temporário após
  5 falhas por e-mail e IP.
- Em `ENVIRONMENT=production` a API recusa iniciar com `JWT_SECRET` ausente ou curto.
- Segredos somente em variáveis de ambiente; os arquivos `.env.example` não contêm valores reais.

## Pendências conhecidas

- **Docker e CI não foram executados** no ambiente de desenvolvimento (sem daemon Docker); os
  arquivos foram escritos, mas precisam de uma primeira execução para confirmação.
- Supabase Auth e políticas RLS no PostgreSQL não implementados (ver decisões acima).
- O token de acesso fica no `localStorage` do navegador e não há refresh token nem revogação:
  a sessão expira em 60 minutos. Migrar para cookie `HttpOnly` antes de publicar.
- O limite de tentativas de login é em memória, por processo; com vários workers, mover para Redis.
- Sem recuperação de senha nem verificação de e-mail.
- As regras de risco estão armazenadas, mas nada as aplica até o simulador existir (Sprint 5).
- As fontes de dados aparecem como "Não configurado": não há candles até a Sprint 2.
- Frontend sem testes unitários; a verificação é lint, tipagem, build e o teste de navegador.

## Roteiro

1. **Fundação** — concluída
2. Dados de mercado: sintéticos, importação CSV/Parquet, conector MT5 de leitura
3. Estratégias: estrutura de plugins e primeiras estratégias verificáveis
4. Backtesting: motor, métricas e relatórios
5. Paper trading: execução virtual, risco e monitoramento
6. Inteligência artificial: explicações, regimes e comparação
7. Dashboard avançado: gráficos e configurações
8. Testes e publicação
