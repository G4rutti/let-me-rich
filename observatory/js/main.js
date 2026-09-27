import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPixelatedPass } from "three/addons/postprocessing/RenderPixelatedPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { buildWorld } from "./world.js";
import { Person } from "./people.js";
import { beatsFor, IDLE, STATION_OF } from "./story.js";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const speed = () => Number($("speed").value);
const SIDE = () => (innerWidth > 860 ? 380 : 0);   // largura ocupada pelo painel da conversa

// ------------------------------------------------------------------ render: isométrico 2:1 + pixel art com contorno
const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });
renderer.setPixelRatio(1); renderer.setSize(innerWidth, innerHeight);
$("scene").appendChild(renderer.domElement);
const labels = new CSS2DRenderer(); labels.setSize(innerWidth, innerHeight); $("labels").appendChild(labels.domElement);

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -300, 500);
const VIEW = 10.5;                                  // meia altura visível, em metros (zoom 1)
function fitView() {
  const P = SIDE(), fullW = innerWidth + P, a = fullW / innerHeight;
  Object.assign(camera, { left: -VIEW * a, right: VIEW * a, top: VIEW, bottom: -VIEW });
  if (P) camera.setViewOffset(fullW, innerHeight, P, 0, innerWidth, innerHeight); else camera.clearViewOffset();
  camera.updateProjectionMatrix();
}
const TARGET = new THREE.Vector3(0.5, 0.8, -6);
const ISO = new THREE.Vector3(Math.SQRT1_2 * Math.cos(Math.PI / 6), Math.sin(Math.PI / 6), Math.SQRT1_2 * Math.cos(Math.PI / 6));   // azimute 45°, 30° de altura = 2:1
camera.position.copy(TARGET).addScaledVector(ISO, 80);
fitView();
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(TARGET);
Object.assign(controls, { enableRotate: false, screenSpacePanning: true, minZoom: 0.5, maxZoom: 3, enableDamping: true });
controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN };

const composer = new EffectComposer(renderer);
let pixel = 2;
const pixelPass = new RenderPixelatedPass(pixel, scene, camera, { normalEdgeStrength: 0.35, depthEdgeStrength: 0.7 });
composer.addPass(pixelPass); composer.addPass(new OutputPass());

const world = buildWorld(scene);

// ------------------------------------------------------------------ elenco
const cast = {
  astra: new Person(scene, { name: "Astra", role: "operador", color: "#e0a800", suit: 0x1c2a4a, tie: 0xf2c14e, skin: 0xf0c08f, hair: 0x5a3418, hairStyle: "side" }),
  luna: new Person(scene, { name: "Luna", role: "gráficos", color: "#8b5cf6", suit: 0x6d4bc4, noTie: true, tie: 0xd9ccff, skin: 0xf6d2b0, hair: 0x1a1a1a, hairStyle: "bob", glasses: true }),
  sol: new Person(scene, { name: "Sol", role: "advogado do diabo", color: "#f26b38", suit: 0xe0562a, tie: 0x2a2a2a, skin: 0xb07650, hair: 0x151515, hairStyle: "curly" }),
  mesa: new Person(scene, { name: "Mesa", role: "exchange · código", color: "#1f9bd1", suit: 0x1f7fb3, tie: 0xffffff, skin: 0xd09a6a, hair: 0x2a1a10, hairStyle: "short" }),
  guarda: new Person(scene, { name: "Guarda", role: "risk manager · código", color: "#475569", suit: 0x2b2f36, tie: 0xd8323c, skin: 0x8d5a3b, hair: 0x111111, hairStyle: "bald", glasses: true }),
  arquivista: new Person(scene, { name: "Arquivista", role: "diário · código", color: "#b7791f", suit: 0x3fa34d, noTie: true, tie: 0xf2c14e, skin: 0xf3cfa6, hair: 0xb8b8b8, hairStyle: "bun", glasses: true }),
};
const NAMES = { astra: "Astra", luna: "Luna", sol: "Sol", mesa: "Mesa", guarda: "Guarda", arquivista: "Arquivista", todos: "todos" };
const V = (x, z) => new THREE.Vector3(x, 0, z);
cast.astra.sit(world.astraSeat, 0);
cast.luna.sit(world.luna.seat, world.luna.faceAngle);
cast.sol.sit(world.sol.seat, world.sol.faceAngle);
cast.mesa.place(V(0, -15.9), 0);
cast.guarda.place(V(-13.2, -14.9), Math.atan2(13.2, 9.9));
cast.arquivista.place(V(13, -15.6), 0);
const extras = world.traders.map((t, i) => {
  const looks = [[0xd8323c, 0xf0c08f, "short", 0x3b2618], [0x2f6fb3, 0xd09a6a, "long", 0x6b3a1e], [0xf2c14e, 0xf6d2b0, "curly", 0x1a1a1a], [0x3fa34d, 0x8d5a3b, "bun", 0x111111]][i];
  const p = new Person(scene, { suit: looks[0], tie: 0xffffff, skin: looks[1], hair: looks[3], hairStyle: looks[2], noTie: i % 2 === 1 });
  p.sit(t.seat, Math.PI); p.typing = true; return p;
});
const everyone = [...Object.values(cast), ...extras];

// materiais → toon (sombreamento em degraus, cor chapada)
const grad = new THREE.DataTexture(new Uint8Array([110, 185, 255]), 3, 1, THREE.RedFormat);
grad.minFilter = grad.magFilter = THREE.NearestFilter; grad.needsUpdate = true;
const toonCache = new Map();
const toon = (m) => {
  if (!(m.isMeshStandardMaterial || m.isMeshLambertMaterial || m.isMeshPhysicalMaterial)) return m;
  if (!toonCache.has(m)) toonCache.set(m, new THREE.MeshToonMaterial({ color: m.color, map: m.map, gradientMap: grad,
    transparent: m.transparent, opacity: m.opacity, side: m.side, depthWrite: m.depthWrite, emissive: m.emissive, emissiveIntensity: m.emissiveIntensity }));
  return toonCache.get(m);
};
scene.traverse((o) => { if (o.isMesh) o.material = Array.isArray(o.material) ? o.material.map(toon) : toon(o.material); });

// onde o operador para para falar com cada um
const SPOT = { mesa: V(0, -13.6), guarda: V(-11.5, -12.8), arquivista: V(13, -12.9), luna: V(-10.9, -3), sol: V(10.9, -3) };
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

// ------------------------------------------------------------------ chat estilo Habbo: nasce na altura de quem fala e sobe
const flying = [];
function habboSay(p, text, { kind = "", to = "" } = {}) {
  const el = document.createElement("div");
  el.className = `hb ${kind}`;
  el.innerHTML = `<i style="background:${p.o.color}">${esc(p.o.name[0])}</i><b>${esc(p.o.name)}</b>` +
    (to ? `<em>→ ${esc(to)}</em>` : "") + `<span>${kind === "think" ? "💭 " : ""}${esc(text).replace(/\n/g, "<br>")}</span>`;
  $("bubbles").appendChild(el);
  const v = p.worldHead().project(camera);
  const x = (v.x * 0.5 + 0.5) * innerWidth, w = el.offsetWidth;
  el.style.left = Math.max(10, Math.min(innerWidth - SIDE() - w - 24, x - w / 2)) + "px";
  flying.push({ el, h: el.offsetHeight });
  // o mais novo fica na linha de base; cada um acima encosta no de baixo pela própria altura
  let y = Math.round(innerHeight * 0.36);
  for (let i = flying.length - 1; i >= 0; i--) {
    const b = flying[i]; if (i < flying.length - 1) y -= b.h + 5;
    b.y = y; b.el.style.top = y + "px"; if (y < 64) b.el.classList.add("gone");
  }
  while (flying.length && flying[0].y < -160) flying.shift().el.remove();
}
function clearBubbles() { flying.splice(0).forEach((b) => b.el.remove()); }

// ------------------------------------------------------------------ estado do pregão (telão, letreiro, barra)
const state = { regime: "—", btc: null, equity: null, free: null, positions: [], candidates: [], passed: null, last: "aguardando o próximo ciclo…", tokens: null };
function absorb(tool, d) {
  if (!d) return;
  if (tool === "get_regime") { state.regime = d.regime; state.btc = d.btc_price; }
  if (tool === "get_portfolio" || (tool === "sync_positions" && d.portfolio)) {
    const p = tool === "get_portfolio" ? d : d.portfolio; state.equity = p.equity_usd; state.free = p.free_usdt; state.positions = p.positions || [];
  }
  if (tool === "scan_market") { state.candidates = d.candidates || []; state.passed = d.passed_filters; }
  renderBar();
}
function renderBar() {
  $("s-regime").textContent = state.regime; $("s-regime").dataset.v = state.regime;
  $("s-equity").textContent = state.equity != null ? "US$ " + state.equity.toFixed(2) : "—";
  $("s-pos").textContent = state.positions.map((p) => `${p.symbol.replace("/USDT", "")} ${p.r_now ?? "?"}R`).join(" · ") || "nenhuma";
  $("s-tokens").textContent = state.tokens ? `${Math.round(state.tokens.input_tokens / 1000)}k` : "—";
}
const chartSeed = Array.from({ length: 120 }, (_, i) => Math.sin(i * 0.21) * 12 + Math.sin(i * 0.05) * 30 + i * 0.4);
function drawWall(now) {   // desenha em coordenadas 2048×704 e escala para o canvas (menor = mais "pixel")
  const { g, c, t } = world.exchange.wall, W = 2048, H = 704;
  g.setTransform(c.width / W, 0, 0, c.height / H, 0, 0);
  g.fillStyle = "#0b1a2e"; g.fillRect(0, 0, W, H);
  g.fillStyle = "#e8eef8"; g.font = "bold 58px monospace"; g.fillText("PREGÃO · SPOT USDT", 56, 92);
  g.fillStyle = "#7f93b0"; g.font = "40px monospace"; g.fillText(new Date(now).toLocaleTimeString("pt-BR"), W - 260, 90);
  const rc = state.regime === "BULL" ? "#22c55e" : state.regime === "BEAR" ? "#ef4444" : "#eab308";
  g.fillStyle = rc; g.fillRect(56, 128, 340, 72);
  g.fillStyle = "#06101c"; g.font = "bold 44px monospace"; g.fillText(`REGIME ${state.regime}`, 76, 178);
  g.fillStyle = "#e8eef8"; g.font = "bold 46px monospace";
  g.fillText(`BANCA ${state.equity != null ? "$" + state.equity.toFixed(2) : "—"}`, 440, 178);
  g.fillText(`BTC ${state.btc ? "$" + Math.round(state.btc).toLocaleString("pt-BR") : "—"}`, 1000, 178);
  g.save(); g.translate(56, 250); const cw = 900, ch = 300;
  const pts = chartSeed.map((v, i) => [i * (cw / 119), ch * 0.55 - v * 2.2 - Math.sin(now / 900 + i * 0.3) * 6]);
  g.fillStyle = "rgba(34,197,94,.25)"; g.beginPath(); g.moveTo(0, ch); pts.forEach(([x, y]) => g.lineTo(x, y)); g.lineTo(cw, ch); g.fill();
  g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.strokeStyle = "#22c55e"; g.lineWidth = 6; g.stroke();
  g.restore();
  g.fillStyle = "#7f93b0"; g.font = "bold 34px monospace"; g.fillText("POSIÇÕES", 1010, 280);
  g.font = "40px monospace";
  if (!state.positions.length) { g.fillStyle = "#56657d"; g.fillText("nenhuma", 1010, 334); }
  state.positions.slice(0, 3).forEach((p, i) => {
    g.fillStyle = (p.r_now ?? 0) >= 0 ? "#22c55e" : "#ef4444";
    g.fillText(`${p.symbol.replace("/USDT", "").padEnd(5)} ${String(p.r_now ?? "?").padStart(6)}R`, 1010, 334 + i * 56);
  });
  g.fillStyle = "#7f93b0"; g.font = "bold 34px monospace"; g.fillText(`SCAN${state.passed != null ? ` · ${state.passed}` : ""}`, 1510, 280);
  g.font = "38px monospace";
  state.candidates.slice(0, 6).forEach((cd, i) => {
    const y = 334 + i * 52; g.fillStyle = "#e8eef8"; g.fillText(cd.symbol.replace("/USDT", "").padEnd(6), 1510, y);
    g.fillStyle = "#1f9bd1"; g.fillRect(1680, y - 28, (cd.score || 0) * 300, 28);
  });
  g.fillStyle = "#1c2a1a"; g.fillRect(0, H - 100, W, 100);
  g.fillStyle = "#f2c14e"; g.font = "bold 44px monospace"; g.fillText("> " + state.last, 56, H - 34);
  t.needsUpdate = true;
}
function drawTicker(now) {
  const { g, c, t } = world.exchange.tick, W = 2048;
  g.setTransform(c.width / W, 0, 0, c.height / 64, 0, 0);
  g.fillStyle = "#050a12"; g.fillRect(0, 0, W, 64);
  const items = state.candidates.length ? state.candidates.slice(0, 12).map((x) => [x.symbol.replace("/USDT", ""), x.price, x.ret_1h])
    : [["BTC", state.btc, 0], ["LET", null, 0], ["ME", null, 0], ["RICH", null, 0]];
  g.font = "bold 40px monospace";
  const parts = items.map(([s, p, r]) => ({ s: `${s} ${p != null ? Number(p).toLocaleString("pt-BR", { maximumSignificantDigits: 6 }) : ""} ${r ? (r > 0 ? "▲" : "▼") + Math.abs(r).toFixed(2) + "%" : ""}   `, r }));
  const total = parts.reduce((a, p) => a + g.measureText(p.s).width, 0) || 1;
  let x = -((now / 12) % total);
  while (x < W) for (const p of parts) { g.fillStyle = p.r > 0 ? "#22c55e" : p.r < 0 ? "#ef4444" : "#f2c14e"; g.fillText(p.s, x, 48); x += g.measureText(p.s).width; }
  t.needsUpdate = true;
}
function drawScreen(s, t, hot) {   // coordenadas lógicas 320 de largura
  const { g, c } = s, k = c.width / 320, H = c.height / k;
  g.setTransform(k, 0, 0, k, 0, 0);
  g.fillStyle = "#0b1a2e"; g.fillRect(0, 0, 320, H);
  let p = H * 0.55;
  for (let i = 0; i < 26; i++) {
    const nz = Math.sin(i * 0.7 + t * (hot ? 2 : 0.5) + s.seed) * 10 + Math.sin(i * 2.3 + s.seed * 3) * 6;
    const o = p, cl = H * 0.55 + nz - i * 0.6 * s.trend; p = cl;
    g.fillStyle = cl < o ? "#22c55e" : "#ef4444";
    g.fillRect(8 + i * 12, Math.min(o, cl), 8, Math.max(4, Math.abs(cl - o)));
  }
  g.fillStyle = hot ? "#f2c14e" : "#c9d4e4"; g.font = "bold 22px monospace"; g.fillText(s.title || "", 8, 24);
  s.t.needsUpdate = true;
}

// ------------------------------------------------------------------ efeitos
const fx = [];
function flash(pos, color, big = false) {
  const l = new THREE.PointLight(color, big ? 40 : 25, 9, 1.6); l.position.copy(pos).setY(2.4); scene.add(l);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.3, 0.5, 24), new THREE.MeshBasicMaterial({ color, transparent: true, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.copy(pos).setY(0.04); scene.add(ring);
  fx.push({ l, ring, t: 0 });
}
const coins = [], coinM = new THREE.MeshToonMaterial({ color: 0xf2c14e, gradientMap: grad });
function coinShower(pos) {
  for (let i = 0; i < 14; i++) {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.03, 10), coinM);
    m.position.copy(pos).setY(1.3); scene.add(m);
    coins.push({ m, v: new THREE.Vector3((Math.random() - 0.5) * 3, 3 + Math.random() * 2, (Math.random() - 0.3) * 3), t: 0 });
  }
}
let wheelSpin = 0;
const working = { mesa: 0, guarda: 0, arquivista: 0, luna: 0, sol: 0 };
function setWorking(k, on) { if (k in working) working[k] = on ? 1 : 0; if (k === "luna" || k === "sol") cast[k].typing = !!on; }

// ------------------------------------------------------------------ histórico (painel)
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
let focus = null;
async function perform(b, my) {
  if (b.system) { chat(b); if (b.usage) { state.tokens = b.usage; renderBar(); } return; }
  const sp = cast[b.who];
  if (b.walk && b.who === "astra") { await astraGo(b.walk); if (my !== epoch) return; }
  if (b.working) setWorking(b.working, true);
  if (b.tool && b.data !== undefined) absorb(b.tool, b.data);
  if (b.tool && !b.working && STATION_OF[b.tool]) setWorking(STATION_OF[b.tool], false);
  const to = b.to && cast[b.to];
  everyone.forEach((p) => (p.lookAt = null));
  if (to) { sp.lookAt = to.worldHead(); to.lookAt = sp.worldHead(); if (sp.state === "stand") sp.faceTo(to.pos); }
  if (b.to === "todos") Object.values(cast).forEach((p) => p !== sp && (p.lookAt = sp.worldHead()));
  const dur = Math.min(9000, Math.max(2300, 1500 + b.text.length * 42)) / speed();
  if (b.kind !== "think") sp.talk(dur);
  habboSay(sp, b.text, { kind: b.kind === "think" ? "think" : b.mood || "", to: to ? NAMES[b.to] : b.to === "todos" ? "todos" : "" });
  chat(b); focus = [sp, to];
  state.last = `${sp.o.name}: ${b.text.split("\n")[0].slice(0, 80)}`;
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
async function idleChatter() {   // entre ciclos, o escritório conversa (não vai pro histórico)
  for (let k = Math.floor(Math.random() * IDLE.length); ; k += 2) {
    await sleep(4000);
    if (paused || idx < events.length || performance.now() - lastActivity < 20000) continue;
    for (const [who, to, text] of [IDLE[k % IDLE.length], IDLE[(k + 1) % IDLE.length]]) {
      const a = cast[who], b = cast[to]; a.lookAt = b.worldHead(); b.lookAt = a.worldHead();
      a.talk(3000); habboSay(a, text, { to: NAMES[to] }); await sleep(3200);
    }
    lastActivity = performance.now() - 5000;
  }
}
function reset() {
  epoch++; idx = 0; events = []; $("chat").innerHTML = ""; $("summary").innerHTML = ""; clearBubbles();
  everyone.forEach((p) => (p.lookAt = null));
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
  $("room-sub").textContent = c.running ? "ciclo rodando agora" : `ciclo ${c.id.replace(/^(cycle|weekly)-/, "")}`;
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
$("pixel").onclick = () => { pixel = { 2: 3, 3: 1, 1: 2 }[pixel]; pixelPass.setPixelSize(pixel); $("pixel").textContent = `▦ pixel ${pixel}×`; };
$("center").onclick = () => { const d = TARGET.clone().sub(controls.target); controls.target.add(d); camera.position.add(d); camera.zoom = 1; camera.updateProjectionMatrix(); };

// ------------------------------------------------------------------ loop
const clock = new THREE.Clock();
let lastScreens = -1, lastWall = -1, lastClock = -1;
function frame() {
  const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime, sp = speed();
  everyone.forEach((p) => p.update(dt, t, sp));
  const L = [[world.exchange.light, working.mesa, 18], [world.vault.lamp, working.guarda, 14], [world.archive.lamp, working.arquivista, 14],
    [world.luna.lamp, working.luna, 12], [world.sol.lamp, working.sol, 12]];
  for (const [l, on, max] of L) l.intensity += ((on ? max : 0) - l.intensity) * 0.08;
  if (wheelSpin > 0) { world.vault.wheel.rotation.z += dt * 5 * sp; wheelSpin -= dt * sp; }
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
  for (let i = fx.length - 1; i >= 0; i--) {
    const f = fx[i]; f.t += dt * sp;
    f.l.intensity *= 0.94; const s = 1 + f.t * 7; f.ring.scale.set(s, s, s); f.ring.material.opacity = Math.max(0, 1 - f.t / 1.4);
    if (f.t > 1.4) { scene.remove(f.l, f.ring); fx.splice(i, 1); }
  }
  for (let i = coins.length - 1; i >= 0; i--) {
    const c = coins[i]; c.t += dt; c.v.y -= 9.8 * dt; c.m.position.addScaledVector(c.v, dt); c.m.rotation.x += dt * 9;
    if (c.m.position.y < 0.03) { c.m.position.y = 0.03; c.v.set(c.v.x * 0.5, Math.abs(c.v.y) * 0.3, c.v.z * 0.5); }
    if (c.t > 2.5) { scene.remove(c.m); coins.splice(i, 1); }
  }
  if (follow && focus) {   // câmera isométrica: move alvo e câmera juntos (o ângulo nunca muda)
    const [a, b] = focus, mid = a.worldHead(); if (b) mid.lerp(b.worldHead(), 0.5); mid.y = 0.8;
    const d = mid.sub(controls.target).multiplyScalar(0.05); controls.target.add(d); camera.position.add(d);
  }
  controls.update();
  composer.render();
  labels.render(scene, camera);
}
function tick() { frame(); requestAnimationFrame(tick); }
addEventListener("resize", () => {
  fitView(); renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight); labels.setSize(innerWidth, innerHeight);
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
