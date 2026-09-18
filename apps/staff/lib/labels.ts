/** T1..T12 from a prefix and a count. Bar counter seats are ordinary tables (B1, B2, ...). */
export function makeLabels(prefix: string, count: number): string[] {
  return Array.from({ length: count }, (_, i) => `${prefix}${i + 1}`);
}
