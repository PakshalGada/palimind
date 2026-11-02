import type { ReactNode } from 'react';
import type { ToolStatus } from '../model';

export function Rail({ children }: { children: ReactNode }) {
  return <div className="act-rail">{children}</div>;
}

export function RailItem({
  status,
  children,
}: {
  status: ToolStatus;
  children: ReactNode;
}) {
  return (
    <div className="act-rail__item">
      <span className={`act-node act-node--${status}`} aria-hidden="true" />
      {children}
    </div>
  );
}
