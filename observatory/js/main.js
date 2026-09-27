import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { buildWorld } from "./world.js";
import { Person } from "./people.js";
import { beatsFor, IDLE, STATION_OF } from "./story.js";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const speed = () => Number($("speed").value);

// ------------------------------------------------------------------ render
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.55;
$("scene").appendChild(renderer.domElement);
const labels = new CSS2DRenderer(); labels.setSize(innerWidth, innerHeight); $("labels").appendChild(labels.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 5000);
camera.position.set(4, 17, 22);
// o painel da conversa ocupa a direita: desloca o centro da projeção para a área livre
function fitView() {
  const P = innerWidth > 860 ? 380 : 0;
  camera.aspect = (innerWidth + P) / innerHeight;   // aspect do quadro virtual inteiro (pixels quadrados)
  if (P) camera.setViewOffset(innerWidth + P, innerHeight, P, 0, innerWidth, innerHeight); else camera.clearViewOffset();
  camera.updateProjectionMatrix();
}
fitView();
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.8, -5); controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.46; controls.minDistance = 4; controls.maxDistance = 60;

const world = buildWorld(scene, renderer);

// ------------------------------------------------------------------ elenco
const cast = {
  astra: new Person(scene, { name: "Astra", role: "operador", color: "#d4a017", suit: 0x1c2a4a, tie: 0xc9a14a, skin: 0xe8b88f, hair: 0x3b2618, hairStyle: "side" }),
  luna: new Person(scene, { name: "Luna", role: "gráficos", color: "#8b7cf6", suit: 0x3b2f5c, noTie: true, tie: 0xb7a9ff, skin: 0xf1c9a5, hair: 0x141414, hairStyle: "bob", glasses: true }),
  sol: new Person(scene, { name: "Sol", role: "advogado do diabo", color: "#f26b38", suit: 0x2f2f33, tie: 0xff7a45, skin: 0xa8704a, hair: 0x111111, hairStyle: "curly" }),
  mesa: new Person(scene, { name: "Mesa", role: "exchange · código", color: "#1f9bd1", suit: 0x1f4f6b, tie: 0x4cc9f0, skin: 0xc68a5e, hair: 0x2a1a10, hairStyle: "short" }),
  guarda: new Person(scene, { name: "Guarda", role: "risk manager · código", color: "#64748b", suit: 0x1d1f23, tie: 0x6b7280, skin: 0x8d5a3b, hair: 0x111111, hairStyle: "bald" }),
  arquivista: new Person(scene, { name: "Arquivista", role: "diário · código", color: "#a47b3b", suit: 0x6b4a2e, noTie: true, tie: 0xd6b98c, skin: 0xf0c8a0, hair: 0x9a9a9a, hairStyle: "bun", glasses: true }),
};
const NAMES = { astra: "Astra", luna: "Luna", sol: "Sol", mesa: "Mesa", guarda: "Guarda", arquivista: "Arquivista", todos: "todos" };
const V = (x, z) => new THREE.Vector3(x, 0, z);
cast.astra.sit(world.astraSeat, 0);
cast.luna.sit(world.luna.seat, world.luna.faceAngle);
cast.sol.sit(world.sol.seat, world.sol.faceAngle);
cast.mesa.place(V(0, -15.9), 0);
cast.guarda.place(V(-13.2, -14.9), Math.atan2(13.2, 9.9));
cast.arquivista.place(V(15.9, -9.6), -Math.PI / 2);
const extras = world.traders.map((t, i) => {
  const looks = [[0x2d3342, 0xe0b089, "short", 0x3b2618], [0x4a3b30, 0xc68a5e, "long", 0x2a1a10], [0x23303d, 0xf1c9a5, "curly", 0x6b4a2e], [0x3a3f4f, 0x8d5a3b, "bald", 0x111111]][i];
  const p = new Person(scene, { suit: looks[0], tie: 0x4cc9f0, skin: looks[1], hair: looks[3], hairStyle: looks[2], noTie: i === 1 });
  p.sit(t.seat, Math.PI); p.typing = true; return p;
});
const everyone = [...Object.values(cast), ...extras];

// onde o operador para para falar com cada um
const SPOT = { mesa: V(0, -13.6), guarda: V(-11.5, -12.8), arquivista: V(13.6, -9.6), luna: V(-10.9, -3), sol: V(10.9, -3) };
const HUB = V(0, -6.8), DESK_EXIT = V(0, -3.05);

async function astraGo(key) {
  const a = cast.astra;
  if (key === "desk" || key === "astra") {
    if (a.state === "sit") return;
    const pts = [HUB, DESK_EXIT, world.astraSeat].filter((p) => p.distanceTo(a.pos) > 0.3);
    await a.walk(pts); a.sit(world.astraSeat, 0); return;
  }
  const target = SPOT[key]; if (!target || target.distanceTo(a.pos) < 0.3) return;
  const pts = [];
  if (a.state === "sit") { a.state = "stand"; a.pos.copy(DESK_EXIT).setZ(-2.7); await sleep(300 / speed()); }
  if (a.pos.distanceTo(HUB) > 1 && !(Math.abs(a.pos.z - target.z) < 1 && Math.abs(a.pos.x - target.x) < 3)) pts.push(HUB);
  pts.push(target);
  await a.walk(pts);
  a.faceTo(cast[key].pos);
}

// ------------------------------------------------------------------ estado do pregão (telão, letreiro, barra)
const state = { regime: "—", btc: null, equity: null, free: null, positions: [], candidates: [], passed: null, last: "aguardando o próximo ciclo…", tokens: null, preflight: "" };
function absorb(tool, d) {
  if (!d) return;
  if (tool === "get_regime") { state.regime = d.regime; state.btc = d.btc_price; }
  if (tool === "get_portfolio" || (tool === "sync_positions" && d.portfolio)) {
    const p = tool === "get_portfolio" ? d : d.portfolio; state.equity = p.equity_usd; state.free = p.free_usdt; state.positions = p.positions || [];
  }
  if (tool === "scan_market") { state.candidates = d.candidates || []; state.passed = d.passed_filters; }
  if (tool === "preflight") state.preflight = d.status;
  renderBar();
}
function renderBar() {
  $("s-regime").textContent = state.regime; $("s-regime").dataset.v = state.regime;
  $("s-equity").textContent = state.equity != null ? "US$ " + state.equity.toFixed(2) : "—";
  $("s-pos").textContent = state.positions.map((p) => `${p.symbol.replace("/USDT", "")} ${p.r_now ?? "?"}R`).join(" · ") || "nenhuma";
  $("s-tokens").textContent = state.tokens ? `${Math.round(state.tokens.input_tokens / 1000)}k` : "—";
}
const chartSeed = Array.from({ length: 120 }, (_, i) => Math.sin(i * 0.21) * 12 + Math.sin(i * 0.05) * 30 + i * 0.4);
function drawWall(now) {
  const { g, c, t } = world.exchange.wall, W = c.width, H = c.height;
  const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#07111f"); bg.addColorStop(1, "#0b1a2e");
  g.fillStyle = bg; g.fillRect(0, 0, W, H);
  g.fillStyle = "#e8eef8"; g.font = "600 54px Inter, Segoe UI, sans-serif"; g.fillText("PREGÃO · SPOT USDT", 56, 90);
  g.fillStyle = "#7f93b0"; g.font = "36px Consolas, monospace"; g.fillText(new Date(now).toLocaleTimeString("pt-BR"), W - 250, 88);
  // regime pill
  const rc = state.regime === "BULL" ? "#22c55e" : state.regime === "BEAR" ? "#ef4444" : "#eab308";
  g.fillStyle = rc; g.beginPath(); g.roundRect(56, 125, 330, 74, 37); g.fill();
  g.fillStyle = "#06101c"; g.font = "700 42px Inter, Segoe UI, sans-serif"; g.fillText(`REGIME ${state.regime}`, 82, 176);
  g.fillStyle = "#e8eef8"; g.font = "600 44px Inter, Segoe UI, sans-serif";
  g.fillText(`BANCA ${state.equity != null ? "US$ " + state.equity.toFixed(2) : "—"}`, 430, 176);
  g.fillText(`BTC ${state.btc ? "US$ " + Math.round(state.btc).toLocaleString("pt-BR") : "—"}`, 960, 176);
  // gráfico decorativo animado
  g.save(); g.translate(56, 250); const cw = 900, ch = 300;
  g.strokeStyle = "rgba(127,147,176,.18)"; g.lineWidth = 2;
  for (let y = 0; y <= ch; y += 60) { g.beginPath(); g.moveTo(0, y); g.lineTo(cw, y); g.stroke(); }
  const off = (now / 400) % 1, pts = chartSeed.map((v, i) => [i * (cw / 119), ch * 0.55 - v * 2.2 - Math.sin(now / 900 + i * 0.3) * 6]);
  const grad = g.createLinearGradient(0, 0, 0, ch); grad.addColorStop(0, "rgba(34,197,94,.35)"); grad.addColorStop(1, "rgba(34,197,94,0)");
  g.beginPath(); g.moveTo(0, ch); pts.forEach(([x, y]) => g.lineTo(x, y)); g.lineTo(cw, ch); g.closePath(); g.fillStyle = grad; g.fill();
  g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.strokeStyle = "#22c55e"; g.lineWidth = 4; g.stroke();
  g.fillStyle = "#22c55e"; g.beginPath(); g.arc(pts[119][0], pts[119][1], 9 + off * 6, 0, 7); g.fill();
  g.restore();
  // posições
  g.fillStyle = "#7f93b0"; g.font = "600 32px Inter, Segoe UI, sans-serif"; g.fillText("POSIÇÕES", 1010, 280);
  g.font = "36px Consolas, monospace";
  if (!state.positions.length) { g.fillStyle = "#56657d"; g.fillText("nenhuma", 1010, 330); }
  state.positions.slice(0, 3).forEach((p, i) => {
    g.fillStyle = (p.r_now ?? 0) >= 0 ? "#22c55e" : "#ef4444";
    g.fillText(`${p.symbol.replace("/USDT", "").padEnd(6)} ${String(p.r_now ?? "?").padStart(6)}R`, 1010, 330 + i * 46);
    g.fillStyle = "#7f93b0"; g.font = "26px Consolas, monospace";
    g.fillText(`stop ${p.stop} · alvo ${p.target}`, 1010, 360 + i * 46); g.font = "36px Consolas, monospace";
  });
  g.fillStyle = "#7f93b0"; g.font = "600 32px Inter, Segoe UI, sans-serif";
  g.fillText(`SCAN${state.passed != null ? ` · ${state.passed} passaram` : ""}`, 1510, 280);
  g.font = "34px Consolas, monospace";
  state.candidates.slice(0, 6).forEach((cd, i) => {
    const y = 330 + i * 50; g.fillStyle = "#e8eef8"; g.fillText(cd.symbol.replace("/USDT", "").padEnd(7), 1510, y);
    g.fillStyle = "#1f9bd1"; g.fillRect(1680, y - 24, (cd.score || 0) * 280, 22);
  });
  // rodapé
  g.fillStyle = "rgba(212,160,23,.12)"; g.fillRect(0, H - 96, W, 96);
  g.fillStyle = "#f5c451"; g.font = "600 40px Inter, Segoe UI, sans-serif"; g.fillText("▸ " + state.last, 56, H - 34);
  t.needsUpdate = true;
}
function drawTicker(now) {
  const { g, c, t } = world.exchange.tick;
  g.fillStyle = "#050a12"; g.fillRect(0, 0, c.width, c.height);
  const items = state.candidates.length
    ? state.candidates.slice(0, 12).map((x) => [x.symbol.replace("/USDT", ""), x.price, x.ret_1h])
    : [["BTC", state.btc, 0], ["LET", null, 0], ["ME", null, 0], ["RICH", null, 0]];
  g.font = "600 36px Consolas, monospace";
  const parts = items.map(([s, p, r]) => ({ s: `${s} ${p != null ? Number(p).toLocaleString("pt-BR", { maximumSignificantDigits: 6 }) : ""} ${r ? (r > 0 ? "▲" : "▼") + Math.abs(r).toFixed(2) + "%" : ""}   `, r }));
  const total = parts.reduce((a, p) => a + g.measureText(p.s).width, 0) || 1;
  let x = -((now / 12) % total);
  while (x < c.width) for (const p of parts) { g.fillStyle = p.r > 0 ? "#22c55e" : p.r < 0 ? "#ef4444" : "#f5c451"; g.fillText(p.s, x, 46); x += g.measureText(p.s).width; }
  t.needsUpdate = true;
}
function drawScreen(s, t, hot) {
  const { g, c } = s;
  g.fillStyle = "#08101c"; g.fillRect(0, 0, c.width, c.height);
  g.strokeStyle = "rgba(127,147,176,.15)";
  for (let y = 24; y < c.height; y += 30) { g.beginPath(); g.moveTo(0, y); g.lineTo(c.width, y); g.stroke(); }
  let p = c.height * 0.55;
  for (let i = 0; i < 30; i++) {
    const nz = Math.sin(i * 0.7 + t * (hot ? 2 : 0.5) + s.seed) * 10 + Math.sin(i * 2.3 + s.seed * 3) * 6;
    const o = p, cl = c.height * 0.55 + nz - i * 0.6 * s.trend; p = cl;
    g.strokeStyle = g.fillStyle = cl < o ? "#22c55e" : "#ef4444";
    const x = 10 + i * 10;
    g.beginPath(); g.moveTo(x + 3, Math.min(o, cl) - 6); g.lineTo(x + 3, Math.max(o, cl) + 6); g.stroke();
    g.fillRect(x, Math.min(o, cl), 6, Math.max(2, Math.abs(cl - o)));
  }
  g.fillStyle = hot ? "#f5c451" : "rgba(232,238,248,.6)"; g.font = "600 16px Inter, Segoe UI, sans-serif"; g.fillText(s.title || "", 10, 18);
  s.t.needsUpdate = true;
}

// ------------------------------------------------------------------ efeitos
const fx = [];
function flash(pos, color, big = false) {
  const l = new THREE.PointLight(color, big ? 40 : 25, 9, 1.6); l.position.copy(pos).setY(2.4); scene.add(l);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.3, 0.42, 48), new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.copy(pos).setY(0.03); scene.add(ring);
  fx.push({ l, ring, t: 0 });
}
const coins = [];
function coinShower(pos) {   // ordem enviada: moedas saltando do balcão
  for (let i = 0; i < 14; i++) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.02, 16), new THREE.MeshStandardMaterial({ color: 0xf5c451, metalness: 1, roughness: 0.25 }));
    m.position.copy(pos).setY(1.3); scene.add(m);
    coins.push({ m, v: new THREE.Vector3((Math.random() - 0.5) * 3, 3 + Math.random() * 2, (Math.random() - 0.3) * 3), t: 0 });
  }
}
let wheelSpin = 0;
const working = { mesa: 0, guarda: 0, arquivista: 0, luna: 0, sol: 0 };
function setWorking(k, on) { if (k in working) working[k] = on ? 1 : 0; if (k === "luna" || k === "sol") cast[k].typing = !!on; }

// ------------------------------------------------------------------ conversa (transcrição)
function chat(beat) {
  const div = document.createElement("div");
  if (beat.system) { div.className = "msg sys"; div.textContent = beat.text; }
  else {
    const p = cast[beat.who];
    div.className = `msg ${beat.kind === "think" ? "think" : ""} ${beat.mood || ""}`;
    div.innerHTML = `<i style="background:${p.o.color}">${p.o.name[0]}</i><div><b>${esc(p.o.name)}</b>` +
      (beat.to ? `<span class="to">→ ${esc(NAMES[beat.to] || beat.to)}</span>` : "") +
      (beat.kind === "think" ? `<span class="to">pensando</span>` : "") +
      (beat.tool ? `<code>${esc(beat.tool)}</code>` : "") + `<p>${esc(beat.text)}</p></div>`;
  }
  const log = $("chat"); log.appendChild(div);
  if (log.scrollHeight - log.scrollTop - log.clientHeight < 240) log.scrollTop = log.scrollHeight;
}
function renderSummary(j) {
  const acts = (j.actions || []).map((a) =>
    `<div class="act"><span class="pill ${a.type}">${esc(a.type)}</span><b>${esc(a.symbol || "—")}</b> ${esc(a.detail)}</div>`).join("");
  $("summary").innerHTML = `<div class="sumh">Resultado · preflight ${esc(j.preflight_status)} · ${esc(j.regime)}</div>${acts}`;
}

// ------------------------------------------------------------------ execução das falas
let focus = null, lastSpeaker = null;   // quem a câmera acompanha / quem falou por último
async function perform(b, my) {
  if (b.system) { chat(b); if (b.usage) { state.tokens = b.usage; renderBar(); } return; }
  const sp = cast[b.who];
  if (b.walk && b.who === "astra") { await astraGo(b.walk); if (my !== epoch) return; }
  if (b.working) setWorking(b.working, true);
  if (b.tool && b.data !== undefined) absorb(b.tool, b.data);
  if (b.tool && !b.working && STATION_OF[b.tool]) setWorking(STATION_OF[b.tool], false);
  const to = b.to && cast[b.to];
  everyone.forEach((p) => { p.lookAt = null; if (p !== sp && p !== lastSpeaker) p.hush(); });   // só pergunta + resposta na tela
  lastSpeaker = sp;
  if (to) { sp.lookAt = to.worldHead(); to.lookAt = sp.worldHead(); if (sp.state === "stand") sp.faceTo(to.pos); }
  if (b.to === "todos") Object.values(cast).forEach((p) => p !== sp && (p.lookAt = sp.worldHead()));
  const dur = Math.min(9000, Math.max(2300, 1500 + b.text.length * 42)) / speed();
  sp.say(esc(b.text).replace(/\n/g, "<br>"), { kind: b.kind === "think" ? "think" : b.mood || "", ms: dur * 1.35, to: to ? NAMES[b.to] : b.to === "todos" ? "todos" : "" });
  chat(b); focus = [sp, to];
  state.last = `${sp.o.name}: ${b.text.split("\n")[0].slice(0, 90)}`;
  if (b.fx === "veto") flash(cast.sol.pos, 0xef4444, true);
  if (b.fx === "bad") flash(sp.pos, 0xef4444);
  if (b.fx === "order") { flash(SPOT.mesa, 0x22c55e, true); coinShower(V(0, -14.9)); }
  if (b.fx === "vault") wheelSpin = 1.2;
  if (b.final) renderSummary(b.final);
  await sleep(dur);
}

// ------------------------------------------------------------------ linha do tempo
let current = null, events = [], idx = 0, paused = false, live = false, epoch = 0, lastActivity = performance.now();
async function runner() {
  for (;;) {
    const my = epoch;
    if (paused || idx >= events.length) { await sleep(200); continue; }
    const i = idx++;
    for (const b of beatsFor(events[i], i)) { if (my !== epoch) break; await perform(b, my); }
    lastActivity = performance.now();
  }
}
async function idleChatter() {   // entre ciclos, o escritório conversa
  for (let k = Math.floor(Math.random() * IDLE.length); ; k += 2) {
    await sleep(4000);
    if (paused || idx < events.length || performance.now() - lastActivity < 20000) continue;
    for (const [who, to, text] of [IDLE[k % IDLE.length], IDLE[(k + 1) % IDLE.length]]) {
      const a = cast[who], b = cast[to]; a.lookAt = b.worldHead(); b.lookAt = a.worldHead();
      a.say(esc(text), { ms: 3800, to: NAMES[to] }); await sleep(3200);
    }
    lastActivity = performance.now() - 5000;
  }
}
function reset() {
  epoch++; idx = 0; events = []; $("chat").innerHTML = ""; $("summary").innerHTML = "";
  everyone.forEach((p) => { p.hush(); p.lookAt = null; });
  Object.keys(working).forEach((k) => setWorking(k, false));
  const a = cast.astra; a.path = []; if (a.onArrive) { const r = a.onArrive; a.onArrive = null; r(); } a.sit(world.astraSeat, 0);
  Object.assign(state, { regime: "—", btc: null, equity: null, free: null, positions: [], candidates: [], passed: null, last: "…", tokens: null });
  renderBar();
}
function pushEvents(list) { for (let i = events.length; i < list.length; i++) events.push(list[i]); }
async function load(id) {
  const c = await (await fetch("/api/cycle/" + id)).json();
  reset(); current = c;
  const when = (c.started_at || "").replace("T", " ").slice(0, 16);
  $("meta").innerHTML = `<b>${esc(c.id.replace(/^(cycle|weekly)-/, ""))}</b> · ${esc(c.status)} · ${esc(when)} UTC` +
    (c.running ? ` · <span class="live-tag">rodando agora</span>` : "");
  pushEvents(c.events);
  if (!c.events.length && c.summary) renderSummary(c.summary);
}
async function refreshList(select) {
  const list = await (await fetch("/api/cycles")).json();
  const sel = $("cycles"), keep = sel.value;
  sel.innerHTML = list.map((c) => `<option value="${c.id}">${c.id.replace(/^(cycle|weekly)-/, "")} · ${c.status}</option>`).join("");
  sel.value = select || keep || (list[0] && list[0].id);
  return list;
}
async function livePoll() {
  if (!live) return;
  try {
    const list = await refreshList();
    const newest = list[0];
    if (newest && (!current || newest.id !== current.id)) { await refreshList(newest.id); await load(newest.id); }
    else if (current && (current.running || current.status === "?")) {
      const c = await (await fetch("/api/cycle/" + current.id)).json();
      current.running = c.running; current.status = c.status; pushEvents(c.events);
    }
  } catch (e) { console.warn(e); }
  setTimeout(livePoll, 2000);
}

// ------------------------------------------------------------------ controles
let follow = false;
$("cycles").onchange = (e) => { if (live) $("live").click(); load(e.target.value); };
$("play").onclick = () => { paused = !paused; $("play").textContent = paused ? "▶ continuar" : "⏸ pausar"; };
$("restart").onclick = () => current && load(current.id);
$("live").onclick = () => { live = !live; $("live").classList.toggle("on", live); if (live) livePoll(); };
$("follow").onclick = () => { follow = !follow; $("follow").classList.toggle("on", follow); };

// ------------------------------------------------------------------ loop
const clock = new THREE.Clock();
let lastScreens = -1, lastWall = -1, lastClock = -1, slowFor = 0, shadowsOn = true;
function frame() {
  const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime, sp = speed();
  everyone.forEach((p) => p.update(dt, t, sp));
  // luzes das estações
  const L = [[world.exchange.light, working.mesa, 18], [world.vault.lamp, working.guarda, 14], [world.archive.lamp, working.arquivista, 14],
    [world.luna.lamp, working.luna, 12], [world.sol.lamp, working.sol, 12]];
  for (const [l, on, max] of L) l.intensity += ((on ? max : 0) - l.intensity) * 0.08;
  if (wheelSpin > 0) { world.vault.wheel.rotation.z += dt * 5 * sp; wheelSpin -= dt * sp; }
  // telas (upload de textura é caro: taxas baixas bastam)
  if (t - lastScreens > 0.25) {
    lastScreens = t;
    world.luna.desk.screens.forEach((s) => drawScreen(s, t, working.luna));
    world.sol.desk.screens.forEach((s) => drawScreen(s, t, working.sol));
    world.astraDesk.screens.forEach((s) => drawScreen(s, t, cast.astra.state === "sit"));
    world.exchange.screens.forEach((s) => drawScreen(s, t, working.mesa));
    if (Math.floor(t) % 3 === 0) world.traders.forEach((d) => d.desk.screens.forEach((s) => drawScreen(s, t * 0.6, false)));
  }
  if (t - lastWall > 0.1) { lastWall = t; drawWall(Date.now()); drawTicker(Date.now()); }
  if (t - lastClock > 1) { lastClock = t; world.clock(Date.now()); }
  // efeitos
  for (let i = fx.length - 1; i >= 0; i--) {
    const f = fx[i]; f.t += dt * sp;
    f.l.intensity *= 0.94; const s = 1 + f.t * 7; f.ring.scale.set(s, s, s); f.ring.material.opacity = Math.max(0, 1 - f.t / 1.4);
    if (f.t > 1.4) { scene.remove(f.l, f.ring); fx.splice(i, 1); }
  }
  for (let i = coins.length - 1; i >= 0; i--) {
    const c = coins[i]; c.t += dt; c.v.y -= 9.8 * dt; c.m.position.addScaledVector(c.v, dt); c.m.rotation.x += dt * 9;
    if (c.m.position.y < 0.02) { c.m.position.y = 0.02; c.v.set(c.v.x * 0.5, Math.abs(c.v.y) * 0.3, c.v.z * 0.5); }
    if (c.t > 2.5) { scene.remove(c.m); coins.splice(i, 1); }
  }
  // câmera acompanhando a conversa
  if (follow && focus) {
    const [a, b] = focus, mid = a.worldHead(); if (b) mid.lerp(b.worldHead(), 0.5); mid.y = 1.2;
    controls.target.lerp(mid, 0.04);
  }
  controls.update();
  renderer.render(scene, camera);
  labels.render(scene, camera);
  // GPU fraca: se ficar abaixo de ~22 fps por 3 s, desliga sombras
  if (shadowsOn && dt > 0.045) { slowFor += dt; if (slowFor > 3) { shadowsOn = false; renderer.shadowMap.enabled = false; scene.traverse((o) => o.material && (o.material.needsUpdate = true)); } } else slowFor = 0;
}
function tick() { frame(); requestAnimationFrame(tick); }
addEventListener("resize", () => {
  fitView();
  renderer.setSize(innerWidth, innerHeight); labels.setSize(innerWidth, innerHeight);
});

(async () => {
  const meta = await (await fetch("/api/meta")).json();
  const role = (p, txt) => { const s = p.tagObj?.element.querySelector("small"); if (s) s.textContent = txt; };
  role(cast.astra, `operador · ${meta.operator || "?"}`); role(cast.luna, `gráficos · ${meta.charts || "?"}`); role(cast.sol, `advogado do diabo · ${meta.bear || "?"}`);
  const list = await refreshList();
  if (list.length) await load(list[0].id);
  if (list[0]?.status === "running") $("live").click();
  renderBar(); tick(); runner(); idleChatter();
})();
