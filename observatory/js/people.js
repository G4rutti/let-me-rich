// Pessoas low-poly articuladas: andam, sentam, digitam, falam gesticulando e olham para quem fala.
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.62, ...o });
const G = {                                   // geometrias compartilhadas
  thigh: new THREE.CapsuleGeometry(0.1, 0.32, 4, 10),
  shin: new THREE.CapsuleGeometry(0.088, 0.32, 4, 10),
  upper: new THREE.CapsuleGeometry(0.078, 0.22, 4, 10),
  fore: new THREE.CapsuleGeometry(0.07, 0.2, 4, 10),
  hand: new THREE.SphereGeometry(0.07, 10, 8),
  shoe: new THREE.BoxGeometry(0.16, 0.1, 0.3),
  torso: new THREE.CylinderGeometry(0.205, 0.165, 0.56, 18),
  belt: new THREE.CylinderGeometry(0.168, 0.17, 0.12, 18),
  neck: new THREE.CylinderGeometry(0.07, 0.075, 0.1, 10),
  head: new THREE.SphereGeometry(0.118, 22, 18),
  eye: new THREE.SphereGeometry(0.017, 8, 6),
  ear: new THREE.SphereGeometry(0.028, 8, 6),
  nose: new THREE.ConeGeometry(0.018, 0.05, 6),
  mouth: new THREE.BoxGeometry(0.05, 0.012, 0.01),
  brow: new THREE.BoxGeometry(0.045, 0.01, 0.01),
  tie: new THREE.BoxGeometry(0.052, 0.3, 0.02),
  collar: new THREE.PlaneGeometry(0.13, 0.17),
  lens: new THREE.TorusGeometry(0.03, 0.005, 6, 16),
};
const black = std(0x16171a, { roughness: 0.3 });
const white = std(0xf7f7f5, { roughness: 0.8 });
const shoeM = std(0x1d1a18, { roughness: 0.25, metalness: 0.1 });
const frameM = std(0x222222, { metalness: 0.6, roughness: 0.3 });

function mesh(geo, m, parent, x = 0, y = 0, z = 0, cast = true) {
  const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = cast; parent.add(o); return o;
}
const damp = (a, b, k, dt) => a + (b - a) * (1 - Math.exp(-k * dt));
const dampAngle = (a, b, k, dt) => { let d = ((b - a + Math.PI) % (Math.PI * 2)) - Math.PI; if (d < -Math.PI) d += Math.PI * 2; return a + d * (1 - Math.exp(-k * dt)); };

function hair(style, m, head) {
  const cap = (r, tl, y = 0.012, sx = 1, sz = 1.04) => {
    const h = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 12, 0, Math.PI * 2, 0, tl), m);
    h.position.y = y; h.scale.set(sx, 1.08, sz); h.castShadow = true; head.add(h); return h;
  };
  if (style === "bald") return;
  if (style === "short") { const h = cap(0.126, Math.PI * 0.5); h.rotation.x = -0.25; }
  if (style === "side") { const h = cap(0.127, Math.PI * 0.52); h.rotation.set(-0.2, 0, 0.18); }
  if (style === "bob" || style === "long") {
    const h = cap(0.132, Math.PI * 0.62, 0.0, 1.06, 1.08); h.rotation.x = -0.15;
    const back = new THREE.Mesh(new THREE.CylinderGeometry(0.128, 0.12, style === "long" ? 0.34 : 0.16, 18, 1, true, Math.PI * 0.62, Math.PI * 1.76), m);
    back.position.set(0, style === "long" ? -0.12 : -0.04, -0.005); back.scale.z = 1.05; back.castShadow = true; head.add(back);
  }
  if (style === "bun") {
    const h = cap(0.127, Math.PI * 0.55); h.rotation.x = -0.2;
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 10), m); b.position.set(0, 0.1, -0.1); head.add(b);
  }
  if (style === "curly") {
    for (let i = 0; i < 16; i++) {
      const b = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 6), m);
      const a = (i / 16) * Math.PI * 2, r = 0.1;
      b.position.set(Math.cos(a) * r, 0.07 + Math.sin(i * 3.1) * 0.02, Math.sin(a) * r - 0.01); head.add(b);
    }
    cap(0.12, Math.PI * 0.45, 0.03);
  }
}

export class Person {
  constructor(scene, o) {
    this.o = o;
    this.root = new THREE.Group(); scene.add(this.root);
    this.pos = this.root.position; this.yaw = 0; this.targetYaw = 0;
    const suit = std(o.suit, { roughness: 0.75 }), pants = std(o.pants ?? o.suit, { roughness: 0.75 });
    const skin = std(o.skin, { roughness: 0.7 }), hairM = std(o.hair, { roughness: 0.85 });
    const tieM = std(o.tie, { roughness: 0.45, emissive: o.tie, emissiveIntensity: 0.08 });

    const p = this.pelvis = new THREE.Group(); p.position.y = 0.95; this.root.add(p);
    mesh(G.belt, pants, p, 0, 0.02, 0);
    // pernas
    this.legs = [-1, 1].map((s) => {
      const hip = new THREE.Group(); hip.position.set(s * 0.11, 0, 0); p.add(hip);
      mesh(G.thigh, pants, hip, 0, -0.22, 0);
      const knee = new THREE.Group(); knee.position.y = -0.45; hip.add(knee);
      mesh(G.shin, pants, knee, 0, -0.21, 0);
      mesh(G.shoe, shoeM, knee, 0, -0.45, 0.05);
      return { hip, knee };
    });
    // tronco
    const chest = this.chest = new THREE.Group(); chest.position.y = 0.04; p.add(chest);
    const torso = mesh(G.torso, suit, chest, 0, 0.3, 0); torso.scale.set(1.28, 1, 0.8);   // tronco largo, jeito Habbo
    const col = new THREE.Mesh(G.collar, white); col.position.set(0, 0.47, 0.109); chest.add(col);
    if (o.tie !== null && !o.noTie) mesh(G.tie, tieM, chest, 0, 0.4, 0.118, false);
    else { const sc = new THREE.Mesh(new THREE.TorusGeometry(0.075, 0.018, 8, 20), tieM); sc.rotation.x = Math.PI / 2 - 0.3; sc.position.set(0, 0.56, 0.02); chest.add(sc); }
    mesh(G.neck, skin, chest, 0, 0.62, 0);
    // cabeça
    const head = this.head = new THREE.Group(); head.position.y = 0.64; head.scale.setScalar(1.9); chest.add(head);   // cabeção, jeito Habbo
    const skull = mesh(G.head, skin, head, 0, 0.1, 0); skull.scale.set(0.93, 1.1, 1);
    this.eyes = [-1, 1].map((s) => mesh(G.eye, black, head, s * 0.04, 0.12, 0.1, false));
    [-1, 1].forEach((s) => { const b = mesh(G.brow, hairM, head, s * 0.041, 0.152, 0.106, false); b.rotation.z = -s * 0.12; });
    [-1, 1].forEach((s) => mesh(G.ear, skin, head, s * 0.11, 0.1, 0, false));
    const nose = mesh(G.nose, skin, head, 0, 0.085, 0.118, false); nose.rotation.x = Math.PI / 2;
    this.mouth = mesh(G.mouth, std(0x7a3b35), head, 0, 0.045, 0.106, false);
    hair(o.hairStyle, hairM, head);
    if (o.glasses) {
      [-1, 1].forEach((s) => mesh(G.lens, frameM, head, s * 0.042, 0.12, 0.118, false));
      mesh(new THREE.BoxGeometry(0.03, 0.005, 0.005), frameM, head, 0, 0.125, 0.12, false);
    }
    // braços
    this.arms = [-1, 1].map((s) => {
      const sh = new THREE.Group(); sh.position.set(s * 0.29, 0.52, 0); chest.add(sh);
      mesh(G.upper, suit, sh, 0, -0.16, 0);
      const el = new THREE.Group(); el.position.y = -0.31; sh.add(el);
      mesh(G.fore, suit, el, 0, -0.14, 0);
      mesh(G.hand, skin, el, 0, -0.3, 0.01);
      return { sh, el };
    });

    // crachá preso à cabeça (acompanha sentar/levantar); as falas vão para o chat do topo, como no Habbo
    if (o.name) {   // figurantes não têm crachá
      const tag = this.tag = document.createElement("div"); tag.className = "name";
      tag.innerHTML = `<i style="background:${o.color}"></i><span>${o.name}</span><small>${o.role}</small>`;
      this.tagObj = new CSS2DObject(tag); this.tagObj.position.set(0, 0.3, 0); head.add(this.tagObj);
    }
    const blob = new THREE.Mesh(new THREE.CircleGeometry(0.34, 16), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.22, depthWrite: false }));
    blob.rotation.x = -Math.PI / 2; blob.position.y = 0.02; blob.scale.set(1.25, 0.9, 1); this.root.add(blob);   // sombra redonda

    this.state = "stand"; this.path = []; this.onArrive = null;
    this.talkUntil = 0; this.typing = false; this.lookAt = null; this.phase = Math.random() * 10;
    this.blinkAt = 1 + Math.random() * 4; this.seed = Math.random() * 100; this.speedMul = 1;
    this.root.traverse((c) => { if (c.isMesh) c.receiveShadow = false; });
  }

  place(v, yaw = 0) { this.pos.copy(v); this.yaw = this.targetYaw = yaw; this.root.rotation.y = yaw; }
  sit(seat, yaw) { this.place(seat, yaw); this.state = "sit"; this.seat = seat.clone(); this.seatYaw = yaw; }
  walk(points) {
    this.state = "walk"; this.path = points.map((p) => p.clone());
    return new Promise((r) => (this.onArrive = r));
  }
  faceTo(v) { const d = new THREE.Vector3().subVectors(v, this.pos); this.targetYaw = Math.atan2(d.x, d.z); }
  talk(ms) { this.talkUntil = performance.now() + Math.min(ms, 4000); }   // boca + gesto; o texto vai pro chat
  worldHead() { return this.head.getWorldPosition(new THREE.Vector3()); }

  update(dt, t, speed) {
    const L = this.legs, A = this.arms, k = 14;
    let pelvisY = 0.95, legX = [0, 0], kneeX = [0, 0], shX = [0.05, 0.05], shZ = [-0.07, 0.07], elX = [-0.18, -0.18];
    let chestX = 0, headX = 0, headY = 0;

    if (this.state === "walk" && this.path.length) {
      const target = this.path[0], d = new THREE.Vector3(target.x - this.pos.x, 0, target.z - this.pos.z);
      const dist = d.length(), step = 1.55 * speed * dt;
      if (dist <= step) {
        this.pos.x = target.x; this.pos.z = target.z; this.path.shift();
        if (!this.path.length) { this.state = "stand"; const r = this.onArrive; this.onArrive = null; r && r(); }
      } else {
        d.normalize(); this.pos.x += d.x * step; this.pos.z += d.z * step; this.targetYaw = Math.atan2(d.x, d.z);
      }
      this.phase += dt * 7.2 * speed;
      const s = Math.sin(this.phase);
      legX = [-s * 0.52, s * 0.52];
      kneeX = [Math.max(0, Math.sin(this.phase + 1.3)) * 0.85, Math.max(0, Math.sin(this.phase + 1.3 + Math.PI)) * 0.85];
      shX = [s * 0.42, -s * 0.42]; elX = [-0.35, -0.35];
      pelvisY = 0.95 + Math.abs(Math.cos(this.phase)) * 0.028; chestX = 0.05;
    } else if (this.state === "sit") {
      pelvisY = 0.54; legX = [-Math.PI / 2 + 0.05, -Math.PI / 2 - 0.05]; kneeX = [Math.PI / 2 - 0.05, Math.PI / 2 + 0.05];
      if (this.typing) {
        const a = Math.sin(t * 14 + this.seed), b = Math.sin(t * 13 + this.seed + 2);
        shX = [-0.75 + a * 0.04, -0.75 + b * 0.04]; elX = [-0.95, -0.95]; shZ = [0.12, -0.12];
        headX = 0.12 + Math.sin(t * 0.7 + this.seed) * 0.04;
      } else { shX = [-0.35, -0.35]; elX = [-0.85, -0.85]; shZ = [0.05, -0.05]; }
      chestX = 0.06;
    } else {   // em pé
      const br = Math.sin(t * 1.6 + this.seed);
      shZ = [-0.08 - br * 0.01, 0.08 + br * 0.01];
      pelvisY = 0.95 + br * 0.003;
    }
    // falando: boca, cabeça e mão direita
    const talking = performance.now() < this.talkUntil;
    if (this.tag && talking !== this._talkingTag) { this.tag.classList.toggle("talking", talking); this._talkingTag = talking; }
    this.mouth.scale.y = talking ? 1 + Math.abs(Math.sin(t * 17 + this.seed)) * 3.2 : 1;
    if (talking) {
      headX += Math.sin(t * 4.5) * 0.06;
      if (this.state !== "walk") { shX[1] = (this.state === "sit" ? -0.9 : -0.55) + Math.sin(t * 3.1) * 0.18; elX[1] = -1.1 + Math.sin(t * 2.3) * 0.2; shZ[1] = 0.25; }
    }
    // olhar para alguém
    if (this.lookAt) {
      const h = this.lookAt.clone().sub(this.pos); const want = Math.atan2(h.x, h.z);
      let rel = ((want - this.yaw + Math.PI) % (Math.PI * 2)) - Math.PI; if (rel < -Math.PI) rel += Math.PI * 2;
      headY = THREE.MathUtils.clamp(rel, -1.1, 1.1);
      if (this.state === "stand" && Math.abs(rel) > 0.9) this.targetYaw = want;   // em pé, vira o corpo
    }
    // piscar
    if (t > this.blinkAt) { this.eyes.forEach((e) => (e.scale.y = 0.1)); if (t > this.blinkAt + 0.12) { this.eyes.forEach((e) => (e.scale.y = 1)); this.blinkAt = t + 2 + Math.random() * 4; } }

    this.yaw = dampAngle(this.yaw, this.targetYaw, 9, dt); this.root.rotation.y = this.yaw;
    this.pelvis.position.y = damp(this.pelvis.position.y, pelvisY, k, dt);
    L.forEach((l, i) => { l.hip.rotation.x = damp(l.hip.rotation.x, legX[i], k, dt); l.knee.rotation.x = damp(l.knee.rotation.x, kneeX[i], k, dt); });
    A.forEach((a, i) => {
      a.sh.rotation.x = damp(a.sh.rotation.x, shX[i], k, dt); a.sh.rotation.z = damp(a.sh.rotation.z, shZ[i], k, dt);
      a.el.rotation.x = damp(a.el.rotation.x, elX[i], k, dt);
    });
    this.chest.rotation.x = damp(this.chest.rotation.x, chestX, k, dt);
    this.head.rotation.x = damp(this.head.rotation.x, headX, 8, dt);
    this.head.rotation.y = damp(this.head.rotation.y, headY, 6, dt);
  }
}
