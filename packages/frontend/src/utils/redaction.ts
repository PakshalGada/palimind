/** Detect and redact common secrets before previewing or sharing context. */

export type RedactionKind = 'email' | 'bearer' | 'api-key' | 'private-key' | 'phone';

export interface RedactionMatch {
  kind: RedactionKind;
  value: string;
}

const PATTERNS: { kind: RedactionKind; regex: RegExp; placeholder: string }[] = [
  {
    kind: 'private-key',
    regex: /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
    placeholder: '[REDACTED:PRIVATE KEY]',
  },
  {
    kind: 'bearer',
    regex: /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b/g,
    placeholder: '[REDACTED:BEARER TOKEN]',
  },
  {
    kind: 'api-key',
    regex: /\b(?:sk|pk|ghp|gho|ghs|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{10,}\b/g,
    placeholder: '[REDACTED:API KEY]',
  },
  {
    kind: 'api-key',
    regex: /\bAKIA[0-9A-Z]{16}\b/g,
    placeholder: '[REDACTED:AWS KEY]',
  },
  {
    kind: 'email',
    regex: /\b[\w.+-]+@[\w-]+\.[A-Za-z]{2,}\b/g,
    placeholder: '[REDACTED:EMAIL]',
  },
  {
    kind: 'phone',
    regex: /(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]\d{3,4}(?:[\s.-]\d{2,4})?(?!\d)/g,
    placeholder: '[REDACTED:PHONE]',
  },
];

export function redactText(input: string): { text: string; matches: RedactionMatch[] } {
  let text = String(input || '');
  const matches: RedactionMatch[] = [];
  for (const pattern of PATTERNS) {
    text = text.replace(pattern.regex, (value) => {
      matches.push({ kind: pattern.kind, value });
      return pattern.placeholder;
    });
  }
  return { text, matches };
}

export function redactionCounts(matches: RedactionMatch[]): Record<RedactionKind, number> {
  const counts: Record<RedactionKind, number> = {
    email: 0,
    bearer: 0,
    'api-key': 0,
    'private-key': 0,
    phone: 0,
  };
  for (const match of matches) counts[match.kind] += 1;
  return counts;
}
