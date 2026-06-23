import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import {
  activateSim,
  toApiError,
  type SimLookupType,
  type SimActivateResult,
} from "../../lib/api";

const PLACEHOLDERS: Record<SimLookupType, string> = {
  registration_id: "REG-20260623-deadbeef",
  msisdn: "9876543210",
};

/**
 * SIM Activation Simulator — resolve a subscriber by MSISDN or Registration ID and
 * drive their NEW_ACTIVATION order straight to ACTIVATED (Story 2.9 AC #1, #2).
 * The server seeds the wallet + Valkey balance with the plan price and publishes a
 * notification event; this page shows the allocated MSISDN + resulting balance.
 *
 * Route: /simulator/sim-activation. Requires `dev` role. This is the full-activation
 * tool — distinct from Story 1.7's order-advance tool at /simulator/activate.
 */
export function SimActivationSimulator() {
  const [lookupType, setLookupType] =
    useState<SimLookupType>("registration_id");
  const [lookupValue, setLookupValue] = useState("");
  const [result, setResult] = useState<SimActivateResult | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      activateSim({
        lookup_type: lookupType,
        lookup_value: lookupValue.trim(),
      }),
    onSuccess: (data) => setResult(data),
  });

  function handleActivate() {
    setResult(null);
    mutation.mutate();
  }

  const errorMessage = mutation.isError
    ? (toApiError(mutation.error)?.message ??
      "Activation failed. Please try again.")
    : null;
  const rupees =
    result !== null ? (result.balance_paise / 100).toFixed(2) : null;
  const canSubmit = lookupValue.trim() !== "" && !mutation.isPending;

  return (
    <main className="px-4 py-10">
      <div className="mx-auto max-w-2xl space-y-6">
        <Card>
          <h1 className="mb-2 text-xl font-bold text-neutral-900">
            SIM Activation — Simulator
          </h1>
          <p className="mb-6 text-sm text-neutral-500">
            Activate a subscriber&apos;s SIM: the order moves to ACTIVATED, the
            wallet + Valkey balance are seeded with the plan price, and a
            notification is published to the Notification Portal.
          </p>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="lookup-type"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                Lookup by
              </label>
              <select
                id="lookup-type"
                value={lookupType}
                onChange={(e) => setLookupType(e.target.value as SimLookupType)}
                className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="registration_id">Registration ID</option>
                <option value="msisdn">MSISDN</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="lookup-value"
                className="mb-1 block text-sm font-medium text-neutral-700"
              >
                {lookupType === "registration_id"
                  ? "Registration ID"
                  : "MSISDN"}
              </label>
              <input
                id="lookup-value"
                type="text"
                value={lookupValue}
                onChange={(e) => setLookupValue(e.target.value)}
                placeholder={PLACEHOLDERS[lookupType]}
                className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
          </div>

          <div className="mt-6 flex items-center gap-4">
            <Button onClick={handleActivate} disabled={!canSubmit}>
              {mutation.isPending ? "Activating…" : "Activate"}
            </Button>
            {errorMessage !== null && (
              <p className="text-xs text-danger-600" role="alert">
                {errorMessage}
              </p>
            )}
          </div>
        </Card>

        {result !== null && (
          <Card>
            <h2 className="mb-4 text-base font-semibold text-neutral-900">
              Activation Result
            </h2>
            <dl className="grid grid-cols-2 gap-y-3 text-sm">
              <dt className="text-neutral-500">MSISDN</dt>
              <dd className="font-mono text-neutral-900">{result.msisdn}</dd>
              <dt className="text-neutral-500">Status</dt>
              <dd className="font-medium text-success-700">{result.status}</dd>
              <dt className="text-neutral-500">Wallet balance</dt>
              <dd className="font-mono text-neutral-900">
                ₹{rupees} ({result.balance_paise}p)
              </dd>
              <dt className="text-neutral-500">Order ID</dt>
              <dd className="font-mono text-xs text-neutral-500">
                {result.order_id.slice(0, 8)}…
              </dd>
            </dl>
          </Card>
        )}
      </div>
    </main>
  );
}
