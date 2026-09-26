import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { Screenshot } from "@/components/Screenshot";
import { CtaBand } from "@/components/Cta";
import { Faq } from "@/components/Faq";
import { Benefits, PageHeader, RelatedLinks, SectionHead, Steps, Story } from "@/components/blocks";

export const metadata: Metadata = pageMetadata({
  title: "AI Voice Ordering for Restaurants",
  description:
    "An AI phone agent built on Gupshup VoiceAI answers calls and takes orders in Hindi, English and Hinglish, strictly from the restaurant's live menu. A person always accepts every order.",
  path: "/ai-voice-ordering",
});

export default function AiVoiceOrderingPage() {
  return (
    <main>
      <PageHeader label="AI voice ordering" title="AI Voice Ordering">
        An AI phone agent answers calls and takes orders in Hindi, English or Hinglish, but it never
        confirms an order by itself. A manager or owner always has the final say.
      </PageHeader>

      <section className="section" aria-labelledby="what-heading">
        <div className="wrap">
          <SectionHead label="What it is" title="A phone agent that sells only your menu" titleId="what-heading" />
          <div className="prose">
            <p>
              The AI voice ordering agent is built on Gupshup VoiceAI. It answers calls to your
              venue&rsquo;s line and takes an order in Hindi, English or Hinglish, selling strictly
              from your own live menu. It never invents an item or a price. Every phone order still
              needs a manager or owner to review and accept it before it&rsquo;s confirmed.
            </p>
            <p>
              It&rsquo;s gated by two separate switches, so an owner can&rsquo;t turn it on alone: the
              platform first has to allow voice ordering for that venue, and only then can the owner
              enable it.
            </p>
          </div>
        </div>
      </section>

      <section className="section alt" aria-labelledby="how-heading">
        <div className="wrap">
          <SectionHead label="How it works" title="From ringing phone to accepted order" titleId="how-heading" />
          <Steps
            steps={[
              {
                title: "The platform allows it",
                body: "Voice ordering is off by default for every venue until a platform admin allows it for that venue.",
              },
              {
                title: "The owner switches it on",
                body: "Once allowed, the owner turns voice ordering on from the voice ordering settings screen.",
              },
              {
                title: "A caller talks to the agent",
                body: "In Hindi, English or Hinglish. The agent reads from your live menu, never a generic or invented one.",
              },
              {
                title: "A person accepts it",
                body: "The order waits on the Phone orders screen for a manager or owner to accept, or decline with a reason, before the kitchen can start it.",
              },
            ]}
          />
        </div>
      </section>

      <section className="section" aria-labelledby="benefits-heading">
        <div className="wrap">
          <SectionHead label="Benefits" title="Why it helps on a busy night" titleId="benefits-heading" />
          <Benefits
            items={[
              {
                title: "Calls answered during the rush",
                body: "The agent can take a call while your staff are busy on the floor.",
              },
              {
                title: "Only the real menu",
                body: "It sells strictly from your own menu, never a guessed price or item.",
              },
              {
                title: "A person always confirms",
                body: "The kitchen can’t start a phone order until a manager or owner accepts it.",
              },
              {
                title: "The languages callers use",
                body: "Hindi, English and Hinglish, matching how people actually speak.",
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
              title="Turning voice ordering on"
              media={
                <Screenshot
                  src="/screenshots/ai-voice-ordering-agent-settings.png"
                  alt="Voice ordering settings screen showing voice ordering off, a Turn on voice ordering button, and a four-step explanation of how the phone assistant works"
                  caption="Voice ordering settings: the owner's switch, usable once the platform has allowed it."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                The voice ordering settings screen an owner sees once the platform has allowed voice
                ordering for their venue.
              </p>
            </Story>
            <Story
              reverse
              title="Orders waiting for a person to accept"
              media={
                <Screenshot
                  src="/screenshots/restaurant-phone-orders-screen.png"
                  alt="Phone orders screen with the note that orders taken by the phone assistant wait here until a manager accepts them, currently showing no phone orders waiting"
                  caption="The Phone orders screen, here with nothing waiting. The kitchen only sees a phone order after it is accepted."
                  width={1440}
                  height={960}
                />
              }
            >
              <p>
                Every phone order the agent takes lands here first, waiting for a manager or owner to
                accept it.
              </p>
            </Story>
          </div>
        </div>
      </section>

      <Faq
        heading="AI voice ordering FAQ"
        entries={[
          {
            question: "Can the AI agent confirm an order on its own?",
            answer:
              "No. Every phone order the AI agent takes needs a manager or owner to review and accept it before it's confirmed. The AI never confirms an order by itself.",
          },
          {
            question: "What languages does the AI agent support?",
            answer: "Hindi, English and Hinglish.",
          },
          {
            question: "Can the AI agent sell items that aren't on the menu, or invent prices?",
            answer:
              "No. It sells strictly from the venue's own live menu, never a hardcoded default or a guess.",
          },
          {
            question: "Who can turn voice ordering on for a restaurant?",
            answer:
              "It's gated by two switches: a platform admin must first allow voice ordering for that venue, and only then can the venue's owner enable it.",
          },
          {
            question: "What happens to an order after the AI agent takes it?",
            answer:
              "It appears on the Phone orders screen, waiting. A manager or owner accepts it (or declines it with a reason), and once accepted it shows up on the same Orders screen and kitchen queue as every other channel.",
          },
        ]}
      />

      <RelatedLinks
        links={[
          { href: "/restaurant-kitchen-management", label: "See where accepted phone orders go next" },
          { href: "/qr-ordering", label: "Compare with QR table ordering" },
          { href: "/pricing", label: "Ask about pricing" },
          { href: "/contact", label: "Contact us to see a live demo" },
        ]}
      />

      <CtaBand
        heading="Ask us about voice ordering for your venue"
        body="Voice ordering is enabled venue by venue. Book a demo and we'll walk you through it."
      />
    </main>
  );
}
