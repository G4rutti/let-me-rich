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
- Resoluções BCB 519–521: exchanges precisam protocolar pedido de autorização até 30/10/2026. Até 18/09/2026 a Binance não havia protocolado publicamente. O código usa ccxt; trocar de exchange exige reimplementar só a entrada protegida (OPOCO/OCO) em `exchange.py`.

## Estrutura
`src/trader/`: `risk.py` (puro), `exchange.py` (ccxt + OPOCO/OCO), `trading.py` (operações), `sync.py` (reconciliação + preflight), `scan.py`, `regime.py`, `shadow.py`, `journal.py`, `mcp_server.py`, `run_cycle.py`, `telegram_daemon.py`, `kill.py`, `report.py`.
Dados em `data/` (SQLite, logs, audit JSONL append-only): não versionado.
