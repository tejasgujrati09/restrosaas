"use client";

import { useRef, useState, type FormEvent } from "react";
import { CONTACT_EMAIL } from "@/lib/site";

const VENUE_TYPES = ["Restaurant", "Bar", "Club", "Café"];
const TABLE_COUNTS = ["Under 15", "15 to 30", "31 to 60", "More than 60"];

/** A 10-digit Indian mobile number, ignoring spaces and dashes. */
export function isIndianMobile(value: string): boolean {
  return /^[6-9]\d{9}$/.test(value.replace(/\D/g, ""));
}

/**
 * Demo request form. There is no form backend: submitting validates the phone number and then
 * opens the visitor's email app with the details addressed to CONTACT_EMAIL. Nothing is sent
 * by the site itself, so there is no "sent" confirmation — only a note about the email app.
 */
export function DemoForm({ idPrefix = "demo", withMessage = false }: { idPrefix?: string; withMessage?: boolean }) {
  const [phoneError, setPhoneError] = useState(false);
  const [opened, setOpened] = useState(false);
  const phoneRef = useRef<HTMLInputElement>(null);
  const id = (name: string) => `${idPrefix}-${name}`;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const get = (k: string) => String(data.get(k) ?? "").trim();

    const bad = !isIndianMobile(get("phone"));
    setPhoneError(bad);
    if (bad) {
      phoneRef.current?.focus();
      return;
    }
    if (!form.reportValidity()) return;

    const lines = [
      `Name: ${get("name")}`,
      `Phone: +91 ${get("phone").replace(/\D/g, "")}`,
      `Venue: ${get("venue")}`,
      `City: ${get("city")}`,
      `Type of venue: ${get("type")}`,
      `Number of tables: ${get("tables")}`,
    ];
    if (withMessage && get("message")) lines.push("", get("message"));
    const subject = `Demo request: ${get("venue") || "new venue"}`;
    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join("\n"))}`;
    setOpened(true);
  }

  return (
    <form className="demo-form" onSubmit={handleSubmit} noValidate>
      <div className="form-grid">
        <div className="field">
          <label className="field-label" htmlFor={id("name")}>
            Your name
          </label>
          <input id={id("name")} name="name" autoComplete="name" required />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={id("phone")}>
            Phone number
          </label>
          <div className="phone-in">
            <span aria-hidden="true">+91</span>
            <input
              ref={phoneRef}
              id={id("phone")}
              name="phone"
              type="tel"
              inputMode="numeric"
              autoComplete="tel-national"
              maxLength={12}
              placeholder="98765 43210"
              required
              aria-invalid={phoneError}
              aria-describedby={id("phone-err")}
              onChange={() => phoneError && setPhoneError(false)}
            />
          </div>
          <span className="field-error" id={id("phone-err")} hidden={!phoneError}>
            Enter a 10-digit mobile number.
          </span>
        </div>
        <div className="field">
          <label className="field-label" htmlFor={id("venue")}>
            Venue name
          </label>
          <input id={id("venue")} name="venue" autoComplete="organization" required />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={id("city")}>
            City
          </label>
          <input id={id("city")} name="city" autoComplete="address-level2" required />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={id("type")}>
            Type of venue
          </label>
          <select id={id("type")} name="type" defaultValue={VENUE_TYPES[0]}>
            {VENUE_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor={id("tables")}>
            Number of tables
          </label>
          <select id={id("tables")} name="tables" defaultValue={TABLE_COUNTS[1]}>
            {TABLE_COUNTS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>
        {withMessage ? (
          <div className="field full">
            <label className="field-label" htmlFor={id("message")}>
              Anything you&rsquo;d like us to know? <span className="hint">(optional)</span>
            </label>
            <textarea id={id("message")} name="message" rows={4} />
          </div>
        ) : null}
      </div>
      <button className="btn btn-lg wide" type="submit">
        Request a demo
      </button>
      <p className="hint form-note" role="status">
        {opened
          ? `Your email app should now be open with these details. Nothing is sent until you send that email. If it didn't open, write to ${CONTACT_EMAIL}.`
          : `This opens your email app with the details addressed to ${CONTACT_EMAIL}. There is no automated form backend yet.`}
      </p>
    </form>
  );
}
