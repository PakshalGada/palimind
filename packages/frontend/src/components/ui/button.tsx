import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "ghost";
  size?: "default" | "icon";
};

export function Button({
  variant = "default",
  size = "default",
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={`ui-button ui-button-${variant} ui-button-${size} ${className}`.trim()}
    />
  );
}
