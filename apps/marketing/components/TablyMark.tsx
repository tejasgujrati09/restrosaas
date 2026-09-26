/**
 * The Tably logo mark: a fork on a table top, drawn inline so it follows the colour tokens.
 * Decorative by default (the wordmark beside it carries the name); pass `title` when the mark
 * stands alone and needs to be announced.
 */
export function TablyMark({ size = 34, title }: { size?: number; title?: string }) {
  const a11y = title
    ? ({ role: "img", "aria-label": title } as const)
    : ({ "aria-hidden": true, focusable: false } as const);
  return (
    <svg
      className="tably-mark"
      width={size}
      height={size}
      viewBox="0 0 160 160"
      xmlns="http://www.w3.org/2000/svg"
      {...a11y}
    >
      {title ? <title>{title}</title> : null}
      <rect width="160" height="160" rx="36" className="tm-tile" />
      <rect x="47" y="38" width="12" height="34" rx="6" className="tm-fg" />
      <rect x="74" y="30" width="12" height="42" rx="6" className="tm-fg" />
      <rect x="101" y="46" width="12" height="26" rx="6" className="tm-fg" />
      <rect x="47" y="72" width="66" height="12" rx="6" className="tm-fg" />
      <rect x="74" y="84" width="12" height="46" rx="6" className="tm-accent" />
    </svg>
  );
}
