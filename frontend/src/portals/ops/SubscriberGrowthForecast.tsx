/**
 * SubscriberGrowthForecast - subscriber growth tab content for the ops forecasts
 * panel (Story 7.3 Task 6/7, AC #2/#4).
 *
 * Fetches the 90-day subscriber growth projection (cached daily on the server),
 * renders the projection chart with confidence bands, and exposes a manual
 * refresh that bypasses the server cache. Owns its own loading / error states.
 */

import { useState } from "react";

import { SubscriberGrowthChart } from "./SubscriberGrowthChart";
import { useSubscriberGrowthForecast } from "./hooks";

function SubscriberGrowthForecast() {
  const [forceRefresh, setForceRefresh] = useState(false);
  const { data, isLoading, error, refetch } = useSubscriberGrowthForecast(forceRefresh);

  const handleRefresh = () => {
    setForceRefresh(true);
    void refetch().finally(() => setForceRefresh(false));
  };

  if (isLoading) {
    return <p className="py-8 text-center text-sm text-neutral-500">Loading forecast…</p>;
  }

  if (error) {
    return (
      <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        Failed to load subscriber growth forecast.
        <button onClick={() => void refetch()} className="ml-2 underline">
          Retry
        </button>
      </div>
    );
  }

  const mapeActivations = data?.metrics.mape_activations?.toFixed(1) ?? "—";
  const mapeChurn = data?.metrics.mape_churn?.toFixed(1) ?? "—";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-4 text-xs text-neutral-400">
          {data?.model_version && <span>Model: {data.model_version}</span>}
          {data?.trained_at && (
            <span>Trained: {new Date(data.trained_at).toLocaleString()}</span>
          )}
          {data?.cache_expires_at && (
            <span>Cache expires: {new Date(data.cache_expires_at).toLocaleString()}</span>
          )}
          {data && <span>{data.from_cache ? "Served from cache" : "Newly trained"}</span>}
          {data && (
            <span>
              Holdout MAPE — activations {mapeActivations}%, churn {mapeChurn}%
            </span>
          )}
        </div>

        <button
          onClick={handleRefresh}
          disabled={isLoading}
          className="rounded border border-neutral-300 px-3 py-1 text-xs text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
        >
          Refresh Forecast
        </button>
      </div>

      <SubscriberGrowthChart data={data?.forecasts ?? []} />
    </div>
  );
}

export { SubscriberGrowthForecast };
