# PaliMind — MONO / OS design contract

**Status:** Phases 0–7 complete. This document is the source of truth for the
redesign. If code and this document disagree, the document wins and the code is
the bug.

---

## 1. Direction

**A monochrome instrument panel with an editorial soul and a tiny pixel
heartbeat.** Black canvas, sharp white type, visible hairlines, compact
controls, one small pixel moment per surface.

The app has four rules that override taste:

1. **One ink, one paper.** Every colour is a step on a neutral ramp. Chrome has
   no hue — not for success, not for danger, not for charts.
2. **Structure is a line, not a shadow.** Resting surfaces have a 1px rule and
   no shadow. Shadows belong to transient overlays only.
3. **Emphasis is inversion.** White block on black (dark) or black block on
   white (light) is the strongest signal available. There is exactly one
   primary action per surface.
4. **Pixel detail is a signature, not a theme.** Pixel art lives in motion and
   iconography only. Geometry, surfaces and type stay rounded and editorial:
   a square control is not "pixel", it is just boxy.

### What content may keep

User content — images, PDFs, generated artifacts, charts inside documents — keeps
its own colours inside the mono frame. The rule applies to product chrome and
system state only.

---

## 2. Decisions (resolved)

| Question | Decision | Why |
|---|---|---|
| Theme model | **Dual mono** — dark default, light is first-class | Already shipped in `ThemeProvider`; paper mode is not an inverted afterthought |
| Pixel mascot | **Abstract pixel mark + glyphs**; no mascot | Keeps the chrome quiet |
| Pixel font | **No** | Identity comes from graphics and motion; body copy stays Inter / Universal Sans |
| Content colours | **Keep** | Respect user media |
| Projects / Artifacts | **Promote to full views** (Phase 2) | The modal/panel split is the biggest IA problem |
| Home view | **Yes** (Phase 2) | A calm starting surface, not a marketing page |
| Pixel placements | **Six recurring spots** — brand, working status, streaming caret, indexing meter, empty-state glyph, one-shot success stamp | Everything else is static |
| No-colour rule | **Strict for chrome and system state** | Content is excepted, documented above |

---

## 3. Tokens

Everything lives in `packages/frontend/src/design/tokens.css`. Components must
not hard-code colour, radius, shadow or duration.

### 3.1 Colour

A single mirrored ramp, declared per theme:

```
--mono-0  … --mono-16
```

`--mono-0` is the paper end, `--mono-16` the ink end, **in both themes**. Light
mode mirrors the ramp, so one semantic layer stays theme-agnostic. Only the
surface ladder and the paper/ink anchors are overridden per theme.

Semantic layer (theme-independent, declared once):

| Token | Meaning |
|---|---|
| `--bg`, `--bg-sunken` | canvas |
| `--surface`, `--surface-2`, `--surface-3` | panel → raised → overlay |
| `--surface-hover`, `--surface-active` | interaction states |
| `--line`, `--line-subtle`, `--line-strong` | 1px construction |
| `--ink`, `--ink-secondary`, `--ink-muted`, `--ink-faint` | type ramp |
| `--inverse-bg`, `--inverse-ink` | emphasis / primary action |
| `--signal`, `--quiet`, `--alert` | status, always greyscale |
| `--focus` | focus ring (pure white / pure black) |

The legacy `--color-*` API and the older `--bg-color`, `--panel-bg`,
`--text-main`, `--border-color` aliases are all mapped onto this layer. New code
uses `--color-*`; `--text-*` aliases are transitional.

### 3.2 Type

Nine steps. Only three weights: **400 / 550 / 700**.

| Token | Size / line | Use |
|---|---|---|
| `--type-2xs` | 10 / 12 | uppercase meta, counters |
| `--type-xs` | 11 / 15 | labels, chips |
| `--type-sm` | 12.5 / 18 | secondary UI |
| `--type-base` | 14 / 22 | body, controls |
| `--type-md` | 16 / 24 | chat text, inputs |
| `--type-lg` | 20 / 28 | section titles |
| `--type-xl` | 24 / 32 | page titles |
| `--type-2xl` | 32 / 38 | hero, empty states |
| `--type-3xl` | 40 / 46 | rare marketing moments |

**Floor:** no chrome text below **10px**, and 10px is reserved for uppercase
mono meta and counters. Everything else is ≥ 11px. The old 8.5–9.5px labels are
gone as surfaces migrate.

`--font-weight-semibold` is retained as an alias that resolves to **550**; the
scale has no 600.

### 3.3 Radii (v2)

```
--radius-xs   4px   kbd, tiny tags
--radius-sm   8px   buttons, inputs, menu items, rows
--radius-md  10px   chips, segmented, small panels
--radius-lg  12px   cards, composer, panels
--radius-xl  16px   dialogs, sheets
--radius-2xl 20px   hero panels, large media
--radius-full 999px pills, avatars, switches, dots
```

Geometry is rounded by default. **Pixel art is not used as shape**: square
switches, 2px tags and pixel ticks are retired. Circles are allowed for avatars,
switches, dots, meters, spinners and scrollbar thumbs.

### 3.4 Shadow (v2)

```
--shadow-xs   0 1px 2px      resting cards
--shadow-sm   0 2px 8px      menus, hovered cards
--shadow-md   0 10px 28px    composer, popovers
--shadow-lg   0 24px 64px    dialogs, drawers
```

One shadow per surface, never stacked. Cards separate with surface + `--shadow-xs`
instead of a 1px outline.

### 3.5 Motion

```
--dur-1  80ms    press, hover
--dur-2  120ms   menus, hovers
--dur-3  180ms   dialogs, route changes
--dur-4  240ms   drawers
--ease-out       cubic-bezier(0.2, 0.8, 0.2, 1)
--ease-in-out    cubic-bezier(0.45, 0, 0.2, 1)
--ease-pixel     steps(4, end)
```

`--ease-spring` and `--ease-entrance` are deprecated aliases that resolve to
`--ease-out`. Nothing in the app may bounce.

---

## 4. Selective hairlines (v2)

MONO v1 flipped every border visible, which produced a wireframe. v2 reverses
that over-correction while keeping structure:

- **Structural edges keep a hairline:** top bar, sidebar, page-header rule,
  table row rules.
- **Resting surfaces do not:** buttons, inputs, cards, nav items and the composer
  use a fill and `--shadow-xs` instead.
- **Focus and selection** may draw a 1px ink edge or a ring.

When a surface looks too busy, remove the container before adding a border.

---

## 5. Cascade contract (do not reorder)

`main.tsx` imports **`index.css` (Tailwind + shadcn) before `App.css`
(tokens + kit)**.

Why: Tailwind v4 emits default `:root` variables (`--font-sans`, `--text-*`,
`--radius-*`, `--shadow-*`, `--ease-*`, `--color-border`). Imported last, they
silently overrode Palimind's tokens — the app was rendering with the system font
stack, 16px `--text-base`, Tailwind radii and Tailwind shadows. Loading the
design system afterwards makes the tokens authoritative.

If you change the import order, verify with:

```bash
grep -o -- '--font-sans:[^;]*' packages/frontend/dist/assets/main-*.css
```

The **last** occurrence must be the Inter/Universal Sans stack.

---

## 6. Status without colour

| Status | Glyph | Treatment |
|---|---|---|
| idle | hollow square | muted text |
| working | 2×2 pixel checker (`PixelLoader`) | ink + animated pixel |
| waiting | outlined diamond | dotted 1px rule + slow blink |
| paused | two bars | 50% opacity |
| scheduled | corner tick | static mono label |
| error | pixel cross | strong 1px rule + explicit label |
| success | pixel check | static / one-shot stamp |

A status is always **glyph + label**. Colour alone never carries meaning.

---

## 7. Pixel layer

`packages/frontend/src/components/pixel/`

| Component | Role |
|---|---|
| `PixelGlyph` | static 8×8 SVG sprite from a string map |
| `PixelLoader` | 4-frame corner-walk, `steps(1)`, 800ms |
| `PixelMeter` | 8-cell progress / indexing meter |
| `PixelCaret` | streaming cursor, `steps(2)`, 1s |
| `PixelStamp` | one-shot check/cross, 240ms |
| `pixel.css` | timing, pause conditions, dither field |

Rules enforced in `pixel.css`:

- `shapeRendering="crispEdges"`, integer coordinates, merged horizontal runs.
- `currentColor` only.
- Loops pause when the tab is hidden (`html[data-pixel-paused="true"]`).
- `prefers-reduced-motion` and `html[data-pixel-accents="off"]` resolve to a
  static frame, never a blank space.
- No layout shift: every glyph has intrinsic width/height.

**Where pixel detail is allowed (v2):**

| Allowed | Role |
|---|---|
| Brand mark + boot assemble | icon / one-shot |
| `PixelLoader` | live status animation |
| `PixelCaret` | streaming animation |
| `PixelTicker` | thinking animation |
| `PixelSweep` | indexing animation |
| `PixelBurst` / `PixelStamp` | one-shot acknowledgement |
| Status glyphs | icons |
| Empty-state glyph | icon |
| `PixelMeter` | animated progress indicator |

**Retired:** `pixel-dither` textures, pixel nav ticks, square switches, square
send buttons, 2px tags and any pixel-shaped control. The guard fails on
`pixel-dither`.

---

## 8. Guard

```bash
npm run check:mono        # strict: any violation fails
npm run audit:mono        # inventory: type, radii, shadows, motion, hue
```

The whole stylesheet tree is now in strict scope: hue, off-scale radii,
`backdrop-filter` outside the two sanctioned overlays, and gradients all fail
the build. `--strict` is the default; there is no warning tier left.

The guard also rejects `backdrop-filter` outside `CommandPalette.css` and the
mobile sidebar scrim, and gradients in strict files.

---

## 9. Phase status

| Phase | Scope | State |
|---|---|---|
| 0 | Audit, decisions, guard, tokens frozen | **done** |
| 1 | Tokens, type, base, primitives, pixel layer | **done** |
| 2 | Shell, top bar, navigation, view state | **done** |
| 3 | Chat surface, composer, empty state | **done** |
| 4 | Agents suite | **done** (reskin + suite tabs) |
| 5 | Knowledge, Projects, Artifacts, Research | **done** (promoted to views) |
| 6 | Overlays + settings appearance | **done** |
| 7 | Polish, responsive, a11y, strict guard | **done** |
| v2 | De-boxing, single CommandBar, expanded pixel motion | **done** |

### What changed in Phases 2–7

- `AppView` is now `home | chat | agents | knowledge | projects | artifacts |
  research`. Projects, Artifacts and Research are routed views, not modals.
- `AppLayout` gained a persistent 48px top bar (`AppTopBar`) with the pixel
  brand mark, breadcrumb, live status, command palette trigger, inbox and theme.
- `ViewHeader` is the single page header: eyebrow, title, subtitle, actions and
  inverted tabs. Home, Projects, Artifacts, Research and Knowledge use it.
- Hash deep links (`#chat`, `#projects`, …) so a reload keeps context.
- Chat: inverted user turns, 760px reading column, solid bordered composer,
  pixel-caret streaming, dither + prompt rows in the empty state, slim chat head.
- Settings gained **Appearance → Motion & pixel accents** (system / full /
  reduced motion, accents on/off), stored per device.
- Overlays are solid paper: no blur outside the palette and mobile scrim, dialogs
  at radius 8 with a hard overlay shadow.

### v2 changes

- **One chrome band.** `CommandBar` replaces `AppTopBar` + `ViewHeader` +
  the agents tab bar + the chat head. It holds identity, breadcrumb, contextual
  tabs (Agents) or the command field, live status and one primary action.
- **Content titles** moved to `PageTitle`: large, editorial, scrolls with the
  page, no background or rule.
- **De-boxed kit:** 4/8/10/12/16/20 radii, soft fills instead of resting
  outlines, pill switch, underline tabs, soft segmented control, circular send.
- **Pixel motion kit grew:** `PixelTicker`, `PixelSweep`, `PixelBurst`,
  `PixelAssemble`, `useOneShot`. Dither textures and pixel nav ticks are gone.
- The command palette anchors under the bar instead of floating mid-screen.

### Current inventory (after Phase 7)

```
Stylesheets                       58
CSS lines                         16,276
Chromatic hex values remaining    0
Files using backdrop-filter       2  (command palette + mobile sidebar)
Legacy literals tracked           0
Pixel motion components           9  (glyph, loader, meter, caret, stamp,
                                    ticker, sweep, burst, assemble)
```

The literal counters in `audit:mono` still include token references
(`var(--type-sm)` etc.); the guard, not the counter, is the source of truth.
