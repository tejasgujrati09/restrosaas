import { isValidElement, type ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { Badge, Card, EmptyState, ErrorBanner, Field, Money, Notice, PageHeader, Skeleton } from "./components";

const VOID = new Set(["input", "br", "img", "hr"]);

/** Expands function components and prints plain markup, so tests read like the page.
 *  (react-dom is not a dependency of this package; the components are pure.) */
function html(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(html).join("");
  if (!isValidElement(node)) return "";
  const { type, props } = node as { type: unknown; props: Record<string, unknown> };
  if (typeof type === "function") return html((type as (p: unknown) => ReactNode)(props));
  const { children, ...rest } = props;
  const attrs = Object.entries(rest)
    .filter(([, v]) => v !== undefined && v !== false)
    .map(([k, v]) => `${k === "className" ? "class" : k}="${String(v)}"`)
    .join(" ");
  const open = `<${String(type)}${attrs ? " " + attrs : ""}>`;
  return VOID.has(String(type)) ? open : `${open}${html(children as ReactNode)}</${String(type)}>`;
}

describe("Field", () => {
  it("wraps the control in its label so the label names it", () => {
    const out = html(
      <Field label="GSTIN" hint="15 characters">
        <input />
      </Field>,
    );
    expect(out).toBe(
      '<label class="field"><span class="field-label">GSTIN</span><input><span class="hint">15 characters</span></label>',
    );
  });

  it("marks a single control invalid and announces the error", () => {
    const out = html(
      <Field label="Phone" error="Enter 10 digits">
        <input />
      </Field>,
    );
    expect(out).toContain('<input aria-invalid="true">');
    expect(out).toContain('<span class="field-error" role="alert">Enter 10 digits</span>');
  });

  it("leaves several children untouched when there is an error", () => {
    const out = html(
      <Field label="Price" error="Too high">
        <input />
        <span>₹</span>
      </Field>,
    );
    expect(out).not.toContain("aria-invalid");
    expect(out).toContain("Too high");
  });
});

describe("banners", () => {
  it("shows an error only when there is one, as an alert", () => {
    expect(html(<ErrorBanner message={null} />)).toBe("");
    expect(html(<ErrorBanner message="Nope" />)).toBe('<p class="error" role="alert">Nope</p>');
  });

  it("announces a notice politely, in warn or info tone", () => {
    expect(html(<Notice>Heads up</Notice>)).toBe('<p class="banner" role="status">Heads up</p>');
    expect(html(<Notice tone="info">FYI</Notice>)).toBe('<p class="notice" role="status">FYI</p>');
  });
});

describe("Badge", () => {
  it("adds the tone as a class and keeps the words", () => {
    expect(html(<Badge>Sent</Badge>)).toBe('<span class="badge">Sent</span>');
    expect(html(<Badge tone="danger">Disputed</Badge>)).toBe('<span class="badge danger">Disputed</span>');
  });
});

describe("Skeleton", () => {
  it("announces what is loading and hides the shapes", () => {
    const out = html(<Skeleton what="the menu" lines={3} />);
    expect(out).toContain('role="status"');
    expect(out).toContain('aria-busy="true"');
    expect(out).toContain("Loading the menu…");
    expect((out.match(/aria-hidden="true"/g) ?? []).length).toBe(3);
    expect(out).toContain('class="skeleton short"');
  });

  it("draws block shapes for card-sized content", () => {
    expect(html(<Skeleton what="your tab" lines={2} block />)).toContain('class="skeleton block"');
  });
});

describe("EmptyState and PageHeader", () => {
  it("says what is empty, why, and offers the next action", () => {
    const out = html(
      <EmptyState title="No requests" action={<a href="/floor">Open floor</a>}>
        Guests can call from their table.
      </EmptyState>,
    );
    expect(out).toContain("<h2>No requests</h2>");
    expect(out).toContain("<p>Guests can call from their table.</p>");
    expect(out).toContain('<a href="/floor">Open floor</a>');
  });

  it("omits the explanation and action when there are none", () => {
    expect(html(<EmptyState title="Nothing here" />)).toBe('<div class="empty"><h2>Nothing here</h2></div>');
  });

  it("puts the title in the only h1 and actions beside it", () => {
    const out = html(<PageHeader title="Menu" subtitle="Prices include taxes" actions={<button>Add</button>} />);
    expect(out).toContain("<h1>Menu</h1>");
    expect(out).toContain("<p>Prices include taxes</p>");
    expect(out).toContain('<div class="actions"><button>Add</button></div>');
    expect(html(<PageHeader title="Menu" />)).not.toContain("actions");
  });
});

describe("Card and Money", () => {
  it("titles a card only when asked", () => {
    expect(html(<Card>body</Card>)).toBe('<section class="card">body</section>');
    expect(html(<Card title="Business">body</Card>)).toBe('<section class="card"><h2>Business</h2>body</section>');
  });

  it("formats paise the Indian way", () => {
    expect(html(<Money paise={12345600} />)).toBe('<span class="money">₹1,23,456.00</span>');
  });
});
