/** Turning stored values into display text. Formatting happens here, at the edge of the UI: the
 *  stored value (an enum, a zone a user typed) is never changed, and nothing is compared by its
 *  display text. Sentence case only: the first letter, nothing else, so "Main hall" and "VIP"
 *  come out as typed. */

/** "floor" -> "Floor". Leaves the rest of the text as it was written. */
export function sentenceCase(value: string): string {
  const text = value.trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "order_pending" -> "Order pending": for a stored code with no better label. */
export function humanize(value: string): string {
  return sentenceCase(value.replace(/[_-]+/g, " "));
}

const ROLES: Record<string, string> = {
  waiter: "Waiter",
  kitchen: "Kitchen",
  bar: "Bar",
  manager: "Manager",
  owner: "Owner",
};

/** A staff role for display. The stored role ("waiter") is what the API takes and returns. */
export function roleLabel(role: string): string {
  return ROLES[role] ?? humanize(role);
}
