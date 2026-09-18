import { formatInr } from "@restosaas/ui";
import type { Totals } from "@/lib/types";

/** Tax split and service charge as separate lines, straight from the API's numbers. */
export function TotalsTable({
  totals,
  onToggleServiceCharge,
  busy,
}: {
  totals: Totals;
  onToggleServiceCharge?: (removed: boolean) => void;
  busy?: boolean;
}) {
  const taxes = totals.cgst_paise + totals.sgst_paise + totals.liquor_vat_paise;
  const lead = totals.prices_include_tax ? "Included in prices: " : "Added: ";
  return (
    <dl className="totals">
      <div>
        <dt>Items</dt>
        <dd>{formatInr(totals.items_paise)}</dd>
      </div>
      {taxes > 0 ? (
        <>
          {totals.cgst_paise > 0 ? (
            <div className="sub">
              <dt>{lead}CGST</dt>
              <dd>{formatInr(totals.cgst_paise)}</dd>
            </div>
          ) : null}
          {totals.sgst_paise > 0 ? (
            <div className="sub">
              <dt>{lead}SGST</dt>
              <dd>{formatInr(totals.sgst_paise)}</dd>
            </div>
          ) : null}
          {totals.liquor_vat_paise > 0 ? (
            <div className="sub">
              <dt>{lead}VAT</dt>
              <dd>{formatInr(totals.liquor_vat_paise)}</dd>
            </div>
          ) : null}
        </>
      ) : null}
      {totals.service_charge_bp > 0 ? (
        <div>
          <dt className={totals.service_charge_removed ? "struck" : undefined}>Service charge</dt>
          <dd>{totals.service_charge_removed ? "Removed" : formatInr(totals.service_charge_paise)}</dd>
        </div>
      ) : null}
      <div className="grand">
        <dt>Total (estimate)</dt>
        <dd>{formatInr(totals.estimated_total_paise)}</dd>
      </div>
      {onToggleServiceCharge && totals.service_charge_bp > 0 ? (
        <button type="button" className="secondary" disabled={busy} onClick={() => onToggleServiceCharge(!totals.service_charge_removed)}>
          {totals.service_charge_removed ? "Add service charge back" : "Remove service charge"}
        </button>
      ) : null}
    </dl>
  );
}
