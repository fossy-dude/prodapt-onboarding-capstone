import { Badge } from "@/components/ui/Badge";
import { useNavigate } from "react-router-dom";

interface PlanRecommendationCardProps {
  readonly plan_id: string;
  readonly name: string;
  readonly price_inr: string;
  readonly data_limit_mb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
  readonly recharge_url: string;
  readonly comparison?: string | null;
  readonly onAccept?: () => void;
  readonly onDismiss?: () => void;
}

function quotaText(value: number | null, unit: string): string {
  return value === null ? "Unlimited" : `${value} ${unit}`;
}

function formatData(mb: number | null): string {
  return mb === null ? "Unlimited" : `${(mb / 1024).toFixed(1)} GB`;
}

function PlanRecommendationCard({
  name,
  price_inr,
  data_limit_mb,
  voice_minutes,
  sms_count,
  recharge_url,
  comparison,
  onAccept,
  onDismiss,
}: PlanRecommendationCardProps) {
  const navigate = useNavigate();

  const handleAccept = () => {
    if (onAccept) {
      onAccept();
    }
    navigate(recharge_url);
  };

  const handleDismiss = () => {
    if (onDismiss) {
      onDismiss();
    }
  };

  const hasCallbacks = onAccept !== undefined || onDismiss !== undefined;

  return (
    <article className="rounded-lg bg-white shadow-sm border border-neutral-200 p-4 flex flex-col gap-3 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h3 className="text-base font-semibold text-neutral-900">{name}</h3>
          {comparison != null && comparison !== "" && (
            <p className="text-xs text-neutral-500">{comparison}</p>
          )}
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

      {hasCallbacks ? (
        <div className="flex gap-2">
          <button
            onClick={handleAccept}
            className="flex-1 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md px-3 py-1.5 transition-colors"
          >
            Accept
          </button>
          <button
            onClick={handleDismiss}
            className="flex-1 text-sm font-medium text-neutral-600 border border-neutral-300 hover:bg-neutral-50 rounded-md px-3 py-1.5 transition-colors"
          >
            Dismiss
          </button>
        </div>
      ) : (
        <button
          onClick={() => navigate(recharge_url)}
          className="text-sm font-medium text-indigo-600 hover:text-indigo-700 text-left flex items-center gap-1"
        >
          Recharge →
        </button>
      )}
    </article>
  );
}

export { PlanRecommendationCard };
export type { PlanRecommendationCardProps };
