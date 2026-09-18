/**
 * Display-only Indian currency formatting: 12345600 paise -> "₹1,23,456.00".
 * Mirrors app.core.money.format_inr in the API. Integer maths only; money
 * rules live in Python and are never re-implemented here.
 */
export function formatInr(paise: number): string {
  if (!Number.isInteger(paise)) {
    throw new RangeError("paise must be an integer");
  }
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const rupees = Math.floor(abs / 100).toString();
  const remainder = (abs % 100).toString().padStart(2, "0");
  return `${sign}₹${groupIndian(rupees)}.${remainder}`;
}

function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const lastThree = digits.slice(-3);
  const groups: string[] = [];
  let rest = digits.slice(0, -3);
  while (rest.length > 2) {
    groups.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  groups.unshift(rest);
  return [...groups, lastThree].join(",");
}
