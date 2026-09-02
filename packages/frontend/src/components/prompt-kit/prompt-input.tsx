import {
  forwardRef,
  type FormEvent,
  type HTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

type PromptInputProps = HTMLAttributes<HTMLFormElement> & {
  value: string;
  onValueChange: (value: string) => void;
  isLoading?: boolean;
  onSubmit?: () => void;
};

export function PromptInput({
  value: _value,
  onValueChange: _onValueChange,
  isLoading: _isLoading,
  onSubmit,
  className = "",
  children,
  ...props
}: PromptInputProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit?.();
  };

  return (
    <form
      {...props}
      className={`prompt-input ${className}`.trim()}
      onSubmit={handleSubmit}
    >
      {children}
    </form>
  );
}

export const PromptInputTextarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function PromptInputTextarea({ className = "", ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={`prompt-input-textarea ${className}`.trim()}
      {...props}
    />
  );
});

export function PromptInputActions({
  className = "",
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...props} className={`prompt-input-actions ${className}`.trim()}>
      {children}
    </div>
  );
}

type PromptInputActionProps = HTMLAttributes<HTMLDivElement> & {
  tooltip?: string;
};

export function PromptInputAction({
  className = "",
  children,
  tooltip: _tooltip,
  ...props
}: PromptInputActionProps) {
  return (
    <div
      {...props}
      className={`prompt-input-action ${className}`.trim()}
      title={_tooltip}
    >
      {children}
    </div>
  );
}
