import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { SITE_NAME } from "@/lib/site";
import { CtaBand } from "@/components/Cta";
import { PageHeader, RelatedLinks } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "Pricing",
  description: `There's no fixed public pricing for ${SITE_NAME} yet. Request a demo and we'll talk through pricing for your restaurant.`,
  path: "/pricing",
});

export default function PricingPage() {
  return (
    <main>
      <PageHeader label="Pricing" title="Pricing on request" actions={false}>
        There&rsquo;s no fixed public pricing yet.
      </PageHeader>

      <section className="section" aria-labelledby="pricing-heading">
        <div className="wrap">
          <div className="prose">
            <h2 id="pricing-heading" className="related-title">
              Where pricing stands today
            </h2>
            <p>
              We&rsquo;re still early, working directly with a small number of pilot venues, and
              haven&rsquo;t published a price list. Rather than guess at a number here, the honest
              answer is: talk to us. Tell us about your venue and we&rsquo;ll walk you through
              what&rsquo;s available and how pricing would work for a place like yours.
            </p>
          </div>
        </div>
      </section>

      <CtaBand
        heading="Ask about pricing for your venue"
        body="Book a demo and we'll talk through pricing directly, based on your restaurant, bar or café."
        secondaryHref="/contact"
        secondaryLabel="Contact us"
      />

      <RelatedLinks
        links={[
          { href: "/qr-ordering", label: "See what QR table ordering includes" },
          { href: "/ai-voice-ordering", label: "See how AI voice ordering works" },
        ]}
      />
    </main>
  );
}
