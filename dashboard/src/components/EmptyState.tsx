import type { ReactNode } from "react";

/** Plain-language placeholder for a panel with nothing to show. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state" role="status">
      <p className="empty-state__title">{title}</p>
      {children ? <div className="empty-state__body">{children}</div> : null}
    </div>
  );
}
