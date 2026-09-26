import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { Screenshot } from "@/components/Screenshot";
import { CtaBand } from "@/components/Cta";
import { Faq } from "@/components/Faq";
import { AnalyticsMock, ExampleTag } from "@/components/mocks";
import { Benefits, PageHeader, RelatedLinks, SectionHead, Steps, Story } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "Restaurant Operational Analytics",
  description:
    "Overview, kitchen, staff, menu and table analytics panels with date ranges and CSV export. Every figure is labelled order value, never revenue.",
  path: "/restaurant-analytics",
});

export default function AnalyticsPage() {
  return (
    <main>
      <PageHeader label="Analytics" title="Operational Analytics">
        Overview, kitchen, staff, menu and table panels with date ranges and CSV export, labelled
        honestly, with no billing system behind the numbers.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap">
          <SectionHead label="What it is" title="Numbers that say what they are" titleId="what-heading" />
          <div className="prose">
            <p>
              Analytics is split into overview, kitchen, staff, menu and table panels, each with a
              date range and CSV export. Because there is no billing or payment system yet, every
              figure is labelled &ldquo;order value&rdquo;, never &ldquo;revenue&rdquo;. Nothing here
              claims to track tax, discounts or payment methods, and there&rsquo;s no forecasting.
            </p>
          </div>
        </div>
      </section>

      <section className="section alt" aria-labelledby="how-heading">
        <div className="wrap">
          <SectionHead label="How it works" title="From orders to a CSV" titleId="how-heading" />
          <Steps
            steps={[
              {
                title: "Orders feed the numbers",
                body: "QR, waiter and accepted phone orders all count, the same way they all land on one Orders screen.",
              },
              {
                title: "Pick a panel",
                body: "Overview, kitchen, staff, menu or table, each showing what matters for that part of the operation.",
              },
              {
                title: "Set a date range",
                body: "Every panel can be filtered to the period you care about.",
              },
              {
                title: "Export to CSV",
                body: "Take the underlying numbers to a spreadsheet or your accountant.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section" aria-labelledby="benefits-heading">
        <div className="wrap">
          <SectionHead label="Benefits" title="Why it’s useful" titleId="benefits-heading" />
          <Benefits
            items={[
              {
                title: "Honest labelling",
                body: "“Order value”, not revenue: no overclaiming what the numbers mean.",
              },
              {
                title: "Five focused panels",
                body: "Overview, kitchen, staff, menu and table, not one generic dashboard.",
              },
              {
                title: "CSV export",
                body: "Take the numbers to a spreadsheet whenever you need them.",
              },
              {
                title: "No invented charts",
                body: "A date range with no orders says exactly that, instead of showing a made-up chart.",
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
              title="The overview panel"
              media={
                <Screenshot
                  src="/screenshots/restaurant-analytics-dashboard.png"
                  alt="Analytics overview for the last 7 days with Overview, Kitchen, Staff, Menu and Tables tabs, KPI cards for rounds and order value, and No data where there is nothing to measure yet"
                  caption="The analytics overview from a test venue with two rounds. Figures are order value, and prep times say “No data” rather than guessing."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                The overview panel from a test venue. Every figure is order value, and where there is nothing
                to measure yet it says &ldquo;No data&rdquo;. A range with no orders at all says &ldquo;No
                orders in this range&rdquo; instead of drawing an empty chart.
              </p>
            </Story>
            <Story
              reverse
              title="With a week of orders"
              media={
                <figure className="mock-wrap">
                  <AnalyticsMock />
                  <figcaption className="mock-caption">
                    <ExampleTag />
                    Illustration. Example figures.
                  </figcaption>
                </figure>
              }
            >
              <p>
                Once orders come in, the overview shows rounds, order value, average order value and
                prep times for the range you pick. The figures in this illustration are examples.
              </p>
            </Story>
            <Story
              title="What feeds the numbers"
              media={
                <Screenshot
                  src="/screenshots/restaurant-unified-orders-dashboard.png"
                  alt="Orders screen with New, In progress, Ready, Completed and Cancelled tabs, a source filter, and two new QR orders for tables T1 and T2"
                  caption="The Orders screen from a test venue: status tabs, a source filter, and each order tagged with its source."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                Analytics is built from the same orders as the Orders screen: QR, waiter and phone
                orders together, each with a source tag.
              </p>
            </Story>
          </div>
        </div>
      </section>

      <Faq
        heading="Analytics FAQ"
        entries={[
          {
            question: "Does analytics track revenue, tax or payments?",
            answer:
              "No. There's no billing or payment system yet, so nothing in analytics claims to track revenue, tax, discounts or payment methods. Every figure is labelled order value.",
          },
          {
            question: "What panels are available?",
            answer: "Overview, kitchen, staff, menu and table, each with date-range filtering.",
          },
          {
            question: "Can I export the data?",
            answer: "Yes, every panel supports CSV export.",
          },
          {
            question: "Is there any forecasting?",
            answer: "No. Analytics reports on what happened in the selected date range, with no forecasting.",
          },
        ]}
      />

      <RelatedLinks
        links={[
          { href: "/restaurant-kitchen-management", label: "See the kitchen queue that feeds these numbers" },
          { href: "/restaurant-staff-management", label: "See staff and table assignment" },
          { href: "/pricing", label: "Ask about pricing" },
          { href: "/contact", label: "Contact us to see a live demo" },
        ]}
      />

      <CtaBand
        heading="See your own order data, honestly labelled"
        body="Book a demo and watch the overview fill in as real orders come through."
      />
    </main>
  );
}
