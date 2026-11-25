const OCTET = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
const IPV4 = new RegExp(`^(${OCTET})\\.(${OCTET})\\.(${OCTET})\\.${OCTET}$`);

export function maskIp(value: string): string {
  const m = IPV4.exec(value);
  return m ? `${m[1]}.${m[2]}.${m[3]}.x` : value;
}
