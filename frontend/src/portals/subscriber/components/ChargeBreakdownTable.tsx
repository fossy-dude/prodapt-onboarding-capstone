/**
 * ChargeBreakdownTable component for displaying CDR charge details (Story 5.7).
 *
 * Renders a collapsible table showing detailed charge breakdown information
 * including event type, duration/data, rate, charge amount, and balance impact.
 */

import { useState } from "react";

interface ChargeBreakdownTableProps {
  readonly cdr_id: string;
  readonly event_type: string;
  readonly duration_or_data: string;
  readonly rate_per_unit: number;
  readonly charge_paise: number;
  readonly balance_before: number;
  readonly balance_after: number;
}

/**
 * Format paise to rupees string (e.g., 15000 → "₹150.00").
 */
function formatRupees(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

/**
 * Format rate per unit based on event type.
 */
function formatRate(ratePaise: number, eventType: string): string {
  const rupees = formatRupees(ratePaise);
  switch (eventType) {
    case "voice":
      return `${rupees}/min`;
    case "data":
      return `${rupees}/MB`;
    case "sms":
      return `${rupees}/SMS`;
    default:
      return rupees;
  }
}

/**
 * Get human-readable event type label.
 */
function getEventTypeLabel(eventType: string): string {
  switch (eventType) {
    case "voice":
      return "Voice Call";
    case "data":
      return "Data Usage";
    case "sms":
      return "SMS";
    default:
      return eventType.charAt(0).toUpperCase() + eventType.slice(1);
  }
}

/**
 * ChargeBreakdownTable component.
 *
 * Displays charge breakdown in a collapsible table format using Tailwind
 * disclosure pattern. Shows event details, rates, charges, and balance impact.
 */
function ChargeBreakdownTable({
  cdr_id,
  event_type,
  duration_or_data,
  rate_per_unit,
  charge_paise,
  balance_before,
  balance_after,
}: ChargeBreakdownTableProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const eventLabel = getEventTypeLabel(event_type);
  const rateDisplay = formatRate(rate_per_unit, event_type);
  const chargeDisplay = formatRupees(charge_paise);
  const balanceBeforeDisplay = formatRupees(balance_before);
  const balanceAfterDisplay = formatRupees(balance_after);

  return (
    <article className="rounded-lg bg-white shadow-sm border border-neutral-200 overflow-hidden">
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-neutral-50 transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-3">
          <span
            className={`transform transition-transform duration-200 ${isExpanded ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          <span className="font-medium text-neutral-900">{eventLabel}</span>
          <span className="text-sm text-neutral-600">{duration_or_data}</span>
        </div>
        <span className="font-semibold text-neutral-900">{chargeDisplay}</span>
      </button>

      {/* Expandable content */}
      {isExpanded && (
        <div className="border-t border-neutral-200 bg-neutral-50">
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-b border-neutral-200">
                <td className="px-4 py-2 text-neutral-600 font-medium">
                  Event Type
                </td>
                <td className="px-4 py-2 text-neutral-900 text-right">
                  {eventLabel}
                </td>
              </tr>
              <tr className="border-b border-neutral-200">
                <td className="px-4 py-2 text-neutral-600 font-medium">
                  Duration/Data
                </td>
                <td className="px-4 py-2 text-neutral-900 text-right">
                  {duration_or_data}
                </td>
              </tr>
              <tr className="border-b border-neutral-200">
                <td className="px-4 py-2 text-neutral-600 font-medium">Rate</td>
                <td className="px-4 py-2 text-neutral-900 text-right">
                  {rateDisplay}
                </td>
              </tr>
              <tr className="border-b border-neutral-200">
                <td className="px-4 py-2 text-neutral-600 font-medium">
                  Charge
                </td>
                <td className="px-4 py-2 text-neutral-900 text-right font-semibold">
                  {chargeDisplay}
                </td>
              </tr>
              <tr className="border-b border-neutral-200">
                <td className="px-4 py-2 text-neutral-600 font-medium">
                  Balance Before
                </td>
                <td className="px-4 py-2 text-neutral-900 text-right">
                  {balanceBeforeDisplay}
                </td>
              </tr>
              <tr>
                <td className="px-4 py-2 text-neutral-600 font-medium">
                  Balance After
                </td>
                <td className="px-4 py-2 text-neutral-900 text-right">
                  {balanceAfterDisplay}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="px-4 py-2 text-xs text-neutral-500 text-center border-t border-neutral-200">
            CDR ID: {cdr_id.slice(0, 8)}...
          </div>
        </div>
      )}
    </article>
  );
}

export { ChargeBreakdownTable };
export type { ChargeBreakdownTableProps };
