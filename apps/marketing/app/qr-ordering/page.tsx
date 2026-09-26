import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { Screenshot } from "@/components/Screenshot";
import { CtaBand } from "@/components/Cta";
import { Faq } from "@/components/Faq";
import { Benefits, PageHeader, RelatedLinks, SectionHead, Steps, Story } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "QR Table Ordering for Restaurants",
  description:
    "Guests scan a table QR code and order from a mobile menu with modifiers, sold-out handling and happy-hour pricing, no app download. See how QR table ordering works.",
  path: "/qr-ordering",
});

export default function QrOrderingPage() {
  return (
    <main>
      <PageHeader label="QR table ordering" title="QR Table Ordering">
        Guests scan a code at their table and order straight from their own phone, on your live
        menu, with no app download.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap">
          <SectionHead label="What it is" title="A live menu for every table" titleId="what-heading" />
          <div className="prose">
            <p>
              Owners add tables organised by zone (patio, indoor, bar and so on) and generate a
              printable PDF of QR codes, one page per zone, ready to print and put on tables. Each code
              opens a mobile menu for that table, showing your real menu items, modifiers, sold-out
              state and any active happy-hour pricing.
            </p>
            <p>
              Guests can place an order, call a waiter, ask for water or request the bill from their
              phone. Friends at the same table can scan and order onto the same tab.
            </p>
          </div>
        </div>
      </section>

      <section className="section alt" aria-labelledby="how-heading">
        <div className="wrap">
          <SectionHead label="How it works" title="From printed QR to placed order" titleId="how-heading" />
          <Steps
            steps={[
              {
                title: "Set up tables by zone",
                body: "Tables are grouped into zones on the Tables and QR screen, and each table gets its own QR code.",
              },
              {
                title: "Print the QR sheet",
                body: "One PDF page per zone, ready to print and place on tables.",
              },
              {
                title: "Guest scans and browses",
                body: "The menu shows modifiers, current sold-out items and any happy-hour price in effect. It is never a static PDF menu.",
              },
              {
                title: "Order, call or ask for the bill",
                body: "All from the same phone screen. The order lands on the Orders screen and in the kitchen queue alongside every other channel.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section" aria-labelledby="benefits-heading">
        <div className="wrap">
          <SectionHead label="Benefits" title="Why venues use it" titleId="benefits-heading" />
          <Benefits
            items={[
              {
                title: "No app download",
                body: "Guests order from the browser tab they land in after scanning. Nothing to install.",
              },
              {
                title: "Always the current menu",
                body: "Sold-out items and happy-hour prices update live, so guests never see stale prices.",
              },
              {
                title: "Fewer trips to the table",
                body: "Guests call a waiter, ask for water or request the bill without flagging someone down.",
              },
              {
                title: "One queue, not a separate app",
                body: "QR orders land on the same Orders screen as waiter and phone orders, tagged by source.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section alt" aria-labelledby="screens-heading">
        <div className="wrap">
          <SectionHead label="Real screens" title="See it running" titleId="screens-heading" />
          <div className="stories">
            <Story
              title="The guest menu, after scanning"
              media={
                <Screenshot
                  phone
                  src="/screenshots/qr-guest-menu-ordering.png"
                  alt="Guest ordering screen for table T1 showing drinks, mains and starters with prices in rupees, a happy-hour price on craft beer, a veg-only filter and a Call waiter button"
                  caption="The guest ordering screen from a test venue: a veg-only filter, veg and non-veg marks, and a happy-hour price."
                  width={430}
                  height={900}
                />
              }
            >
              <p>
                This is the mobile ordering screen a diner sees after scanning their table&rsquo;s QR
                code, with happy-hour pricing applied.
              </p>
            </Story>
            <Story
              reverse
              title="Generating the QR sheet"
              media={
                <Screenshot
                  src="/screenshots/restaurant-tables-qr-code-generator.png"
                  alt="Tables and QR codes screen with a form to add tables by zone, a list of tables T1 to T4, and Print QR sheet (PDF) and Print all QR sheets buttons"
                  caption="The Tables and QR screen, where tables are added by zone and the printable QR sheet is generated."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                Owners and managers manage tables by zone and generate the printable PDF QR sheet from
                this screen, one page per zone.
              </p>
            </Story>
          </div>
        </div>
      </section>

      <Faq
        heading="QR ordering FAQ"
        entries={[
          {
            question: "Do guests need to download an app to order?",
            answer:
              "No. Scanning the table QR code opens a mobile web menu in the guest's browser. There's no app to install.",
          },
          {
            question: "Does the QR menu show real-time sold-out items?",
            answer:
              "Yes. Items are marked sold out live from the kitchen and bar screen, and the guest menu reflects that immediately.",
          },
          {
            question: "How does happy-hour pricing work on the QR menu?",
            answer:
              "When a venue has an active happy-hour pricing window, the guest menu shows the adjusted price automatically, without a separate menu or code.",
          },
          {
            question: "Can guests call a waiter or ask for the bill from the QR menu?",
            answer:
              "Yes. Calling a waiter, asking for water and requesting the bill are all available from the guest's phone.",
          },
          {
            question: "Where do QR orders show up for staff?",
            answer:
              "QR orders land on the same Orders screen as waiter and phone orders, grouped by status and tagged with their source, and as tickets in the kitchen queue.",
          },
        ]}
      />

      <RelatedLinks
        links={[
          { href: "/restaurant-kitchen-management", label: "See how QR orders become kitchen tickets" },
          { href: "/ai-voice-ordering", label: "Compare with AI voice ordering" },
          { href: "/pricing", label: "Ask about pricing" },
          { href: "/contact", label: "Contact us to see a live demo" },
        ]}
      />

      <CtaBand
        heading="Put a QR code on every table"
        body="Sign up with just a phone number, add your tables by zone and print your QR sheet. Or book a demo and we'll walk you through it."
      />
    </main>
  );
}
