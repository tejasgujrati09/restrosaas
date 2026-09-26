"use client";

import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, EmptyState, PageHeader, roleLabel, Skeleton } from "@restosaas/ui";
import { Card, ErrorBanner, Field } from "@/components/ui";
import { useAction, useResource } from "@/components/hooks";
import { api } from "@/lib/api";
import { toE164 } from "@/lib/phone";
import { rolesAt } from "@/lib/session";
import { useToken } from "@/lib/use-token";
import type { Invite, Staff } from "@/lib/types";

const ALL_ROLES = ["waiter", "kitchen", "bar", "manager", "owner"] as const;

export default function StaffPage() {
  const { outletId } = useParams<{ outletId: string }>();
  const base = `/v1/outlets/${outletId}`;
  const staff = useResource<Staff[]>(`${base}/staff`);
  const invites = useResource<Invite[]>(`${base}/invites`);
  // Read after hydration (the token is null on the server), so both renders start the same.
  const token = useToken();
  const isOwner = rolesAt(token, outletId).includes("owner");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<string>("waiter");
  const [created, setCreated] = useState<Invite | null>(null);
  const action = useAction();
  const e164 = toE164(phone);

  async function invite(event: FormEvent) {
    event.preventDefault();
    if (!e164) return;
    let result: Invite | null = null;
    const ok = await action.run(async () => { result = await api<Invite>(`${base}/invites`, { method: "POST", body: { phone: e164, role } }); });
    if (ok && result) { setCreated(result); setPhone(""); invites.reload(); }
  }

  const roleOptions = isOwner ? ALL_ROLES : (["waiter"] as const);

  return (
    <>
      <PageHeader title="Staff" subtitle="Invite your team by mobile number. They join with a one-time code." />
      <Card title="Invite someone">
        <form onSubmit={invite}>
          <div className="row">
            <Field label="Their mobile number" hint="The invite only works for this number.">
              <input inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </Field>
            <Field label="Role">
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {roleOptions.map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
              </select>
            </Field>
            <button type="submit" disabled={action.busy || !e164}>Create invite</button>
          </div>
        </form>
        {created?.link ? (
          <div role="status">
            <p className="ok">Invite ready for {created.phone}.</p>
            <div className="inline">
              {created.whatsapp_url ? <a className="button" href={created.whatsapp_url} target="_blank" rel="noreferrer">Send on WhatsApp</a> : null}
              <button type="button" className="secondary" onClick={() => navigator.clipboard.writeText(created.link ?? "")}>Copy link</button>
            </div>
            <p className="muted">This link is shown only once. It expires in 7 days.</p>
          </div>
        ) : null}
      </Card>

      {invites.data && invites.data.length > 0 ? (
        <Card title="Waiting to join">
          <ul className="list">
            {invites.data.map((i) => (
              <li key={i.id}><span>{i.phone} <Badge>{roleLabel(i.role)}</Badge></span>
                <button type="button" className="danger" onClick={() => action.run(async () => { await api(`${base}/invites/${i.id}`, { method: "DELETE" }); invites.reload(); })}>Cancel</button>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card title="Team">
        <ErrorBanner message={staff.error} onRetry={staff.reload} />
        {!staff.data && !staff.error ? <Skeleton what="your team" lines={3} /> : null}
        {staff.data && staff.data.length === 0 ? <EmptyState title="No one on the team yet">Invite someone above and they will appear here once they join.</EmptyState> : null}
        {staff.data && staff.data.length > 0 ? (
        <table className="stacked">
          <thead><tr><th>Name</th><th>Phone</th><th>Role</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
          <tbody>
            {staff.data?.map((s) => (
              <tr key={s.id}>
                <td data-label="Name">{s.name ?? "—"} {!s.active ? <Badge tone="danger">Inactive</Badge> : null}</td>
                <td data-label="Phone">{s.phone}</td>
                <td data-label="Role">{roleLabel(s.role)}</td>
                <td>
                  <button type="button" className={s.active ? "tertiary" : "secondary"}
                    onClick={() => action.run(async () => { await api(`${base}/staff/${s.id}`, { method: "PATCH", body: { active: !s.active } }); staff.reload(); })}>
                    {s.active ? "Deactivate" : "Reactivate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        ) : null}
      </Card>
    </>
  );
}
