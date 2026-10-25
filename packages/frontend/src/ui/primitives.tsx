import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'icon';

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button
      {...rest}
      className={`ui-btn ui-btn--${variant} ui-btn--${size} ${className}`.trim()}
    />
  );
}

export function IconButton({
  label,
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={`ui-icon-btn ${className}`.trim()}
    />
  );
}

type Tone = 'default' | 'muted' | 'success' | 'warn' | 'danger' | 'accent';

export function Chip({
  children,
  tone = 'default',
  className = '',
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return <span className={`ui-chip ui-chip--${tone} ${className}`.trim()}>{children}</span>;
}

export function Badge({ children, tone = 'default' }: { children: ReactNode; tone?: Tone }) {
  return <span className={`ui-badge ui-badge--${tone}`}>{children}</span>;
}

export function Field({
  label,
  hint,
  children,
  className = '',
}: {
  label?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`ui-field ${className}`.trim()}>
      {label != null && <span className="ui-field__label">{label}</span>}
      {children}
      {hint != null && <span className="ui-field__hint">{hint}</span>}
    </label>
  );
}

export function TextInput({
  className = '',
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={`ui-input ${className}`.trim()} />;
}

export function TextArea({
  className = '',
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={`ui-textarea ${className}`.trim()} />;
}

export function Select({
  className = '',
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={`ui-select ${className}`.trim()}>
      {children}
    </select>
  );
}

/** Single-line input. Alias of TextInput with the shorter, canonical name. */
export function Input({
  className = '',
  ...rest
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={`ui-input ${className}`.trim()} />;
}

export function Card({
  children,
  className = '',
  interactive = false,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      {...rest}
      className={`ui-card${interactive ? ' ui-card--interactive' : ''} ${className}`.trim()}
    >
      {children}
    </div>
  );
}

export function Kbd({
  children,
  className = '',
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <kbd className={`ui-kbd ${className}`.trim()} title={title}>
      {children}
    </kbd>
  );
}

type AvatarSize = 'xs' | 'sm' | 'md' | 'lg';
type AvatarTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

export function Avatar({
  name,
  src,
  size = 'md',
  tone = 'neutral',
  status,
  className = '',
}: {
  name: string;
  src?: string;
  size?: AvatarSize;
  tone?: AvatarTone;
  status?: 'online' | 'busy' | 'offline';
  className?: string;
}) {
  return (
    <span
      className={`ui-avatar ui-avatar--${size} ui-avatar--${tone} ${className}`.trim()}
      title={name}
    >
      {src ? (
        <img className="ui-avatar__img" src={src} alt={name} />
      ) : (
        <span className="ui-avatar__initials" aria-hidden="true">
          {initialsFor(name)}
        </span>
      )}
      {status && <span className={`ui-avatar__status ui-avatar__status--${status}`} aria-label={status} />}
      <span className="ui-sr-only">{name}</span>
    </span>
  );
}

export function Separator({
  orientation = 'horizontal',
  label,
  className = '',
}: {
  orientation?: 'horizontal' | 'vertical';
  label?: ReactNode;
  className?: string;
}) {
  if (orientation === 'vertical') {
    return <span role="separator" aria-orientation="vertical" className={`ui-separator ui-separator--vertical ${className}`.trim()} />;
  }
  if (label != null) {
    return (
      <div role="separator" className={`ui-separator ui-separator--labelled ${className}`.trim()}>
        <span>{label}</span>
      </div>
    );
  }
  return <div role="separator" aria-orientation="horizontal" className={`ui-separator ${className}`.trim()} />;
}

/** Theme-aware scroll container with consistently styled scrollbars. */
export function Scrollbar({
  children,
  className = '',
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={`ui-scrollbar ${className}`.trim()}>
      {children}
    </div>
  );
}

export function Skeleton({
  width,
  height = 12,
  radius = 'sm',
  className = '',
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: 'sm' | 'md' | 'full';
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      aria-hidden="true"
      className={`ui-skeleton ui-skeleton--${radius} ${className}`.trim()}
      style={{ width, height, ...style }}
    />
  );
}

/** A stack of skeleton lines for paragraph-shaped loading states. */
export function SkeletonText({
  lines = 3,
  className = '',
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <span className={`ui-skeleton-text ${className}`.trim()}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? '64%' : '100%'} height={11} />
      ))}
    </span>
  );
}

/** Avatar + two-line skeleton row, used for lists and panels while loading. */
export function SkeletonList({
  rows = 4,
  avatar = true,
  className = '',
}: {
  rows?: number;
  avatar?: boolean;
  className?: string;
}) {
  return (
    <span className={`ui-skeleton-list ${className}`.trim()} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <span className="ui-skeleton-row" key={i}>
          {avatar && <Skeleton width={28} height={28} radius="full" />}
          <span className="ui-skeleton-row__lines">
            <Skeleton width={`${72 - (i % 3) * 12}%`} height={11} />
            <Skeleton width={`${44 + (i % 2) * 10}%`} height={9} />
          </span>
        </span>
      ))}
    </span>
  );
}

/** Alias that reads well when several skeleton blocks form one surface. */
export const SkeletonCollection = SkeletonList;

export function InlineError({
  title = 'Something went wrong',
  message,
  onRetry,
  onDismiss,
  className = '',
}: {
  title?: ReactNode;
  message?: ReactNode;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div className={`ui-error-banner ${className}`.trim()} role="alert">
      <AlertTriangle size={15} className="ui-error-banner__icon" />
      <div className="ui-error-banner__text">
        <span className="ui-error-banner__title">{title}</span>
        {message != null && <span className="ui-error-banner__message">{message}</span>}
      </div>
      {onRetry && (
        <button type="button" className="ui-error-banner__retry" onClick={onRetry}>
          Retry
        </button>
      )}
      {onDismiss && (
        <button
          type="button"
          className="ui-error-banner__dismiss"
          onClick={onDismiss}
          aria-label="Dismiss error"
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}

export interface PickerOption {
  value: string;
  label: ReactNode;
  description?: ReactNode;
}

/**
 * Custom dropdown that fully follows the design system, unlike a native
 * `<select>` whose popup cannot be themed. The menu renders in a portal and is
 * positioned against the trigger so it never clips inside panels or modals.
 */
export function Picker({
  value,
  options,
  onChange,
  placeholder = 'Select',
  ariaLabel,
  disabled,
  className = '',
}: {
  value: string;
  options: PickerOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<{ left: number; top: number; width: number } | null>(null);
  const btnRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onClose = () => setOpen(false);
    window.addEventListener('mousedown', onDoc);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onClose);
    window.addEventListener('scroll', onClose, true);
    return () => {
      window.removeEventListener('mousedown', onDoc);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onClose);
      window.removeEventListener('scroll', onClose, true);
    };
  }, [open]);

  const toggle = () => {
    if (disabled) return;
    if (open) {
      setOpen(false);
      return;
    }
    const r = btnRef.current?.getBoundingClientRect();
    if (r) setRect({ left: r.left, top: r.bottom + 4, width: r.width });
    setOpen(true);
  };

  const selected = options.find((o) => o.value === value);

  return (
    <>
      {/* A div (not a <button>) so nesting inside a <label>-based Field cannot
          trigger label click-forwarding that would toggle twice / swallow the
          click. Keyboard activation is handled explicitly. */}
      <div
        ref={btnRef}
        role="button"
        tabIndex={disabled ? -1 : 0}
        className={`ui-picker${disabled ? ' is-disabled' : ''} ${className}`.trim()}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-disabled={disabled}
        aria-label={ariaLabel}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
            e.preventDefault();
            toggle();
          }
        }}
      >
        <span className={`ui-picker__value${selected ? '' : ' is-placeholder'}`}>
          {selected ? selected.label : placeholder}
        </span>
        <svg
          className="ui-picker__chevron"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
      {open && rect
        ? createPortal(
            <div
              ref={menuRef}
              className="ui-picker-menu"
              role="listbox"
              style={{ left: rect.left, top: rect.top, minWidth: rect.width }}
            >
              {options.length === 0 && <div className="ui-picker-empty">No options</div>}
              {options.map((o) => (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={o.value === value}
                  className={`ui-picker-option${o.value === value ? ' is-selected' : ''}`}
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                >
                  <span className="ui-picker-option__label">{o.label}</span>
                  {o.description != null && <span className="ui-picker-option__desc">{o.description}</span>}
                </button>
              ))}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

/**
 * Lightweight anchored overlay for menus, filters and contextual actions.
 * The panel renders in a portal so it is never clipped by a scroll container.
 */
export function Popover({
  trigger,
  children,
  align = 'start',
  ariaLabel,
  className = '',
}: {
  trigger: ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: 'start' | 'end';
  ariaLabel?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<{ left: number; right: number; top: number; width: number } | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = () => setOpen(false);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (anchorRef.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    const onLayout = () => close();
    window.addEventListener('mousedown', onDoc);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onLayout);
    window.addEventListener('scroll', onLayout, true);
    return () => {
      window.removeEventListener('mousedown', onDoc);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onLayout);
      window.removeEventListener('scroll', onLayout, true);
    };
  }, [open]);

  const toggle = () => {
    if (open) {
      close();
      return;
    }
    const r = anchorRef.current?.getBoundingClientRect();
    if (r) setRect({ left: r.left, right: r.right, top: r.bottom + 6, width: r.width });
    setOpen(true);
  };

  return (
    <>
      <span
        ref={anchorRef}
        className="ui-popover-anchor"
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            toggle();
          }
        }}
      >
        {trigger}
      </span>
      {open && rect
        ? createPortal(
            <div
              ref={menuRef}
              role="dialog"
              aria-label={ariaLabel}
              className={`ui-popover ${align === 'end' ? 'ui-popover--end' : ''} ${className}`.trim()}
              style={{
                top: rect.top,
                ...(align === 'end' ? { right: window.innerWidth - rect.right } : { left: rect.left }),
                minWidth: rect.width,
              }}
            >
              {typeof children === 'function' ? children(close) : children}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

export function Toggle({
  checked,
  onChange,
  title,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`ui-toggle${disabled ? ' is-disabled' : ''}`}>
      <span className="ui-toggle__text">
        <span className="ui-toggle__title">{title}</span>
        {description != null && <span className="ui-toggle__desc">{description}</span>}
      </span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="ui-toggle__switch" aria-hidden="true" />
    </label>
  );
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  ariaLabel?: string;
}) {
  return (
    <div className="ui-segmented" role="radiogroup" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          className={`ui-segmented__btn${value === o.value ? ' is-active' : ''}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Spinner({ size = 16, className = '' }: { size?: number; className?: string }) {
  return (
    <span
      className={`ui-spinner ${className}`.trim()}
      style={{ width: size, height: size }}
      aria-label="Loading"
      role="status"
    />
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  children,
  compact = false,
  className = '',
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={`ui-empty${compact ? ' ui-empty--compact' : ''} ${className}`.trim()}>
      {icon != null && <div className="ui-empty__icon">{icon}</div>}
      <div className="ui-empty__title">{title}</div>
      {description != null && <div className="ui-empty__desc">{description}</div>}
      {action != null && <div className="ui-empty__action">{action}</div>}
      {children != null && <div className="ui-empty__extra">{children}</div>}
    </div>
  );
}

export type ToastTone = 'default' | 'success' | 'warning' | 'error' | 'info';

const TOAST_ICONS = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
  info: Info,
  default: Info,
} as const;

export function Toast({
  title,
  message,
  tone = 'default',
  action,
  onDismiss,
  duration,
  className = '',
}: {
  title?: ReactNode;
  message: ReactNode;
  tone?: ToastTone;
  action?: { label: string; onClick: () => void };
  onDismiss?: () => void;
  /** Auto-dismiss delay, used to pace the progress bar. Omit for no bar. */
  duration?: number;
  className?: string;
}) {
  const Icon = TOAST_ICONS[tone];
  return (
    <div className={`ui-toast ui-toast--${tone} ${className}`.trim()} role={tone === 'error' ? 'alert' : 'status'}>
      <span className="ui-toast__icon" aria-hidden="true">
        <Icon size={16} />
      </span>
      <div className="ui-toast__body">
        {title != null && <div className="ui-toast__title">{title}</div>}
        <div className="ui-toast__message">{message}</div>
      </div>
      {action && (
        <button
          type="button"
          className="ui-toast__action"
          onClick={() => {
            action.onClick();
            onDismiss?.();
          }}
        >
          {action.label}
        </button>
      )}
      {onDismiss && (
        <button type="button" className="ui-toast__close" onClick={onDismiss} aria-label="Dismiss notification">
          <X size={14} />
        </button>
      )}
      {duration != null && duration > 0 && (
        <span
          className="ui-toast__progress"
          aria-hidden="true"
          style={{ animationDuration: `${duration}ms` }}
        />
      )}
    </div>
  );
}

export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 720,
  className = '',
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="ui-modal-overlay" onMouseDown={onClose}>
      <div
        className={`ui-modal ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        style={{ width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ui-modal__head">
          <div className="ui-modal__heading">
            <div className="ui-modal__title">{title}</div>
            {subtitle != null && <div className="ui-modal__subtitle">{subtitle}</div>}
          </div>
          <IconButton label="Close" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </IconButton>
        </div>
        <div className="ui-modal__body">{children}</div>
        {footer != null && <div className="ui-modal__foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Backwards-compatible alias; new code should use `Dialog`. */
export const Modal = Dialog;

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="ui-tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          className={`ui-tab${value === t.id ? ' is-active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
          {t.count != null && t.count > 0 && <span className="ui-tab__count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/**
 * Progress bar. Pass `value` (0–1) for a determinate bar or leave it out for
 * an indeterminate sliding bar.
 */
export function ProgressBar({
  value,
  label,
  className = '',
}: {
  value?: number | null;
  label?: ReactNode;
  className?: string;
}) {
  const indeterminate = value == null;
  const pct = indeterminate ? undefined : Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div
      className={`ui-progress${indeterminate ? ' ui-progress--indeterminate' : ''} ${className}`.trim()}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      {label != null && <div className="ui-progress__label">{label}</div>}
      <div className="ui-progress__track">
        <div className="ui-progress__fill" style={pct === undefined ? undefined : { width: `${pct}%` }} />
      </div>
    </div>
  );
}
