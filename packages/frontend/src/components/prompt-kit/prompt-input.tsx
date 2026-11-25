import {
  forwardRef,
  type HTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

type PromptInputProps = HTMLAttributes<HTMLDivElement> & {
  value: string;
  onValueChange: (value: string) => void;
  isLoading?: boolean;
};

export function PromptInput({
  value: _value,
  onValueChange: _onValueChange,
  isLoading: _isLoading,
  className = "",
  children,
  ...props
}: PromptInputProps) {
  return (
    <div {...props} className={`prompt-input ${className}`.trim()}>
      {children}
    </div>
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
