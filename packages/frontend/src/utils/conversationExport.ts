/**
 * Full conversation export.
 *
 * Complements the clipboard transcript with real files for colleagues and
 * archives: Markdown, PDF (client-side jspdf, same pattern as artifact
 * export) and DOCX (client-side `docx`, so it works while the backend's
 * office pipeline is unreachable).
 */

export type ConversationExportFormat = 'md' | 'pdf' | 'docx';

export interface ExportableMessage {
  role: string;
  content: string;
  timestamp?: number;
}

export interface ExportableConversation {
  title: string;
  createdAt?: number;
  messages: ExportableMessage[];
}

export function roleLabel(role: string): string {
  if (role === 'user') return 'You';
  if (role === 'assistant' || role === 'system') return 'Assistant';
  if (role === 'tool') return 'Tool';
  return role.charAt(0).toUpperCase() + role.slice(1);
}

/** Keep fences and code verbatim; soften the inline Markdown markers. */
function stripInlineMarkdown(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/^(\s*)[-*]\s+/gm, '$1• ')
    .replace(/[*_~]/g, '');
}

export function buildTranscriptMarkdown(conversation: ExportableConversation): string {
  const date = new Date(conversation.createdAt ?? Date.now()).toLocaleString();
  const lines: string[] = [
    `# ${conversation.title || 'Conversation'}`,
    '',
    `*Exported from PaliMind · ${date}*`,
    '',
    '---',
    '',
  ];
  for (const message of conversation.messages) {
    lines.push(`**${roleLabel(message.role)}:**`, '', stripInlineMarkdown(message.content).trim(), '', '---', '');
  }
  return lines.join('\n');
}

function safeFilename(title: string, extension: string): string {
  const base = title.replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'conversation';
  return `${base}.${extension}`;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function conversationPdf(conversation: ExportableConversation): Promise<Blob> {
  const { jsPDF } = await import('jspdf');
  const pdf = new jsPDF({ unit: 'pt', format: 'a4' });
  const margin = 48;
  const usable = pdf.internal.pageSize.getWidth() - margin * 2;
  const pageHeight = pdf.internal.pageSize.getHeight();
  let y = margin;

  const ensureSpace = (needed: number) => {
    if (y + needed <= pageHeight - margin) return;
    pdf.addPage();
    y = margin;
  };

  pdf.setFont('helvetica', 'bold');
  pdf.setFontSize(18);
  const titleLines = pdf.splitTextToSize(
    conversation.title || 'Conversation',
    usable,
  ) as string[];
  pdf.text(titleLines, margin, y);
  y += titleLines.length * 22 + 6;

  pdf.setFont('helvetica', 'normal');
  pdf.setFontSize(9);
  pdf.text(
    `Exported from PaliMind · ${new Date(conversation.createdAt ?? Date.now()).toLocaleString()}`,
    margin,
    y,
  );
  y += 20;

  for (const message of conversation.messages) {
    ensureSpace(40);
    pdf.setFont('helvetica', 'bold');
    pdf.setFontSize(11.5);
    pdf.text(roleLabel(message.role), margin, y);
    y += 16;

    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(10.5);
    const lineHeight = 14.5;
    for (const raw of stripInlineMarkdown(message.content).split('\n')) {
      const inCode = /^\s{0,3}(```|\t| {4})/.test(raw);
      const wrapped = pdf.splitTextToSize(raw || ' ', usable) as string[];
      for (const part of wrapped) {
        ensureSpace(lineHeight);
        if (inCode) pdf.setFont('courier', 'normal');
        pdf.text(part, margin, y);
        if (inCode) pdf.setFont('helvetica', 'normal');
        y += lineHeight;
      }
    }
    y += 10;
  }

  return pdf.output('blob');
}

async function conversationDocx(conversation: ExportableConversation): Promise<Blob> {
  const docx = await import('docx');
  const { Document, HeadingLevel, Packer, Paragraph, TextRun } = docx;

  const children: InstanceType<typeof Paragraph>[] = [
    new Paragraph({
      text: conversation.title || 'Conversation',
      heading: HeadingLevel.HEADING_1,
    }),
    new Paragraph({
      children: [
        new TextRun({
          text: `Exported from PaliMind · ${new Date(
            conversation.createdAt ?? Date.now(),
          ).toLocaleString()}`,
          italics: true,
          color: '6B7280',
          size: 18,
        }),
      ],
    }),
  ];

  for (const message of conversation.messages) {
    children.push(
      new Paragraph({ text: roleLabel(message.role), heading: HeadingLevel.HEADING_3 }),
    );
    let inCode = false;
    for (const raw of message.content.split('\n')) {
      const line = raw.replace(/\s+$/, '');
      if (line.trim().startsWith('```')) {
        inCode = !inCode;
        continue;
      }
      if (inCode) {
        children.push(
          new Paragraph({
            children: [new TextRun({ text: line || ' ', font: 'Courier New', size: 18 })],
            spacing: { after: 40 },
          }),
        );
        continue;
      }
      const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
      if (bullet) {
        children.push(new Paragraph({ text: bullet[1], bullet: { level: 0 } }));
        continue;
      }
      children.push(new Paragraph({ text: line || ' ', spacing: { after: 80 } }));
    }
  }

  const document = new Document({
    creator: 'Palimind',
    title: conversation.title || 'Conversation',
    sections: [{ properties: {}, children }],
  });
  return Packer.toBlob(document);
}

/** Export a conversation and trigger the browser download. */
export async function exportConversation(
  conversation: ExportableConversation,
  format: ConversationExportFormat,
): Promise<string> {
  if (!conversation.messages.length) throw new Error('Nothing to export yet.');
  switch (format) {
    case 'md': {
      const blob = new Blob([buildTranscriptMarkdown(conversation)], {
        type: 'text/markdown;charset=utf-8',
      });
      const filename = safeFilename(conversation.title, 'md');
      downloadBlob(blob, filename);
      return filename;
    }
    case 'pdf': {
      const blob = await conversationPdf(conversation);
      const filename = safeFilename(conversation.title, 'pdf');
      downloadBlob(blob, filename);
      return filename;
    }
    case 'docx': {
      const blob = await conversationDocx(conversation);
      const filename = safeFilename(conversation.title, 'docx');
      downloadBlob(blob, filename);
      return filename;
    }
    default: {
      const exhaustive: never = format;
      throw new Error(`Unsupported export format: ${String(exhaustive)}`);
    }
  }
}
