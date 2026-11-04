import { memo, useMemo } from 'react';
import { captionFor, type Caption } from './activity/caption';
import { useActivitySelector } from './activity/hooks';
import { isTerminal, type ActivityState } from './activity/model';
import { useOptionalActivitySurface } from '../stream/context';

const captionSelector = (state: ActivityState | null): string => {
  if (!state || state.status === 'idle' || isTerminal(state.status)) return '';
  return JSON.stringify(captionFor(state));
};

/**
 * The one status line inside the composer shell, above the textarea. It shows
 * the same computed caption the activity panel renders, so sending and
 * working never look like nothing is happening. It truncates to the row and
 * never wraps; the waiting-for-approval caption is a button that scrolls to
 * the pending receipt.
 */
export const ComposerCaption = memo(function ComposerCaption() {
  const surface = useOptionalActivitySurface();
  // Serialize once per store tick; re-renders only when the caption itself
  // changes — never per token.
  const raw = useActivitySelector(surface?.store ?? null, captionSelector);
  const caption: Caption | null = useMemo(() => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Caption;
    } catch {
      return null;
    }
  }, [raw]);

  if (!caption) return null;

  const approval = caption.kind === 'approval';
  const line = (
    <>
      <span className="act-caption-dot" aria-hidden="true" data-live={caption.live} />
      <span className="act-caption-line__text">{caption.text}</span>
    </>
  );

  return (
    <div className="act act-caption-line" role="status" aria-live="polite">
      {approval ? (
        <button
          type="button"
          className="act-caption-line__button"
          onClick={() => {
            document
              .querySelector('[data-pending-approval]')
              ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }}
        >
          {line}
        </button>
      ) : (
        line
      )}
    </div>
  );
});
