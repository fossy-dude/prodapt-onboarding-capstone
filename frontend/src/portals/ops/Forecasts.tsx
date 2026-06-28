/**
 * Forecasts - tabbed forecast dashboard for the ops portal (Story 7.4 Task 6).
 *
 * Tabs:
 *   - "Plan Demand"       — 30/60/90-day per-plan demand forecast (Story 7.4)
 *   - "Subscriber Growth" — 90-day subscriber activation/churn projection (Story 7.3)
 */

import { useState } from "react";
import { PlanForecastSelector } from "./PlanForecastSelector";
import { PlanDemandTable } from "./PlanDemandTable";
import { SubscriberGrowthForecast } from "./SubscriberGrowthForecast";
import { usePlanDemandForecast, usePlanStock } from "./hooks";

type Tab = "plan_demand" | "subscriber_growth";

function Forecasts() {
  const [activeTab, setActiveTab] = useState<Tab>("plan_demand");
  const [selectedPlanIds, setSelectedPlanIds] = useState<readonly string[]>([]);
  const [forecastRequest, setForecastRequest] = useState({
    forceRefresh: false,
    planIds: [] as readonly string[],
    runId: 0,
  });

  const {
    data: forecastData,
    isLoading,
    error,
    refetch,
  } = usePlanDemandForecast(forecastRequest);
  const { data: plans = [], isLoading: isPlanStockLoading } = usePlanStock();

  const handleRefresh = () => {
    setForecastRequest((current) => ({
      forceRefresh: true,
      planIds: [],
      runId: current.runId + 1,
    }));
  };

  const handleTogglePlan = (planId: string) => {
    setSelectedPlanIds((current) =>
      current.includes(planId) ? current.filter((id) => id !== planId) : [...current, planId],
    );
  };

  const handleRunSelectedForecast = () => {
    setForecastRequest((current) => ({
      forceRefresh: true,
      planIds: selectedPlanIds,
      runId: current.runId + 1,
    }));
  };

  const tabClass = (tab: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      activeTab === tab
        ? "border-blue-600 text-blue-600"
        : "border-transparent text-neutral-500 hover:text-neutral-700"
    }`;

  return (
    <div className="rounded-lg border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-200 px-6 pt-4">
        <div className="flex gap-1">
          <button className={tabClass("plan_demand")} onClick={() => setActiveTab("plan_demand")}>
            Plan Demand
          </button>
          <button
            className={tabClass("subscriber_growth")}
            onClick={() => setActiveTab("subscriber_growth")}
          >
            Subscriber Growth
          </button>
        </div>

        {activeTab === "plan_demand" && (
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="mb-2 rounded border border-neutral-300 px-3 py-1 text-xs text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
          >
            {isLoading ? "Refreshing…" : "Refresh Forecast"}
          </button>
        )}
      </div>

      <div className="p-6">
        {activeTab === "plan_demand" && (
          <>
            {error && (
              <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                Failed to load forecast data.
                <button onClick={() => void refetch()} className="ml-2 underline">
                  Retry
                </button>
              </div>
            )}

            <PlanForecastSelector
              plans={plans}
              isLoading={isPlanStockLoading}
              selectedPlanIds={selectedPlanIds}
              onTogglePlan={handleTogglePlan}
              onClear={() => setSelectedPlanIds([])}
            />

            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-neutral-500">
                Select one or more plans, then run a fresh forecast for just those plans.
              </p>
              <button
                type="button"
                onClick={handleRunSelectedForecast}
                disabled={selectedPlanIds.length === 0 || isLoading}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoading ? "Running…" : "Run forecast"}
              </button>
            </div>

            {forecastData && (
              <div className="mb-3 flex items-center gap-4 text-xs text-neutral-400">
                {forecastData.trained_at && (
                  <span>Trained: {new Date(forecastData.trained_at).toLocaleString()}</span>
                )}
                {forecastData.cache_expires_at && (
                  <span>Cache expires: {new Date(forecastData.cache_expires_at).toLocaleString()}</span>
                )}
                {forecastData.model_version && <span>Model: {forecastData.model_version}</span>}
              </div>
            )}

            <PlanDemandTable
              items={forecastData?.forecasts ?? []}
              isLoading={isLoading}
            />
          </>
        )}

        {activeTab === "subscriber_growth" && <SubscriberGrowthForecast />}
      </div>
    </div>
  );
}

export { Forecasts };
