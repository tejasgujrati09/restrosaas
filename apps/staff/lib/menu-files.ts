/** Display-side checks for the menu upload. The server repeats every one of these; this only
 *  lets the owner fix a problem before waiting for an upload. */
export const MAX_FILES = 20;
export const MAX_FILE_BYTES = 15_000_000;
export const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

const OK_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png"];
const OK_TYPES = ["application/pdf", "image/jpeg", "image/png"];

export function isSupported(file: { name: string; type: string }): boolean {
  const name = file.name.toLowerCase();
  return OK_EXTENSIONS.some((e) => name.endsWith(e)) || OK_TYPES.includes(file.type);
}

export function formatSize(bytes: number): string {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

/** Adds newly chosen files to the list (in the order given) and says why any were left out. */
export function addFiles<F extends { name: string; type: string; size: number }>(
  current: F[],
  added: F[],
): { files: F[]; problems: string[] } {
  const files = [...current];
  const problems: string[] = [];
  for (const file of added) {
    if (!isSupported(file)) problems.push(`${file.name} is not a PDF, JPG or PNG.`);
    else if (file.size === 0) problems.push(`${file.name} is empty.`);
    else if (file.size > MAX_FILE_BYTES) problems.push(`${file.name} is too large (${formatSize(file.size)}; the limit is ${formatSize(MAX_FILE_BYTES)}).`);
    else if (files.length >= MAX_FILES) problems.push(`Only ${MAX_FILES} files at a time; ${file.name} was left out.`);
    else files.push(file);
  }
  return { files, problems };
}

export function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length || from === to) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}
