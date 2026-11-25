export type PageId = "monitor" | "tapes" | "containment";

export const NAV_ITEMS: ReadonlyArray<{
  id: PageId;
  href: string;
  label: string;
  description: string;
}> = [
  { id: "monitor", href: "#/monitor", label: "Lab Monitor", description: "Overview of current attacks" },
  { id: "tapes", href: "#/tapes", label: "Lab Tapes", description: "Replay each attack session" },
  { id: "containment", href: "#/containment", label: "Containment", description: "Ready-made hardening rules" },
];

/** Primary navigation. Wraps instead of hiding, so it stays reachable at 640px and below. */
export function Nav({ current }: { current: PageId }) {
  return (
    <nav className="app-nav" aria-label="Primary">
      {NAV_ITEMS.map((item) => (
        <a
          key={item.id}
          className="nav-link"
          href={item.href}
          title={item.description}
          aria-current={item.id === current ? "page" : undefined}
        >
          {item.label}
        </a>
      ))}
    </nav>
  );
}
