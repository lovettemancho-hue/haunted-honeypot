export type ChecklistState = Record<string, boolean>;

/** Returns a new state with `id` flipped; unknown ids are added as true. */
export function toggleItem(state: ChecklistState, id: string): ChecklistState {
  return { ...state, [id]: !state[id] };
}

/** Number of entries that are checked. */
export function progressCount(state: ChecklistState): number {
  return Object.values(state).filter((v) => v === true).length;
}

export interface ChecklistItem {
  id: string;
  label: string;
  description: string;
}

/** Fixed hardening steps shown on the Containment page. */
export const CHECKLIST_ITEMS: readonly ChecklistItem[] = [
  {
    id: "disable-password-auth",
    label: "Turn off SSH password logins",
    description: "Allow only SSH keys, so guessed passwords can never open a door.",
  },
  {
    id: "disable-root-login",
    label: "Block direct root login",
    description: "Attackers try the root account first. Log in as a normal user and escalate only when needed.",
  },
  {
    id: "firewall-block",
    label: "Apply the generated firewall rules",
    description: "Block the addresses seen attacking the trap before they reach your real server.",
  },
  {
    id: "fail2ban",
    label: "Install automatic ban for repeated failures",
    description: "A tool such as fail2ban bans an address after several failed logins.",
  },
  {
    id: "change-ssh-port",
    label: "Move SSH off the default port",
    description: "Cuts down the noise from bots that only scan port 22.",
  },
  {
    id: "update-packages",
    label: "Install pending security updates",
    description: "Patched software closes the holes that attackers look for.",
  },
  {
    id: "rotate-credentials",
    label: "Replace weak or reused passwords",
    description: "Change any password that appears in the top guessed passwords list.",
  },
];
