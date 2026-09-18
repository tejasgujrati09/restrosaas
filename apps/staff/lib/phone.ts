/** "98765 43210" -> "+919876543210"; a number already starting with "+" is kept. Null if unusable. */
export function toE164(input: string): string | null {
  const compact = input.replace(/[\s-]/g, "");
  if (compact.startsWith("+")) return /^\+[1-9]\d{7,14}$/.test(compact) ? compact : null;
  if (/^[6-9]\d{9}$/.test(compact)) return `+91${compact}`;
  if (/^0[6-9]\d{9}$/.test(compact)) return `+91${compact.slice(1)}`;
  return null;
}
