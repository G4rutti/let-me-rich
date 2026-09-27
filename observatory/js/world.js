// Cenário: andar alto de um prédio em Wall Street, de dia. Corte "casa de boneca": sem teto e sem parede da frente.
import * as THREE from "three";
import { Sky } from "three/addons/objects/Sky.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const W = 36, D = 26, H = 5.4;            // sala: x ∈ [-18, 18], z ∈ [-18, 8]
const BACK = -18, FRONT = 8;

// ------------------------------------------------------------------ helpers
const M = {};                              // materiais compartilhados (menos programas/draw state)
function mats() {
  const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0, ...o });
  Object.assign(M, {
    white: std(0xf3f1ec, { roughness: 0.85 }),
    wall: std(0xe9e5dc, { roughness: 0.9 }),
    steel: std(0x9aa3ad, { metalness: 0.9, roughness: 0.28 }),
    darkSteel: std(0x2e333b, { metalness: 0.8, roughness: 0.35 }),
    black: std(0x15171b, { roughness: 0.4 }),
    walnut: std(0x5a3a22, { roughness: 0.45 }),
    oakTop: std(0xb98a57, { roughness: 0.4 }),
    leather: std(0x2b2320, { roughness: 0.55 }),
    fabric: std(0x33475c, { roughness: 0.95 }),
    brass: std(0xc9a14a, { metalness: 1, roughness: 0.25 }),
    bronze: std(0x7a5230, { metalness: 0.9, roughness: 0.38 }),
    plant: std(0x3f7d3a, { roughness: 0.8, flatShading: true }),
    plantDark: std(0x2d5f2c, { roughness: 0.8, flatShading: true }),
    pot: std(0xd9d2c5, { roughness: 0.7 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0xcfe6f5, roughness: 0.04, metalness: 0, transparent: true,
      opacity: 0.2, depthWrite: false, side: THREE.DoubleSide, envMapIntensity: 1.5 }),
    mullion: std(0x3a4049, { metalness: 0.7, roughness: 0.3 }),
    marble: std(0xf2efe9, { roughness: 0.18 }),
  });
}
function box(w, h, d, m, x, y, z, parent, cast = true) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  b.position.set(x, y, z); b.castShadow = cast; b.receiveShadow = true; parent.add(b); return b;
}
function cyl(rt, rb, h, m, x, y, z, parent, seg = 20, cast = true) {
  const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
  c.position.set(x, y, z); c.castShadow = cast; c.receiveShadow = true; parent.add(c); return c;
}
function canvasTex(w, h, draw, repeat) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
export function screenCanvas(w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  return { c, g: c.getContext("2d"), t };
}

// ------------------------------------------------------------------ céu, sol, ambiente
function sky(scene, renderer) {
  const sky = new Sky(); sky.scale.setScalar(4000); scene.add(sky);
  const u = sky.material.uniforms;
  u.turbidity.value = 3.2; u.rayleigh.value = 1.1; u.mieCoefficient.value = 0.004; u.mieDirectionalG.value = 0.82;
  const sun = new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(90 - 38), THREE.MathUtils.degToRad(318));   // frente-esquerda: ilumina o rosto de quem está no salão
  u.sunPosition.value.copy(sun);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;

  const hemi = new THREE.HemisphereLight(0xcfe3ff, 0xb59a78, 1.1); scene.add(hemi);
  const light = new THREE.DirectionalLight(0xfff0d8, 2.6);
  light.position.copy(sun).multiplyScalar(60); light.position.y = Math.max(light.position.y, 30);
  light.castShadow = true;
  light.shadow.mapSize.set(2048, 2048);
  Object.assign(light.shadow.camera, { left: -26, right: 26, top: 22, bottom: -22, near: 1, far: 160 });
  light.shadow.bias = -0.0004; light.shadow.normalBias = 0.03;
  light.target.position.set(0, 0, -5); scene.add(light, light.target);
  scene.fog = new THREE.Fog(0xc9dcec, 90, 420);
}

// ------------------------------------------------------------------ cidade lá fora
function skyline(scene) {
  const facades = [
    (g, w, h) => { // vidro azul
      const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, "#9cc3e0"); gr.addColorStop(1, "#4f7896");
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      g.strokeStyle = "rgba(30,45,60,.55)"; g.lineWidth = 2;
      for (let x = 0; x <= w; x += 16) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
      for (let y = 0; y <= h; y += 22) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke(); }
    },
    (g, w, h) => { // pedra clara com janelas
      g.fillStyle = "#d9cdb8"; g.fillRect(0, 0, w, h);
      for (let y = 6; y < h; y += 18) for (let x = 5; x < w; x += 14) {
        g.fillStyle = Math.random() > 0.15 ? "#48617a" : "#7d93a8"; g.fillRect(x, y, 8, 11);
      }
    },
    (g, w, h) => { // vidro verde-escuro com faixas
      g.fillStyle = "#3f5f63"; g.fillRect(0, 0, w, h);
      for (let y = 0; y < h; y += 12) { g.fillStyle = y % 24 ? "#6c8e90" : "#2d4548"; g.fillRect(0, y, w, 7); }
    },
    (g, w, h) => { // tijolo antigo
      g.fillStyle = "#9c6b52"; g.fillRect(0, 0, w, h);
      for (let y = 8; y < h; y += 20) for (let x = 6; x < w; x += 16) { g.fillStyle = "#34495a"; g.fillRect(x, y, 9, 12); }
    },
  ];
  const base = facades.map((f) => canvasTex(128, 256, f));
  const roof = new THREE.MeshStandardMaterial({ color: 0x8e9398, roughness: 0.8 });
  const rnd = (a, b) => a + Math.random() * (b - a);
  const place = (x, z) => {
    const w = rnd(8, 18), d = rnd(8, 18), h = rnd(40, 150), kind = Math.floor(Math.random() * 4);
    const tex = base[kind].clone(); tex.needsUpdate = true;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(Math.ceil(w / 7), Math.ceil(h / 12));
    const m = new THREE.MeshStandardMaterial({ map: tex, roughness: kind === 0 || kind === 2 ? 0.15 : 0.8,
      metalness: kind === 0 || kind === 2 ? 0.4 : 0 });
    const y0 = -90;
    const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), [m, m, roof, roof, m, m]);
    b.position.set(x, y0 + h / 2, z); scene.add(b);
    if (Math.random() > 0.55) {   // recuo no topo, estilo art déco
      const t = new THREE.Mesh(new THREE.BoxGeometry(w * 0.6, h * 0.12, d * 0.6), [m, m, roof, roof, m, m]);
      t.position.set(x, y0 + h + h * 0.06, z); scene.add(t);
      if (Math.random() > 0.5) cyl(0.25, 0.4, 12, M.steel, x, y0 + h * 1.12 + 6, z, scene, 8, false);
    }
  };
  for (let i = 0; i < 26; i++) place(-150 + i * 12 + rnd(-3, 3), rnd(-60, -170));   // atrás
  for (let i = 0; i < 14; i++) place(rnd(-60, -170), -140 + i * 12 + rnd(-3, 3));    // à esquerda
  for (let i = 0; i < 10; i++) place(rnd(60, 170), rnd(-160, -40));                   // direita, ao fundo
  // nuvens
  const cloudM = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 1, emissive: 0xffffff, emissiveIntensity: 0.35 });
  for (let i = 0; i < 9; i++) {
    const g = new THREE.Group(); g.position.set(rnd(-260, 260), rnd(70, 130), rnd(-380, -220));
    for (let k = 0; k < 6; k++) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(rnd(10, 20), 10, 8), cloudM);
      s.position.set(k * 13 - 30, rnd(-3, 6), rnd(-6, 6)); s.scale.y = 0.55; g.add(s);
    }
    scene.add(g);
  }
}

// ------------------------------------------------------------------ sala
function room(scene) {
  const planks = canvasTex(512, 512, (g, w, h) => {
    for (let y = 0; y < h; y += 32) {
      let x = (y / 32) % 2 ? -90 : 0;
      while (x < w) {
        const len = 140 + Math.random() * 140, l = 44 + Math.random() * 12;
        g.fillStyle = `hsl(30, 42%, ${l}%)`; g.fillRect(x, y, len, 32);
        g.strokeStyle = "rgba(80,50,20,.25)"; g.strokeRect(x, y, len, 32);
        for (let k = 0; k < 6; k++) { g.strokeStyle = `rgba(120,80,40,${0.05 + Math.random() * 0.08})`;
          g.beginPath(); const yy = y + 4 + Math.random() * 24; g.moveTo(x, yy); g.bezierCurveTo(x + len / 3, yy + 3, x + len * 0.6, yy - 3, x + len, yy); g.stroke(); }
        x += len;
      }
    }
  }, [6, 5]);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshLambertMaterial({ map: planks }));   // fosco: sol e câmera vêm da frente, especular lavava a madeira
  floor.rotation.x = -Math.PI / 2; floor.position.set(0, 0, (BACK + FRONT) / 2); floor.receiveShadow = true; scene.add(floor);
  // laje e borda do corte
  box(W + 0.6, 0.6, D + 0.6, M.wall, 0, -0.32, (BACK + FRONT) / 2, scene, false);   // topo 2 cm abaixo do piso (sem z-fighting)
  // tapete central sob a mesa do operador
  const rug = canvasTex(512, 320, (g, w, h) => {
    g.fillStyle = "#1f3552"; g.fillRect(0, 0, w, h);
    g.strokeStyle = "#c9a14a"; g.lineWidth = 6; g.strokeRect(18, 18, w - 36, h - 36);
    g.lineWidth = 2; g.strokeRect(34, 34, w - 68, h - 68);
    g.fillStyle = "rgba(201,161,74,.15)"; for (let i = 0; i < 12; i++) g.fillRect(60 + i * 34, 60, 14, h - 120);
  });
  const rugM = new THREE.Mesh(new THREE.PlaneGeometry(9, 5.6), new THREE.MeshStandardMaterial({ map: rug, roughness: 0.95 }));
  rugM.rotation.x = -Math.PI / 2; rugM.position.set(0, 0.012, -1.6); rugM.receiveShadow = true; scene.add(rugM);
  // piso de mármore na frente da exchange
  const marble = new THREE.Mesh(new THREE.PlaneGeometry(16, 5), M.marble);
  marble.rotation.x = -Math.PI / 2; marble.position.set(0, 0.011, -15.3); marble.receiveShadow = true; scene.add(marble);

  // fachada de vidro: fundo e esquerda (montantes + vidro + peitoril)
  const curtain = (len, axis, fixed) => {
    const n = Math.round(len / 3);
    for (let i = 0; i <= n; i++) {
      const p = -len / 2 + (i * len) / n;
      if (axis === "x") box(0.14, H, 0.2, M.mullion, p, H / 2, fixed, scene); else box(0.2, H, 0.14, M.mullion, fixed, H / 2, p + (BACK + FRONT) / 2, scene);
    }
    const g = new THREE.Mesh(new THREE.PlaneGeometry(len, H), M.glass);
    if (axis === "x") g.position.set(0, H / 2, fixed); else { g.rotation.y = Math.PI / 2; g.position.set(fixed, H / 2, (BACK + FRONT) / 2); }
    scene.add(g);
    if (axis === "x") { box(len, 0.35, 0.3, M.mullion, 0, 0.17, fixed, scene); box(len, 0.25, 0.3, M.mullion, 0, H, fixed, scene); }
    else { box(0.3, 0.35, len, M.mullion, fixed, 0.17, (BACK + FRONT) / 2, scene); box(0.3, 0.25, len, M.mullion, fixed, H, (BACK + FRONT) / 2, scene); }
  };
  curtain(W, "x", BACK);
  curtain(D, "z", -W / 2);
  // parede direita sólida (arquivo + marca)
  box(0.4, H, D, M.wall, W / 2 + 0.2, H / 2, (BACK + FRONT) / 2, scene);
  const brand = canvasTex(1024, 256, (g, w, h) => {
    g.fillStyle = "#e9e5dc"; g.fillRect(0, 0, w, h);
    g.fillStyle = "#1f3552"; g.font = "600 92px Georgia, serif"; g.textAlign = "center"; g.fillText("LET ME RICH", w / 2, 128);
    g.fillStyle = "#b8923f"; g.font = "500 40px Georgia, serif"; g.fillText("C A P I T A L", w / 2, 190);
    g.fillRect(w / 2 - 190, 212, 380, 3);
  });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(6, 1.5), new THREE.MeshStandardMaterial({ map: brand, roughness: 0.6 }));
  sign.rotation.y = -Math.PI / 2; sign.position.set(W / 2 - 0.01, 3.6, 2.2); scene.add(sign);
  // colunas
  for (const [x, z] of [[-7.5, -16.6], [7.5, -16.6]]) { box(1, H, 1, M.white, x, H / 2, z, scene); }
}

// ------------------------------------------------------------------ mobília
function plant(scene, x, z, s = 1) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s); scene.add(g);
  cyl(0.32, 0.26, 0.6, M.pot, 0, 0.3, 0, g, 16);
  for (let i = 0; i < 7; i++) {
    const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.28 + Math.random() * 0.14, 0), i % 2 ? M.plant : M.plantDark);
    leaf.position.set(Math.sin(i * 1.7) * 0.22, 0.85 + i * 0.12, Math.cos(i * 1.7) * 0.22); leaf.castShadow = true; g.add(leaf);
  }
}
function chair(scene, x, z, ry) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry; scene.add(g);
  cyl(0.04, 0.04, 0.4, M.darkSteel, 0, 0.22, 0, g, 8);
  for (let i = 0; i < 5; i++) { const leg = box(0.05, 0.04, 0.34, M.darkSteel, 0, 0.04, 0, g, false); leg.rotation.y = (i * Math.PI * 2) / 5; leg.translateZ(0.17); }
  box(0.52, 0.09, 0.5, M.leather, 0, 0.47, 0, g);
  box(0.5, 0.62, 0.08, M.leather, 0, 0.84, -0.25, g);
  return g;
}
function monitor(parent, x, y, z, ry, w, h) {
  const s = screenCanvas(320, Math.round((320 * h) / w));
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = ry; parent.add(g);
  box(w + 0.05, h + 0.05, 0.035, M.black, 0, 0, 0, g);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: s.t, toneMapped: false }));
  scr.position.z = 0.02; g.add(scr);
  box(0.05, 0.28, 0.05, M.darkSteel, 0, -h / 2 - 0.12, -0.03, g, false);
  box(0.24, 0.02, 0.16, M.darkSteel, 0, -h / 2 - 0.26, -0.03, g, false);
  return s;
}
// mesa: frente da mesa = +z local (lado de quem senta). Telas viradas para +z.
function desk(scene, x, z, ry, { w = 2.4, mons = 2, title = [] } = {}) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = ry; scene.add(g);
  box(w, 0.06, 1.0, M.oakTop, 0, 0.76, 0, g);
  box(0.06, 0.73, 0.9, M.darkSteel, -w / 2 + 0.08, 0.37, 0, g); box(0.06, 0.73, 0.9, M.darkSteel, w / 2 - 0.08, 0.37, 0, g);
  box(w - 0.2, 0.4, 0.03, M.darkSteel, 0, 0.55, -0.42, g, false);
  const screens = [];
  for (let i = 0; i < mons; i++) {
    const off = (i - (mons - 1) / 2) * 0.78;
    const s = monitor(g, off, 1.22, -0.28, -off * 0.3, 0.72, 0.43); s.title = title[i] || ""; s.seed = Math.random() * 9;
    s.trend = Math.random() - 0.3; screens.push(s);
  }
  box(0.55, 0.02, 0.18, M.black, 0, 0.8, 0.12, g, false);           // teclado
  const mug = cyl(0.045, 0.04, 0.1, M.white, w / 2 - 0.35, 0.84, 0.15, g, 12, false);
  mug.material = M.white;
  return { g, screens };
}

// ------------------------------------------------------------------ estações
function exchangeZone(scene) {
  const g = new THREE.Group(); g.position.set(0, 0, -17.2); scene.add(g);
  box(15, 5.2, 0.4, M.darkSteel, 0, 2.6, 0, g);
  const wall = screenCanvas(2048, 704);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(14.2, 4.4), new THREE.MeshBasicMaterial({ map: wall.t, toneMapped: false }));
  scr.position.set(0, 2.75, 0.21); g.add(scr);
  // faixa de cotações acima
  const tick = screenCanvas(2048, 64);
  const tk = new THREE.Mesh(new THREE.PlaneGeometry(15, 0.47), new THREE.MeshBasicMaterial({ map: tick.t, toneMapped: false }));
  tk.position.set(0, 5.05, 0.22); g.add(tk);
  // balcão de mármore com tampo de latão
  const c = new THREE.Group(); c.position.set(0, 0, 2.3); g.add(c);
  box(5.4, 1.05, 0.8, M.marble, 0, 0.52, 0, c);
  box(5.6, 0.06, 0.95, M.brass, 0, 1.08, 0, c);
  const s1 = monitor(c, -1.4, 1.35, -0.15, Math.PI, 0.6, 0.36); const s2 = monitor(c, 1.4, 1.35, -0.15, Math.PI, 0.6, 0.36);
  s1.title = "ORDENS"; s2.title = "BOOK"; s1.seed = 2; s2.seed = 5; s1.trend = 0.3; s2.trend = -0.2;
  const light = new THREE.PointLight(0x7fd3ff, 0, 12, 1.6); light.position.set(0, 3, -14.5); scene.add(light);
  return { wall, tick, screens: [s1, s2], light };
}
function vaultZone(scene) {
  const g = new THREE.Group(); g.position.set(-15.6, 0, -15.6); g.rotation.y = Math.PI / 4; scene.add(g);
  box(5, H, 1.2, M.wall, 0, H / 2, -0.2, g);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(1.35, 0.16, 16, 48), M.steel); ring.position.set(0, 1.8, 0.45); g.add(ring);
  const door = new THREE.Mesh(new THREE.CylinderGeometry(1.25, 1.25, 0.35, 48), M.steel);
  door.rotation.x = Math.PI / 2; door.position.set(0, 1.8, 0.55); door.castShadow = true; g.add(door);
  const wheel = new THREE.Group(); wheel.position.set(0, 1.8, 0.78); g.add(wheel);
  const tor = new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.05, 12, 32), M.brass); wheel.add(tor);
  for (let i = 0; i < 3; i++) { const sp = box(0.05, 0.95, 0.05, M.brass, 0, 0, 0, wheel, false); sp.rotation.z = (i * Math.PI) / 3; }
  for (let i = 0; i < 10; i++) { const b = cyl(0.06, 0.06, 0.1, M.brass, Math.cos(i / 10 * Math.PI * 2) * 1.05, 1.8 + Math.sin(i / 10 * Math.PI * 2) * 1.05, 0.75, g, 8, false); b.rotation.x = Math.PI / 2; }
  // detector/catraca
  box(0.25, 2.2, 0.5, M.darkSteel, -1.9, 1.1, 1.4, g); box(0.25, 2.2, 0.5, M.darkSteel, 1.9, 1.1, 1.4, g);
  const lamp = new THREE.PointLight(0xffe0a0, 0, 8, 1.6); lamp.position.set(-13, 3.2, -13); scene.add(lamp);
  return { wheel, lamp };
}
function archiveZone(scene) {
  const g = new THREE.Group(); scene.add(g);
  const colors = [0x8c2f39, 0x2f5d8c, 0xd6b98c, 0x3d6b4f, 0x6b4f8c, 0xb5651d, 0x1f3552];
  const bookM = colors.map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7 }));
  for (const zc of [-13.2, -9.6, -6.0]) {
    const s = new THREE.Group(); s.position.set(17.55, 0, zc); s.rotation.y = -Math.PI / 2; g.add(s);
    box(3.3, 3.6, 0.55, M.walnut, 0, 1.8, 0, s);
    for (let r = 0; r < 5; r++) {
      box(3.1, 0.04, 0.5, M.walnut, 0, 0.3 + r * 0.7, 0.05, s, false);
      let x = -1.45;
      while (x < 1.4) { const w = 0.07 + Math.random() * 0.08, h = 0.42 + Math.random() * 0.18;
        const b = box(w, h, 0.36, bookM[Math.floor(Math.random() * bookM.length)], x + w / 2, 0.32 + r * 0.7 + h / 2, 0.08, s, false);
        if (Math.random() > 0.9) b.rotation.z = 0.25; x += w + 0.01; }
    }
  }
  // mesa do arquivista com livro-razão aberto
  const d = new THREE.Group(); d.position.set(14.8, 0, -9.6); d.rotation.y = Math.PI / 2; g.add(d);
  box(2.2, 0.06, 0.9, M.walnut, 0, 0.78, 0, d); box(2.1, 0.74, 0.08, M.walnut, 0, 0.38, -0.4, d);
  box(0.08, 0.74, 0.85, M.walnut, -1.05, 0.38, 0, d); box(0.08, 0.74, 0.85, M.walnut, 1.05, 0.38, 0, d);
  const page = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.45), M.white); page.rotation.x = -Math.PI / 2; page.position.set(0, 0.82, 0.1); d.add(page);
  const lamp = new THREE.PointLight(0xffd7a0, 0, 7, 1.6); lamp.position.set(14, 3, -9.6); scene.add(lamp);
  return { lamp };
}
function office(scene, side) {   // side -1 = esquerda (Luna), +1 = direita (Sol)
  const x0 = side * 12.5, z0 = -3;
  // divisórias de vidro: fundo (encostado na parede externa) e laterais; aberta para o centro
  const glassPanel = (w, x, z, ry) => {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(w, 2.6), M.glass); p.position.set(x, 1.3, z); p.rotation.y = ry; scene.add(p);
    box(ry ? 0.03 : w, 0.03, ry ? w : 0.03, M.steel, x, 2.6, z, scene, false);
  };
  glassPanel(6.4, x0 - side * 0.2, z0 - 3.4, 0); glassPanel(6.4, x0 - side * 0.2, z0 + 3.4, 0);
  // quem senta fica do lado da parede, olhando para o centro; telas entre a pessoa e o salão
  const d = desk(scene, x0, z0, side < 0 ? -Math.PI / 2 : Math.PI / 2,
    { w: side < 0 ? 2.8 : 2.2, mons: side < 0 ? 3 : 2, title: side < 0 ? ["1h", "4h", "VOLUME"] : ["RISCO", "CONTRA"] });
  const chr = chair(scene, x0 + side * 0.95, z0, side < 0 ? Math.PI / 2 : -Math.PI / 2);
  plant(scene, x0 + side * 2.4, z0 - 2.6, 0.9);
  const lamp = new THREE.PointLight(side < 0 ? 0xb9a8ff : 0xffa070, 0, 7, 1.6); lamp.position.set(x0, 2.6, z0); scene.add(lamp);
  return { desk: d, chair: chr, lamp, seat: new THREE.Vector3(x0 + side * 0.95, 0, z0), faceAngle: side < 0 ? Math.PI / 2 : -Math.PI / 2 };
}
function bull(scene, x, z) {   // o touro de Wall Street, low-poly em bronze
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = -Math.PI / 5; scene.add(g);
  box(2.4, 0.5, 1.3, M.marble, 0, 0.25, 0, g);
  const b = new THREE.Group(); b.position.y = 0.5; b.scale.setScalar(0.85); g.add(b);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 1.1, 6, 12), M.bronze); body.rotation.z = Math.PI / 2; body.position.set(0, 1.05, 0); body.castShadow = true; b.add(body);
  const hump = new THREE.Mesh(new THREE.SphereGeometry(0.5, 14, 10), M.bronze); hump.position.set(0.45, 1.25, 0); hump.scale.set(1, 0.85, 0.9); b.add(hump);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.42, 0.42), M.bronze); head.position.set(1.12, 0.85, 0); head.rotation.z = -0.5; head.castShadow = true; b.add(head);
  const snout = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.26, 0.34), M.bronze); snout.position.set(1.36, 0.66, 0); b.add(snout);
  for (const s of [-1, 1]) {
    const horn = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.55, 8), M.bronze);
    horn.position.set(1.1, 1.12, s * 0.28); horn.rotation.set(s * 0.9, 0, -0.6); b.add(horn);
    for (const fx of [-0.55, 0.55]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.07, 0.75, 8), M.bronze);
      leg.position.set(fx, 0.38, s * 0.22); leg.rotation.z = fx > 0 ? -0.35 : 0.3; leg.castShadow = true; b.add(leg);
    }
  }
  const tail = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.02, 0.8, 6), M.bronze); tail.position.set(-0.95, 1.35, 0); tail.rotation.z = 0.9; b.add(tail);
}
function lounge(scene) {
  const g = new THREE.Group(); g.position.set(-13.5, 0, 4.8); scene.add(g);
  box(3.4, 0.42, 1.0, M.fabric, 0, 0.3, 0, g); box(3.4, 0.7, 0.25, M.fabric, 0, 0.7, -0.45, g);
  box(0.25, 0.6, 1.0, M.fabric, -1.6, 0.5, 0, g); box(0.25, 0.6, 1.0, M.fabric, 1.6, 0.5, 0, g);
  const table = new THREE.Group(); table.position.set(0, 0, 1.4); g.add(table);
  cyl(0.7, 0.7, 0.05, M.marble, 0, 0.42, 0, table, 32); cyl(0.05, 0.05, 0.4, M.brass, 0, 0.2, 0, table, 8);
  box(0.3, 0.02, 0.4, M.white, 0.2, 0.46, 0.1, table, false);                   // jornal
  plant(scene, -16.8, 6.8, 1.2); plant(scene, -10.8, 6.9, 0.9);
  // café
  const k = new THREE.Group(); k.position.set(-16.9, 0, -9.4); k.rotation.y = Math.PI / 2; scene.add(k);
  box(2.4, 0.95, 0.7, M.walnut, 0, 0.47, 0, k); box(2.5, 0.05, 0.75, M.marble, 0, 0.97, 0, k);
  box(0.45, 0.55, 0.4, M.black, -0.6, 1.27, 0, k); box(0.35, 0.45, 0.35, M.steel, 0.3, 1.22, 0, k);
  for (let i = 0; i < 3; i++) cyl(0.045, 0.04, 0.1, M.white, 0.8 + i * 0.12, 1.05, 0.15, k, 10, false);
  // bebedouro
  cyl(0.18, 0.18, 1.0, M.white, -16.9, 0.5, -11.6, scene, 16); const w = cyl(0.16, 0.16, 0.5, new THREE.MeshStandardMaterial({ color: 0x8fc7ec, transparent: true, opacity: 0.6, roughness: 0.1 }), -16.9, 1.25, -11.6, scene, 16, false);
  w.castShadow = false;
}
function wallClock(scene) {
  const face = screenCanvas(256, 256);
  const m = new THREE.Mesh(new THREE.CircleGeometry(0.55, 48), new THREE.MeshBasicMaterial({ map: face.t }));
  m.rotation.y = -Math.PI / 2; m.position.set(W / 2 - 0.02, 3.9, -1.8); scene.add(m);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(0.56, 0.04, 8, 48), M.brass); rim.rotation.y = -Math.PI / 2; rim.position.copy(m.position); scene.add(rim);
  return (now) => {
    const { g } = face, d = new Date(now);
    g.fillStyle = "#fbfaf6"; g.fillRect(0, 0, 256, 256);
    g.save(); g.translate(128, 128); g.strokeStyle = "#1f3552";
    for (let i = 0; i < 12; i++) { g.rotate(Math.PI / 6); g.lineWidth = 5; g.beginPath(); g.moveTo(0, -104); g.lineTo(0, -88); g.stroke(); }
    const hand = (a, len, w, c) => { g.save(); g.rotate(a); g.strokeStyle = c; g.lineWidth = w; g.lineCap = "round"; g.beginPath(); g.moveTo(0, 12); g.lineTo(0, -len); g.stroke(); g.restore(); };
    hand(((d.getHours() % 12) + d.getMinutes() / 60) * Math.PI / 6, 58, 8, "#1f3552");
    hand((d.getMinutes() + d.getSeconds() / 60) * Math.PI / 30, 84, 5, "#1f3552");
    hand(d.getSeconds() * Math.PI / 30, 92, 2, "#b8923f");
    g.restore(); face.t.needsUpdate = true;
  };
}

// ------------------------------------------------------------------ montagem
export function buildWorld(scene, renderer) {
  mats(); sky(scene, renderer); skyline(scene); room(scene);
  const exchange = exchangeZone(scene), vault = vaultZone(scene), archive = archiveZone(scene);
  const luna = office(scene, -1), sol = office(scene, 1);
  bull(scene, 13.6, 5.6); lounge(scene);
  plant(scene, 16.6, -16.4, 1.3); plant(scene, -9.2, -16.6, 1.1); plant(scene, 9.2, -16.6, 1.1); plant(scene, 16.8, 6.9, 1.1);
  // mesa do operador (centro, virada para a câmera: ele senta de costas pro telão e olha o salão)
  const astraDesk = desk(scene, 0, -1.1, Math.PI, { w: 3, mons: 3, title: ["CARTEIRA", "SCAN", "ORDENS"] });
  chair(scene, 0, -2.05, 0);
  // mesas dos traders (figurantes) de frente para o telão
  const traders = [];
  for (const [x, z] of [[-6.2, 4.2], [-2.1, 4.2], [2.1, 4.2], [6.2, 4.2]]) {
    const d = desk(scene, x, z, 0, { w: 2.2, mons: 2, title: ["BTC", "ETH", "SOL", "BNB", "XRP"].sort(() => Math.random() - 0.5) });
    chair(scene, x, z + 0.95, Math.PI);
    traders.push({ desk: d, seat: new THREE.Vector3(x, 0, z + 0.95) });
  }
  return {
    exchange, vault, archive, luna, sol, astraDesk, traders,
    astraSeat: new THREE.Vector3(0, 0, -2.05),
    clock: wallClock(scene),
    bounds: { W, D, BACK, FRONT },
  };
}
