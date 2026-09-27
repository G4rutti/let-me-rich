// Roteiro: transforma os eventos do ciclo (tools, pensamentos, resumo) em falas entre os personagens.
// Tudo que é dito vem dos dados do ciclo; só o jeito de falar é inventado.

// quem atende cada tool
export const STATION_OF = {
  preflight: "guarda", get_safety_status: "guarda",
  sync_positions: "mesa", get_portfolio: "mesa", get_regime: "mesa", scan_market: "mesa",
  move_stop: "mesa", take_partial: "mesa", close_position: "mesa",
  get_candles: "astra", read_charts: "luna", place_entry: "sol",
  get_pending_postmortems: "arquivista", get_setup_stats: "arquivista", get_recent_journal: "arquivista",
  write_journal: "arquivista", write_proposal: "arquivista",
};

const n = (v, d = 2) => (v == null || v === "" || Number.isNaN(Number(v)) ? String(v ?? "?")
  : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: d }));
const usd = (v) => "US$ " + n(v, 2);
const sym = (s) => String(s || "").replace("/USDT", "");
const cut = (s, k = 150) => { s = String(s || "").replace(/\s+/g, " ").trim(); return s.length > k ? s.slice(0, k - 1) + "…" : s; };
const pick = (arr, i) => arr[Math.abs(i) % arr.length];
const trendPt = { up: "subindo", down: "caindo", flat: "de lado" };
const list = (xs) => xs.length <= 1 ? xs.join("") : xs.slice(0, -1).join(", ") + " e " + xs[xs.length - 1];

// ------------------------------------------------------------------ pedidos (o operador fala)
function ask(tool, a, i) {
  switch (tool) {
    case "preflight": return pick(["Bom dia! Tô liberado pra operar?", "Antes de tudo: checa as travas pra mim?", "Posso começar? Como tão os sistemas?"], i);
    case "get_safety_status": return pick(["Quanto ainda posso arriscar hoje?", "Me lembra os limites de hoje?"], i);
    case "sync_positions": return pick(["Bate minhas posições com a corretora, por favor.", "Sincroniza tudo com a exchange pra mim?"], i);
    case "get_regime": return pick(["E o Bitcoin, como tá? Qual o regime?", "Como tá o humor do mercado?"], i);
    case "get_portfolio": return pick(["Me passa a carteira?", "Como tá a banca agora?"], i);
    case "scan_market": return pick(["Roda o scanner: quem tá se mexendo?", "Quais pares passaram nos filtros?"], i);
    case "get_pending_postmortems": return "Tem trade fechado esperando post-mortem?";
    case "get_setup_stats": return pick(["Quais setups tão funcionando?", "Me mostra os números por setup?"], i);
    case "get_recent_journal": return pick(["Me lembra o que anotei nos últimos ciclos?", "Lê pra mim as últimas anotações do diário?"], i);
    case "read_charts": { const s = (a.symbols || []).map(sym); return `Luna, dá uma olhada no gráfico de ${list(s)} pra mim?`; }
    case "get_candles": return `Deixa eu ver o ${sym(a.symbol)} no ${a.timeframe || "1h"}…`;
    case "place_entry":
      return `Sol, quero comprar ${sym(a.symbol)} (${a.setup}). Stop ${n(a.stop_price, 6)}, alvo ${n(a.target_price, 6)}. ` +
        `${cut(a.reason, 120)} Me convence do contrário.`;
    case "write_journal": {
      const what = { skip: `pulei ${sym(a.symbol)}`, entry: `entrei em ${sym(a.symbol)}`, manage: `gestão de ${sym(a.symbol)}`,
        postmortem: `post-mortem do trade #${a.trade_id}`, cycle_note: "nota do ciclo" }[a.kind] || a.kind;
      const why = a.kind === "postmortem" ? `Lição: ${a.lesson}` : a.thesis;
      return `Anota aí: ${what}. ${cut(why, 140)}`;
    }
    case "move_stop": return `Sobe o stop de ${sym(a.symbol)} pra ${n(a.new_stop, 6)}.`;
    case "take_partial": return `Realiza ${Math.round((a.fraction || 0) * 100)}% de ${sym(a.symbol)}. ${cut(a.reason, 100)}`;
    case "close_position": return `Zera ${sym(a.symbol)}. ${cut(a.reason, 100)}`;
    case "write_proposal": return `Anota uma proposta: "${cut(a.title, 70)}".`;
    default: return `Preciso de um ${tool}.`;
  }
}

// ------------------------------------------------------------------ respostas (quem atende fala)
function answer(tool, d, a, i) {
  switch (tool) {
    case "preflight":
      if (d.status === "OK") return { text: `Tudo liberado. Modo ${d.mode}, nenhum problema.` + (d.warnings?.length ? ` Atenção: ${cut(d.warnings.join("; "), 90)}` : ""), mood: "good" };
      if (d.status === "MANAGE_ONLY") return { text: `Hoje só gestão, nada de entrada nova. ${cut([...(d.problems || []), ...(d.warnings || [])].join("; "), 110)}`, mood: "bad" };
      return { text: `Negativo. ${cut((d.problems || []).join("; "), 120)} Encerra o ciclo.`, mood: "bad" };
    case "get_safety_status":
      return { text: `${d.trades_today} de ${d.max_trades_per_day} trades hoje. Ainda dá pra perder ${usd(d.daily_loss_left_usd)}.` + (d.paused ? " E o bot tá pausado!" : "") };
    case "sync_positions": {
      const ev = d.events || [], pm = d.pending_postmortems || 0;
      return { text: (ev.length ? `Atualizei ${ev.length} coisa(s) desde o último ciclo.` : "Tudo batendo com a corretora.") + (pm ? ` Tem ${pm} post-mortem pendente.` : "") };
    }
    case "get_regime":
      return { text: `Bitcoin a ${usd(d.btc_price)}: ${trendPt[d.btc_trend_4h] || d.btc_trend_4h} no 4h, ${trendPt[d.btc_trend_1h] || d.btc_trend_1h} no 1h. Regime ${d.regime}.`,
        mood: d.regime === "BULL" ? "good" : d.regime === "BEAR" ? "bad" : "" };
    case "get_portfolio": {
      const ps = (d.positions || []).map((p) => `${sym(p.symbol)} a ${n(p.r_now)}R (${n(p.unrealized_pct)}%)`);
      return { text: `Banca de ${usd(d.equity_usd)}, ${n(d.free_usdt)} USDT livres. ` + (ps.length ? `Posições: ${list(ps)}.` : "Nenhuma posição aberta.") };
    }
    case "scan_market": {
      const c = d.candidates || [];
      if (!c.length) return { text: `${d.passed_filters ?? 0} passaram nos filtros, mas nenhum candidato bom agora.` };
      return { text: `${d.passed_filters} pares passaram nos filtros. Os melhores: ${list(c.slice(0, 3).map((x) => `${sym(x.symbol)} (${n(x.score, 2)})`))}.` };
    }
    case "get_pending_postmortems": {
      const t = d.trades || [];
      return { text: t.length ? `${t.length} esperando: ${list(t.map((x) => `#${x.id ?? x.trade_id} ${sym(x.symbol)}`))}.` : "Nada pendente, tá tudo documentado." };
    }
    case "get_setup_stats": {
      const ag = d.agent || {}, names = Object.keys(ag);
      if (!names.length) return { text: `Ainda não tem amostra suficiente em nenhum setup (mínimo ${d.min_samples}).` };
      const st = names.slice(0, 4).map((k) => { const s = ag[k]; const status = s.status || s.total?.status || ""; return `${k} ${status}`.trim(); });
      return { text: `Por setup: ${list(st)}.` };
    }
    case "get_recent_journal": {
      const e = d.entries || [], c = {};
      e.forEach((x) => (c[x.kind] = (c[x.kind] || 0) + 1));
      const kinds = { skip: "skips", entry: "entradas", manage: "gestões", postmortem: "post-mortems", cycle_note: "notas" };
      const last = e[0];
      return { text: `Nos últimos ${e.length}: ${list(Object.entries(c).map(([k, v]) => `${v} ${kinds[k] || k}`))}.` +
        (last ? ` O último: ${last.kind} ${sym(last.symbol || "")} — ${cut(last.thesis || last.lesson, 90)}` : "") };
    }
    case "read_charts": {
      const lines = (d.pairs || []).map((p) =>
        `${sym(p.symbol)}: ${p.trend_4h} no 4h, ${p.trend_1h} no 1h, ${p.pattern}. Suporte ${n(p.support, 6)}, resistência ${n(p.resistance, 6)}; a ideia morre abaixo de ${n(p.invalidation, 6)}.`);
      return { text: lines.join("\n") || "Não consegui ler nada." };
    }
    case "get_candles": {
      const x = d.indicators || {};
      return { text: `RSI ${n(x.rsi14, 1)}, EMA20 ${n(x.ema20, 6)} vs EMA50 ${n(x.ema50, 6)}, ATR ${n(x.atr14_pct, 2)}%.`, think: true };
    }
    case "write_journal": return { text: pick(["Anotado.", "Registrado no diário.", "Tá no livro."], i) + (d.journal_id ? ` (#${d.journal_id})` : "") };
    case "write_proposal": return { text: `Proposta guardada em ${d.file}.` };
    case "move_stop": return { text: `Feito. Stop de ${sym(a.symbol)} agora em ${n(a.new_stop, 6)}.`, mood: "good" };
    case "take_partial": return { text: `Parcial executada em ${sym(a.symbol)}.`, mood: "good" };
    case "close_position": return { text: `Posição em ${sym(a.symbol)} zerada.`, mood: "good" };
    default: return { text: cut(JSON.stringify(d), 160) };
  }
}

function problem(text) {   // recusas e erros → frase curta
  const t = String(text || "");
  const m = t.match(/RECUSADO\s+([A-Z_]+):?\s*(.*)/s);
  if (m) return { code: m[1], hint: cut(m[2], 200) };
  if (/validation error/i.test(t)) {
    if (/at most (\d+) characters/.test(t)) return { code: "TEXTO_LONGO", hint: `passou de ${t.match(/at most (\d+) characters/)[1]} caracteres` };
    return { code: "INVALIDO", hint: cut(t.split("\n")[0], 120) };
  }
  if (/^EXCHANGE/.test(t)) return { code: "EXCHANGE", hint: cut(t.replace(/^EXCHANGE\s*/, ""), 160) };
  return { code: "ERRO", hint: cut(t, 160) };
}

// ------------------------------------------------------------------ beats
// beat = { who, to?, text, kind?: "say"|"think", mood?: "good"|"bad", walk?: stationKey, tool?, fx? }
export function beatsFor(ev, i) {
  if (ev.kind === "message") {
    let j = null; try { j = JSON.parse(ev.text); } catch { /* texto livre */ }
    if (j && j.summary) {
      const entries = (j.actions || []).filter((a) => a.type === "entry");
      const out = [{ who: "astra", to: "todos", walk: "desk", text: `Fechando o ciclo: ${cut(j.summary, 220)}`, final: j }];
      if (j.preflight_status === "ABORT") out.push({ who: "guarda", to: "astra", text: "Ciclo abortado. Melhor assim do que operar às cegas." });
      else if (entries.length) out.push({ who: "sol", to: "astra", text: `Boa sorte com ${list(entries.map((e) => sym(e.symbol)))}. Vou ficar de olho.` });
      else out.push({ who: "sol", to: "astra", text: pick(["Ficar de fora também é posição.", "Nenhum trade é melhor que um trade ruim.", "Paciência paga as taxas."], i) });
      return out;
    }
    return [{ who: "astra", kind: "think", text: cut(ev.text, 170) }];
  }
  if (ev.kind === "usage") return [{ system: true, text: `Ciclo usou ${n(Math.round((ev.usage.input_tokens || 0) / 1000), 0)}k tokens de entrada (${n(Math.round((ev.usage.cached_input_tokens || 0) / 1000), 0)}k em cache) e ${n(ev.usage.output_tokens, 0)} de saída.`, usage: ev.usage }];
  if (ev.kind === "error") return [{ who: "astra", kind: "say", mood: "bad", text: `Deu erro no Codex: ${cut(ev.text, 140)}` }];

  const tool = ev.tool, who = STATION_OF[tool] || "mesa", a = ev.args || {};
  if (ev.phase === "start") {
    if (who === "astra") return [{ who: "astra", kind: "think", walk: "desk", text: ask(tool, a, i), tool }];
    return [{ who: "astra", to: who, walk: who, text: ask(tool, a, i), tool, working: who }];
  }
  // fim da chamada
  const d = ev.data;
  const errText = ev.error || (!d ? ev.result : null);
  if (errText) {
    const p = problem(errText);
    if (tool === "place_entry" && p.code === "BEAR_VETO") {
      const force = (p.hint.match(/força (\d)/) || [])[1];
      return [{ who: "sol", to: "astra", mood: "bad", text: `Não entra.${force ? ` Força ${force} de 5.` : ""} ${cut(p.hint.replace(/^força \d:\s*/, ""), 230)}`, tool, fx: "veto" },
        { who: "astra", to: "sol", text: pick(["Justo. Fica pra próxima.", "Ok, você me convenceu.", "Tá bom, não vou brigar com os números."], i) }];
    }
    if (tool === "place_entry" && p.code === "REVIEW_FAILED")
      return [{ who: "sol", to: "astra", mood: "bad", text: `Não consegui revisar a tempo (${p.hint}). Sem revisão, sem entrada.`, tool, fx: "veto" }];
    const speaker = ["NOT_IN_UNIVERSE", "EXCHANGE"].includes(p.code) ? "mesa" : tool === "write_journal" ? "arquivista" : "guarda";
    const msg = p.code === "TEXTO_LONGO" ? `Não coube: o texto ${p.hint}. Resume aí.` : `Barrado: ${p.code}. ${p.hint}`;
    return [{ who: speaker, to: "astra", mood: "bad", text: msg, tool, fx: "bad" }];
  }
  if (tool === "place_entry") {
    const br = d.bear_review;
    const out = [];
    if (br) out.push({ who: "sol", to: "astra", mood: "good", text: `Olha… o pior que achei foi: ${cut((br.against || [])[0], 120)} Mas é força ${br.strength}. Pode ir.`, tool });
    out.push({ who: "astra", to: "mesa", walk: "mesa", text: `Manda a compra de ${sym(a.symbol)}!` });
    out.push({ who: "mesa", to: "astra", mood: "good", fx: "order", text: `Ordem enviada: ${sym(a.symbol)}, trade #${d.trade_id ?? "?"} (${d.status ?? "ok"}). Stop e alvo já na corretora.`, tool });
    return out;
  }
  const r = answer(tool, d, a, i);
  if (r.think) return [{ who: "astra", kind: "think", text: r.text, tool, data: d }];
  const fx = ["move_stop", "take_partial", "close_position"].includes(tool) ? "order" : tool === "preflight" ? "vault" : null;
  return [{ who, to: "astra", mood: r.mood, text: r.text, tool, fx, data: d }];
}

// papo de corredor entre ciclos: sem fatos, só clima de escritório
export const IDLE = [
  ["luna", "sol", "Café?"], ["sol", "luna", "Só se for sem açúcar. Igual o mercado hoje."],
  ["mesa", "guarda", "Movimento calmo por aqui."], ["guarda", "mesa", "Calmo é bom. Calmo não estoura limite."],
  ["arquivista", "luna", "Alguém lembra de resumir as teses? O diário tem limite de 300 caracteres."],
  ["luna", "arquivista", "Vou avisar o Astra."], ["sol", "guarda", "Se ele quiser entrar em meme hoje, eu vou ser chato."],
  ["guarda", "sol", "Eu sou chato por contrato."], ["luna", "sol", "Esse pavio no 4h tá me incomodando."],
  ["sol", "luna", "Tudo te incomoda. Por isso você é boa."],
];
