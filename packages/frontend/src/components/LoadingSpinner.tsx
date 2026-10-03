import Thinking from './Thinking';

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
      <Thinking variant="trace" size={sizePixels} />
      {text && <span className="loading-spinner-text">{text}</span>}
    </div>
  );
}
