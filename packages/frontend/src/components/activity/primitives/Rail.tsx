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
    <div className="act-rail__item" data-status={status}>
      {children}
    </div>
  );
}
