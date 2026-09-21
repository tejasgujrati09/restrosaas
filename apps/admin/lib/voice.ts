import type { Tone } from "@restosaas/ui";

/** How a provisioning phase reads on the admin screen. The phase values come from the API. */
const PHASES: Record<string, { label: string; tone: Tone }> = {
  unavailable: { label: "Not set up", tone: "neutral" },
  off: { label: "Off", tone: "neutral" },
  setting_up: { label: "Setting up", tone: "info" },
  active: { label: "Active", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  turning_off: { label: "Turning off", tone: "info" },
};

export function phaseView(phase: string): { label: string; tone: Tone } {
  return PHASES[phase] ?? { label: phase, tone: "neutral" };
}

/** Ask again quickly only while a job is still running. */
export function isInFlight(phase: string): boolean {
  return phase === "setting_up" || phase === "turning_off";
}

/** What "allowed" means, in the two forms the control shows. */
export function allowanceCopy(allowed: boolean): { headline: string; body: string } {
  return allowed
    ? { headline: "● Enabled", body: "Customers can place orders through the restaurant's voice agent, once its owner switches it on." }
    : { headline: "○ Disabled", body: "Voice ordering is currently unavailable for this restaurant." };
}

const STEP_LABEL: Record<string, string> = {
  checking: "Checking",
  number: "Phone number",
  agent: "Voice agent",
  configure: "Order integration",
  link: "Number link",
  route: "Call routing",
  verify: "Verification",
};

export function stepLabel(step: string | null | undefined): string {
  return step ? (STEP_LABEL[step] ?? step) : "";
}
