interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  text?: string;
  className?: string;
  inline?: boolean;
}

export default function LoadingSpinner({
  size = 'md',
  text,
  className = '',
  inline = false,
}: LoadingSpinnerProps) {
  const sizePixels = size === 'sm' ? 16 : size === 'lg' ? 32 : 22;

  return (
    <div className={`loading-spinner-container size-${size} ${inline ? 'inline' : ''} ${className}`}>
      <svg
        className="loading-spinner-svg"
        width={sizePixels}
        height={sizePixels}
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <circle
          className="loading-spinner-track"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="2.5"
        />
        <path
          className="loading-spinner-head"
          d="M12 2C6.47715 2 2 6.47715 2 12C2 14.7364 3.09743 17.2166 4.87858 19.034"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      {text && <span className="loading-spinner-text">{text}</span>}
    </div>
  );
}
