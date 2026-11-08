/**
 * Fallback prompt builders for the composer's artifact skills.
 *
 * The Word/PowerPoint skills normally resolve their detailed instructions from
 * the backend skill registry; these local prompts keep the same contract when
 * the API is offline. Each asks for one fenced artifact so the transcript block
 * and preview see exactly one output.
 */

export type CreateArtifactKind =
  | 'document'
  | 'word'
  | 'slides'
  | 'pptx'
  | 'webpage'
  | 'code';

export interface CreateArtifactOption {
  kind: CreateArtifactKind;
  label: string;
  description: string;
  placeholder: string;
  /** When set, the composer downloads a real Office file when the turn ends. */
  officeFormat?: 'docx' | 'pptx';
}

export const CREATE_ARTIFACT_OPTIONS: readonly CreateArtifactOption[] = [
  {
    kind: 'document',
    label: 'Document',
    description: 'A long-form Markdown document with headings and sections.',
    placeholder: 'e.g. A launch plan for our new pricing page',
  },
  {
    kind: 'word',
    label: 'Word document',
    description: 'A formatted .docx file you can open in Word or Google Docs.',
    placeholder: 'e.g. A launch plan for our new pricing page',
    officeFormat: 'docx',
  },
  {
    kind: 'slides',
    label: 'Slide deck',
    description: 'A presentation outline you can preview and export to PowerPoint.',
    placeholder: 'e.g. Q3 results presentation for the leadership team',
  },
  {
    kind: 'pptx',
    label: 'PowerPoint file',
    description: 'A real .pptx deck with a title slide and bullet slides.',
    placeholder: 'e.g. Q3 results presentation for the leadership team',
    officeFormat: 'pptx',
  },
  {
    kind: 'webpage',
    label: 'Web page',
    description: 'A self-contained, responsive HTML page.',
    placeholder: 'e.g. A landing page for a local coffee roaster',
  },
  {
    kind: 'code',
    label: 'Code file',
    description: 'A single runnable source file in the language you name.',
    placeholder: 'e.g. A TypeScript debounce hook',
  },
];

const ARTIFACT_RULES =
  'Return the artifact inside exactly one fenced code block and keep any ' +
  'explanation before the fence short. Do not split it across several fences.';

export function buildArtifactPrompt(kind: CreateArtifactKind, topic: string): string {
  const subject = topic.trim();
  if (!subject) return '';

  if (kind === 'slides' || kind === 'pptx') {
    return [
      `Create a polished presentation slide deck about: ${subject}`,
      '',
      'Format it as a fenced ```slides block.',
      'Rules:',
      '- Start each slide with a single # heading.',
      '- Put 3–5 short, concrete bullet points under each heading.',
      '- Aim for 6–12 slides, including a title slide and a closing slide.',
      '- Separate slides with a blank line (a --- rule is also accepted).',
      '- Do not add speaker notes or raw Markdown tables.',
      kind === 'pptx'
        ? '- The app turns this outline into a downloadable .pptx file automatically; do not call a file-writing tool and keep each bullet one line.'
        : '',
      ARTIFACT_RULES,
    ].filter(Boolean).join('\n');
  }

  if (kind === 'webpage') {
    return [
      `Create a polished, self-contained web page about: ${subject}`,
      '',
      'Format it as a fenced ```html block.',
      'Rules:',
      '- Include a <!doctype html> document with inline CSS and no external assets.',
      '- Make it responsive and accessible (semantic landmarks, alt text, good contrast).',
      '- No JavaScript unless the interaction genuinely needs it.',
      '- Populate it with realistic placeholder content, not lorem ipsum.',
      ARTIFACT_RULES,
    ].join('\n');
  }

  if (kind === 'code') {
    return [
      `Write a complete, production-quality code file for: ${subject}`,
      '',
      'Format it as a single fenced code block with the correct language tag.',
      'Rules:',
      '- Include the necessary imports, types and error handling.',
      '- Add concise comments only where the intent is not obvious.',
      '- Do not invent dependencies that are obviously unavailable.',
      ARTIFACT_RULES,
    ].join('\n');
  }

  return [
    `Create a comprehensive, well-structured document about: ${subject}`,
    '',
    'Format it as a fenced ```markdown block.',
    'Rules:',
    '- Start with a # title, then a short executive summary.',
    '- Use ## sections with clear, descriptive headings.',
    '- Include concrete details, examples and a closing next-steps section.',
    '- Prefer short paragraphs and bullet lists over walls of text.',
    '- Aim for a genuinely useful 800–1500 word document.',
    kind === 'word'
      ? '- The app converts this Markdown into a formatted .docx file automatically; tables and bullet lists are supported, so do not call a file-writing tool.'
      : '',
    ARTIFACT_RULES,
  ].filter(Boolean).join('\n');
}
