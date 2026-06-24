import { Badge } from "../../components/ui/Badge";
import { useActivePlan } from "../../hooks/useActivePlan";
import { useUsage } from "../../hooks/useUsage";

/** Days-remaining threshold for the amber "Expiring soon" badge (UI-only). */
const EXPIRY_WARNING_DAYS = 3;

/** Format an ISO expiry as DD MMM YYYY in IST (e.g. "29 Jan 2026"). */
function formatExpiry(iso: string | null): string {
  if (iso === null) {
    return "—";
  }
  return new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

interface QuotaColumnProps {
  readonly label: string;
  readonly allowance: number | null;
  readonly unit: string;
  readonly remaining: number | null;
}

function QuotaColumn({ label, allowance, unit, remaining }: QuotaColumnProps) {
  const isUnlimited = allowance === null;
  return (
    <div className="rounded-lg bg-neutral-50 px-3 py-2 text-center">
      <p className="text-sm font-semibold text-neutral-900">
        {label} {isUnlimited ? "Unlimited" : `${allowance} ${unit}`}
      </p>
      {remaining !== null && !isUnlimited && (
        <p className="text-[11px] text-neutral-500">
          {remaining.toFixed(0)} {unit} left
        </p>
      )}
    </div>
  );
}

/** Active-plan card: name, validity expiry (IST), quotas, and remaining allowances.
 *
 * Remaining allowances are composed on the client from this card's plan quotas
 * (allowance) and GET /usage (used) — usage is NOT re-aggregated here.
 */
function PlanDetailsCard() {
  const { data: plan, isLoading, isError } = useActivePlan();
  const { data: usage } = useUsage();

  if (isLoading) {
    return (
      <div className="rounded-xl bg-white shadow p-6 animate-pulse h-40" />
    );
  }
  if (isError || !plan) {
    return (
      <div className="rounded-xl bg-red-50 border border-red-200 p-6">
        <p className="text-sm text-red-600">Failed to load plan details.</p>
      </div>
    );
  }

  const days = plan.days_remaining;
  const expiringSoon =
    days !== null && days >= 0 && days <= EXPIRY_WARNING_DAYS;

  const remaining = (
    allowance: number | null,
    used: number | null,
  ): number | null => {
    if (allowance === null || used === null) {
      return null;
    }
    return Math.max(0, allowance - used);
  };

  const dataRemainingGb = usage
    ? remaining(plan.quotas.data_gb, usage.data_gb)
    : null;
  const voiceRemaining = usage
    ? remaining(plan.quotas.voice_minutes, usage.voice_minutes.used)
    : null;
  const smsRemaining = usage
    ? remaining(plan.quotas.sms_count, usage.sms.used)
    : null;

  return (
    <div className="rounded-xl bg-white shadow p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-neutral-500 uppercase tracking-wide">
          Active Plan
        </h2>
        {expiringSoon && <Badge variant="pending">Expiring soon</Badge>}
      </div>

      <div className="flex items-baseline justify-between">
        <p className="text-xl font-semibold text-neutral-900">
          {plan.plan_name}
        </p>
        {days !== null && (
          <span className="text-xs text-neutral-400">
            {days < 0
              ? "Expired"
              : `${days} ${days === 1 ? "day" : "days"} left`}
          </span>
        )}
      </div>

      <p className="text-xs text-neutral-500">
        Valid until {formatExpiry(plan.validity_expiry)} ({plan.validity_days}
        -day plan)
      </p>

      <div className="grid grid-cols-3 gap-3">
        <QuotaColumn
          label="Data"
          allowance={plan.quotas.data_gb}
          unit="GB"
          remaining={dataRemainingGb}
        />
        <QuotaColumn
          label="Voice"
          allowance={plan.quotas.voice_minutes}
          unit="min"
          remaining={voiceRemaining}
        />
        <QuotaColumn
          label="SMS"
          allowance={plan.quotas.sms_count}
          unit="msgs"
          remaining={smsRemaining}
        />
      </div>
    </div>
  );
}

export { PlanDetailsCard };
