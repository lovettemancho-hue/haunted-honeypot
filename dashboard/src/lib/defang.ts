// Defanging of http(s) URLs so attacker-supplied links are never live.

// scheme://authority, where the authority ends at "/", "?", "#" or whitespace.
const URL_RE = /(https?):\/\/([^\s/?#]*)/gi;

function defangMatch(_match: string, scheme: string, authority: string): string {
  const safeScheme = scheme.toLowerCase() === "https" ? "hxxps" : "hxxp";
  return `${safeScheme}://${authority.replace(/\./g, "[.]")}`;
}

export function defangUrl(url: string): string {
  return url.replace(URL_RE, defangMatch);
}

export function defangText(text: string): string {
  // Repeat until stable: a URL nested in another URL's authority
  // (e.g. "http://http://x") only becomes visible after the outer pass.
  // Each pass removes at least one live scheme, so this terminates.
  let current = text;
  for (;;) {
    const next = current.replace(URL_RE, defangMatch);
    if (next === current) return current;
    current = next;
  }
}
