import { formatMarkdown } from './markdown';

function escapeHtml(input: string): string {
  return input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function safeName(title: string): string {
  return (title || 'canvas').replace(/[^\w.-]+/g, '_').slice(0, 80) || 'canvas';
}

export function exportMarkdown(title: string, content: string): void {
  triggerDownload(new Blob([content], { type: 'text/markdown;charset=utf-8' }), `${safeName(title)}.md`);
}

const DOC_STYLE = `
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 760px; margin: 40px auto; padding: 0 24px; line-height: 1.65; color: #1a1a1a; }
  h1, h2, h3 { font-family: -apple-system, Segoe UI, Roboto, sans-serif; line-height: 1.3; }
  pre { background: #f4f4f4; padding: 12px 14px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9em; }
  blockquote { border-left: 3px solid #ccc; margin: 0; padding-left: 14px; color: #555; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  .hljs { color: #24292e; background: transparent; }
  .hljs-comment, .hljs-quote { color: #6a737d; font-style: italic; }
  .hljs-keyword, .hljs-selector-tag, .hljs-literal, .hljs-name { color: #d73a49; }
  .hljs-built_in, .hljs-type, .hljs-title.class_ { color: #22863a; }
  .hljs-string, .hljs-title, .hljs-section, .hljs-attribute, .hljs-regexp { color: #032f62; }
  .hljs-number, .hljs-symbol, .hljs-variable, .hljs-meta { color: #005cc5; }
  .hljs-title.function_, .hljs-function .hljs-title { color: #6f42c1; }
  .hljs-attr, .hljs-property, .hljs-params { color: #005cc5; }
`;

/** Open a print-ready window; the user chooses "Save as PDF". */
export function exportPdf(title: string, content: string): boolean {
  const win = window.open('', '_blank');
  if (!win) return false;
  win.document.write(
    `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${DOC_STYLE}</style></head>` +
      `<body>${formatMarkdown(content)}</body></html>`,
  );
  win.document.close();
  const print = () => {
    win.focus();
    win.print();
  };
  if (win.document.readyState === 'complete') setTimeout(print, 200);
  else win.onload = () => setTimeout(print, 200);
  return true;
}

/**
 * Lightweight Word export: Word opens HTML content saved with a .doc
 * extension. Avoids bundling a full OOXML writer for this use case.
 */
export function exportDoc(title: string, content: string): void {
  const html =
    `<html xmlns:o="urn:schemas-microsoft-com:office:office" ` +
    `xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">` +
    `<head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${DOC_STYLE}</style></head>` +
    `<body>${formatMarkdown(content)}</body></html>`;
  triggerDownload(new Blob([html], { type: 'application/msword' }), `${safeName(title)}.doc`);
}
