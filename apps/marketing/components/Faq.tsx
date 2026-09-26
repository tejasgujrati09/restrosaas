import { JsonLd } from "./JsonLd";

export type FaqEntry = { question: string; answer: string };

/**
 * Renders an FAQ section and its FAQPage JSON-LD together, so a page can never ship the schema
 * without the matching visible content (or vice versa).
 */
export function Faq({ heading, entries }: { heading: string; entries: FaqEntry[] }) {
  const schema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: entries.map((e) => ({
      "@type": "Question",
      name: e.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: e.answer,
      },
    })),
  };

  return (
    <section aria-labelledby="faq-heading" className="section alt">
      <div className="wrap faq">
        <div className="section-head">
          <span className="label">FAQ</span>
          <h2 id="faq-heading">{heading}</h2>
        </div>
        <dl>
          {entries.map((e) => (
            <div className="faq-item" key={e.question}>
              <dt>
                <h3>{e.question}</h3>
              </dt>
              <dd>{e.answer}</dd>
            </div>
          ))}
        </dl>
      </div>
      <JsonLd data={schema} />
    </section>
  );
}
