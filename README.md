# let-me-rich

Bot de trading **spot** na Binance operado pelo **Claude Code em modo headless** (`claude -p`), disparado pelo Agendador do Windows.
**Quem decide é o Claude; quem executa e trava é o Python.** Dinheiro real, banca pequena: o risk manager é a parte mais importante.

> Não é recomendação de investimento. A maioria dos LLMs perdeu dinheiro operando cripto de verdade (Alpha Arena 2025: 4 de 6).
> A estratégia sombra existe para medir se o agente agrega algo; se não agregar, desligue.

## Como funciona

```
Agendador (30 min) ─► run_cycle.py ─► claude -p (Opus, só tools mcp__trader__*) ─► mcp_server.py ─► risk.py ─► Binance
                          │                                                                         (OPOCO: compra + OCO)
                          └─► no fim, SEMPRE: sync em Python (recria stop faltando) + estratégia sombra
Daemon Telegram (sempre ligado): /status /posicoes /pnl /pause /resume /kill + aviso de fills
```

- **Entrada**: ordem OPOCO da Binance: compra LIMIT + OCO de venda (alvo LIMIT_MAKER, stop STOP_LOSS a mercado) que entra sozinho no fill, com a quantidade líquida da taxa. A proteção fica na exchange: funciona com o PC desligado.
- **Tamanho**: o Claude nunca escolhe. `risk.py` calcula por risco da categoria ÷ distância do stop, e só reduz (nunca aumenta para caber no mínimo da exchange).
- **Travas** (`config/risk.yaml`): risco por categoria (major 1,5% / alt 1% / meme 0,5%), exposição meme ≤ 10%, 3 posições, stop mín/máx e ≤ 3 ATR, R:R ≥ 1,5, alvo ≥ 3× custos, perda diária 4%, 4 trades/dia, cooldown pós-stop, StoplossGuard, circuit breaker, regime BEAR, `max_order_usd`.
- **Isolamento do Claude no ciclo**: `--tools Agent` + `--allowedTools mcp__trader__*` + deny em `.claude/cycle-settings.json` + hook `hooks/guard.py` (fail-closed). Testado: sem Read/Bash/Web/Edit nem pelos subagentes.

## Instalação

```powershell
uv sync
copy config\.env.example config\.env   # e preencha
uv run pytest                           # 70+ testes
uv run python -m trader.check           # checagem SOMENTE LEITURA (mercados, relógio, permissões da chave, saldo)
```

### Chave da Binance (obrigatório)
1. API Management → Create API → **System generated** ou **Ed25519** (recomendada).
2. Permissões: **só "Enable Spot & Margin Trading"**. **Saque DESLIGADO**. Nada de futuros/margem/transferência.
3. **Restrict access to trusted IPs**: seu IP público. Sem whitelist a Binance tira a permissão de trading em 90 dias.
   O preflight **recusa operar** se a chave tiver saque habilitado ou não tiver whitelist.
   IP residencial muda? Quando mudar, a API recusa (-2015), o bot para de operar (stops continuam na exchange) e o Telegram avisa: atualize o IP na Binance.
4. Mantenha um pouco de **BNB** com "Using BNB to pay for fees" ligado (25% de desconto; o bot nunca vende BNB).
5. Deixe na Binance **só o capital do bot**.

### Telegram
Crie um bot com o @BotFather → `TELEGRAM_BOT_TOKEN`. Mande uma mensagem ao bot e pegue seu `chat.id` em `https://api.telegram.org/bot<TOKEN>/getUpdates` → `TELEGRAM_CHAT_ID`. O daemon ignora qualquer outro chat.

### Claude Code
- Versão ≥ 2.1.259 (usa `--permission-prompts`). O `run_cycle` desliga o auto-update na execução; não atualize sem rodar um ciclo `dry` depois (o `--bare` deve virar padrão do `-p` no futuro e quebraria o MCP).
- Usa o login da sua assinatura. **Não** defina `ANTHROPIC_API_KEY` (o wrapper remove, mas evite). Se a tarefa agendada não achar o login: `claude setup-token` e `setx CLAUDE_CODE_OAUTH_TOKEN <token>`.
- Cada ciclo conta no limite da assinatura. `est_cost_usd` na tabela `cycles` é estimativa a preço de lista, não cobrança.

## Operação

| Comando | O quê |
|---|---|
| `iniciar.bat` / `parar.bat` | liga/desliga em segundo plano (daemon + ciclo a cada 30 min). Parar não vende nada |
| `uv run python -m trader.run_cycle` | um ciclo (o que o agendador roda) |
| `uv run python -m trader.run_cycle --model sonnet` | idem com outro modelo |
| `uv run python -m trader.run_cycle --weekly` | revisão semanal: propostas em `proposals/`, nunca aplica |
| `uv run python -m trader.telegram_daemon` | daemon |
| `uv run python -m trader.report` / `--csv trades.csv` | agente vs sombra / export fiscal |
| `uv run python -m trader.kill --yes` | kill switch manual |
| `powershell -File scripts\install_tasks.ps1` | cria as tarefas no Agendador |

`mode` em `config/risk.yaml`: `off` (nada), `dry` (valida e registra, não envia), `live` (ordem real; só você escreve isso).

## Imposto e regulação (Brasil)
- O CSV (`report --csv`) traz data UTC, par, lado, quantidade, preço, taxa e ativo da taxa, cotação USDT/BRL do momento e IDs. Se a Binance contar como exchange estrangeira para você, vale a Lei 14.754/2023 (15% sobre ganho anual, sem isenção de R$ 35 mil). Confirme com um contador.
- Resoluções BCB 519–521: exchanges precisam protocolar pedido de autorização até 30/10/2026. Até 18/09/2026 a Binance não havia protocolado publicamente. O código usa ccxt; trocar de exchange exige reimplementar só a entrada protegida (OPOCO/OCO) em `broker/binance_spot.py`.

## Modo B3: day trade de mini-índice (WIN) via MetaTrader 5

**A IA planeja, o Python executa e trava.** Antes da abertura, uma equipe de analistas (modelos sem tools) monta um
dossiê; o operador (codex) grava um **plano do dia** estruturado; durante o pregão o **executor** Python dispara as
entradas a partir do plano, em fechamento de barra, sempre pelo `risk_b3`. Não existe tool de entrada para a IA.

### ⚠️ Riscos (leia antes de instalar)
- **Futuro pode deixar a conta negativa.** Gap forte, leilão ou falta de liquidez podem executar o stop muito pior
  que o planejado; a perda pode passar do saldo e o valor fica **devido à corretora**.
- Os limites de **R$30/dia e R$60 no total** são calculados sobre o preço de stop planejado. **Não são garantia.**
- Não houve backtest nem demo: o objetivo desta fase é validar execução e coletar dados, não crescer a banca.
  Dois dias de stop cheio encerram o experimento (trava de perda total desliga o agendador; religar é decisão sua).
- 1 contrato sempre; margem de day trade do WIN na Clear tem que caber no saldo (senão não roda com R$100).

### Como funciona
```
07:45  morning.py      coletores (Yahoo, RSS, agenda) + analistas macro/contexto/técnico/fluxo -> bull x bear -> dossiê
       run_b3 plan     operador lê o dossiê e grava o plano (write_day_plan: bear independente por setup, schema fechado)
08:55  executor.py     loop de 2 s: gatilho no fechamento da barra -> risk_b3 -> ordem com SL+TP no mesmo envio
       watchdog.py     1x/min (e dentro do executor): sem SL, volume > 1, fora da janela, banco != MT5, terminal
                       caído, conta errada -> zera e pausa; perda diária trava o dia; perda total desliga tudo
hora   run_b3 revise   revisão curta: só reduz risco
17:30  executor        zera tudo (flatten_at) ; 17:45 run_b3 close: post-mortems + nota do dia
sábado run_b3 weekly   analytics: real x sombra_regra (sem LLM) x sombra_sem_macro -> propostas (nunca aplica)
```

### Instalação
1. Terminal **MetaTrader 5 da Clear** (servidor `CLEAR PRD`), logado na conta real, **Algo Trading ligado**.
   O pacote Python `MetaTrader5` só roda no Windows e fala com o terminal aberto.
2. `uv sync` (instala o `MetaTrader5`). Codex CLI logado (`backend: codex` em `config/cycle.yaml`).
3. `config/b3.yaml`: confira sessão, custos e símbolo contínuo contra a Clear (itens `[VERIFICAR]`).
   `config/b3_calendar.yaml`: preencha os eventos de alto impacto da semana (Copom, IPCA, payroll, CPI, FOMC).
4. `mode: "dry"` e rode `uv run python -m trader.smoke` (MT5 real, só leitura; ordens no papel). **Tudo OK** antes de
   seguir. Deixe alguns pregões em `dry` (o executor opera no papel com dados reais e grava tudo).
5. Para live: `account_number: <sua conta>` e `mode: "live"` **à mão**; rode o smoke de novo.
   Live só envia ordem se a conta logada for real **e** o número bater. No primeiro pregão tudo vira aviso no Telegram.
6. `powershell -ExecutionPolicy Bypass -File scripts\install_tasks_b3.ps1` cria as tarefas do agendador.

| Comando | O quê |
|---|---|
| `uv run python -m trader.smoke [--sim] [--no-llm]` | teste de fumaça; qualquer FALHOU = não liberar live |
| `uv run python -m trader.morning [--then-plan]` | dossiê do dia (e o plano) |
| `uv run python -m trader.run_b3 --kind plan\|revise\|close\|weekly` | operador |
| `uv run python -m trader.executor` / `trader.watchdog` | pregão |
| `uv run python -m trader.analytics --days 7` | relatório (setup, horário, regime, analistas, ablação) |
| `uv run python -m trader.watchdog --religar --yes` | limpa a trava de perda total (decisão humana) |
| `/b3`, `/plano`, `/kill confirmar` no Telegram | status, plano do dia, zera WIN + cripto |

### Imposto (day trade)
20% sobre o lucro líquido mensal de day trade, via DARF (código 6015) até o último dia útil do mês seguinte; a
corretora retém 1% de IRRF na fonte, que abate do devido. Prejuízo de day trade só compensa com lucro de day trade.
**Confirme com um contador.** `b3_trades` guarda preço, custo estimado e resultado de cada operação.

### Pendências para você verificar
Margem de day trade do WIN na Clear · horário da zeragem compulsória (ajuste `flatten_at` para antes) · nome do
contínuo (`WIN$`?) · custos reais na primeira nota de corretagem (`costs_per_contract_brl`) · se a Clear entrega
flags de agressão e book no MT5 · horários de pregão (mudam com o horário de verão dos EUA) · se o servidor MT5 da
Clear está no horário de Brasília (o smoke compara o relógio do último tick).

## Estrutura
`src/trader/`: `risk.py` (puro), `broker/binance_spot.py` (ccxt + OPOCO/OCO), `broker/base.py` (interface de corretora), `trading.py` (operações), `sync.py` (reconciliação + preflight), `scan.py`, `regime.py`, `shadow.py`, `journal.py`, `mcp_server.py`, `run_cycle.py`, `telegram_daemon.py`, `kill.py`, `report.py`.
Modo B3: `risk_b3.py` (puro), `broker/mt5.py` + `broker/sim.py` (papel/replay), `trading_b3.py`, `plan.py`, `executor.py`, `watchdog.py`, `morning.py`, `mcp_server_b3.py`, `run_b3.py`, `analytics.py`, `smoke.py`, `b3/` (config, instrumento, features, fluxo, regime, agenda, runtime), `collectors/`. Instruções do operador em `CLAUDE_B3.md`.
Dados em `data/` (SQLite, logs, audit JSONL append-only): não versionado.
