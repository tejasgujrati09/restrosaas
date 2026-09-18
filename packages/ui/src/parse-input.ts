/**
 * Owner-typed input -> the integers the API stores. String maths only, so no
 * float ever touches a price. Returns null for anything that is not a plain
 * number, so a form can show its own message.
 */
const RUPEES = /^(\d+)(?:\.(\d{1,2}))?$/;
const PERCENT = /^(\d+)(?:\.(\d{1,2}))?$/;

function clean(text: string): string {
  return text.replace(/[₹,\s]/g, "");
}

/** "120" -> 12000, "120.5" -> 12050, "₹1,250.75" -> 125075 (paise). */
export function parseRupees(text: string): number | null {
  const m = RUPEES.exec(clean(text));
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0") || "0");
}

/** "12.5" -> 1250 (basis points: percent * 100), the unit tax and discount rates use. */
export function parsePercentToBp(text: string): number | null {
  const m = PERCENT.exec(clean(text).replace(/%$/, ""));
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0") || "0");
}

/** 1250 -> "12.5"; 500 -> "5". */
export function formatBp(bp: number): string {
  const whole = Math.floor(bp / 100);
  const frac = String(bp % 100).padStart(2, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : String(whole);
}

/** 12050 -> "120.50" for an input box (not for display; use formatInr there). */
export function paiseToInput(paise: number): string {
  return `${Math.floor(paise / 100)}.${String(paise % 100).padStart(2, "0")}`;
}
