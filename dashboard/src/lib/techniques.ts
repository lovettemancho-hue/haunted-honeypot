/** Well-known names for the techniques the Brain detects. */
export const TECHNIQUE_NAMES: Readonly<Record<string, string>> = {
  T1110: "Brute Force",
  T1078: "Valid Accounts",
  T1082: "System Information Discovery",
  T1105: "Ingress Tool Transfer",
  "T1059.004": "Unix Shell",
  "T1053.003": "Cron",
  "T1098.004": "SSH Authorized Keys",
  T1496: "Resource Hijacking",
  "T1070.004": "File Deletion",
};
