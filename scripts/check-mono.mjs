#!/usr/bin/env node
/**
 * check-mono.mjs — non-negotiable design guard.
 *
 * Fails the build (or CI) when the app chrome gains hue, a non-monochrome
 * colour recipe, or an off-scale radius in the core design layers.
 *
 * Strict scope (errors):
 *   design/            tokens
 *   base.css           element + shell baseline
 *   ui/                primitives kit
 *   components/pixel/  pixel layer
 *
 * Tracked scope (warnings): every other component stylesheet. These still
 * contain legacy literals that later phases remove; the count should only go
 * down. Run with `--strict` to promote warnings to errors.
 *
 * Usage:
 *   node scripts/check-mono.mjs
 *   node scripts/check-mono.mjs --strict
 *   node scripts/check-mono.mjs --verbose
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'packages', 'frontend', 'src');

const args = new Set(process.argv.slice(2));
const STRICT = args.has('--strict');
const VERBOSE = args.has('--verbose');

const STRICT_PREFIXES = [
  'design/',
  'ui/',
  'components/pixel/',
];
const STRICT_FILES = new Set(['base.css']);

const EXTENSIONS = new Set(['.css', '.tsx', '.ts']);

/**
 * Modules that generate *content* rather than chrome (exported documents,
 * user artifacts). Content may carry its own colours and typography; only
 * product chrome is policed.
 */
const CONTENT_FILES = new Set(['utils/artifactExport.ts']);

/** CSS named colours that carry hue. Greys, black and white are allowed. */
const NAMED_HUE = [
  'red', 'green', 'blue', 'orange', 'purple', 'violet', 'yellow', 'amber',
  'teal', 'cyan', 'magenta', 'pink', 'brown', 'lime', 'olive', 'navy',
  'maroon', 'gold', 'indigo', 'crimson', 'salmon', 'coral', 'turquoise',
  'lavender', 'beige', 'khaki', 'orchid', 'plum', 'azure', 'chartreuse',
  'fuchsia', 'aqua', 'sienna', 'peru', 'tomato', 'crimson', 'forestgreen',
  'seagreen', 'steelblue', 'royalblue', 'dodgerblue', 'hotpink', 'deeppink',
];

/**
 * MONO v2 radius scale: geometry is rounded, pixel art is not used as shape.
 * 4 is the floor (kbd / tiny tags); 8-20 for real surfaces.
 */
const ALLOWED_RADII = new Set(['0', '1', '4', '8', '10', '12', '16', '20', '999', '9999', '50%']);

const RADIUS_SCALE = /^var\(--radius-(?:xs|sm|md|lg|xl|2xl|card|bubble|full|panel|control)\)$/;

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (entry === 'vendor' || entry === 'assets' || entry === 'node_modules') continue;
      walk(full, out);
    } else if (EXTENSIONS.has(full.slice(full.lastIndexOf('.')))) {
      out.push(full);
    }
  }
  return out;
}

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
}

function isStrict(relPath) {
  if (STRICT_FILES.has(relPath)) return true;
  return STRICT_PREFIXES.some((p) => relPath.startsWith(p));
}

function lineAt(text, index) {
  return text.slice(0, index).split('\n').length;
}

function greyDelta(r, g, b) {
  return Math.max(r, g, b) - Math.min(r, g, b);
}

const problems = [];
const warnings = [];

function report(file, text, index, message, strict) {
  const entry = { file, line: lineAt(text, index), message };
  if (strict) problems.push(entry);
  else warnings.push(entry);
}

const files = walk(SRC);

for (const file of files) {
  const rel = relative(SRC, file).split(sep).join('/');
  if (CONTENT_FILES.has(rel)) continue;
  const strict = isStrict(rel);
  const text = stripComments(readFileSync(file, 'utf8'));
  const isCss = file.endsWith('.css');

  // 1. Hex colours that are not grey.
  for (const m of text.matchAll(/#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g)) {
    let h = m[1];
    if (h.length === 4) h = h.slice(0, 3);
    if (h.length === 8) h = h.slice(0, 6);
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    if (h.length !== 6) continue;
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    if (greyDelta(r, g, b) > 2) {
      report(file, text, m.index, `hue hex ${m[0]} — chrome must stay monochrome`, strict);
    }
  }

  // 2. rgb()/rgba() with chroma.
  for (const m of text.matchAll(/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/g)) {
    const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (greyDelta(r, g, b) > 3) {
      report(file, text, m.index, `hue ${m[0]}…) — chrome must stay monochrome`, strict);
    }
  }

  // 3. hsl()/hsla() with saturation.
  for (const m of text.matchAll(/hsla?\(\s*[\d.]+(?:deg)?[\s,]+([\d.]+)%?/g)) {
    if (Number(m[1]) > 0) {
      report(file, text, m.index, `saturated hsl(${m[1]}%) — chrome must stay monochrome`, strict);
    }
  }

  // 4. Colour keywords used as values (stylesheets only; prose is not a rule).
  if (isCss) {
    const named = NAMED_HUE.join('|');
    for (const m of text.matchAll(new RegExp(`(?:^|[\\s:(,])(${named})(?=[\\s;,)]|$)`, 'gi'))) {
      report(file, text, m.index, `named hue colour "${m[1]}"`, strict);
    }
  }

  // 5. Radii outside 2 / 4 / 6 / 8 (plus circles and the full token).
  if (isCss) {
    for (const m of text.matchAll(/border-radius\s*:\s*([^;}\n]+)/g)) {
      const value = m[1].trim();
      const parts = value.split('/')[0].split(/\s+/).filter(Boolean);
      for (const part of parts) {
        if (RADIUS_SCALE.test(part)) continue;
        const px = part.match(/^(-?[\d.]+)(px|rem)?$/);
        if (!px) continue; // calc(), var() fallbacks etc. are not policed here.
        const raw = px[2] === 'rem' ? Number(px[1]) * 16 : Number(px[1]);
        const key = String(raw);
        if (!ALLOWED_RADII.has(key)) {
          report(file, text, m.index, `off-scale radius ${part} (allowed: 0/1/4/8/10/12/16/20/999/50%)`, strict);
        }
      }
    }
  }

  // 6. Pixel art must not be used as a texture or a border.
  for (const m of text.matchAll(/pixel-dither/g)) {
    report(file, text, m.index, 'pixel-dither is retired — pixel art is motion/icons only', true);
  }

  // 7. Glass and decorative gradients outside the two sanctioned overlays.
  if (isCss) {
    const glassAllowed =
      rel.endsWith('CommandPalette.css') || rel.endsWith('components/layout/layout.css');
    for (const m of text.matchAll(/backdrop-filter\s*:\s*([^;}\n]+)/g)) {
      if (!glassAllowed) {
        report(file, text, m.index, `backdrop-filter ${m[1].trim()} — solid surfaces only`, strict);
      }
    }
    if (strict) {
      for (const m of text.matchAll(/(?:linear|radial|conic)-gradient\(/g)) {
        report(file, text, m.index, 'decorative gradient — the mono layer allows no gradients', strict);
      }
    }
  }
}

function print(list, label) {
  if (list.length === 0) return;
  console.error(`\n${label} (${list.length})`);
  for (const p of list) {
    console.error(`  ${p.file}:${p.line}  ${p.message}`);
  }
}

if (VERBOSE && warnings.length > 0) {
  const byFile = new Map();
  for (const w of warnings) {
    byFile.set(w.file, (byFile.get(w.file) ?? 0) + 1);
  }
  console.log('Legacy literals still to migrate (tracked, not blocking):');
  for (const [file, count] of [...byFile.entries()].sort((a, b) => b[1] - a[1])) {
    console.log(`  ${String(count).padStart(3)}  ${file}`);
  }
}

print(problems, 'MONO CHECK FAILED');

if (STRICT && warnings.length > 0) {
  print(warnings, 'MONO CHECK (strict) — legacy literals promoted to errors');
}

if (problems.length > 0 || (STRICT && warnings.length > 0)) {
  console.error('\nDesign contract: docs/design/mono.md');
  process.exit(1);
}

const tracked = warnings.length;
console.log(
  tracked === 0
    ? 'mono check: clean'
    : `mono check: core clean — ${tracked} legacy literal(s) tracked across ${new Set(warnings.map((w) => w.file)).size} file(s)`,
);
