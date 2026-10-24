// The avatar controller: owns a canvas, resolves options into a look, runs the
// simulation on a shared animation loop and handles pointer play.

import { adjust, autoInk } from './color.js';
import { BotSim, restPose, STATES } from './engine.js';
import { drawBot, OVERSCAN, BODY, RISE } from './render.js';
import { presets, getShape, shapeFromSvgPath } from './shapes.js';

export const DEFAULTS = Object.freeze({
  type: 'clover',
  state: 'default',
  face: 'eyes',
  size: 64,
  shading: 'fabric',
  brightness: 1,
  saturation: 1,
  depth: 0.65,
  hat: 'none',
  glasses: 'none',
  headphones: false,
  bowTie: false,
  blush: false,
  speed: 1,
  paused: false,
  interactive: true,
  theme: 'auto',
});

export const SHADINGS = ['fabric', 'plastic', 'smooth', 'crisp', 'flat'];
export const HATS = ['none', 'beanie', 'party', 'crown', 'beret', 'tophat'];
export const GLASSES = ['none', 'round', 'square', 'shades'];

const STATE_WORDS = { default: 'idle', working: 'working', sleeping: 'sleeping' };

function pageTheme() {
  if (typeof document === 'undefined') return 'light';
  const t = document.documentElement.dataset.theme;
  if (t === 'dark' || t === 'light') return t;
  return typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Resolve options into what the renderer needs. */
export function resolveLook(opts) {
  const o = { ...DEFAULTS, ...opts };
  const preset = presets[o.type] || presets.circle;
  const shape = (o.path && shapeFromSvgPath(o.path, o.type)) || getShape(o.type);
  const color = adjust(o.color || preset.color, { brightness: o.brightness, saturation: o.saturation });
  return {
    ...o,
    shape,
    color,
    ink: o.ink || autoInk(color),
    label: o.label || `${preset.label} bot`,
    theme: o.theme === 'auto' ? pageTheme() : o.theme,
  };
}

// --- Shared loop ------------------------------------------------------------

const live = new Set();
let raf = 0, last = 0;
function frame(now) {
  const dt = last ? (now - last) / 1000 : 1 / 60;
  last = now;
  for (const bot of live) bot._tick(dt);
  raf = live.size ? requestAnimationFrame(frame) : 0;
  if (!raf) last = 0;
}
function startLoop(bot) {
  live.add(bot);
  if (!raf && typeof requestAnimationFrame !== 'undefined') raf = requestAnimationFrame(frame);
}
function stopLoop(bot) { live.delete(bot); }

let pointer = null;
let pointerBound = false;
function bindPointer() {
  if (pointerBound || typeof window === 'undefined') return;
  pointerBound = true;
  window.addEventListener('pointermove', (e) => { pointer = { x: e.clientX, y: e.clientY }; }, { passive: true });
  document.addEventListener('pointerleave', () => { pointer = null; });
  window.addEventListener('blur', () => { pointer = null; });
}

const reducedMotion = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

// --- The avatar -------------------------------------------------------------

export class BotAvatar {
  /**
   * @param {HTMLElement|HTMLCanvasElement} target  a canvas, or an element to put one in
   * @param {object} options
   */
  constructor(target, options = {}) {
    this.options = { ...DEFAULTS, ...options };
    this._ownCanvas = !(target instanceof HTMLCanvasElement);
    if (!this._ownCanvas) this.canvas = target;
    else {
      this.canvas = document.createElement('canvas');
      target.appendChild(this.canvas);
    }
    this.canvas.setAttribute('role', 'img');
    this.ctx = this.canvas.getContext('2d');
    this.sim = new BotSim(this.options.seed ?? Math.random(), this.options.state, this.options);
    this.visible = true;
    this.look = resolveLook(this.options);
    this._onClick = () => {
      if (!this.options.interactive) return;
      this.sim.poke();
      this.canvas.dispatchEvent(new CustomEvent('bot-poke', { bubbles: true }));
    };
    this.canvas.addEventListener('click', this._onClick);
    if (typeof IntersectionObserver !== 'undefined') {
      this._io = new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; this._sync(); });
      this._io.observe(this.canvas);
    }
    bindPointer();
    this._layout();
    this._sync();
    this.draw();
  }

  /** Update options; anything not passed is kept. */
  set(options) {
    const prev = this.options;
    this.options = { ...prev, ...options };
    if (options.state && options.state !== this.sim.state) this.sim.setState(options.state);
    this.sim.setOptions(this.options);
    this.look = resolveLook(this.options);
    if (options.size !== undefined && options.size !== prev.size) this._layout();
    this._sync();
    this.draw();
    return this;
  }

  setState(state) { return this.set({ state }); }
  /** Hop and turn round, as a click does. */
  poke() { this.sim.poke(); }

  _layout() {
    const size = this.options.size;
    const dpr = Math.min(2, (typeof devicePixelRatio !== 'undefined' && devicePixelRatio) || 1);
    const full = size * OVERSCAN;
    this.dpr = dpr;
    this.canvas.width = Math.round(full * dpr);
    this.canvas.height = Math.round(full * dpr);
    Object.assign(this.canvas.style, {
      width: `${full}px`,
      height: `${full}px`,
      margin: `${-(full - size) / 2}px`,
      display: 'block',
      cursor: this.options.interactive ? 'pointer' : '',
    });
  }

  _animating() {
    return this.visible && !this.options.paused && !reducedMotion();
  }

  _sync() {
    const label = this.options['aria-label'] || `${this.look.label}, ${STATE_WORDS[this.options.state] || 'idle'}`;
    this.canvas.setAttribute('aria-label', label);
    if (this._animating()) startLoop(this);
    else stopLoop(this);
  }

  _tick(dt) {
    if (this.options.interactive && pointer) {
      const r = this.canvas.getBoundingClientRect();
      const R = this.options.size * BODY;
      const dx = (pointer.x - (r.left + r.width / 2)) / R;
      const dy = (pointer.y - (r.top + r.height / 2 + RISE * this.options.size)) / R;
      const d = Math.hypot(dx, dy);
      this.sim.setPointer(d < 5 && d > 0.05 ? { x: Math.max(-1, Math.min(1, dx / 2.5)), y: Math.max(-1, Math.min(1, dy / 2.5)) } : null);
    } else this.sim.setPointer(null);
    this.sim.update(dt);
    this.draw();
  }

  /** The pose drawn right now. */
  get pose() {
    if (!this._animating()) {
      const still = this.options.paused && this.sim.pose ? this.sim.pose : restPose(this.options.state);
      return this.options.pose ? { ...still, ...this.options.pose } : still;
    }
    return this.sim.pose;
  }

  draw() {
    drawBot(this.ctx, { size: this.options.size, dpr: this.dpr, pose: this.pose, look: this.look, time: this.sim.time });
  }

  /** PNG data URL of the current frame, cropped to the avatar's box unless `full`. */
  toDataURL({ full = false, scale = 2 } = {}) {
    const size = this.options.size;
    const c = document.createElement('canvas');
    const total = size * OVERSCAN;
    const box = full ? total : size * 1.2;
    c.width = c.height = Math.round(box * scale);
    const tmp = document.createElement('canvas');
    tmp.width = tmp.height = Math.round(total * scale);
    drawBot(tmp.getContext('2d'), { size, dpr: scale, pose: this.pose, look: this.look, time: this.sim.time });
    const off = ((total - box) / 2) * scale;
    c.getContext('2d').drawImage(tmp, -off, -off);
    return c.toDataURL('image/png');
  }

  destroy() {
    stopLoop(this);
    this._io?.disconnect();
    this.canvas.removeEventListener('click', this._onClick);
    if (this._ownCanvas) this.canvas.remove();
  }
}

/** Create an avatar in `target` (an element or a canvas). */
export function createBot(target, options) {
  if (typeof target === 'string') target = document.querySelector(target);
  return new BotAvatar(target, options);
}

export { STATES };
