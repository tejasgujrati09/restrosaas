import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { CONTACT_EMAIL, SITE_NAME } from "@/lib/site";
import { DemoForm } from "@/components/DemoForm";
import { PageHeader } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "Contact and Book a Demo",
  description: `Request a ${SITE_NAME} demo or ask a question. Send us your venue details and we'll get back to you.`,
  path: "/contact",
});

export default function ContactPage() {
  return (
    <main>
      <PageHeader label="Contact" title="Talk to us about your venue" actions={false}>
        Tell us about your restaurant, bar or café and we&rsquo;ll get back to you, or write to us
        directly at <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </PageHeader>

      <section className="section alt" aria-labelledby="form-heading">
        <div className="wrap close-grid">
          <div className="prose">
            <h2 id="form-heading" className="related-title">
              Request a demo
            </h2>
            <p>
              We&rsquo;ll show you the product on a menu like yours: the guest&rsquo;s QR menu, the
              waiter&rsquo;s tables, the kitchen queue, the Orders screen and, if you&rsquo;d like, AI
              phone ordering.
            </p>
            <p>There&rsquo;s no fixed public pricing yet, so this is also the place to ask about it.</p>
          </div>
          <div className="demo">
            <DemoForm idPrefix="contact" withMessage />
          </div>
        </div>
      </section>
    </main>
  );
}
