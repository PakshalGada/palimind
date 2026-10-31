import { formatMarkdown } from './markdown';
import {
  artifactFilename,
  type ArtifactType,
  type ExportFormat,
} from './artifacts';

export interface ExportableArtifact {
  type: ArtifactType;
  language: string;
  title: string;
  content: string;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function isMarkdownLike(type: ArtifactType): boolean {
  return (
    type === 'markdown' ||
    type === 'document' ||
    type === 'table' ||
    type === 'slide-outline'
  );
}

function fenceLanguage(artifact: ExportableArtifact): string {
  if (artifact.type === 'html') return 'html';
  if (artifact.type === 'svg') return 'svg';
  if (artifact.type === 'mermaid') return 'mermaid';
  if (artifact.type === 'react') return 'jsx';
  return artifact.language || 'text';
}

export function artifactToMarkdown(artifact: ExportableArtifact): string {
  if (isMarkdownLike(artifact.type)) {
    return artifact.type === 'slide-outline'
      ? `# ${artifact.title}\n\n${artifact.content}\n`
      : `${artifact.content}\n`;
  }
  return `# ${artifact.title}\n\n\`\`\`${fenceLanguage(artifact)}\n${artifact.content}\n\`\`\`\n`;
}

function pageShell(title: string, body: string, dark: boolean): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}</title>
<style>
  :root { color-scheme: ${dark ? 'dark' : 'light'}; }
  body {
    margin: 0;
    padding: 40px;
    font: 15px/1.65 Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: ${dark ? '#09090b' : '#ffffff'};
    color: ${dark ? '#f4f4f5' : '#18181b'};
  }
  main { max-width: 860px; margin: 0 auto; }
  pre { padding: 16px; border-radius: 10px; overflow: auto; background: ${dark ? '#18181b' : '#f4f4f5'}; }
  code { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.9em; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid ${dark ? '#3f3f46' : '#d4d4d8'}; padding: 7px 10px; text-align: left; }
  h1, h2, h3 { line-height: 1.25; }
  img, svg { max-width: 100%; height: auto; }
</style>
</head>
<body><main>${body}</main></body>
</html>`;
}

async function artifactToHtml(artifact: ExportableArtifact, dark: boolean): Promise<string> {
  if (artifact.type === 'html') {
    return artifact.content.includes('<html')
      ? artifact.content
      : pageShell(artifact.title, artifact.content, dark);
  }
  if (artifact.type === 'svg') {
    return pageShell(artifact.title, artifact.content, dark);
  }
  if (artifact.type === 'mermaid') {
    try {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({
        startOnLoad: false,
        theme: dark ? 'dark' : 'default',
        securityLevel: 'strict',
      });
      const { svg } = await mermaid.render(`export-${Date.now()}-${Math.random().toString(36).slice(2)}`, artifact.content);
      return pageShell(artifact.title, svg, dark);
    } catch {
      return pageShell(
        artifact.title,
        `<h1>${escapeHtml(artifact.title)}</h1><pre><code>${escapeHtml(artifact.content)}</code></pre>`,
        dark,
      );
    }
  }
  if (isMarkdownLike(artifact.type)) {
    const body = artifact.type === 'slide-outline'
      ? formatMarkdown(`# ${artifact.title}\n\n${artifact.content}`)
      : formatMarkdown(artifact.content);
    return pageShell(artifact.title, body, dark);
  }
  return pageShell(
    artifact.title,
    `<h1>${escapeHtml(artifact.title)}</h1><pre><code class="language-${escapeHtml(fenceLanguage(artifact))}">${escapeHtml(artifact.content)}</code></pre>`,
    dark,
  );
}

function textForPdf(artifact: ExportableArtifact): string[] {
  const plain = artifact.content
    .replace(/```[^\n]*\n?/g, '')
    .replace(/```/g, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/[*_`]/g, '');
  return plain.split('\n');
}

async function exportPdf(artifact: ExportableArtifact): Promise<Blob> {
  const { jsPDF } = await import('jspdf');
  const pdf = new jsPDF({ unit: 'pt', format: 'a4' });
  const margin = 48;
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const usable = pageWidth - margin * 2;
  let y = margin;

  pdf.setFont('helvetica', 'bold');
  pdf.setFontSize(18);
  const titleLines = pdf.splitTextToSize(artifact.title || 'Artifact', usable) as string[];
  pdf.text(titleLines, margin, y);
  y += titleLines.length * 22 + 14;

  pdf.setFont('helvetica', 'normal');
  pdf.setFontSize(10.5);
  const lineHeight = 15;
  for (const line of textForPdf(artifact)) {
    const wrapped = pdf.splitTextToSize(line || ' ', usable) as string[];
    for (const part of wrapped) {
      if (y > pageHeight - margin) {
        pdf.addPage();
        y = margin;
      }
      pdf.text(part, margin, y);
      y += lineHeight;
    }
  }
  return pdf.output('blob');
}

function markdownParagraphs(
  artifact: ExportableArtifact,
  docx: typeof import('docx'),
): InstanceType<typeof docx.Paragraph>[] {
  const { HeadingLevel, Paragraph, TextRun } = docx;
  const out: InstanceType<typeof Paragraph>[] = [
    new Paragraph({
      text: artifact.title || 'Artifact',
      heading: HeadingLevel.HEADING_1,
    }),
  ];
  let inCode = false;
  for (const raw of artifact.content.split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (line.trim().startsWith('```')) {
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      out.push(
        new Paragraph({
          children: [new TextRun({ text: line || ' ', font: 'Courier New', size: 18 })],
          spacing: { after: 40 },
        }),
      );
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      const levels = [
        HeadingLevel.HEADING_1,
        HeadingLevel.HEADING_2,
        HeadingLevel.HEADING_3,
        HeadingLevel.HEADING_4,
      ] as const;
      out.push(new Paragraph({ text: heading[2], heading: levels[level - 1] }));
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      out.push(new Paragraph({ text: bullet[1], bullet: { level: 0 } }));
      continue;
    }
    out.push(new Paragraph({ text: line || ' ', spacing: { after: 80 } }));
  }
  return out;
}

async function exportDocx(artifact: ExportableArtifact): Promise<Blob> {
  const docx = await import('docx');
  const { Document, Packer } = docx;
  const document = new Document({
    creator: 'Palimind',
    title: artifact.title,
    sections: [{ properties: {}, children: markdownParagraphs(artifact, docx) }],
  });
  return Packer.toBlob(document);
}

interface SlideSpec {
  title: string;
  bullets: string[];
}

function parseSlideOutline(artifact: ExportableArtifact): SlideSpec[] {
  const slides: SlideSpec[] = [];
  let current: SlideSpec | null = null;
  const startSlide = (title: string): SlideSpec => {
    const spec = { title: title || `Slide ${slides.length + 1}`, bullets: [] as string[] };
    slides.push(spec);
    current = spec;
    return spec;
  };

  if (artifact.type !== 'slide-outline') {
    startSlide(artifact.title || 'Artifact');
    artifact.content
      .split('\n')
      .map(line => line.replace(/^#{1,6}\s*/, '').replace(/^\s*[-*]\s+/, '').trim())
      .filter(Boolean)
      .forEach(line => {
        if (current && current.bullets.length < 12) current.bullets.push(line.slice(0, 220));
        else startSlide('Continued');
      });
    return slides;
  }

  for (const raw of artifact.content.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (/^---+$/.test(line)) {
      current = null;
      continue;
    }
    const heading =
      line.match(/^#{1,4}\s+(.+)$/)?.[1] ||
      line.match(/^slide\s*\d+\s*[:.-]\s*(.+)$/i)?.[1];
    if (heading) {
      startSlide(heading.replace(/[*_`]/g, '').slice(0, 200));
      continue;
    }
    if (!current) current = startSlide(artifact.title || 'Slide');
    const bullet = line.replace(/^\s*[-*•]\s+/, '').replace(/^\d+[.)]\s+/, '');
    current.bullets.push(bullet.slice(0, 220));
  }
  if (slides.length === 0) startSlide(artifact.title || 'Artifact');
  return slides;
}

async function exportPptx(artifact: ExportableArtifact): Promise<Blob> {
  const PptxGenJS = (await import('pptxgenjs')).default;
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'Palimind';
  pptx.title = artifact.title;
  const dark = document.documentElement.classList.contains('light-mode') === false;

  const cover = pptx.addSlide();
  cover.background = { color: dark ? '09090B' : 'FFFFFF' };
  cover.addText(artifact.title || 'Artifact', {
    x: 0.7,
    y: 2.4,
    w: 11.9,
    h: 1.1,
    fontSize: 34,
    bold: true,
    color: dark ? 'F4F4F5' : '18181B',
    fontFace: 'Arial',
  });
  cover.addText('Generated with Palimind', {
    x: 0.7,
    y: 5.6,
    w: 11.9,
    h: 0.5,
    fontSize: 13,
    color: dark ? 'A1A1AA' : '52525B',
    fontFace: 'Arial',
  });

  for (const spec of parseSlideOutline(artifact)) {
    const slide = pptx.addSlide();
    slide.background = { color: dark ? '09090B' : 'FFFFFF' };
    slide.addText(spec.title, {
      x: 0.6,
      y: 0.45,
      w: 12.1,
      h: 0.8,
      fontSize: 26,
      bold: true,
      color: dark ? 'F4F4F5' : '18181B',
      fontFace: 'Arial',
    });
    if (spec.bullets.length) {
      slide.addText(
        spec.bullets.map(text => ({ text, options: { bullet: true } })),
        {
          x: 0.8,
          y: 1.5,
          w: 11.7,
          h: 5,
          fontSize: 17,
          color: dark ? 'D4D4D8' : '3F3F46',
          fontFace: 'Arial',
          breakLine: true,
        },
      );
    }
  }

  return (await pptx.write({ outputType: 'blob' })) as Blob;
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  for (const raw of text.split('\n')) {
    if (!raw.trim()) {
      lines.push('');
      continue;
    }
    let line = '';
    for (const word of raw.split(/\s+/)) {
      const next = line ? `${line} ${word}` : word;
      if (ctx.measureText(next).width > maxWidth && line) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    }
    if (line) lines.push(line);
  }
  return lines;
}

async function textToPng(artifact: ExportableArtifact): Promise<Blob> {
  const dark = !document.documentElement.classList.contains('light-mode');
  const scale = 2;
  const width = 1200;
  const padding = 70;
  const lineHeight = 27;
  const canvas = document.createElement('canvas');
  canvas.width = width * scale;
  canvas.height = 1600 * scale;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas is not available');
  ctx.scale(scale, scale);
  ctx.fillStyle = dark ? '#09090b' : '#ffffff';
  ctx.fillRect(0, 0, width, 1600);

  ctx.fillStyle = dark ? '#f4f4f5' : '#18181b';
  ctx.font = '600 30px Inter, ui-sans-serif, system-ui, sans-serif';
  ctx.fillText(artifact.title || 'Artifact', padding, padding + 20);

  ctx.fillStyle = dark ? '#a1a1aa' : '#52525b';
  ctx.font = '16px "IBM Plex Mono", ui-monospace, monospace';
  const lines = wrapText(ctx, artifact.content, width - padding * 2);
  let y = padding + 70;
  for (const line of lines) {
    if (y > 1600 - padding) break;
    ctx.fillText(line, padding, y);
    y += lineHeight;
  }
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error('Could not render PNG'));
    }, 'image/png');
  });
}

async function svgToPng(svg: string): Promise<Blob> {
  const dark = !document.documentElement.classList.contains('light-mode');
  const source = svg.trim().startsWith('<svg')
    ? svg
    : `<!doctype html><html><body>${svg}</body></html>`;
  const image = new Image();
  image.decoding = 'async';
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error('Could not load SVG for PNG export'));
    image.src = url;
  });
  const width = image.naturalWidth || 1200;
  const height = image.naturalHeight || 900;
  const scale = 2;
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas is not available');
  ctx.scale(scale, scale);
  ctx.fillStyle = dark ? '#09090b' : '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(image, 0, 0, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error('Could not render PNG'));
    }, 'image/png');
  });
}

async function exportPng(artifact: ExportableArtifact): Promise<Blob> {
  if (artifact.type === 'svg') return svgToPng(artifact.content);
  if (artifact.type === 'mermaid') {
    try {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({
        startOnLoad: false,
        theme: document.documentElement.classList.contains('light-mode') ? 'default' : 'dark',
        securityLevel: 'strict',
      });
      const { svg } = await mermaid.render(
        `png-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        artifact.content,
      );
      return svgToPng(svg);
    } catch {
      return textToPng(artifact);
    }
  }
  return textToPng(artifact);
}

export async function exportArtifactAs(
  artifact: ExportableArtifact,
  format: ExportFormat,
): Promise<{ blob: Blob; filename: string }> {
  const dark = !document.documentElement.classList.contains('light-mode');
  switch (format) {
    case 'md': {
      const blob = new Blob([artifactToMarkdown(artifact)], {
        type: 'text/markdown;charset=utf-8',
      });
      return { blob, filename: artifactFilename(artifact, 'md') };
    }
    case 'html': {
      const html = await artifactToHtml(artifact, dark);
      return {
        blob: new Blob([html], { type: 'text/html;charset=utf-8' }),
        filename: artifactFilename(artifact, 'html'),
      };
    }
    case 'pdf':
      return { blob: await exportPdf(artifact), filename: artifactFilename(artifact, 'pdf') };
    case 'docx':
      return { blob: await exportDocx(artifact), filename: artifactFilename(artifact, 'docx') };
    case 'pptx':
      return { blob: await exportPptx(artifact), filename: artifactFilename(artifact, 'pptx') };
    case 'png':
      return { blob: await exportPng(artifact), filename: artifactFilename(artifact, 'png') };
    default:
      throw new Error(`Unsupported export format: ${format}`);
  }
}
