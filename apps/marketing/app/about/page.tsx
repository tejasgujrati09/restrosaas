import type { Metadata } from "next";
import Link from "next/link";
import { pageMetadata } from "@/lib/seo";
import { SITE_NAME } from "@/lib/site";
import { CtaBand } from "@/components/Cta";
import { PageHeader } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "About",
  description: `${SITE_NAME} is early-stage restaurant ordering software for independent restaurants, bars and cafés in India, built around QR table ordering and AI phone ordering.`,
  path: "/about",
});

export default function AboutPage() {
  return (
    <main>
      <PageHeader label="About" title={`About ${SITE_NAME}`} actions={false}>
        Ordering software for Indian restaurants, bars and cafés, built around QR table ordering and
        AI phone ordering, and honest about being early-stage.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap prose">
          <h2 id="what-heading" className="related-title">
            What this is
          </h2>
          <p>
            {SITE_NAME} is ordering and operations software for independent venues in India: QR
            table ordering, AI phone ordering, a kitchen ticket queue, table and staff management,
            and operational analytics, in one system with phone-number sign-in and no passwords
            anywhere.
          </p>
        </div>
      </section>

      <section className="section" aria-labelledby="stage-heading">
        <div className="wrap prose">
          <h2 id="stage-heading" className="related-title">
            Where things stand
          </h2>
          <p>
            This is early-stage software, not a large, established vendor with years of history.
            We&rsquo;re working closely with a small number of pilot venues to make sure the core
            workflows (QR ordering, AI voice ordering with a person always accepting the order, and
            one Orders screen across every channel) hold up on a real, busy floor before expanding
            further.
          </p>
          <p>
            We&rsquo;d rather be precise about what exists today than describe features,
            integrations or a company history that isn&rsquo;t real yet. Things like in-app payments
            and GST billing are planned, and we say so where they come up.
          </p>
        </div>
      </section>

      <section className="section" aria-labelledby="learn-heading">
        <div className="wrap prose">
          <h2 id="learn-heading" className="related-title">
            What to look at next
          </h2>
          <p>
            See <Link href="/qr-ordering">how QR table ordering works</Link>, how{" "}
            <Link href="/ai-voice-ordering">AI voice ordering</Link> keeps a person in the loop, or{" "}
            <Link href="/contact">get in touch</Link> if you&rsquo;d like a walkthrough.
          </p>
        </div>
      </section>

      <CtaBand
        heading="Want to see it running on a real menu?"
        body="Book a demo and we'll show you the product, not a pitch deck."
      />
    </main>
  );
}
