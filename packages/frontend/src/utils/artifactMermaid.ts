/**
 * Shared Mermaid loader for the artifact preview and exports.
 *
 * `mermaid.initialize` replaces the whole site config, so every caller has to
 * go through one place or they silently undo each other's settings.
 */

type MermaidApi = typeof import('mermaid').default;
export type MermaidTheme = 'dark' | 'light';

let mermaidPromise: Promise<MermaidApi> | null = null;
let configuredTheme: MermaidTheme | null = null;

export function currentMermaidTheme(): MermaidTheme {
  return document.documentElement.classList.contains('light-mode') ? 'light' : 'dark';
}

async function getMermaid(theme: MermaidTheme): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid')
      .then(module => module.default)
      .catch(error => {
        // Allow a retry after a failed chunk load instead of caching the error.
        mermaidPromise = null;
        throw error;
      });
  }
  const mermaid = await mermaidPromise;
  if (configuredTheme !== theme) {
    mermaid.initialize({
      startOnLoad: false,
      theme: theme === 'light' ? 'default' : 'dark',
      securityLevel: 'strict',
      fontFamily: 'var(--font-sans)',
      // Without this Mermaid leaves its "Syntax error" bomb graphic appended
      // to <body> on every failed render.
      suppressErrorRendering: true,
    });
    configuredTheme = theme;
  }
  return mermaid;
}

/** Render a diagram to SVG markup, always removing Mermaid's temp nodes. */
export async function renderMermaid(
  id: string,
  code: string,
  theme: MermaidTheme = currentMermaidTheme(),
): Promise<string> {
  const mermaid = await getMermaid(theme);
  try {
    const { svg } = await mermaid.render(id, code);
    return svg;
  } finally {
    document.getElementById(`d${id}`)?.remove();
    document.getElementById(`i${id}`)?.remove();
  }
}
