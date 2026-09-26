import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { Screenshot } from "@/components/Screenshot";
import { CtaBand } from "@/components/Cta";
import { Faq } from "@/components/Faq";
import { Benefits, PageHeader, RelatedLinks, SectionHead, Steps, Story } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "Staff Roles and Table Assignment for Restaurants",
  description:
    "Five staff roles with a real permission matrix, WhatsApp invite links with phone-number sign-in, and managers assigning specific tables to specific waiters with a live floor view.",
  path: "/restaurant-staff-management",
});

export default function StaffManagementPage() {
  return (
    <main>
      <PageHeader label="Staff and tables" title="Staff Roles and Table Assignment">
        Real, permission-scoped roles and tables assigned to specific waiters, not one shared login
        where everyone sees everything.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap">
          <SectionHead label="What it is" title="The right view for every person" titleId="what-heading" />
          <div className="prose">
            <p>
              There are five staff roles: waiter, kitchen, bar, manager and owner, each governed by a
              permission matrix rather than a single shared account. Staff are invited with a WhatsApp
              link and sign in with their own phone number. Managers can invite waiters; only owners
              manage every other role.
            </p>
            <p>
              Managers assign specific tables to specific waiters, and a live floor view shows the
              state of every table at a glance. Waiters can move a tab to another table or merge two
              tabs.
            </p>
          </div>
        </div>
      </section>

      <section className="section alt" aria-labelledby="how-heading">
        <div className="wrap">
          <SectionHead label="How it works" title="From invite to a covered floor" titleId="how-heading" />
          <Steps
            steps={[
              {
                title: "Send an invite",
                body: "The owner or a manager sends a WhatsApp link. The new person signs in with their phone number, no password to set up.",
              },
              {
                title: "The role sets what they see",
                body: "Waiter, kitchen, bar, manager and owner each have their own permissions.",
              },
              {
                title: "Assign tables to waiters",
                body: "Table coverage is explicit, from the Assign tables screen, rather than left to whoever notices first.",
              },
              {
                title: "Watch the live floor",
                body: "The floor view shows which tables are free, seated, have an order in progress or have asked for the bill.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section" aria-labelledby="benefits-heading">
        <div className="wrap">
          <SectionHead label="Benefits" title="Why it matters on the floor" titleId="benefits-heading" />
          <Benefits
            items={[
              {
                title: "No shared logins",
                body: "Everyone signs in with their own phone number. No shared password to leak.",
              },
              {
                title: "Clear table ownership",
                body: "Waiters know which tables are theirs, and managers know who’s covering what.",
              },
              {
                title: "Permission-scoped access",
                body: "Kitchen and bar staff see what they need to run their station, not the owner’s view.",
              },
              {
                title: "One live floor view",
                body: "Table state is visible without walking the floor to check.",
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
              title="Roles and invites"
              media={
                <Screenshot
                  src="/screenshots/restaurant-staff-role-management.png"
                  alt="Staff screen with a form to invite someone by mobile number and role, and a team list showing each person’s role"
                  caption="The Staff screen from a test venue: invite by mobile number with a role, then share the invite link (for example on WhatsApp)."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                The Staff screen, where owners and managers manage roles and send WhatsApp invite
                links.
              </p>
            </Story>
            <Story
              reverse
              title="Assigning tables to waiters"
              media={
                <Screenshot
                  src="/screenshots/restaurant-waiter-table-assignments.png"
                  alt="Assign tables screen showing tables assigned to specific waiters"
                  caption="The Assign tables screen: specific tables mapped to specific waiters."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>Managers assign specific tables to specific waiters, so coverage is explicit.</p>
            </Story>
            <Story
              title="The live floor"
              media={
                <Screenshot
                  src="/screenshots/restaurant-floor-table-management.png"
                  alt="Floor view with a legend for free, seated, order in progress and bill requested, showing two tables with orders in progress and two free tables"
                  caption="The live floor view: table state at a glance, without walking the room."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>A real-time view of every table: free, seated, order in progress or bill requested.</p>
            </Story>
          </div>
        </div>
      </section>

      <Faq
        heading="Staff and table assignment FAQ"
        entries={[
          {
            question: "What staff roles are there?",
            answer: "Five roles: waiter, kitchen, bar, manager and owner, each with its own permissions.",
          },
          {
            question: "Who can invite new staff?",
            answer:
              "Managers can invite waiters. Only owners can manage every other role. Invites go out as a WhatsApp link.",
          },
          {
            question: "Does every waiter see every table?",
            answer:
              "No. Managers assign specific tables to specific waiters, so table coverage is explicit rather than open to everyone.",
          },
          {
            question: "How do staff sign in?",
            answer:
              "With their phone number and a one-time code, the same as owners. There are no passwords anywhere in the product.",
          },
        ]}
      />

      <RelatedLinks
        links={[
          { href: "/restaurant-kitchen-management", label: "See how kitchen and bar staff work their queue" },
          { href: "/restaurant-analytics", label: "See staff and table performance in analytics" },
          { href: "/pricing", label: "Ask about pricing" },
          { href: "/contact", label: "Contact us to see a live demo" },
        ]}
      />

      <CtaBand
        heading="Give every role the right view of the floor"
        body="Invite your team by phone number, assign tables, and see the floor live. Book a demo to see it."
      />
    </main>
  );
}
