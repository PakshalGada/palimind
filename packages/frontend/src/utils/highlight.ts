import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import python from 'highlight.js/lib/languages/python';
import rust from 'highlight.js/lib/languages/rust';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import './highlight.css';

const LANGUAGES: [string, Parameters<typeof hljs.registerLanguage>[1]][] = [
  ['bash', bash],
  ['c', c],
  ['cpp', cpp],
  ['css', css],
  ['diff', diff],
  ['dockerfile', dockerfile],
  ['go', go],
  ['ini', ini],
  ['java', java],
  ['javascript', javascript],
  ['json', json],
  ['markdown', markdown],
  ['python', python],
  ['rust', rust],
  ['sql', sql],
  ['typescript', typescript],
  ['xml', xml],
  ['yaml', yaml],
];

let registered = false;
function ensureRegistered(): void {
  if (registered) return;
  for (const [name, language] of LANGUAGES) hljs.registerLanguage(name, language);
  registered = true;
}

export interface HighlightResult {
  html: string;
  language: string;
}

function escapeCode(code: string): string {
  return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Highlight source code to themed HTML. Falls back to escaped plain text when
 * the language is unknown or highlighting throws.
 *
 * `autoDetect` runs highlight.js' language guesser, which is deliberately
 * expensive (it scores every registered grammar). During streaming the same
 * growing block is re-highlighted many times, so callers turn it off there.
 */
export function highlightCode(
  code: string,
  lang?: string,
  { autoDetect = true }: { autoDetect?: boolean } = {},
): HighlightResult {
  ensureRegistered();
  const language = (lang || '').trim().toLowerCase().split(/\s+/)[0];
  try {
    if (language && hljs.getLanguage(language)) {
      return { html: hljs.highlight(code, { language, ignoreIllegals: true }).value, language };
    }
    // Untagged blocks: only guess for small, settled snippets.
    if (autoDetect && code.length <= 2000) {
      const auto = hljs.highlightAuto(code);
      return { html: auto.value, language: auto.language || language || 'text' };
    }
    return { html: escapeCode(code), language: language || 'text' };
  } catch {
    return { html: escapeCode(code), language: language || 'text' };
  }
}
