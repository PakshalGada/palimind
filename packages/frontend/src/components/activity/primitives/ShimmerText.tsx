export function ShimmerText({
  children,
  active = true,
  className = '',
}: {
  children: React.ReactNode;
  active?: boolean;
  className?: string;
}) {
  return (
    <span className={`${active ? 'act-shimmer' : ''} ${className}`.trim()}>{children}</span>
  );
}
