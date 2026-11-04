#!/usr/bin/env node
/**
 * mono-audit.mjs — inventory of the design surface.
 *
 * Prints the numbers the design contract is measured against: stylesheet
 * size, type/radius/shadow drift, motion budget and monochrome violations.
 * Read-only; safe to run at any time.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'packages', 'frontend', 'src');

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (['vendor', 'assets', 'node_modules'].includes(entry)) continue;
      walk(full, out);
    } else if (full.endsWith('.css')) {
      out.push(full);
    }
  }
  return out;
}

const files = walk(SRC);
const styles = files.map((f) => ({
  file: relative(SRC, f),
  text: readFileSync(f, 'utf8'),
}));
const all = styles.map((s) => s.text).join('\n');

const count = (re) => (all.match(re) ?? []).length;
const tally = (re, group = 1) => {
  const map = new Map();
  for (const m of all.matchAll(re)) {
    const key = m[group];
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
};

const fontSize = tally(/font-size\s*:\s*([^;}]+)/g);
const radius = tally(/border-radius\s*:\s*([^;}]+)/g);
const shadows = tally(/box-shadow\s*:\s*([^;}]+)/g);

const reducedMotionFiles = styles.filter((s) => s.text.includes('prefers-reduced-motion')).length;
const backdropFiles = styles.filter((s) => s.text.includes('backdrop-filter')).length;

const hueHex = all.match(/#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/g) ?? [];
const chromatic = new Set();
for (const hex of hueHex) {
  let h = hex.slice(1);
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  if (Math.max(r, g, b) - Math.min(r, g, b) > 2) chromatic.add(hex);
}

const line = (label, value) => console.log(`${label.padEnd(38)} ${value}`);

console.log('\nPALIMIND — MONO AUDIT\n');
line('Stylesheets', files.length);
line('CSS lines', all.split('\n').length.toLocaleString());
line('Distinct literal font sizes', fontSize.length);
line('Distinct literal radii', radius.length);
line('Distinct literal box-shadows', shadows.length);
line('Animations declared', count(/animation\s*:/g));
line('Files with reduced-motion guard', `${reducedMotionFiles} / ${files.length}`);
line('Files using backdrop-filter', backdropFiles);
line('Chromatic hex values remaining', chromatic.size);

console.log('\nFont sizes (literal, top 15)');
for (const [v, n] of fontSize.slice(0, 15)) console.log(`  ${String(n).padStart(3)}  ${v}`);

console.log('\nRadii (literal, top 15)');
for (const [v, n] of radius.slice(0, 15)) console.log(`  ${String(n).padStart(3)}  ${v}`);

console.log('\nMonochrome violations');
if (chromatic.size === 0) console.log('  none');
else for (const hex of chromatic) console.log(`  ${hex}`);
console.log('');
