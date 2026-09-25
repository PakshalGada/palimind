import {
  useEffect,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';
import { createPortal } from 'react-dom';
import './ui.css';

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
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="ui-empty">
      {icon != null && <div className="ui-empty__icon">{icon}</div>}
      <div className="ui-empty__title">{title}</div>
      {description != null && <div className="ui-empty__desc">{description}</div>}
      {action != null && <div className="ui-empty__action">{action}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 720,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return createPortal(
    <div className="ui-modal-overlay" onMouseDown={onClose}>
      <div
        className="ui-modal"
        role="dialog"
        aria-modal="true"
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
