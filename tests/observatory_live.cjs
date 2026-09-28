const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

// Exercise the actual polling code without WebGL or a running trading bot.
const source = readFileSync('observatory/js/main.js', 'utf8');
for (const name of ['main', 'world', 'story']) {
  const code = readFileSync(`observatory/js/${name}.js`, 'utf8');
  new Function(code.replace(/^import .*;\r?$/gm, '').replace(/^export /gm, ''));
}
const section = source.slice(source.indexOf('let liveSession ='), source.indexOf('// ------------------------------------------------------------------ controles'));
const elements = {};
let cycle;
let offline = false;
const messages = [];
const story = vm.createContext({});
vm.runInContext(readFileSync('observatory/js/story.js', 'utf8').replace(/^export /gm, ''), story);
const format = (event) => { story.event = event; return vm.runInContext('liveBeatFor(event)', story); };
const context = vm.createContext({
  live: true, current: null, events: [], idx: 0, paused: false, resenha: null, lastActivity: 0,
  performance: { now: () => 0 }, backToWork() { context.resenha = null; },
  state: {}, working: {}, STATION_OF: {}, cast: { astra: {}, mesa: {} },
  liveBeatFor: format, NAMES: {}, absorb() {},
  $: (id) => elements[id] ||= { classList: { toggle() {} } },
  setWorking() {}, renderBar() {}, habboSay() {}, clearBubbles() {},
  chat: (event) => messages.push(event.text),
  reset() {}, setTimeout() {}, clearTimeout() {}, console: { log: console.log, warn() {} },
  refreshList: async () => { if (offline) throw Error('offline'); return cycle ? [cycle] : []; },
  fetch: async () => ({ ok: true, json: async () => structuredClone(cycle) }),
});
vm.runInContext(section, context);
const poll = (baseline = false) => vm.runInContext(`livePoll(0, ${baseline})`, context);
(async () => {
  const charts = format({ kind: 'tool', phase: 'end', tool: 'read_charts', data: { pairs: [
    { symbol: 'SEI/USDT', trend_4h: 'alta', trend_1h: 'alta', support: 0.07875, resistance: 0.08658, pattern: 'rompimento' },
  ] } });
  assert.match(charts.text, /SEI: tendência de alta/);
  assert.match(charts.text, /0,07875/);
  assert.doesNotMatch(charts.text, /[{}]|trend_4h|undefined/);
  const journal = format({ kind: 'tool', phase: 'start', tool: 'write_journal', args: { kind: 'skip', symbol: 'QNT/USDT', thesis: 'Resistência próxima; não há espaço para o alvo.' } });
  assert.equal(journal.text, 'Decidi não entrar em QNT. Resistência próxima; não há espaço para o alvo.');
  assert.equal(format({ kind: 'tool', phase: 'end', tool: 'write_journal', data: { journal_id: 161 } }).text, 'Registrado no diário.');
  assert.equal(format({ kind: 'message', text: JSON.stringify({ summary: 'Ciclo concluído sem nova entrada.', actions: [] }) }).text, 'Ciclo concluído sem nova entrada.');
  assert.doesNotMatch(format({ kind: 'tool', phase: 'end', tool: 'unknown', data: { internal: 123 } }).text, /internal|[{}]/);
  assert.equal(format({ kind: 'error', text: JSON.stringify({ error: { message: 'Conexão perdida.' } }) }).text, 'Ocorreu um problema: Conexão perdida.');
  cycle = { id: 'old', running: false, status: 'ok', events: [{ kind: 'message', text: 'old message' }] };
  await poll(true);
  assert.equal(messages.length, 0, 'completed cycle must not replay on opening');
  assert.match(elements.meta.textContent, /Nenhum ciclo em execução/);
  assert.equal(vm.runInContext('liveReady', context), true);
  context.resenha = {};
  cycle = { id: 'new', running: true, status: 'running', events: [{ kind: 'message', text: 'new event' }] };
  await poll();
  assert.deepEqual(messages, ['new event']);
  assert.equal(context.resenha, null, 'new cycle ends the lounge animation');
  await poll();
  assert.equal(messages.length, 1, 'polls must not duplicate events');
  cycle.events.push({ kind: 'message', text: 'done' });
  cycle.running = false; cycle.status = 'ok';
  await poll();
  assert.deepEqual(messages, ['new event', 'done']);
  assert.match(elements.meta.textContent, /Nenhum ciclo em execução/);
  cycle = { id: 'running', running: true, status: 'running', events: [{ kind: 'message', text: 'before opening' }] };
  await poll(true);
  assert.equal(messages.length, 2, 'joining an active cycle skips earlier events');
  offline = true;
  await poll();
  assert.match(elements.meta.textContent, /estado atual desconhecido/);
  assert.equal(vm.runInContext('liveReady', context), false);
  vm.runInContext("liveReady = true; current = null; scheduleCycle = { ended_at: '2026-09-28T02:52:02Z' }", context);
  let board = vm.runInContext("nextCycleBoard(Date.parse('2026-09-28T03:00:02Z'))", context);
  assert.equal(board[0], '00:22 · Brasília');
  assert.equal(board[1], 'Faltam 22:00');
  board = vm.runInContext("nextCycleBoard(Date.parse('2026-09-28T04:00:00Z'))", context);
  assert.equal(board[1], 'Aguardando início');
  vm.runInContext('current = { running: true }', context);
  assert.equal(vm.runInContext('nextCycleBoard(Date.now())[0]', context), 'EM EXECUÇÃO');
  console.log('Observatory live polling checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
