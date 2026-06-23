import { useNavigate } from "react-router-dom";

import { UsageRing } from "../../components/charts/UsageRing";
import { useBalance, useRefreshBalance } from "../../hooks/useBalance";
import { useUsage } from "../../hooks/useUsage";
import { PlanDetailsCard } from "./PlanDetailsCard";

function BalanceCard() {
  const { data, isLoading, isError } = useBalance();
  const refresh = useRefreshBalance();

  if (isLoading) {
    return (
      <div className="rounded-xl bg-white shadow p-6 animate-pulse h-40" />
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl bg-red-50 border border-red-200 p-6">
        <p className="text-sm text-red-600">Failed to load balance.</p>
      </div>
    );
  }

  const isDepleted = data.balance_paise === 0;

  return (
    <div className="rounded-xl bg-white shadow p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-neutral-500 uppercase tracking-wide">
          Wallet Balance
        </h2>
        <button
          onClick={() => void refresh()}
          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
          aria-label="Refresh balance"
        >
          Refresh
        </button>
      </div>

      {isDepleted && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 flex items-center justify-between">
          <p className="text-sm font-medium text-amber-700">Balance depleted</p>
          <RechargeButton />
        </div>
      )}

      <p className="text-4xl font-bold text-neutral-900">{data.balance_inr}</p>

      <div className="flex items-center gap-3 text-xs text-neutral-400">
        <span>MSISDN: {data.msisdn_masked}</span>
        {data.last_updated_at && (
          <span>
            Updated:{" "}
            {new Date(data.last_updated_at).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
            })}
          </span>
        )}
      </div>
    </div>
  );
}

function RechargeButton() {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate("/subscriber/recharge")}
      className="text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 px-3 py-1.5 rounded-md"
    >
      Recharge Now
    </button>
  );
}

function UsageSection() {
  const { data, isLoading, isError } = useUsage();

  if (isLoading) {
    return (
      <div className="rounded-xl bg-white shadow p-6 animate-pulse h-48" />
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl bg-red-50 border border-red-200 p-6">
        <p className="text-sm text-red-600">Failed to load usage data.</p>
      </div>
    );
  }

  const periodLabel = data.plan_period.end
    ? `${new Date(data.plan_period.start).toLocaleDateString("en-IN")} – ${new Date(data.plan_period.end).toLocaleDateString("en-IN")}`
    : `From ${new Date(data.plan_period.start).toLocaleDateString("en-IN")}`;

  return (
    <div className="rounded-xl bg-white shadow p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-neutral-500 uppercase tracking-wide">
          Usage Breakdown
        </h2>
        <span className="text-xs text-neutral-400">{periodLabel}</span>
      </div>

      <div className="flex flex-wrap gap-6 justify-around pt-2">
        <UsageRing
          used={data.voice_minutes.used}
          allowance={data.voice_minutes.allowance}
          unlimited={data.voice_minutes.unlimited}
          label="Voice"
          unit="min"
        />
        <UsageRing
          used={data.data_gb}
          allowance={
            data.data.allowance !== null ? data.data.allowance / 1024 : null
          }
          unlimited={data.data.unlimited}
          label="Data"
          unit="GB"
        />
        <UsageRing
          used={data.sms.used}
          allowance={data.sms.allowance}
          unlimited={data.sms.unlimited}
          label="SMS"
          unit="msgs"
        />
        <UsageRing
          used={data.roaming_mb.used}
          allowance={data.roaming_mb.allowance}
          unlimited={data.roaming_mb.unlimited}
          label="Roaming"
          unit="MB"
        />
      </div>
    </div>
  );
}

function Dashboard() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-8 flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-neutral-900">Dashboard</h1>
      <BalanceCard />
      <PlanDetailsCard />
      <UsageSection />
    </main>
  );
}

export { Dashboard };
