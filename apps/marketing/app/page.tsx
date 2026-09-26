import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Icon, type IconName } from "@restosaas/ui";
import { pageMetadata } from "@/lib/seo";
import { SITE_NAME, SITE_TAGLINE, SITE_URL } from "@/lib/site";
import { JsonLd } from "@/components/JsonLd";
import { Screenshot } from "@/components/Screenshot";
import { DemoForm } from "@/components/DemoForm";
import { RoleTabs, type RoleTab } from "@/components/RoleTabs";
import { SectionHead, Story, Ticks } from "@/components/blocks";
import {
  AnalyticsMock,
  ExampleTag,
  FloorCard,
  GuestMenuPhone,
  GuestTabMock,
  KitchenTicketsMock,
  OrdersMock,
  WaiterFloorMock,
} from "@/components/mocks";

export const metadata: Metadata = pageMetadata({
  title: "QR Table Ordering and AI Phone Ordering for Restaurants in India",
  description:
    "Tably is QR table ordering and AI phone ordering for Indian restaurants, bars and cafés: guests order from their own phone, every order lands on one Orders screen and one kitchen queue.",
  path: "/",
});

function Mock({ children, note = "Example data" }: { children: ReactNode; note?: string }) {
  return (
    <figure className="mock-wrap">
      {children}
      <figcaption className="mock-caption">
        <ExampleTag />
        {note}
      </figcaption>
    </figure>
  );
}

const PROBLEMS = [
  {
    label: "Slow first order",
    quote: "“We’ve been sitting here fifteen minutes.”",
    context: "At peak, guests wait for a waiter to reach them before anything happens.",
    fix: "Guests scan the table QR and order from their own phone. No app to install. You can also have a waiter confirm the table first.",
  },
  {
    label: "Waiter bottleneck",
    quote: "“One waiter, twelve tables.”",
    context: "Orders queue up while one person keys in every table’s round.",
    fix: "Orders go straight to the kitchen and bar queue. Waiters see their own tables and guest requests live, and spend their time on service.",
  },
  {
    label: "Bill disputes",
    quote: "“I didn’t order that.”",
    context: "The bill arrives with items the guest doesn’t recognise.",
    fix: "Guests see an itemised tab that shows who added each line, and confirm anything a waiter adds above a set amount.",
  },
];

const HOW: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "qr",
    title: "Scan the table QR",
    body: "Each table has its own code. The menu opens in the browser, already set to that table.",
  },
  {
    icon: "book",
    title: "Order with options",
    body: "Modifiers, notes and quantity, with happy-hour prices applied automatically. Friends at the table can order onto the same tab from their own phones.",
  },
  {
    icon: "grid",
    title: "Watch the tab live",
    body: "Every line shows who added it. If a waiter adds something above your set amount, the guest confirms it first.",
  },
  {
    icon: "bell",
    title: "Call for service",
    body: "One tap to call a waiter, ask for water or request the bill. Requests show up live on the waiter’s screen.",
  },
];

const FACTS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "user",
    title: "Phone-number sign-in",
    body: "Owners and staff sign in with their phone number and a one-time code. No email and no passwords anywhere.",
  },
  {
    icon: "phone",
    title: "Hindi, English and Hinglish",
    body: "The AI phone agent talks the way your callers do, and sells only from your live menu.",
  },
  {
    icon: "tag",
    title: "Rupee pricing and happy hours",
    body: "Prices in rupees, veg and non-veg marks with a veg-only filter for guests, and happy-hour windows by day and time, applied on the guest’s menu automatically.",
  },
  {
    icon: "users",
    title: "WhatsApp staff invites",
    body: "Invite waiters, kitchen, bar and managers with a WhatsApp link. Each person gets their own role.",
  },
  {
    icon: "sliders",
    title: "Self-serve setup",
    body: "Sign up with a phone number, add your menu and tables, and print your QR codes without waiting on anyone.",
  },
  {
    icon: "chart",
    title: "Honest numbers",
    body: "Analytics reports order value, never “revenue”, with CSV export and no forecasting.",
  },
];

const ROLES: RoleTab[] = [
  {
    id: "guest",
    label: "Guest",
    panel: (
      <>
        <div className="role-copy">
          <h3>A tab guests can trust</h3>
          <Ticks
            items={[
              "A live, itemised tab that shows who added every line",
              "Items a waiter adds above a set amount need the guest’s OK",
              "Friends at the table order onto the same tab from their own phones",
              "Call a waiter, ask for water or request the bill in one tap",
            ]}
          />
          <Link className="role-link" href="/qr-ordering">
            How QR table ordering works
          </Link>
        </div>
        <Mock>
          <GuestTabMock />
        </Mock>
      </>
    ),
  },
  {
    id: "waiter",
    label: "Waiter",
    panel: (
      <>
        <div className="role-copy">
          <h3>Your tables at a glance</h3>
          <Ticks
            items={[
              "The tables a manager assigned to you, with orders and requests in real time",
              "Add items for guests who’d rather not use their phone",
              "Open a tab at a table, confirm a table, move a tab or merge two",
              "Water, waiter and bill requests, marked done in one tap",
            ]}
          />
          <p className="theme-note">
            <span className="badge">Dark theme</span>Floor, kitchen and bar staff work in dim light.
          </p>
          <Link className="role-link" href="/restaurant-staff-management">
            How staff roles and table assignment work
          </Link>
        </div>
        <Mock>
          <WaiterFloorMock />
        </Mock>
      </>
    ),
  },
  {
    id: "kitchen",
    label: "Kitchen and bar",
    panel: (
      <>
        <div className="role-copy">
          <h3>Tickets that show what’s waiting</h3>
          <Ticks
            items={[
              "QR, waiter and accepted phone orders arrive as tickets in one queue",
              "Each ticket shows how long it has waited, and changes colour as it ages",
              "Filter by station, then mark tickets started and ready",
              "Mark an item sold out and it greys out on every guest’s menu",
            ]}
          />
          <Link className="role-link" href="/restaurant-kitchen-management">
            How the kitchen ticket queue works
          </Link>
        </div>
        <Mock>
          <KitchenTicketsMock />
        </Mock>
      </>
    ),
  },
  {
    id: "manager",
    label: "Manager",
    panel: (
      <>
        <div className="role-copy">
          <h3>Every order, from every channel, in one place</h3>
          <Ticks
            items={[
              "One Orders screen for QR, waiter and phone orders: New, In progress, Ready, Completed and Cancelled, each with its source",
              "Accept or decline orders the AI phone agent takes; declining needs a reason",
              "A timeline on each order of what happened, when and by whom",
              "Assign tables to waiters and set happy-hour pricing windows",
            ]}
          />
          <Link className="role-link" href="/ai-voice-ordering">
            How AI voice ordering works
          </Link>
        </div>
        <Mock>
          <OrdersMock />
        </Mock>
      </>
    ),
  },
  {
    id: "owner",
    label: "Owner",
    panel: (
      <>
        <div className="role-copy">
          <h3>Set up once, from your phone</h3>
          <Ticks
            items={[
              "Menu with categories and modifiers, or import it from a CSV",
              "Print table QR codes (one PDF page per zone) and a menu PDF from your current menu",
              "Invite staff by WhatsApp link and give each person one of five roles",
              "Analytics panels for overview, kitchen, staff, menu and tables, with CSV export",
            ]}
          />
          <Link className="role-link" href="/restaurant-analytics">
            What the analytics show
          </Link>
        </div>
        <Mock note="Example figures.">
          <AnalyticsMock />
        </Mock>
      </>
    ),
  },
];

export default function HomePage() {
  const softwareApplicationSchema = {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE_NAME,
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web",
    url: SITE_URL,
    description: SITE_TAGLINE,
  };

  return (
    <main id="top">
      <JsonLd data={softwareApplicationSchema} />

      {/* ===== Hero ===== */}
      <section className="hero" aria-labelledby="hero-title">
        <div className="wrap">
          <div className="hero-copy">
            <span className="label">QR, waiter and phone ordering</span>
            <h1 id="hero-title">
              Orders start at the table, <em>not at the counter.</em>
            </h1>
            <p className="lede">
              Guests scan a QR and order from their own phone, callers talk to an AI phone agent,
              and waiters add rounds from the floor. Every order lands on one Orders screen and one
              kitchen queue. Built for Indian restaurants, bars and cafés.
            </p>
            <div className="hero-actions">
              <a className="btn btn-lg" href="#demo">
                Book a demo
              </a>
              <a className="btn btn-lg secondary" href="#how">
                See how it works
              </a>
            </div>
            <ul className="hero-facts">
              <li>
                <Icon name="check" />
                No app for guests
              </li>
              <li>
                <Icon name="check" />
                Phone orders in Hindi, English or Hinglish
              </li>
              <li>
                <Icon name="check" />
                Sign in by phone, no passwords
              </li>
            </ul>
          </div>

          <figure className="stage">
            <GuestMenuPhone />
            <FloorCard />
            <figcaption className="stage-caption">
              <ExampleTag />
              Illustration: a guest&rsquo;s menu and a waiter&rsquo;s tables, with example data.
            </figcaption>
          </figure>
        </div>
      </section>

      {/* ===== Problems ===== */}
      <section className="section alt" aria-labelledby="problems-title">
        <div className="wrap">
          <SectionHead label={`Why ${SITE_NAME}`} title="Where a busy Saturday goes wrong" titleId="problems-title">
            Three situations most venues will recognise. {SITE_NAME} is built around fixing them.
          </SectionHead>
          <div className="problems">
            {PROBLEMS.map((p) => (
              <article className="problem" key={p.label}>
                <span className="label">{p.label}</span>
                <p className="quote">{p.quote}</p>
                <p className="muted">{p.context}</p>
                <p className="fix">
                  <Icon name="check" />
                  <span>{p.fix}</span>
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ===== How it works ===== */}
      <section className="section" id="how" aria-labelledby="how-title">
        <div className="wrap">
          <SectionHead label="How it works" title="From seat to bill request, on the guest’s own phone" titleId="how-title" />
          <ol className="steps">
            {HOW.map((s) => (
              <li className="how-step" key={s.title}>
                <div className="how-step-top">
                  <Icon name={s.icon} />
                </div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ===== Phone + Orders (real screenshots) ===== */}
      <section className="section alt" id="phone" aria-labelledby="phone-title">
        <div className="wrap">
          <SectionHead label="Beyond the table" title="Phone orders, and one screen for every order" titleId="phone-title">
            An AI agent can answer your phone, and every order, however it came in, lands in the same
            place.
          </SectionHead>
          <div className="stories">
            <Story
              label="AI voice ordering"
              title="An AI agent takes the call, a person accepts the order"
              media={
                <Screenshot
                  src="/screenshots/restaurant-phone-orders-screen.png"
                  alt="Phone orders screen with the note that orders taken by the phone assistant wait here until a manager accepts them, currently showing no phone orders waiting"
                  caption="The Phone orders screen, here with nothing waiting. Orders the AI agent takes wait here until a manager or owner accepts them."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                Callers order in Hindi, English or Hinglish. The agent sells only from your live menu
                and never confirms an order itself: a manager or owner accepts or declines each one.
                Voice ordering is switched on per venue, once the platform has allowed it.
              </p>
              <Link href="/ai-voice-ordering">See how AI voice ordering works</Link>
            </Story>
            <Story
              reverse
              label="Orders"
              title="QR, waiter and phone orders on one screen"
              media={
                <Screenshot
                  src="/screenshots/restaurant-unified-orders-dashboard.png"
                  alt="Orders screen with New, In progress, Ready, Completed and Cancelled tabs, a source filter, and two new QR orders for tables T1 and T2"
                  caption="The Orders screen from a test venue: status tabs, a source filter, and each order tagged with its source (here, QR order)."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                Orders are grouped as New, In progress, Ready, Completed and Cancelled, with a source
                tag on each, so nobody checks three places to find out what&rsquo;s waiting.
              </p>
              <Link href="/restaurant-kitchen-management">See where orders go in the kitchen</Link>
            </Story>
          </div>
        </div>
      </section>

      {/* ===== Roles ===== */}
      <section className="section" id="roles" aria-labelledby="roles-title">
        <div className="wrap">
          <SectionHead label="One product, every role" title="Everyone sees exactly what their job needs" titleId="roles-title">
            Guests, waiters, the kitchen and bar, managers and owners each get their own view. Floor
            staff work in a dark theme that&rsquo;s easy on the eyes at night.
          </SectionHead>
          <RoleTabs tabs={ROLES} label="Roles" />
        </div>
      </section>

      {/* ===== Built for Indian venues ===== */}
      <section className="section alt" id="india" aria-labelledby="india-title">
        <div className="wrap">
          <SectionHead label="Made for Indian venues" title="Built for how Indian venues actually run" titleId="india-title">
            From the way staff sign in to the languages your callers speak.
          </SectionHead>
          <div className="facts">
            {FACTS.map((f) => (
              <div className="fact" key={f.title}>
                <span className="f-ic">
                  <Icon name={f.icon} />
                </span>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ===== Setup path ===== */}
      <section className="section" aria-labelledby="setup-title">
        <div className="wrap">
          <SectionHead label="Getting started" title="From sign-up to printed QR codes" titleId="setup-title">
            Four steps, all done by the owner.
          </SectionHead>
          <ol className="path">
            <li>
              <h3>Sign up</h3>
              <p>Create your venue with just your phone number and a one-time code.</p>
            </li>
            <li>
              <h3>Menu</h3>
              <p>Add items with modifiers, or import your whole menu from a CSV.</p>
            </li>
            <li>
              <h3>Tables and QR</h3>
              <p>Add tables by zone and print a PDF of QR codes, one page per zone.</p>
            </li>
            <li>
              <h3>Staff</h3>
              <p>Invite waiters, kitchen, bar and managers with a WhatsApp link.</p>
            </li>
          </ol>
          <div className="roadmap">
            <span className="label">Coming later</span>
            <span className="badge info">In-app payments and GST billing</span>
            <span className="badge info">Kitchen display screens</span>
            <span className="badge info">Menu import from a photo</span>
            <span className="badge info">Tally export</span>
            <span className="badge info">Multi-outlet dashboard</span>
            <p className="hint">Planned, not available today. No dates yet.</p>
          </div>
        </div>
      </section>

      {/* ===== Pricing + demo ===== */}
      <section className="section alt" id="pricing" aria-labelledby="pricing-title">
        <div className="wrap">
          <SectionHead label="Pricing and demo" title="See it on your own menu" titleId="pricing-title">
            Tell us about your venue and we&rsquo;ll set up a demo with your tables and your dishes.
          </SectionHead>
          <div className="close-grid">
            <div className="pricing">
              <span className="label">Pricing</span>
              <h3>Pricing on request</h3>
              <p>
                We haven&rsquo;t published a price list yet. We&rsquo;re working with a small number of
                pilot venues, so pricing is something we talk through with you, based on your venue.
              </p>
              <Link href="/pricing" className="btn secondary">
                About pricing
              </Link>
            </div>
            <div className="demo" id="demo">
              <h3>Book a demo</h3>
              <p>Share a few details and we&rsquo;ll get in touch to arrange it.</p>
              <DemoForm idPrefix="home-demo" />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
