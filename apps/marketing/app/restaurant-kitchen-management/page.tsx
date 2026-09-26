import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { Screenshot } from "@/components/Screenshot";
import { CtaBand } from "@/components/Cta";
import { Faq } from "@/components/Faq";
import { ExampleTag, KitchenTicketsMock } from "@/components/mocks";
import { Benefits, PageHeader, RelatedLinks, SectionHead, Steps, Story } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "Kitchen Ticket Queue for Restaurants",
  description:
    "One ticket queue for QR, waiter and accepted phone orders, filterable by kitchen or bar station, with ticket ageing, a short undo window and live sold-out toggling.",
  path: "/restaurant-kitchen-management",
});

export default function KitchenManagementPage() {
  return (
    <main>
      <PageHeader label="Kitchen and bar" title="Kitchen Ticket Queue">
        Every order, from every channel, becomes a ticket in a single queue the kitchen and bar can
        actually work from.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap">
          <SectionHead label="What it is" title="One queue for every channel" titleId="what-heading" />
          <div className="prose">
            <p>
              The ticket queue turns QR orders, waiter-entered orders and accepted phone orders into
              tickets. Tickets can be filtered by station, such as kitchen or bar, so each station sees
              what&rsquo;s relevant to it. Each ticket shows how long it has been waiting and changes
              colour as it ages.
            </p>
            <p>
              A guest&rsquo;s QR order has a short undo window before the kitchen can start it, and
              a phone order can&rsquo;t be started until a manager or owner accepts it. Items can be
              marked sold out, or available again, right from this screen.
            </p>
          </div>
        </div>
      </section>

      <section className="section alt" aria-labelledby="how-heading">
        <div className="wrap">
          <SectionHead label="How it works" title="From order to ready" titleId="how-heading" />
          <Steps
            steps={[
              {
                title: "An order is placed or accepted",
                body: "From a QR scan, a waiter, or an accepted phone order, it becomes a ticket.",
              },
              {
                title: "Filtered by station",
                body: "Kitchen staff see kitchen items and bar staff see bar items, from the same queue.",
              },
              {
                title: "Started, then ready",
                body: "Staff mark a ticket started and then ready. Its colour shows how long it has waited.",
              },
              {
                title: "Sold out, live",
                body: "Marking an item sold out here updates the guest QR menu and the waiter’s screen straight away.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section" aria-labelledby="benefits-heading">
        <div className="wrap">
          <SectionHead label="Benefits" title="Why kitchens like it" titleId="benefits-heading" />
          <Benefits
            items={[
              {
                title: "One queue, every channel",
                body: "No separate list to check for phone orders versus QR orders.",
              },
              {
                title: "Station filtering",
                body: "Kitchen and bar each see only what they need to make.",
              },
              {
                title: "Late tickets stand out",
                body: "Ticket colour changes as a ticket ages, so nothing sits unnoticed.",
              },
              {
                title: "Sold out stays in sync",
                body: "Marking an item here updates the guest-facing menu right away.",
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
              title="Kitchen and bar, live"
              media={
                <Screenshot
                  src="/screenshots/restaurant-kitchen-ticket-queue.png"
                  alt="Kitchen and bar screen with two tickets still in the guest undo window, a station filter, and a Sold out list with a Mark sold out button for each item"
                  caption="The kitchen and bar screen from a test venue: two fresh tickets waiting out the guest’s undo window, and the sold-out list below."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>Live tickets and the sold-out list, as the kitchen and bar screen shows them.</p>
            </Story>
            <Story
              reverse
              title="What an ageing ticket looks like"
              media={
                <figure className="mock-wrap">
                  <KitchenTicketsMock />
                  <figcaption className="mock-caption">
                    <ExampleTag />
                    Illustration with example tickets.
                  </figcaption>
                </figure>
              }
            >
              <p>
                A fresh ticket and one that has waited too long. The waiting time is on every ticket,
                and the colour changes as it grows.
              </p>
            </Story>
          </div>
        </div>
      </section>

      <Faq
        heading="Kitchen queue FAQ"
        entries={[
          {
            question: "Do QR, waiter and phone orders all show up in the same kitchen queue?",
            answer:
              "Yes. Every order, whatever its channel, becomes a ticket in the same queue. Phone orders can only be started once a manager or owner has accepted them.",
          },
          {
            question: "Can kitchen and bar staff filter what they see?",
            answer:
              "Yes. Tickets can be filtered by station, so kitchen staff see kitchen items and bar staff see bar items.",
          },
          {
            question: "What if a guest places a QR order by mistake?",
            answer:
              "There's a short undo window after a guest places an order, before the kitchen can start it.",
          },
          {
            question: "How does marking an item sold out affect guests?",
            answer:
              "Marking an item sold out, or available again, from the kitchen and bar screen updates live, and the guest QR menu reflects it immediately.",
          },
        ]}
      />

      <RelatedLinks
        links={[
          { href: "/qr-ordering", label: "See how QR orders reach the kitchen" },
          { href: "/restaurant-staff-management", label: "See how tables and staff are assigned" },
          { href: "/pricing", label: "Ask about pricing" },
          { href: "/contact", label: "Contact us to see a live demo" },
        ]}
      />

      <CtaBand
        heading="Give your kitchen one queue to work from"
        body="Book a demo and see how orders from every channel land in a single kitchen and bar queue."
      />
    </main>
  );
}
