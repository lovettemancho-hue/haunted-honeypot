export const MAX_ATTACKER_TEXT_LENGTH = 4096;

export function truncateAttackerText(value: string): { text: string; truncated: boolean } {
  if (value.length <= MAX_ATTACKER_TEXT_LENGTH) {
    return { text: value, truncated: false };
  }
  return { text: value.slice(0, MAX_ATTACKER_TEXT_LENGTH), truncated: true };
}
