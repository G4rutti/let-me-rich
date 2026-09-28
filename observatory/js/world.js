// Cenário estilo Habbo: sala flutuando, duas paredes (fundo e esquerda), piso de ladrilhos, móveis coloridos.
// O visual "pixel + contorno" vem do RenderPixelatedPass e dos materiais toon aplicados no main.js.
import * as THREE from "three";

const W = 36, D = 26, H = 5.4;            // sala: x ∈ [-18, 18], z ∈ [-18, 8]
const BACK = -18, FRONT = 8, LEFT = -W / 2;

// ------------------------------------------------------------------ helpers
const M = {};
function mats() {
  const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, ...o });
  Object.assign(M, {
    white: std(0xf7f4ee), wall: std(0xf2b63d), wallTop: std(0xc98320), base: std(0x9a5d18),
    steel: std(0xb7c0cc), darkSteel: std(0x3a414c), black: std(0x1c1f25),
    walnut: std(0x8a5a2e), oakTop: std(0xd9a860), leather: std(0x3b3f8f), fabric: std(0x2f6fb3),
    brass: std(0xf2c14e), bronze: std(0xa8662f), plant: std(0x4caf50), plantDark: std(0x2e8b3a),
    pot: std(0xe86a4a), marble: std(0xf4f1ea), slab: std(0xa89170),
    glass: std(0xbfe6ff, { transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide }),
    red: std(0xd8323c), gold: std(0xf2c14e),
  });
}
function box(w, h, d, m, x, y, z, parent) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); b.position.set(x, y, z); parent.add(b); return b;
}
function cyl(rt, rb, h, m, x, y, z, parent, seg = 16) {
  const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m); c.position.set(x, y, z); parent.add(c); return c;
}
function pixelTex(w, h, draw, repeat) {   // texturas pequenas com filtro "nearest": pixels grandes, jeito Habbo
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.NearestFilter; t.minFilter = THREE.NearestFilter;
  t.generateMipmaps = false;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
export function screenCanvas(w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return { c, g: c.getContext("2d"), t };
}

// ------------------------------------------------------------------ fundo, luz
function backdrop(scene) {
  scene.background = pixelTex(160, 90, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#5fb6e8"); gr.addColorStop(1, "#bfe7fb");
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    g.fillStyle = "#ffffff";
    for (const [x, y, s] of [[14, 12, 1], [58, 8, 1.3], [110, 16, 1], [132, 40, 0.8], [30, 52, 0.9], [88, 62, 1.1]]) {
      g.fillRect(x, y, 16 * s, 4 * s); g.fillRect(x + 4 * s, y - 3 * s, 8 * s, 3 * s); g.fillRect(x - 3 * s, y + 2 * s, 22 * s, 3 * s);
    }
  });
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8c7a8, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.9); sun.position.set(-8, 20, 14); sun.target.position.set(0, 0, -5);
  scene.add(sun, sun.target);
}

// ------------------------------------------------------------------ sala
function room(scene) {
  const tiles = pixelTex(16, 16, (g) => {       // um ladrilho: 16×16 px com rejunte
    g.fillStyle = "#efe6d2"; g.fillRect(0, 0, 16, 16);
    g.fillStyle = "#f7f0e2"; g.fillRect(1, 1, 14, 2);
    g.fillStyle = "#d9cbb0"; g.fillRect(0, 15, 16, 1); g.fillRect(15, 0, 1, 16);
  }, [W / 1.5, D / 1.5]);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ map: tiles }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(0, 0, (BACK + FRONT) / 2); scene.add(floor);
  box(W, 0.7, D, M.slab, 0, -0.37, (BACK + FRONT) / 2, scene);   // espessura do piso (topo abaixo do piso: sem z-fighting)
  // tapete vermelho de "VIP" sob a mesa do operador
  const rug = pixelTex(48, 30, (g, w, h) => {
    g.fillStyle = "#c81e3a"; g.fillRect(0, 0, w, h); g.fillStyle = "#f2c14e"; g.fillRect(2, 2, w - 4, 1); g.fillRect(2, h - 3, w - 4, 1);
    g.fillRect(2, 2, 1, h - 4); g.fillRect(w - 3, 2, 1, h - 4); g.fillStyle = "#a3152d";
    for (let i = 6; i < w - 6; i += 6) g.fillRect(i, 6, 3, h - 12);
  });
  const r = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.6), new THREE.MeshStandardMaterial({ map: rug }));
  r.rotation.x = -Math.PI / 2; r.position.set(0, 0.015, -1.6); scene.add(r);

  // paredes: fundo e esquerda (as da frente não existem, como no Habbo)
  const T = 0.35;
  box(W + T, H, T, M.wall, T / 2 * -1 + 0, H / 2, BACK - T / 2, scene);
  box(T, H, D, M.wall, LEFT - T / 2, H / 2, (BACK + FRONT) / 2, scene);
  box(W + T, 0.18, T + 0.08, M.wallTop, 0, H + 0.09, BACK - T / 2, scene);             // borda de cima
  box(T + 0.08, 0.18, D + T, M.wallTop, LEFT - T / 2, H + 0.09, (BACK + FRONT) / 2 - T / 2, scene);
  box(W, 0.22, 0.06, M.base, 0, 0.11, BACK + 0.03, scene);                              // rodapé
  box(0.06, 0.22, D, M.base, LEFT + 0.03, 0.11, (BACK + FRONT) / 2, scene);

  // janelas com vista da cidade (pixel art)
  const view = pixelTex(40, 30, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#6cc3f0"); gr.addColorStop(1, "#c9ecfb");
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
    g.fillStyle = "#fff"; g.fillRect(4, 5, 8, 2); g.fillRect(6, 4, 4, 1); g.fillRect(25, 8, 9, 2);
    const bs = [[0, 14, 6, "#3d6f9c"], [6, 10, 5, "#5a86b0"], [11, 17, 7, "#2f5a80"], [18, 7, 5, "#4b7aa6"], [23, 13, 6, "#36668f"], [29, 9, 5, "#5c8bb5"], [34, 15, 6, "#2f5a80"]];
    for (const [x, top, bw, c] of bs) {
      g.fillStyle = c; g.fillRect(x, top, bw, h - top);
      g.fillStyle = "#ffe08a"; for (let y = top + 2; y < h - 1; y += 3) for (let xx = x + 1; xx < x + bw - 1; xx += 2) if ((xx * 7 + y * 3) % 5) g.fillRect(xx, y, 1, 1);
    }
  });
  const windowAt = (x, z, ry) => {
    const g = new THREE.Group(); g.position.set(x, 2.8, z); g.rotation.y = ry; scene.add(g);
    box(3.0, 2.4, 0.08, M.white, 0, 0, 0, g);
    const v = new THREE.Mesh(new THREE.PlaneGeometry(2.7, 2.1), new THREE.MeshBasicMaterial({ map: view })); v.position.z = 0.05; g.add(v);
    box(0.08, 2.1, 0.1, M.white, 0, 0, 0.06, g); box(2.7, 0.08, 0.1, M.white, 0, 0, 0.06, g);
    box(3.2, 0.12, 0.3, M.white, 0, -1.25, 0.12, g);                                    // peitoril
  };
  windowAt(LEFT + 0.03, -3, Math.PI / 2); windowAt(LEFT + 0.03, 3.5, Math.PI / 2);
  windowAt(-10.5, BACK + 0.03, 0);

  // placa da empresa na parede esquerda
  const brand = pixelTex(96, 28, (g, w, h) => {
    g.fillStyle = "#1f3552"; g.fillRect(0, 0, w, h); g.fillStyle = "#f2c14e"; g.fillRect(1, 1, w - 2, 1); g.fillRect(1, h - 2, w - 2, 1);
    g.font = "bold 12px monospace"; g.textAlign = "center"; g.fillText("LET ME RICH", w / 2, 15); g.font = "8px monospace"; g.fillStyle = "#fff"; g.fillText("CAPITAL", w / 2, 24);
  });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 1.2), new THREE.MeshBasicMaterial({ map: brand }));
  sign.rotation.y = Math.PI / 2; sign.position.set(LEFT + 0.03, 4.4, -9.5); scene.add(sign);
  for (const [x, z] of [[-7.8, -17.4], [7.8, -17.4]]) box(0.8, H, 0.8, M.white, x, H / 2, z, scene);   // pilares
}

// ------------------------------------------------------------------ mobília
function plant(scene, x, z, s = 1) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s); scene.add(g);
  cyl(0.32, 0.26, 0.6, M.pot, 0, 0.3, 0, g, 12);
  for (let i = 0; i < 6; i++) {
    const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.3 + (i % 3) * 0.06, 0), i % 2 ? M.plant : M.plantDark);
    leaf.position.set(Math.sin(i * 1.7) * 0.22, 0.85 + i * 0.13, Math.cos(i * 1.7) * 0.22); g.add(leaf);
  }
}
function chair(scene, x, z, ry) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry; scene.add(g);
  cyl(0.05, 0.05, 0.4, M.darkSteel, 0, 0.22, 0, g, 8);
  cyl(0.3, 0.3, 0.05, M.darkSteel, 0, 0.03, 0, g, 10);
  box(0.54, 0.1, 0.52, M.leather, 0, 0.47, 0, g);
  box(0.52, 0.62, 0.1, M.leather, 0, 0.84, -0.25, g);
  return g;
}
function monitor(parent, x, y, z, ry, w, h) {
  const s = screenCanvas(96, Math.round((96 * h) / w));
  s.t.magFilter = THREE.NearestFilter;
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = ry; parent.add(g);
  box(w + 0.06, h + 0.06, 0.05, M.black, 0, 0, 0, g);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: s.t }));
  scr.position.z = 0.03; g.add(scr);
  box(0.06, 0.28, 0.06, M.darkSteel, 0, -h / 2 - 0.12, -0.03, g);
  box(0.26, 0.03, 0.18, M.darkSteel, 0, -h / 2 - 0.26, -0.03, g);
  return s;
}
// mesa: quem senta fica no +z local, olhando para -z; telas viradas para +z
function desk(scene, x, z, ry, { w = 2.4, mons = 2, title = [] } = {}) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry; scene.add(g);
  box(w, 0.1, 1.0, M.oakTop, 0, 0.76, 0, g);
  box(0.1, 0.72, 0.9, M.walnut, -w / 2 + 0.08, 0.36, 0, g); box(0.1, 0.72, 0.9, M.walnut, w / 2 - 0.08, 0.36, 0, g);
  box(w - 0.2, 0.42, 0.05, M.walnut, 0, 0.52, -0.42, g);
  const screens = [];
  for (let i = 0; i < mons; i++) {
    const off = (i - (mons - 1) / 2) * 0.8;
    const s = monitor(g, off, 1.24, -0.28, -off * 0.3, 0.74, 0.45); s.title = title[i] || ""; s.seed = Math.random() * 9; s.trend = Math.random() - 0.3;
    screens.push(s);
  }
  box(0.55, 0.03, 0.18, M.black, 0, 0.82, 0.12, g);
  cyl(0.05, 0.045, 0.12, M.red, w / 2 - 0.35, 0.87, 0.15, g, 10);                        // caneca
  return { g, screens };
}

// ------------------------------------------------------------------ estações
function exchangeZone(scene) {
  const g = new THREE.Group(); g.position.set(0, 0, -17.2); scene.add(g);
  box(15, 5.2, 0.4, M.darkSteel, 0, 2.6, 0, g);
  const wall = screenCanvas(1024, 352);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(14.2, 4.4), new THREE.MeshBasicMaterial({ map: wall.t }));
  scr.position.set(0, 2.75, 0.21); g.add(scr);
  const tick = screenCanvas(1024, 32);
  const tk = new THREE.Mesh(new THREE.PlaneGeometry(15, 0.47), new THREE.MeshBasicMaterial({ map: tick.t }));
  tk.position.set(0, 5.05, 0.22); g.add(tk);
  const c = new THREE.Group(); c.position.set(0, 0, 2.3); g.add(c);
  box(5.4, 1.05, 0.8, M.marble, 0, 0.52, 0, c);
  box(5.6, 0.1, 0.95, M.gold, 0, 1.08, 0, c);
  const s1 = monitor(c, -1.4, 1.35, -0.15, Math.PI, 0.6, 0.36), s2 = monitor(c, 1.4, 1.35, -0.15, Math.PI, 0.6, 0.36);
  s1.title = "ORDENS"; s2.title = "BOOK"; s1.seed = 2; s2.seed = 5; s1.trend = 0.3; s2.trend = -0.2;
  const light = new THREE.PointLight(0x7fd3ff, 0, 12, 1.6); light.position.set(0, 3, -14.5); scene.add(light);
  return { wall, tick, screens: [s1, s2], light };
}
function vaultZone(scene) {
  const g = new THREE.Group(); g.position.set(-15.6, 0, -15.6); g.rotation.y = Math.PI / 4; scene.add(g);
  box(5, H, 1.2, M.steel, 0, H / 2, -0.2, g);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.16, 10, 32), M.darkSteel); ring.position.set(0, 1.8, 0.45); g.add(ring);
  const door = new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.25, 0.35, 32), M.steel);
  door.rotation.x = Math.PI / 2; door.position.set(0, 1.8, 0.55); g.add(door);
  const wheel = new THREE.Group(); wheel.position.set(0, 1.8, 0.78); g.add(wheel);
  wheel.add(new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.06, 8, 24), M.gold));
  for (let i = 0; i < 3; i++) { const sp = box(0.06, 0.95, 0.06, M.gold, 0, 0, 0, wheel); sp.rotation.z = (i * Math.PI) / 3; }
  box(0.25, 2.2, 0.5, M.darkSteel, -1.9, 1.1, 1.4, g); box(0.25, 2.2, 0.5, M.darkSteel, 1.9, 1.1, 1.4, g);
  const lamp = new THREE.PointLight(0xffe0a0, 0, 8, 1.6); lamp.position.set(-13, 3.2, -13); scene.add(lamp);
  return { wheel, lamp };
}
function archiveZone(scene) {   // estantes encostadas na parede do fundo, à direita do telão
  const g = new THREE.Group(); scene.add(g);
  const bookM = [0xd8323c, 0x2f6fb3, 0xf2c14e, 0x3fa34d, 0x8e44ad, 0xe67e22, 0x1f3552].map((c) => new THREE.MeshStandardMaterial({ color: c }));
  for (const xc of [11.2, 14.6]) {
    const s = new THREE.Group(); s.position.set(xc, 0, -17.5); g.add(s);
    box(3.3, 3.6, 0.55, M.walnut, 0, 1.8, 0, s);
    for (let r = 0; r < 5; r++) {
      box(3.1, 0.05, 0.5, M.oakTop, 0, 0.3 + r * 0.7, 0.05, s);
      let x = -1.45, k = r;
      while (x < 1.35) { const w = 0.1 + ((k * 37) % 5) * 0.02, h = 0.42 + ((k * 13) % 4) * 0.05;
        box(w, h, 0.36, bookM[k % bookM.length], x + w / 2, 0.33 + r * 0.7 + h / 2, 0.08, s); x += w + 0.015; k++; }
    }
  }
  const d = new THREE.Group(); d.position.set(13, 0, -14.6); d.rotation.y = Math.PI; g.add(d);
  box(2.2, 0.1, 0.9, M.walnut, 0, 0.78, 0, d); box(2.1, 0.74, 0.08, M.walnut, 0, 0.38, -0.4, d);
  box(0.1, 0.74, 0.85, M.walnut, -1.05, 0.38, 0, d); box(0.1, 0.74, 0.85, M.walnut, 1.05, 0.38, 0, d);
  const page = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.45), M.white); page.rotation.x = -Math.PI / 2; page.position.set(0, 0.84, 0.1); d.add(page);
  const lamp = new THREE.PointLight(0xffd7a0, 0, 7, 1.6); lamp.position.set(13, 3, -14); scene.add(lamp);
  return { lamp };
}
function office(scene, side) {   // side -1 = esquerda (Luna), +1 = direita (Sol)
  const x0 = side * 12.5, z0 = -3;
  const glassPanel = (w, x, z) => {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(w, 2.4), M.glass); p.position.set(x, 1.2, z); scene.add(p);
    box(w, 0.08, 0.08, M.white, x, 2.44, z, scene); box(w, 0.08, 0.08, M.white, x, 0.04, z, scene);
  };
  glassPanel(6.4, x0 - side * 0.2, z0 - 3.4); glassPanel(6.4, x0 - side * 0.2, z0 + 3.4);
  // quem senta fica do lado da parede, olhando para o centro
  const d = desk(scene, x0, z0, side < 0 ? -Math.PI / 2 : Math.PI / 2,
    { w: side < 0 ? 2.8 : 2.2, mons: side < 0 ? 3 : 2, title: side < 0 ? ["1h", "4h", "VOL"] : ["RISCO", "CONTRA"] });
  chair(scene, x0 + side * 0.95, z0, side < 0 ? Math.PI / 2 : -Math.PI / 2);
  plant(scene, x0 + side * 2.4, z0 - 2.6, 0.9);
  const lamp = new THREE.PointLight(side < 0 ? 0xb9a8ff : 0xffa070, 0, 7, 1.6); lamp.position.set(x0, 2.6, z0); scene.add(lamp);
  return { desk: d, lamp, seat: new THREE.Vector3(x0 + side * 0.95, 0, z0), faceAngle: side < 0 ? Math.PI / 2 : -Math.PI / 2 };
}
function bull(scene, x, z) {   // o touro de Wall Street
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = -Math.PI / 5; scene.add(g);
  box(2.4, 0.5, 1.3, M.marble, 0, 0.25, 0, g);
  const b = new THREE.Group(); b.position.y = 0.5; b.scale.setScalar(0.85); g.add(b);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 1.1, 4, 10), M.bronze); body.rotation.z = Math.PI / 2; body.position.set(0, 1.05, 0); b.add(body);
  const hump = new THREE.Mesh(new THREE.SphereGeometry(0.5, 12, 8), M.bronze); hump.position.set(0.45, 1.25, 0); hump.scale.set(1, 0.85, 0.9); b.add(hump);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.42, 0.42), M.bronze); head.position.set(1.12, 0.85, 0); head.rotation.z = -0.5; b.add(head);
  const snout = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.26, 0.34), M.bronze); snout.position.set(1.36, 0.66, 0); b.add(snout);
  for (const s of [-1, 1]) {
    const horn = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.55, 6), M.gold); horn.position.set(1.1, 1.12, s * 0.28); horn.rotation.set(s * 0.9, 0, -0.6); b.add(horn);
    for (const fx of [-0.55, 0.55]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.07, 0.75, 6), M.bronze);
      leg.position.set(fx, 0.38, s * 0.22); leg.rotation.z = fx > 0 ? -0.35 : 0.3; b.add(leg);
    }
  }
}
// canto da resenha: sinuca, café e sofá (frente-esquerda). Os agentes vêm pra cá quando não há ciclo rodando.
function lounge(scene) {
  const V = (x, z) => new THREE.Vector3(x, 0, z);
  // sofá virado para a mesa de sinuca
  const g = new THREE.Group(); g.position.set(-11.5, 0, 7.3); g.rotation.y = Math.PI; scene.add(g);
  box(3.4, 0.42, 1.0, M.fabric, 0, 0.3, 0, g); box(3.4, 0.7, 0.25, M.fabric, 0, 0.7, -0.45, g);
  box(0.25, 0.6, 1.0, M.fabric, -1.6, 0.5, 0, g); box(0.25, 0.6, 1.0, M.fabric, 1.6, 0.5, 0, g);
  plant(scene, -16.8, 7.0, 1.2); plant(scene, -8.6, 7.3, 0.9);

  // mesa de sinuca
  const cx = -11.5, cz = 4.4, HX = 1.25, HZ = 0.62, R = 0.06, TOP = 0.86;
  const felt = new THREE.MeshStandardMaterial({ color: 0x1f8a4c });
  const t = new THREE.Group(); t.position.set(cx, 0, cz); scene.add(t);
  for (const [x, z] of [[-1.25, -0.6], [1.25, -0.6], [-1.25, 0.6], [1.25, 0.6]]) box(0.18, 0.7, 0.18, M.walnut, x, 0.35, z, t);
  box(2.9, 0.16, 1.6, M.walnut, 0, 0.74, 0, t);
  box(2.5, 0.04, 1.24, felt, 0, 0.84, 0, t);
  box(2.9, 0.1, 0.18, M.walnut, 0, 0.87, -0.71, t); box(2.9, 0.1, 0.18, M.walnut, 0, 0.87, 0.71, t);   // tabelas
  box(0.18, 0.1, 1.6, M.walnut, -1.36, 0.87, 0, t); box(0.18, 0.1, 1.6, M.walnut, 1.36, 0.87, 0, t);
  for (const [x, z] of [[-1.25, -0.62], [0, -0.64], [1.25, -0.62], [-1.25, 0.62], [0, 0.64], [1.25, 0.62]]) cyl(0.08, 0.08, 0.03, M.black, x, 0.87, z, t, 10);
  const lampM = new THREE.MeshStandardMaterial({ color: 0x1f8a4c, emissive: 0xfff1b0, emissiveIntensity: 0.2 });
  cyl(0.02, 0.02, 1.6, M.darkSteel, 0, 3.9, 0, t, 6); cyl(0.35, 0.55, 0.3, lampM, 0, 3.05, 0, t, 12);        // luminária
  const colors = [0xffffff, 0xf2c14e, 0x2f6fb3, 0xd8323c, 0x8e44ad, 0xe67e22, 0x3fa34d, 0x111111];
  const rack = [[-0.7, 0], [0.45, 0], [0.56, -0.065], [0.56, 0.065], [0.67, -0.13], [0.67, 0], [0.67, 0.13], [0.78, 0.065]];
  const balls = rack.map(([x, z], i) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(R, 10, 8), new THREE.MeshStandardMaterial({ color: colors[i] }));
    m.position.set(cx + x, TOP + R, cz + z); scene.add(m); return { m, v: new THREE.Vector2() };
  });
  const pool = {
    center: V(cx, cz),
    shoot() {   // tacada: bola branca na direção de uma bola qualquer
      const cue = balls[0], other = balls[1 + Math.floor(Math.random() * (balls.length - 1))];
      const d = new THREE.Vector2(other.m.position.x - cue.m.position.x, other.m.position.z - cue.m.position.z);
      if (d.lengthSq() < 1e-4) d.set(1, 0.3);
      cue.v.copy(d.normalize().rotateAround(new THREE.Vector2(), (Math.random() - 0.5) * 0.25).multiplyScalar(2.2 + Math.random() * 1.4));
    },
    update(dt) {
      for (const b of balls) {
        b.v.multiplyScalar(Math.exp(-0.9 * dt)); if (b.v.lengthSq() < 4e-4) b.v.set(0, 0);
        b.m.position.x += b.v.x * dt; b.m.position.z += b.v.y * dt;
        const lx = b.m.position.x - cx, lz = b.m.position.z - cz;
        if (Math.abs(lx) > HX - R) { b.m.position.x = cx + Math.sign(lx) * (HX - R); b.v.x *= -0.85; }
        if (Math.abs(lz) > HZ - R) { b.m.position.z = cz + Math.sign(lz) * (HZ - R); b.v.y *= -0.85; }
        b.m.rotation.x += b.v.y * dt / R; b.m.rotation.z -= b.v.x * dt / R;
      }
      for (let i = 0; i < balls.length; i++) for (let j = i + 1; j < balls.length; j++) {   // choque elástico, massas iguais
        const a = balls[i], b = balls[j], dx = b.m.position.x - a.m.position.x, dz = b.m.position.z - a.m.position.z, dist = Math.hypot(dx, dz);
        if (dist >= 2 * R || dist === 0) continue;
        const nx = dx / dist, nz = dz / dist, push = (2 * R - dist) / 2;
        a.m.position.x -= nx * push; a.m.position.z -= nz * push; b.m.position.x += nx * push; b.m.position.z += nz * push;
        const rel = (a.v.x - b.v.x) * nx + (a.v.y - b.v.y) * nz; if (rel <= 0) continue;
        a.v.x -= rel * nx; a.v.y -= rel * nz; b.v.x += rel * nx; b.v.y += rel * nz;
      }
    },
  };

  // balcão do café com máquina de espresso, encostado na parede esquerda
  const k = new THREE.Group(); k.position.set(-17.0, 0, 0.8); k.rotation.y = Math.PI / 2; scene.add(k);
  box(2.4, 0.95, 0.7, M.walnut, 0, 0.47, 0, k); box(2.5, 0.08, 0.75, M.marble, 0, 0.99, 0, k);
  const mach = new THREE.Group(); mach.position.set(-0.3, 1.03, -0.05); k.add(mach);
  box(0.75, 0.6, 0.5, M.red, 0, 0.3, 0, mach); box(0.8, 0.08, 0.55, M.steel, 0, 0.64, 0, mach);          // corpo e tampo
  box(0.55, 0.12, 0.12, M.steel, 0, 0.42, 0.3, mach);                                                   // grupo
  for (const x of [-0.14, 0.14]) { cyl(0.03, 0.03, 0.12, M.black, x, 0.3, 0.32, mach, 6); cyl(0.05, 0.045, 0.09, M.white, x, 0.05, 0.3, mach, 10); }
  box(0.5, 0.04, 0.3, M.darkSteel, 0, 0.02, 0.3, mach);                                                 // bandeja
  cyl(0.02, 0.02, 0.2, M.steel, 0.36, 0.45, 0.2, mach, 6);                                              // vaporizador
  box(0.3, 0.45, 0.3, M.black, 0.62, 1.26, 0, k);                                                      // moedor
  for (let i = 0; i < 4; i++) cyl(0.05, 0.045, 0.09, M.white, 0.75 + (i % 2) * 0.13, 1.08, 0.2 + Math.floor(i / 2) * 0.12, k, 10);
  const machineAt = V(-17.0, 1.1).setY(1.75);   // bico da máquina (balcão girado 90°)
  cyl(0.18, 0.18, 1.0, M.white, -16.9, 0.5, -12.2, scene, 12);                                          // bebedouro
  cyl(0.16, 0.16, 0.5, new THREE.MeshStandardMaterial({ color: 0x8fd3ff, transparent: true, opacity: 0.8 }), -16.9, 1.25, -12.2, scene, 12);

  // onde cada um fica na resenha (via = desvio para não atravessar a mesa)
  const slots = {
    pool1: { pos: V(-11.5, 2.75), face: V(cx, cz), activity: "pool" },
    pool2: { pos: V(-13.8, 4.4), face: V(cx, cz), activity: "pool", via: [V(-13.8, 2.6)] },
    coffee: { pos: V(-15.75, 1.0), face: V(-17, 1.1), activity: "coffee" },
    sofa1: { seat: V(-12.3, 7.2), yaw: Math.PI, via: [V(-9.0, 6.3)] },
    sofa2: { seat: V(-10.7, 7.2), yaw: Math.PI, via: [V(-9.0, 6.3)] },
  };
  return { pool, slots, machineAt };
}
function scheduleBoard(scene) {
  const face = screenCanvas(640, 320);
  const frame = new THREE.Group();
  frame.position.set(LEFT + 0.08, 2.7, -9.5); frame.rotation.y = Math.PI / 2;
  scene.add(frame);
  box(4.6, 2.35, 0.1, M.walnut, 0, 0, 0, frame);
  const panel = new THREE.Mesh(new THREE.PlaneGeometry(4.35, 2.1), new THREE.MeshBasicMaterial({ map: face.t }));
  panel.position.z = 0.065; frame.add(panel);
  return ([time, detail, note]) => {
    const { g, t } = face;
    g.fillStyle = "#173a33"; g.fillRect(0, 0, 640, 320);
    g.textAlign = "center";
    g.fillStyle = "#f2c14e"; g.font = "bold 34px sans-serif";
    g.fillText("PRÓXIMO CICLO", 320, 52);
    g.fillStyle = "#fffdf5"; g.font = "bold 48px sans-serif";
    g.fillText(time, 320, 134, 602);
    g.font = "30px sans-serif"; g.fillText(detail, 320, 208, 602);
    g.fillStyle = "#b6d1c5"; g.font = "24px sans-serif"; g.fillText(note, 320, 279, 602);
    t.needsUpdate = true;
  };
}
function wallClock(scene) {
  const face = screenCanvas(64, 64);
  const m = new THREE.Mesh(new THREE.CircleGeometry(0.55, 24), new THREE.MeshBasicMaterial({ map: face.t }));
  m.position.set(12.9, 4.55, BACK + 0.04); scene.add(m);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.56, 0.06, 6, 24), M.gold); rim.position.copy(m.position); scene.add(rim);
  return (now) => {
    const { g } = face, d = new Date(now);
    g.fillStyle = "#fffdf5"; g.fillRect(0, 0, 64, 64);
    g.save(); g.translate(32, 32); g.fillStyle = "#1f3552";
    for (let i = 0; i < 12; i++) { g.rotate(Math.PI / 6); g.fillRect(-1, -28, 2, 5); }
    const hand = (a, len, w, c) => { g.save(); g.rotate(a); g.fillStyle = c; g.fillRect(-w / 2, -len, w, len + 3); g.restore(); };
    hand(((d.getHours() % 12) + d.getMinutes() / 60) * Math.PI / 6, 15, 3, "#1f3552");
    hand((d.getMinutes() + d.getSeconds() / 60) * Math.PI / 30, 22, 2, "#1f3552");
    hand(d.getSeconds() * Math.PI / 30, 24, 1, "#d8323c");
    g.restore(); face.t.needsUpdate = true;
  };
}

// ------------------------------------------------------------------ montagem
export function buildWorld(scene) {
  mats(); backdrop(scene); room(scene);
  const exchange = exchangeZone(scene), vault = vaultZone(scene), archive = archiveZone(scene);
  const luna = office(scene, -1), sol = office(scene, 1);
  bull(scene, 13.6, 5.6); const lounge_ = lounge(scene);
  plant(scene, 8.6, -16.4, 1.2); plant(scene, -9.2, -16.5, 1.1); plant(scene, 17, 6.9, 1.1); plant(scene, 17, -11.5, 1.1);
  const astraDesk = desk(scene, 0, -1.1, Math.PI, { w: 3, mons: 3, title: ["CARTEIRA", "SCAN", "ORDENS"] });
  chair(scene, 0, -2.05, 0);
  const traders = [];
  for (const [x, z] of [[-6.2, 4.2], [-2.1, 4.2], [2.1, 4.2], [6.2, 4.2]]) {
    const d = desk(scene, x, z, 0, { w: 2.2, mons: 2, title: ["BTC", "ETH", "SOL", "BNB", "XRP"].sort(() => Math.random() - 0.5) });
    chair(scene, x, z + 0.95, Math.PI);
    traders.push({ desk: d, seat: new THREE.Vector3(x, 0, z + 0.95) });
  }
  return { exchange, vault, archive, luna, sol, astraDesk, traders, lounge: lounge_, astraSeat: new THREE.Vector3(0, 0, -2.05), clock: wallClock(scene), schedule: scheduleBoard(scene) };
}
