import { useNavigate } from "react-router-dom";

import { Badge } from "../../../../components/ui/Badge";

interface PlanRecommendationCardProps {
  readonly plan_id: string;
  readonly name: string;
  readonly price_inr: string;
  readonly data_limit_mb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
  readonly recharge_url: string;
}

/** Render a quota value, or "Unlimited" when the allowance is null. */
function quotaText(value: number | null, unit: string): string {
  return value === null ? "Unlimited" : `${value} ${unit}`;
}

/** Format data from MB to GB for display. */
function formatData(mb: number | null): string {
  return mb === null ? "Unlimited" : `${(mb / 1024).toFixed(1)} GB`;
}

/** Plan recommendation card for chat UI (Story 5.6 AC #3). */
function PlanRecommendationCard({
  name,
  price_inr,
  data_limit_mb,
  voice_minutes,
  sms_count,
  recharge_url,
}: PlanRecommendationCardProps) {
  const navigate = useNavigate();

  const handleClick = () => {
    navigate(recharge_url);
  };

  return (
    <article className="rounded-lg bg-white shadow-sm border border-neutral-200 p-4 flex flex-col gap-3 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h3 className="text-base font-semibold text-neutral-900">{name}</h3>
        </div>
        <Badge variant="neutral">{price_inr}</Badge>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
          {formatData(data_limit_mb)} data
        </span>
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
          {quotaText(voice_minutes, "min")} voice
        </span>
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
          {quotaText(sms_count, "SMS")}
        </span>
      </div>

      <button
        onClick={handleClick}
        className="text-sm font-medium text-indigo-600 hover:text-indigo-700 text-left flex items-center gap-1"
      >
        Recharge →
      </button>
    </article>
  );
}

export { PlanRecommendationCard };
export type { PlanRecommendationCardProps };
