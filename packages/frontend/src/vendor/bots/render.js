// The renderer: one frame of an avatar on a 2D canvas. The body is the outline
// stacked through its depth with a cushion profile (thick in the middle,
// rounding off toward front and back), turned by the pose's yaw and pitch.
// Light, fur, the face and anything worn are laid over it.

import { shade, mix, rgba, clamp } from './color.js';
import { mulberry32, smoothstep } from './engine.js';

/** The canvas is this much larger than the avatar's box, so hops never clip. */
export const OVERSCAN = 1.5;
/** Body radius as a fraction of the box. */
export const BODY = 0.4;
/** How far below the box centre the body's centre sits, as a fraction of the box. */
export const RISE = 0.04;

const LAYERS = 15;
const MIN_TURN = 0.14;

const profile = (u) => 0.5 + 0.5 * Math.sqrt(Math.max(0, 1 - u * u));

function shapePath(shape) {
  if (!shape._path) {
    const p = new Path2D();
    shape.points.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y)));
    p.closePath();
    shape._path = p;
  }
  return shape._path;
}

// --- Fur ---------------------------------------------------------------------

const furTiles = new Map();
function furTile(length, density, curl) {
  const key = `${length.toFixed(2)}|${density.toFixed(2)}|${curl.toFixed(2)}`;
  if (furTiles.has(key)) return furTiles.get(key);
  const S = 160;
  const c = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(S, S) : Object.assign(document.createElement('canvas'), { width: S, height: S });
  const g = c.getContext('2d');
  const rand = mulberry32(0.4242);
  const n = Math.round(900 * density);
  g.lineCap = 'round';
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < n; i++) {
      const x = rand() * S, y = rand() * S;
      const a = Math.PI / 2 + (rand() - 0.5) * 1.3;
      const l = (5 + rand() * 9) * length;
      const bend = (rand() - 0.5) * curl * l * 0.8;
      const dark = pass === 0;
      g.strokeStyle = dark ? `rgba(0,0,0,${0.05 + rand() * 0.08})` : `rgba(255,255,255,${0.06 + rand() * 0.12})`;
      g.lineWidth = dark ? 1.4 : 0.9;
      const ox = dark ? 0 : Math.cos(a) * 1.2, oy = dark ? 0 : Math.sin(a) * 1.2;
      for (const dx of [-S, 0, S]) for (const dy of [-S, 0, S]) {
        const x0 = x + dx + ox, y0 = y + dy + oy;
        if (x0 < -20 || x0 > S + 20 || y0 < -20 || y0 > S + 20) continue;
        g.beginPath();
        g.moveTo(x0, y0);
        g.quadraticCurveTo(x0 + Math.cos(a) * l * 0.5 - Math.sin(a) * bend, y0 + Math.sin(a) * l * 0.5 + Math.cos(a) * bend, x0 + Math.cos(a) * l, y0 + Math.sin(a) * l);
        g.stroke();
      }
    }
  }
  furTiles.set(key, c);
  return c;
}

const strandCache = new WeakMap();
function strands(shape, count) {
  let byCount = strandCache.get(shape);
  if (!byCount) strandCache.set(shape, (byCount = new Map()));
  if (byCount.has(count)) return byCount.get(count);
  const rand = mulberry32(0.1337);
  const n = shape.points.length;
  const out = [];
  for (let i = 0; i < count; i++) {
    const idx = rand() * n;
    const i0 = Math.floor(idx) % n, i1 = (i0 + 1) % n, t = idx - Math.floor(idx);
    const [ax, ay] = shape.points[i0], [bx, by] = shape.points[i1];
    const [nx0, ny0] = shape.normals[i0], [nx1, ny1] = shape.normals[i1];
    out.push({
      x: ax + (bx - ax) * t, y: ay + (by - ay) * t,
      nx: nx0 + (nx1 - nx0) * t, ny: ny0 + (ny1 - ny0) * t,
      u: (rand() * 2 - 1) * 0.98,
      len: 0.5 + rand() * 0.6,
      jitter: (rand() - 0.5) * 0.9,
      bend: rand() - 0.5,
      tone: rand(),
    });
  }
  byCount.set(count, out);
  return out;
}

// --- Helpers -----------------------------------------------------------------

// A shared scratch canvas holding the body's complement (everything but the
// body), so an inner shadow is the shadow of that image clipped to the body.
let scratch = null;
function bodyHole(ctx, path, color) {
  const { width, height } = ctx.canvas;
  if (!scratch) scratch = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(width, height) : document.createElement('canvas');
  if (scratch.width < width || scratch.height < height) { scratch.width = Math.max(scratch.width, width); scratch.height = Math.max(scratch.height, height); }
  const g = scratch.getContext('2d');
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalCompositeOperation = 'source-over';
  g.clearRect(0, 0, width, height);
  g.fillStyle = color;
  g.fillRect(0, 0, width, height);
  g.setTransform(ctx.getTransform());
  g.globalCompositeOperation = 'destination-out';
  g.fill(path);
  return scratch;
}

function innerShadow(ctx, path, hole, color, blur, ox, oy, dpr) {
  ctx.save();
  ctx.clip(path);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.shadowColor = color;
  ctx.shadowBlur = blur * dpr;
  ctx.shadowOffsetX = ox * dpr;
  ctx.shadowOffsetY = oy * dpr;
  ctx.drawImage(hole, 0, 0);
  ctx.restore();
}

function sphere(ctx, x, y, r, color, lx, ly) {
  const g = ctx.createRadialGradient(x + lx * r * 0.45, y + ly * r * 0.45, r * 0.05, x, y, r);
  g.addColorStop(0, shade(color, 0.2));
  g.addColorStop(0.55, color);
  g.addColorStop(1, shade(color, -0.22));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
}

function roundRect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// --- The frame -----------------------------------------------------------------

/**
 * Draw one frame.
 * @param {CanvasRenderingContext2D} ctx  a context on a canvas `size * OVERSCAN * dpr` px square
 * @param {object} f  { size, dpr, pose, look, time }
 */
export function drawBot(ctx, { size, dpr = 1, pose, look, time = 0 }) {
  const full = size * OVERSCAN;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, full, full);

  const shape = look.shape;
  const R = size * BODY;
  const D = clamp(look.depth ?? 0.65, 0.2, 2) * 0.5;
  const base = look.color;
  const la = ((look.light ?? (look.shading === 'fabric' ? 295 : 300)) * Math.PI) / 180;
  const lx = Math.sin(la), ly = -Math.cos(la);
  const fabric = look.shading === 'fabric';
  const shadowK = look.shadow ?? (fabric ? 1.15 : 0.6);
  const highK = look.highlight ?? (fabric ? 1.2 : 1.3);
  const rimK = look.rim ?? (fabric ? 0.6 : 0.5);

  const c0 = Math.cos(pose.yaw), s = Math.sin(pose.yaw);
  const c = Math.abs(c0) < MIN_TURN ? (c0 < 0 ? -MIN_TURN : MIN_TURN) : c0;
  const cp = Math.cos(pose.pitch), sp = Math.sin(pose.pitch);
  const facing = c0 * cp;

  const cx = full / 2 + pose.x * R;
  const groundY = full / 2 + RISE * size + shape.bounds.maxY * R;
  const cy = full / 2 + RISE * size + pose.y * R;

  // Floor shadow.
  if (look.floorShadow !== false) {
    const lift = clamp(-pose.y / 0.5, 0, 1);
    const hw = Math.max(-shape.bounds.minX, shape.bounds.maxX) * R;
    ctx.save();
    ctx.translate(full / 2 + pose.x * R, groundY + R * 0.06);
    ctx.scale(1, 0.14);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, hw * (0.95 - lift * 0.3));
    const a = (look.theme === 'dark' ? 0.45 : 0.2) * (1 - lift * 0.6);
    g.addColorStop(0, `rgba(10,8,20,${a})`);
    g.addColorStop(1, 'rgba(10,8,20,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, hw, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  // Body frame: centre, roll, squash about the bottom.
  ctx.translate(cx, cy);
  const pivot = shape.bounds.maxY * R;
  ctx.translate(0, pivot);
  ctx.rotate(pose.roll);
  ctx.scale(pose.sx, pose.sy);
  ctx.translate(0, -pivot);

  // Project a body point (normalised units, z through the depth) to the frame.
  const proj = (x, y, z) => {
    const z1 = -x * s + z * c0;
    return [R * (x * c0 + z * s), R * (y * cp + z1 * sp), z1 * cp - y * sp];
  };

  const extras = shape.extras || {};
  const lightSide = (sign) => clamp(0.6 + 0.4 * sign * lx, 0.2, 1);

  // Side parts: ears / headphone cups, split into behind and in front of the body.
  const sideParts = [];
  if (extras.ears) {
    const w = shape.halfWidthAt(extras.ears.y);
    for (const side of [-1, 1]) {
      const [X, Y, Z] = proj(side * (w + extras.ears.r * 0.25), extras.ears.y, 0);
      sideParts.push({ z: Z, draw: () => {
        const rw = extras.ears.r * R * (0.35 * Math.abs(c0) + Math.abs(s));
        const rh = extras.ears.r * R;
        ctx.save();
        ctx.translate(X, Y);
        const g = ctx.createRadialGradient(-rw * 0.3, -rh * 0.3, 1, 0, 0, Math.max(rw, rh));
        g.addColorStop(0, shade(base, 0.1));
        g.addColorStop(1, shade(base, -0.18 * lightSide(side)));
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.ellipse(0, 0, Math.max(rw, 1), rh, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = shade(base, -0.25);
        ctx.beginPath();
        ctx.ellipse(0, 0, Math.max(rw * 0.5, 0.5), rh * 0.5, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } });
    }
  }
  const acc = look.accessoryColor || '#2b2833';
  const cupY = shape.faceY - 0.02;
  if (look.headphones) {
    const w = shape.halfWidthAt(cupY);
    for (const side of [-1, 1]) {
      const [X, Y, Z] = proj(side * (w + 0.04), cupY, 0);
      sideParts.push({ z: Z, draw: () => {
        const rw = R * (0.09 * Math.abs(c0) + 0.2 * Math.abs(s)) + 1;
        const rh = R * 0.24;
        ctx.save();
        ctx.translate(X, Y);
        const g = ctx.createLinearGradient(-rw, -rh, rw, rh);
        g.addColorStop(0, shade(acc, 0.22));
        g.addColorStop(1, shade(acc, -0.1));
        ctx.fillStyle = g;
        roundRect(ctx, -rw, -rh, rw * 2, rh * 2, rw);
        ctx.fill();
        ctx.fillStyle = 'rgba(255,255,255,0.18)';
        roundRect(ctx, -rw * 0.55, -rh * 0.75, rw * 1.1, rh * 1.5, rw * 0.55);
        ctx.fill();
        ctx.restore();
      } });
    }
  }
  sideParts.sort((a, b) => a.z - b.z);
  sideParts.filter((p) => p.z < 0).forEach((p) => p.draw());

  // Antennae (behind the body; the stalk grows out of the top).
  if (extras.antennae && !look.hat) {
    for (const a of extras.antennae) {
      const top = shape.topAt(a.x, 0.1);
      const [X0, Y0] = proj(a.x, top + 0.12, 0);
      const [X1, Y1] = proj(a.x * 1.1, top - a.len, 0);
      ctx.strokeStyle = shade(base, -0.28);
      ctx.lineWidth = R * 0.06;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(X0, Y0);
      ctx.lineTo(X1, Y1);
      ctx.stroke();
      sphere(ctx, X1, Y1, a.ball * R, look.antennaColor || shade(base, 0.05, -20, 1.4), lx, ly);
    }
  }

  // The body: the outline stacked through the depth, back to front.
  const path = shapePath(shape);
  const body = new Path2D();
  const order = c0 * cp >= 0 ? 1 : -1;
  for (let i = 0; i < LAYERS; i++) {
    const u = order * (-1 + (2 * i) / (LAYERS - 1));
    const k = profile(u);
    const z = u * D;
    body.addPath(path, new DOMMatrix([R * k * c, -R * k * s * sp, 0, R * k * cp, R * z * s, R * z * c0 * sp]));
  }
  const darkC = shade(base, -0.3, 6, 1.15);

  ctx.fillStyle = base;
  ctx.fill(body);

  // Turn shading: the side that shows as the head turns.
  {
    const reveal = Math.abs(s);
    if (reveal > 0.02) {
      const sideDir = s > 0 ? -1 : 1; // the side faces away from where the face moved
      const lit = sideDir * lx;
      const frontX = R * D * s;
      const edge = frontX + sideDir * R * (Math.abs(c) * 0.55 + 0.3);
      const g = ctx.createLinearGradient(frontX, 0, edge + sideDir * R * 0.7, 0);
      const col = lit > 0 ? `rgba(255,255,255,${0.16 * lit * reveal})` : rgba(darkC, 0.5 * -lit * reveal + 0.12 * reveal);
      g.addColorStop(0, 'rgba(0,0,0,0)');
      g.addColorStop(0.45, lit > 0 ? 'rgba(255,255,255,0)' : rgba(darkC, 0.08 * reveal));
      g.addColorStop(1, col);
      ctx.save();
      ctx.clip(body);
      ctx.fillStyle = g;
      ctx.fillRect(-R * 3, -R * 3, R * 6, R * 6);
      ctx.restore();
    }
  }

  if (look.shading !== 'flat') {
    // Fur texture laid over the whole body.
    if (fabric) {
      const fl = look.furLength ?? 1, fd = look.furDensity ?? 1.6, fc = look.furCurl ?? 0.7;
      const tile = furTile(fl, fd, fc);
      const pat = ctx.createPattern(tile, 'repeat');
      if (pat && pat.setTransform) {
        const sc = (R / 95) * 0.55;
        pat.setTransform(new DOMMatrix().translate(R * D * s * 1.4, R * D * sp * c0 * 1.4).scale(sc, sc));
      }
      ctx.save();
      ctx.clip(body);
      ctx.globalAlpha = 0.7;
      ctx.fillStyle = pat;
      ctx.fillRect(-R * 3, -R * 3, R * 6, R * 6);
      ctx.restore();
    }

    const hole = bodyHole(ctx, body, darkC);
    // Shade side: an inner shadow pushed toward the light.
    const blur = R * (fabric ? 0.55 : look.shading === 'smooth' ? 0.7 : 0.45) * (look.spread ?? 1.4) / 1.4;
    innerShadow(ctx, body, hole, rgba(darkC, clamp(0.55 * shadowK, 0, 1)), blur, lx * R * 0.32, ly * R * 0.32, dpr);
    // Ambient occlusion all round the edge for the inflated look.
    innerShadow(ctx, body, hole, rgba(darkC, clamp(0.28 * shadowK, 0, 1)), R * 0.18, 0, 0, dpr);

    // Lit side.
    ctx.save();
    ctx.clip(body);
    const hx = lx * R * 0.42 + R * D * s * 0.8, hy = ly * R * 0.42;
    const spread = look.spread ?? 1.4;
    const g = ctx.createRadialGradient(hx, hy, 0, hx, hy, R * 0.95 * spread);
    const hiA = (fabric ? 0.2 : look.shading === 'plastic' ? 0.3 : 0.26) * highK;
    g.addColorStop(0, `rgba(255,255,255,${clamp(hiA)})`);
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(-R * 3, -R * 3, R * 6, R * 6);
    ctx.restore();

    // Back light / Fresnel rim on the far side from the key.
    if (rimK > 0 && look.shading !== 'smooth') {
      const rimCol = look.shading === 'plastic' ? 'rgba(255,255,255,0.75)' : rgba(shade(base, 0.35), 0.9);
      innerShadow(ctx, body, hole, rimCol, R * (look.shading === 'crisp' ? 0.02 : 0.08) * (0.6 + rimK), -lx * R * 0.05 * (0.5 + rimK), -ly * R * 0.05 * (0.5 + rimK), dpr);
    }

    if (look.shading === 'plastic') {
      // Hot spot and a window reflection.
      ctx.save();
      ctx.clip(body);
      const px = lx * R * 0.48 + R * D * s * 0.9, py = ly * R * 0.5 + R * D * sp;
      const hs = ctx.createRadialGradient(px, py, 0, px, py, R * 0.22 * spread);
      hs.addColorStop(0, `rgba(255,255,255,${clamp(0.85 * highK / 1.3)})`);
      hs.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = hs;
      ctx.fillRect(-R * 3, -R * 3, R * 6, R * 6);
      ctx.translate(px, py);
      ctx.rotate(la + Math.PI / 2);
      ctx.fillStyle = `rgba(255,255,255,${clamp(0.55 * highK / 1.3)})`;
      roundRect(ctx, -R * 0.13, -R * 0.045, R * 0.26, R * 0.09, R * 0.045);
      ctx.fill();
      ctx.restore();
    }
    if (look.shading === 'crisp') {
      ctx.strokeStyle = rgba(darkC, 0.55);
      ctx.lineWidth = Math.max(1, R * 0.025);
      ctx.stroke(body);
    }
  }

  // Fur halo at the silhouette.
  if (fabric) {
    const fl = look.furLength ?? 1;
    const fuzz = look.furFuzz ?? 0.9;
    const grav = look.furGravity ?? 0.9;
    const curl = look.furCurl ?? 0.7;
    const list = strands(shape, Math.round(380 * (look.furDensity ?? 1.6) / 1.6 * (0.4 + fuzz)));
    const paths = [new Path2D(), new Path2D(), new Path2D()];
    const swayT = time * 2.2;
    for (const st of list) {
      const w = Math.sqrt(1 - st.u * st.u);
      const k = profile(st.u);
      // Normal of the cushion at that point, then turned with the head.
      let Nx = st.nx * w, Ny = st.ny * w, Nz = st.u;
      const nx1 = Nx * c0 + Nz * s, nz1 = -Nx * s + Nz * c0;
      const ny1 = Ny * cp + nz1 * sp, nzv = nz1 * cp - Ny * sp;
      const a = Math.abs(nzv);
      if (a > 0.55) continue;
      const [X, Y] = proj(st.x * k * 0.97, st.y * k * 0.97, st.u * D);
      let dx = nx1 + st.jitter * 0.5, dy = ny1 + grav * 0.45 + Math.sin(swayT + st.tone * 6) * 0.04;
      const l = Math.hypot(dx, dy) || 1;
      dx /= l; dy /= l;
      const len = R * 0.055 * fl * st.len * (0.6 + fuzz * 0.6) * (1 - a * 1.2);
      const bx = -dy * st.bend * curl * len * 0.8, by = dx * st.bend * curl * len * 0.8;
      const p = paths[st.tone < 0.45 ? 0 : st.tone < 0.8 ? 1 : 2];
      p.moveTo(X - dx * len * 0.5, Y - dy * len * 0.5);
      p.quadraticCurveTo(X + dx * len * 0.3 + bx, Y + dy * len * 0.3 + by, X + dx * len, Y + dy * len);
    }
    ctx.lineCap = 'round';
    ctx.lineWidth = Math.max(0.6, R * 0.014);
    ctx.strokeStyle = shade(base, -0.06, 0, 0.85);
    ctx.stroke(paths[0]);
    ctx.strokeStyle = shade(base, 0.04, 0, 0.85);
    ctx.stroke(paths[1]);
    ctx.lineWidth = Math.max(0.5, R * 0.01);
    ctx.strokeStyle = shade(base, 0.2, 0, 0.8);
    ctx.stroke(paths[2]);
  }

  // Face, glasses and bow tie ride on the front of the body.
  const faceA = smoothstep((facing - 0.18) / 0.3);
  const fs = shape.faceScale * (look.faceScale ?? 1);
  if (faceA > 0) {
    ctx.save();
    ctx.clip(body);
    ctx.globalAlpha = faceA;
    const fx = pose.lookX * 0.09, fy = shape.faceY + pose.lookY * 0.07;
    const [X, Y] = proj(fx, fy, Math.min(1, D * 1.4));
    ctx.transform(R * c0, -R * s * sp, 0, R * cp, X, Y);
    drawFace(ctx, look, pose, fs, R);
    if (look.glasses && look.glasses !== 'none') drawGlasses(ctx, look.glasses, acc, fs);
    ctx.restore();
    if (look.bowTie) {
      const by = Math.min(shape.faceY + 0.5 * fs, shape.bounds.maxY - 0.2);
      const [bX, bY] = proj(0, by, Math.min(1, D * 1.2));
      ctx.save();
      ctx.globalAlpha = faceA;
      ctx.transform(R * c0, -R * s * sp, 0, R * cp, bX, bY);
      drawBowTie(ctx, acc, fabric);
      ctx.restore();
    }
  }

  sideParts.filter((p) => p.z >= 0).forEach((p) => p.draw());

  // Headphone band over the top of the head.
  if (look.headphones) {
    const w = shape.halfWidthAt(cupY) + 0.04;
    const top = shape.topAt(0) - 0.06;
    ctx.save();
    ctx.lineCap = 'round';
    const band = new Path2D();
    for (let i = 0; i <= 24; i++) {
      const t = Math.PI + (i / 24) * Math.PI;
      const [X, Y] = proj(Math.cos(t) * w, cupY - 0.15 + Math.sin(t) * (cupY - 0.15 - top), 0);
      i ? band.lineTo(X, Y) : band.moveTo(X, Y);
    }
    ctx.lineWidth = R * 0.1;
    ctx.strokeStyle = shade(acc, -0.05);
    ctx.stroke(band);
    ctx.lineWidth = R * 0.035;
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.stroke(band);
    ctx.restore();
  }

  // Hat.
  if (look.hat && look.hat !== 'none') {
    const top = shape.topAt(0, 0.22);
    const [X, Y] = proj(0, top + 0.12, D * 0.15);
    const hw = clamp(shape.halfWidthAt(top + 0.2, 0.06) * 0.78, 0.34, 0.62);
    ctx.save();
    ctx.translate(X, Y);
    ctx.rotate(-pose.pitch * 0.1);
    ctx.scale(R, R * (0.75 + 0.25 * cp));
    drawHat(ctx, look.hat, acc, hw, s, lx, time);
    ctx.restore();
  }

  // Z's while asleep.
  if (pose.sleep > 0.05) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const ink = look.theme === 'dark' ? '#e9e6ff' : '#6b6880';
    for (let i = 0; i < 3; i++) {
      const p = ((time / 2.6 + i / 3) % 1);
      const a = Math.sin(p * Math.PI) * pose.sleep;
      const fz = size * (0.09 + p * 0.07);
      ctx.fillStyle = rgba(ink, a * 0.85);
      ctx.font = `700 ${fz}px ui-rounded, system-ui, sans-serif`;
      ctx.fillText('z', full / 2 + R * (0.6 + p * 0.45) + Math.sin(p * 6 + i) * R * 0.08, full / 2 - R * (0.55 + p * 0.85));
    }
  }
}

// --- Face --------------------------------------------------------------------

function drawFace(ctx, look, pose, fs, R) {
  const ink = look.ink;
  const gap = 0.25 * fs * (look.eyeGap ?? 1);
  const rx = 0.085 * fs * (look.eyeSize ?? 1), ry = 0.118 * fs * (look.eyeSize ?? 1);
  const lw = Math.max(0.035 * fs, 1.2 / R);
  ctx.fillStyle = ink;
  ctx.strokeStyle = ink;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  const happy = pose.happy > 0.5;
  for (const side of [-1, 1]) {
    const ex = side * gap;
    if (pose.sleep > 0.5 && pose.eyeOpen < 0.2) {
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.arc(ex, -ry * 0.25, rx * 1.05, Math.PI * 0.15, Math.PI * 0.85);
      ctx.stroke();
    } else if (happy) {
      ctx.lineWidth = lw * 1.1;
      ctx.beginPath();
      ctx.arc(ex, ry * 0.35, rx * 1.05, Math.PI * 1.15, Math.PI * 1.85);
      ctx.stroke();
    } else if (pose.eyeOpen < 0.18) {
      ctx.lineWidth = lw;
      ctx.beginPath();
      ctx.moveTo(ex - rx, 0);
      ctx.quadraticCurveTo(ex, ry * 0.25, ex + rx, 0);
      ctx.stroke();
    } else {
      const h = ry * pose.eyeOpen;
      ctx.beginPath();
      ctx.ellipse(ex, 0, rx, h, 0, 0, Math.PI * 2);
      ctx.fill();
      if (look.eyeShine !== false && pose.eyeOpen > 0.5) {
        ctx.save();
        ctx.fillStyle = 'rgba(255,255,255,0.9)';
        ctx.beginPath();
        ctx.arc(ex + rx * 0.32 + pose.lookX * rx * 0.15, -h * 0.38, rx * 0.3, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }
  }

  if (look.blush) {
    ctx.save();
    ctx.fillStyle = rgba(look.blushColor || '#ff6f91', 0.35);
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(side * (gap + rx * 0.9), ry * 1.35, rx * 0.95, rx * 0.5, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  if (look.face === 'mouth') {
    const my = ry * 1.55;
    const w = 0.1 * fs;
    ctx.lineWidth = lw;
    if (pose.smile < 0.15) {
      ctx.beginPath();
      ctx.ellipse(0, my + 0.01 * fs, 0.03 * fs, (0.022 + 0.03 * pose.mouthOpen) * fs, 0, 0, Math.PI * 2);
      ctx.fill();
    } else if (pose.mouthOpen < 0.3) {
      ctx.beginPath();
      ctx.moveTo(-w * 0.75, my);
      ctx.quadraticCurveTo(0, my + 0.08 * fs * pose.smile, w * 0.75, my);
      ctx.stroke();
    } else {
      const depth = (0.05 + 0.09 * pose.mouthOpen) * fs;
      ctx.beginPath();
      ctx.moveTo(-w, my - 0.01 * fs);
      ctx.quadraticCurveTo(0, my + 0.02 * fs, w, my - 0.01 * fs);
      ctx.quadraticCurveTo(w * 0.85, my + depth * 1.25, 0, my + depth * 1.3);
      ctx.quadraticCurveTo(-w * 0.85, my + depth * 1.25, -w, my - 0.01 * fs);
      ctx.closePath();
      ctx.fill();
      ctx.save();
      ctx.clip();
      ctx.fillStyle = '#ff7a8a';
      ctx.beginPath();
      ctx.ellipse(0, my + depth * 1.3, w * 0.55, depth * 0.55, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }
}

function drawGlasses(ctx, kind, acc, fs) {
  const gap = 0.25 * fs;
  const r = 0.155 * fs;
  ctx.lineWidth = 0.035 * fs;
  ctx.strokeStyle = acc;
  ctx.lineJoin = 'round';
  const lens = (x) => {
    if (kind === 'round') { ctx.beginPath(); ctx.arc(x, 0, r, 0, Math.PI * 2); }
    else if (kind === 'square') roundRect(ctx, x - r * 1.05, -r * 0.85, r * 2.1, r * 1.7, r * 0.35);
    else { // shades
      ctx.beginPath();
      ctx.moveTo(x - r * 1.15, -r * 0.7);
      ctx.lineTo(x + r * 1.15, -r * 0.7);
      ctx.quadraticCurveTo(x + r * 1.1, r * 0.95, x, r * 0.85);
      ctx.quadraticCurveTo(x - r * 1.1, r * 0.95, x - r * 1.15, -r * 0.7);
      ctx.closePath();
    }
  };
  for (const side of [-1, 1]) {
    const x = side * gap;
    lens(x);
    if (kind === 'shades') {
      const g = ctx.createLinearGradient(0, -r, 0, r);
      g.addColorStop(0, '#2c2a3a');
      g.addColorStop(1, '#0d0c14');
      ctx.fillStyle = g;
      ctx.fill();
    } else {
      ctx.fillStyle = 'rgba(210,230,255,0.18)';
      ctx.fill();
    }
    ctx.stroke();
    // Reflection.
    ctx.save();
    lens(x);
    ctx.clip();
    ctx.strokeStyle = 'rgba(255,255,255,0.55)';
    ctx.lineWidth = 0.025 * fs;
    ctx.beginPath();
    ctx.moveTo(x - r * 0.6, r * 0.1);
    ctx.lineTo(x - r * 0.05, -r * 0.6);
    ctx.stroke();
    ctx.restore();
    // Temple arm.
    ctx.beginPath();
    ctx.moveTo(x + side * r * (kind === 'round' ? 1 : 1.1), -r * 0.2);
    ctx.lineTo(x + side * r * 1.9, -r * 0.35);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(-gap + r * 0.95, -r * 0.15);
  ctx.quadraticCurveTo(0, -r * 0.45, gap - r * 0.95, -r * 0.15);
  ctx.stroke();
}

function drawBowTie(ctx, acc, fabric) {
  const w = 0.24, h = 0.13;
  const g = ctx.createLinearGradient(0, -h, 0, h);
  g.addColorStop(0, shade(acc, 0.22));
  g.addColorStop(1, shade(acc, -0.1));
  ctx.fillStyle = g;
  for (const side of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(side * w * 0.5, -h * 1.4, side * w, -h);
    ctx.quadraticCurveTo(side * w * 1.1, 0, side * w, h);
    ctx.quadraticCurveTo(side * w * 0.5, h * 1.4, 0, 0);
    ctx.fill();
    ctx.strokeStyle = fabric ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.3)';
    ctx.lineWidth = 0.012;
    ctx.beginPath();
    ctx.moveTo(side * w * 0.2, -h * 0.25);
    ctx.quadraticCurveTo(side * w * 0.55, -h * 0.75, side * w * 0.9, -h * 0.6);
    ctx.stroke();
  }
  ctx.fillStyle = shade(acc, 0.08);
  roundRect(ctx, -0.05, -0.065, 0.1, 0.13, 0.035);
  ctx.fill();
}

// --- Hats --------------------------------------------------------------------

function drawHat(ctx, kind, acc, hw, s, lx, time) {
  const lit = (col, x0, x1) => {
    const g = ctx.createLinearGradient(x0, 0, x1, 0);
    g.addColorStop(0, lx < 0 ? shade(col, 0.16) : shade(col, -0.12));
    g.addColorStop(1, lx < 0 ? shade(col, -0.14) : shade(col, 0.14));
    return g;
  };
  if (kind === 'beanie') {
    const h = hw * 0.95;
    ctx.fillStyle = lit(acc, -hw, hw);
    ctx.beginPath();
    ctx.ellipse(0, -0.04, hw * 1.02, h, 0, Math.PI, Math.PI * 2);
    ctx.fill();
    // Knit rows.
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(0, -0.04, hw * 1.02, h, 0, Math.PI, Math.PI * 2);
    ctx.clip();
    ctx.strokeStyle = 'rgba(0,0,0,0.12)';
    ctx.lineWidth = 0.012;
    for (let i = -6; i <= 6; i++) {
      const x = i * hw * 0.16 + s * hw * 0.25;
      ctx.beginPath();
      ctx.moveTo(x, -0.04);
      ctx.quadraticCurveTo(x * 0.7, -h * 0.7, x * 0.2, -h * 1.05);
      ctx.stroke();
    }
    ctx.restore();
    // Cuff.
    ctx.fillStyle = lit(shade(acc, 0.06), -hw, hw);
    roundRect(ctx, -hw * 1.1, -0.1, hw * 2.2, 0.2, 0.08);
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.16)';
    ctx.lineWidth = 0.014;
    for (let i = -9; i <= 9; i++) {
      const x = i * hw * 0.115 + ((s * hw * 0.3) % (hw * 0.115));
      if (Math.abs(x) > hw * 1.05) continue;
      ctx.beginPath();
      ctx.moveTo(x, -0.07);
      ctx.lineTo(x, 0.07);
      ctx.stroke();
    }
    // Pompom.
    const pr = hw * 0.32;
    ctx.save();
    ctx.translate(0, -h - pr * 0.45);
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * Math.PI * 2;
      ctx.fillStyle = i % 3 ? shade(acc, 0.12) : shade(acc, 0.28);
      ctx.beginPath();
      ctx.arc(Math.cos(a) * pr * 0.55, Math.sin(a) * pr * 0.55, pr * 0.55, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  } else if (kind === 'party') {
    const h = hw * 1.7, b = hw * 0.8;
    ctx.save();
    ctx.rotate(-0.12);
    const cone = new Path2D();
    cone.moveTo(-b, 0);
    cone.lineTo(0, -h);
    cone.lineTo(b, 0);
    cone.quadraticCurveTo(0, 0.1, -b, 0);
    ctx.fillStyle = lit(acc, -b, b);
    ctx.fill(cone);
    ctx.save();
    ctx.clip(cone);
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    for (let i = -4; i < 6; i++) {
      const y = -i * h * 0.22 + ((s * 0.15) % 0.2);
      ctx.beginPath();
      ctx.moveTo(-b * 2, y);
      ctx.lineTo(b * 2, y - h * 0.3);
      ctx.lineTo(b * 2, y - h * 0.3 - h * 0.07);
      ctx.lineTo(-b * 2, y - h * 0.07);
      ctx.fill();
    }
    ctx.restore();
    // Foil trim + tinsel.
    ctx.strokeStyle = '#ffd34d';
    ctx.lineWidth = 0.05;
    ctx.beginPath();
    ctx.moveTo(-b, 0);
    ctx.quadraticCurveTo(0, 0.1, b, 0);
    ctx.stroke();
    for (let i = 0; i < 18; i++) {
      const a = (i / 18) * Math.PI * 2;
      ctx.fillStyle = ['#ffd34d', '#ff6f91', '#7ad7ff'][i % 3];
      ctx.beginPath();
      ctx.arc(Math.cos(a) * 0.07, -h + Math.sin(a) * 0.07, 0.055, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  } else if (kind === 'crown') {
    const b = hw * 0.95, h = hw * 0.85;
    const gold = '#f2c14e';
    const crown = new Path2D();
    crown.moveTo(-b, 0.04);
    crown.lineTo(-b * 1.05, -h);
    crown.lineTo(-b * 0.5, -h * 0.5);
    crown.lineTo(0, -h * 1.15);
    crown.lineTo(b * 0.5, -h * 0.5);
    crown.lineTo(b * 1.05, -h);
    crown.lineTo(b, 0.04);
    crown.quadraticCurveTo(0, 0.12, -b, 0.04);
    crown.closePath();
    const g = ctx.createLinearGradient(-b, -h, b, 0.1);
    g.addColorStop(0, '#fff1b8');
    g.addColorStop(0.35, gold);
    g.addColorStop(0.7, '#c98a1b');
    g.addColorStop(1, '#f5d070');
    ctx.fillStyle = g;
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#b07514';
    ctx.lineWidth = 0.025;
    ctx.fill(crown);
    ctx.stroke(crown);
    for (const [x, y] of [[-b * 1.05, -h], [0, -h * 1.15], [b * 1.05, -h]]) sphere(ctx, x, y, 0.065, '#fff3c4', lx, -1);
    const gems = [['#e8395b', 0], ['#3b82f6', -b * 0.55], ['#22c55e', b * 0.55]];
    for (const [col, x] of gems) {
      const gx = x + s * 0.06;
      if (Math.abs(gx) > b * 0.9) continue;
      sphere(ctx, gx, -h * 0.18, 0.07, col, lx, -1);
    }
  } else if (kind === 'beret') {
    ctx.save();
    ctx.rotate(-0.2);
    const w = hw * 1.25;
    ctx.fillStyle = lit(acc, -w, w);
    ctx.beginPath();
    ctx.ellipse(-0.05, -0.12, w, 0.24, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = shade(acc, -0.25);
    ctx.lineWidth = 0.05;
    ctx.beginPath();
    ctx.ellipse(-0.05, -0.04, w * 0.85, 0.12, 0, 0.1, Math.PI - 0.1);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(0,0,0,0.12)';
    ctx.lineWidth = 0.012;
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2 + s;
      ctx.beginPath();
      ctx.moveTo(-0.05, -0.18);
      ctx.lineTo(-0.05 + Math.cos(a) * w * 0.9, -0.14 + Math.sin(a) * 0.2);
      ctx.stroke();
    }
    ctx.strokeStyle = shade(acc, -0.1);
    ctx.lineWidth = 0.04;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(-0.02, -0.34);
    ctx.quadraticCurveTo(0.02, -0.44, 0.08, -0.46);
    ctx.stroke();
    ctx.restore();
  } else if (kind === 'tophat') {
    const b = hw * 0.75, h = hw * 1.45;
    ctx.fillStyle = lit(acc, -b, b);
    ctx.beginPath();
    ctx.ellipse(0, -0.02, b * 1.55, 0.12, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(-b, -0.04);
    ctx.lineTo(-b * 0.95, -h);
    ctx.ellipse(0, -h, b * 0.95, 0.1, 0, Math.PI, 0);
    ctx.lineTo(b, -0.04);
    ctx.ellipse(0, -0.04, b, 0.09, 0, 0, Math.PI);
    ctx.fill();
    ctx.fillStyle = shade(acc, 0.25);
    ctx.beginPath();
    ctx.ellipse(0, -h, b * 0.95, 0.1, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#c0394b';
    ctx.fillRect(-b * 0.985, -0.26, b * 1.97, 0.14);
  }
}
