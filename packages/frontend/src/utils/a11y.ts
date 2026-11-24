/** Lightweight, local accessibility audit for interactive UI checks. */

export interface A11yIssue {
  rule: string;
  message: string;
  target: string;
}

function label(element: Element): string {
  const tag = element.tagName.toLowerCase();
  const id = element.getAttribute('id');
  const parts = [tag];
  if (id) parts.push(`#${id}`);
  const cls = element.getAttribute('class')?.split(/\s+/).filter(Boolean).slice(0, 2).join('.');
  if (cls) parts.push(`.${cls}`);
  return parts.join('');
}

function accessibleName(element: Element, root: ParentNode): string {
  const aria = element.getAttribute('aria-label')?.trim();
  if (aria) return aria;
  const labelledBy = element.getAttribute('aria-labelledby');
  if (labelledBy) {
    const text = labelledBy
      .split(/\s+/)
      .map((id) => root.querySelector(`#${CSS.escape(id)}`)?.textContent?.trim() || '')
      .join(' ')
      .trim();
    if (text) return text;
  }
  if (element instanceof HTMLInputElement) {
    const labels = element.labels ? Array.from(element.labels).map((node) => node.textContent?.trim() || '') : [];
    if (labels.join(' ').trim()) return labels.join(' ').trim();
    if (element.getAttribute('placeholder')?.trim()) return element.getAttribute('placeholder')!.trim();
    if (element.getAttribute('title')?.trim()) return element.getAttribute('title')!.trim();
    return '';
  }
  const text = element.textContent?.replace(/\s+/g, ' ').trim();
  if (text) return text;
  return element.getAttribute('title')?.trim() || '';
}

export function auditAccessibility(root: ParentNode = document): A11yIssue[] {
  const issues: A11yIssue[] = [];
  const interactive = root.querySelectorAll<HTMLElement>(
    'button, a[href], input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"]',
  );
  interactive.forEach((element) => {
    if (!accessibleName(element, root)) {
      issues.push({
        rule: 'accessible-name',
        message: 'Interactive control has no accessible name',
        target: label(element),
      });
    }
  });

  root.querySelectorAll('img').forEach((image) => {
    if (!image.hasAttribute('alt')) {
      issues.push({
        rule: 'image-alt',
        message: 'Image is missing an alt attribute',
        target: label(image),
      });
    }
  });

  const ids = new Map<string, number>();
  root.querySelectorAll('[id]').forEach((element) => {
    const id = element.getAttribute('id') || '';
    if (id) ids.set(id, (ids.get(id) || 0) + 1);
  });
  for (const [id, count] of ids) {
    if (count > 1) {
      issues.push({
        rule: 'duplicate-id',
        message: `Duplicate id "${id}"`,
        target: id,
      });
    }
  }

  root.querySelectorAll('[tabindex]').forEach((element) => {
    const value = Number(element.getAttribute('tabindex'));
    if (Number.isFinite(value) && value > 0) {
      issues.push({
        rule: 'positive-tabindex',
        message: 'Positive tabindex makes keyboard order unpredictable',
        target: label(element),
      });
    }
  });

  root.querySelectorAll('[role="dialog"]').forEach((element) => {
    if (!element.getAttribute('aria-label') && !element.getAttribute('aria-labelledby')) {
      issues.push({
        rule: 'dialog-label',
        message: 'Dialog needs an accessible label',
        target: label(element),
      });
    }
  });

  return issues.slice(0, 100);
}
