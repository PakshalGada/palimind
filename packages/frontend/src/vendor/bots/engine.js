// The rig and its behaviour. A pose is a handful of numbers — head turn, tilt,
// position, squash and the face — and each state is a little behaviour that
// produces a pose every frame. Switching state cross-fades the two behaviours
// over a timed ease, so nothing ever snaps.

export const STATES = ['default', 'working', 'sleeping'];

export const REST = Object.freeze({
  yaw: 0, pitch: 0, roll: 0, x: 0, y: 0, sx: 1, sy: 1,
  lookX: 0, lookY: 0, eyeOpen: 1, happy: 0, smile: 0.25, mouthOpen: 0, sleep: 0,
});
const KEYS = Object.keys(REST);

export function mulberry32(seed) {
  let a = Math.floor(seed * 2 ** 32) >>> 0 || 0x9e3779b9;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const approach = (cur, target, rate, dt) => cur + (target - cur) * (1 - Math.exp(-rate * dt));
export const smoothstep = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * A jump: crouch, take-off, air with a stretch, landing squash and rebound.
 * `p` is 0..1 over the whole jump. Returns y (negative = up), squash and spin.
 */
export function jumpCurve(p, height, { squash = 1, stretch = 1 } = {}) {
  const crouch = 0.17, land = 0.78;
  if (p <= 0 || p >= 1) return { y: 0, sx: 1, sy: 1, spin: p >= 1 ? 1 : 0 };
  if (p < crouch) {
    const q = Math.sin((p / crouch) * Math.PI / 2);
    return { y: 0, sy: 1 - 0.16 * squash * q, sx: 1 + 0.11 * squash * q, spin: 0 };
  }
  if (p < land) {
    const q = (p - crouch) / (land - crouch);
    const s = 1 + 0.12 * stretch * Math.sin(q * Math.PI) * (1 - 0.6 * q);
    return { y: -height * 4 * q * (1 - q), sy: s, sx: 1 / Math.sqrt(s), spin: easeInOut(q) };
  }
  const q = (p - land) / (1 - land);
  const k = Math.sin(q * Math.PI) * (1 - 0.35 * q) * 0.2 * squash - Math.sin(q * Math.PI * 2) * 0.03 * (1 - q);
  return { y: 0, sy: 1 - k, sx: 1 + k * 0.75, spin: 1 };
}

// ---------------------------------------------------------------------------
// Behaviours

class Blinker {
  constructor(rand, min = 2, max = 5.5) {
    this.rand = rand; this.min = min; this.max = max;
    this.wait = min + rand() * (max - min);
    this.t = -1;
    this.double = false;
  }
  update(dt) {
    if (this.t >= 0) {
      this.t += dt / 0.17;
      if (this.t >= 1) {
        this.t = -1;
        if (this.double) { this.double = false; this.wait = 0.12; }
        else this.wait = this.min + this.rand() * (this.max - this.min);
      }
    } else if ((this.wait -= dt) <= 0) {
      this.t = 0;
      this.double = this.rand() < 0.22;
    }
    return this.t < 0 ? 1 : 1 - Math.sin(this.t * Math.PI);
  }
}

class Idle {
  constructor(rand, opts) {
    this.rand = rand;
    this.opts = opts;
    this.blink = new Blinker(rand);
    this.side = rand() < 0.5 ? -1 : 1;
    this.look = { x: 0, y: 0, tx: 0.6 * this.side, ty: -0.1 };
    this.glance = 1 + rand() * 2;
    this.jumpP = -1;
    this.jumpWait = this.nextJump();
  }
  nextJump() {
    const every = this.opts.jumpEvery ?? 8;
    return every > 0 ? every * (0.6 + this.rand() * 0.8) : Infinity;
  }
  poke() { if (this.jumpP < 0) this.jumpP = 0; }
  update(dt, t, pointer) {
    const o = this.opts;
    const turn = o.turn ?? 1;
    if ((this.glance -= dt) <= 0) {
      // Look to a corner, hold, swing across to the opposite one.
      this.side = -this.side;
      this.look.tx = this.side * (0.45 + this.rand() * 0.55);
      this.look.ty = -0.35 + this.rand() * 0.6;
      if (this.rand() < 0.25) { this.look.tx *= 0.2; this.look.ty = 0; }
      this.glance = 1.6 + this.rand() * 2.8;
    }
    let tx = this.look.tx, ty = this.look.ty;
    if (pointer) { tx = pointer.x; ty = pointer.y; }
    this.look.x = approach(this.look.x, tx, pointer ? 9 : 5, dt);
    this.look.y = approach(this.look.y, ty, pointer ? 9 : 5, dt);

    if (this.jumpP < 0 && (this.jumpWait -= dt) <= 0) { this.jumpP = 0; }
    let j = { y: 0, sx: 1, sy: 1, spin: 0 };
    if (this.jumpP >= 0) {
      this.jumpP += dt / (o.jumpTime ?? 0.95);
      j = jumpCurve(this.jumpP, (o.jumpHeight ?? 0.42));
      if (this.jumpP >= 1) { this.jumpP = -1; this.jumpWait = this.nextJump(); j.spin = 0; }
    }
    const breath = Math.sin(t * 2.1);
    const spins = o.jumpSpin ?? 1;
    return {
      ...REST,
      yaw: this.look.x * 0.62 * turn + j.spin * Math.PI * 2 * spins,
      pitch: this.look.y * 0.32,
      roll: -this.look.x * 0.04 + (j.y ? Math.sin(j.spin * Math.PI) * 0.1 : 0),
      y: j.y,
      sx: j.sx * (1 - 0.008 * breath),
      sy: j.sy * (1 + 0.014 * breath),
      lookX: this.look.x,
      lookY: this.look.y,
      eyeOpen: this.blink.update(dt),
      smile: 0.3,
    };
  }
}

class Working {
  constructor(rand, opts) {
    this.rand = rand;
    this.opts = opts;
    this.blink = new Blinker(rand, 2.5, 6);
    this.hop = 0;
    this.count = Math.floor(rand() * 3);
    this.laugh = -1;
    this.laughWait = 3 + rand() * 4;
    this.extra = -1;
  }
  poke() { this.extra = 0; }
  update(dt, t, pointer) {
    const spin = this.count % 3 === 2;
    const dur = spin ? 0.85 : 0.5;
    this.hop += dt / dur;
    if (this.hop >= 1) { this.hop -= 1; this.count++; }
    const j = jumpCurve(this.hop, spin ? 0.36 : 0.16, { squash: 0.8, stretch: 0.7 });
    let spinAngle = spin ? j.spin * Math.PI * 2 : 0;
    if (this.extra >= 0) {
      this.extra += dt / 0.7;
      if (this.extra >= 1) this.extra = -1;
      else spinAngle += easeInOut(this.extra) * Math.PI * 2;
    }

    let happy = 0;
    if (this.laugh >= 0) {
      this.laugh += dt / 1.1;
      happy = Math.sin(Math.min(1, this.laugh) * Math.PI) ** 0.4;
      if (this.laugh >= 1) { this.laugh = -1; this.laughWait = 4 + this.rand() * 5; }
    } else if ((this.laughWait -= dt) <= 0) this.laugh = 0;

    const lx = pointer ? pointer.x : Math.sin(t * 1.1) * 0.35;
    const ly = pointer ? pointer.y : 0.12 + Math.sin(t * 0.7) * 0.08;
    return {
      ...REST,
      yaw: lx * 0.4 + spinAngle,
      pitch: ly * 0.25,
      roll: Math.sin(t * Math.PI * 2 / 1.0) * 0.06,
      y: j.y,
      sx: j.sx,
      sy: j.sy,
      lookX: lx,
      lookY: ly,
      eyeOpen: happy > 0.5 ? 1 : this.blink.update(dt),
      happy,
      smile: 1,
      mouthOpen: 0.45 + 0.55 * happy + 0.1 * Math.sin(t * 9) * happy,
    };
  }
}

class Sleeping {
  constructor(rand) {
    this.rand = rand;
    this.nod = -1;
    this.nodWait = 4 + rand() * 5;
  }
  poke() { this.nod = 0; }
  update(dt, t) {
    let nod = 0;
    if (this.nod >= 0) {
      this.nod += dt / 1.4;
      nod = Math.sin(Math.min(1, this.nod) * Math.PI) * (1 - this.nod * 0.3);
      if (this.nod >= 1) { this.nod = -1; this.nodWait = 6 + this.rand() * 6; }
    } else if ((this.nodWait -= dt) <= 0) this.nod = 0;
    const breath = Math.sin(t * 1.25);
    return {
      ...REST,
      yaw: -0.12,
      pitch: 0.34 + nod * 0.16 + breath * 0.025,
      roll: 0.1 + nod * 0.03,
      y: 0.05,
      sx: 1.02 - 0.012 * breath,
      sy: 0.97 + 0.03 * breath,
      lookX: -0.1,
      lookY: 0.35,
      eyeOpen: 0,
      smile: 0,
      mouthOpen: 0.25 + 0.15 * breath,
      sleep: 1,
    };
  }
}

const BEHAVIOURS = { default: Idle, working: Working, sleeping: Sleeping };

function blend(a, b, t) {
  const out = {};
  for (const k of KEYS) out[k] = a[k] + (b[k] - a[k]) * t;
  return out;
}

/** Still pose for a state: what reduced-motion and `paused` show. */
export function restPose(state) {
  if (state === 'working') return { ...REST, smile: 1, mouthOpen: 0.45, lookY: 0.1 };
  if (state === 'sleeping') return { ...REST, pitch: 0.3, roll: 0.08, y: 0.05, eyeOpen: 0, smile: 0, mouthOpen: 0.25, lookY: 0.35, sleep: 1 };
  return { ...REST };
}

/**
 * The simulation for one avatar. Call `update(dt)` each frame and read `pose`.
 */
export class BotSim {
  constructor(seed = Math.random(), state = 'default', opts = {}) {
    this.rand = mulberry32(seed);
    this.opts = opts;
    this.time = this.rand() * 100;
    this.state = BEHAVIOURS[state] ? state : 'default';
    this.current = new BEHAVIOURS[this.state](this.rand, opts);
    this.previous = null;
    this.mix = 1;
    this.pointer = null;
    this.pose = this.current.update(0, this.time, null);
  }
  setState(state) {
    if (!BEHAVIOURS[state] || state === this.state) return;
    this.previous = this.current;
    this.state = state;
    this.current = new BEHAVIOURS[state](this.rand, this.opts);
    this.mix = 0;
  }
  setOptions(opts) {
    this.opts = opts;
    if (this.current) this.current.opts = opts;
  }
  /** Look toward a point, in body radii from the body's centre; null to stop. */
  setPointer(p) { this.pointer = p; }
  /** A click: hop and turn round (idle), an extra spin (working), a nod (sleeping). */
  poke() { this.current.poke?.(); }
  update(dt) {
    dt = Math.min(dt, 0.1) * (this.opts.speed ?? 1);
    this.time += dt;
    const p = this.pointer;
    const cur = this.current.update(dt, this.time, p);
    if (this.previous) {
      this.mix += dt / 0.75;
      const prev = this.previous.update(dt, this.time, p);
      if (this.mix >= 1) { this.previous = null; this.mix = 1; this.pose = cur; }
      else {
        // Turns can be whole revolutions apart: blend the shortest way round.
        const d = cur.yaw - prev.yaw;
        prev.yaw += Math.round(d / (Math.PI * 2)) * Math.PI * 2;
        this.pose = blend(prev, cur, easeInOut(this.mix));
      }
    } else this.pose = cur;
    return this.pose;
  }
}

export { clamp };
