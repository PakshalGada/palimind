import { useId, type ReactNode } from 'react';
import { Icon } from '../icons';

export function Disclosure({
  summary,
  children,
  open,
  onOpenChange,
  className = '',
  summaryClassName = '',
  contentClassName = '',
  chevron = true,
  disabled = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
  summaryClassName?: string;
  contentClassName?: string;
  chevron?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        className={summaryClassName}
        aria-expanded={open}
        aria-controls={id}
        disabled={disabled}
        onClick={() => onOpenChange(!open)}
      >
        {summary}
        {chevron && (
          <span className="act-chevron" data-open={open} aria-hidden="true">
            <Icon name="chevron-right" size={14} />
          </span>
        )}
      </button>
      <div className="act-disclosure" data-open={open}>
        <div className="act-disclosure__inner" id={id} inert={open ? undefined : true}>
          <div className={contentClassName}>{children}</div>
        </div>
      </div>
    </div>
  );
}
