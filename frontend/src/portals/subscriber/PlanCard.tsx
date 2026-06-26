import { useNavigate } from "react-router-dom";

import { Badge } from "../../components/ui/Badge";
import type { PlanCatalogueItem } from "../../lib/api";

interface PlanCardProps {
  readonly plan: PlanCatalogueItem;
  readonly isCurrent: boolean;
}

/** Format integer paise as an INR display string (no decimals for plan prices). */
function formatInr(paise: number): string {
  return `₹${(paise / 100).toFixed(0)}`;
}

/** Render a quota value, or "Unlimited" when the allowance is null. */
function quotaText(value: number | null, unit: string): string {
  return value === null ? "Unlimited" : `${value} ${unit}`;
}

/** One browsable plan in the catalogue. */
function PlanCard({ plan, isCurrent }: PlanCardProps) {
  const navigate = useNavigate();

  return (
    <article className="rounded-xl bg-white shadow p-5 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h3 className="text-lg font-semibold text-neutral-900">
            {plan.name}
          </h3>
          <Badge variant="neutral">{plan.validity_days} days</Badge>
        </div>
        {isCurrent && <Badge variant="verified">Current Plan</Badge>}
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-600">
          {quotaText(plan.data_gb, "GB")} data
        </span>
        <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-600">
          {quotaText(plan.voice_minutes, "min")} voice
        </span>
        <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-600">
          {quotaText(plan.sms_count, "SMS")}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-2xl font-bold text-neutral-900">
          {formatInr(plan.price_paise)}
        </p>
        <button
          onClick={() => navigate(`/subscriber/recharge?plan_id=${plan.id}`)}
          disabled={isCurrent}
          className="text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.5 rounded-md"
        >
          {isCurrent ? "Active" : "Recharge"}
        </button>
      </div>
    </article>
  );
}

export { PlanCard };
