/**
 * Login portal — passwordless OTP login (Story 1.8; AC #1, #2).
 *
 * Two-step flow:
 *   Step 1: Enter Registration ID (pre-activation) or MSISDN (post-activation).
 *   Step 2: Enter the OTP surfaced on the Notification Portal.
 *
 * On success the JWT access token is saved in localStorage and the user is
 * redirected to their role's portal root.
 *
 * This screen is top-level and NOT role-gated (§1.9.1, UX-DR7).
 */

import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";

import {
  initiateLogin,
  toApiError,
  verifyLoginOtp,
  ERROR_CODES,
} from "../../lib/api";
import { getRole, isAuthenticated, saveToken } from "../../lib/auth";
import { validateIdentifier } from "./identifier";

/** Map portal role to its root route. */
const ROLE_ROUTE: Record<string, string> = {
  subscriber: "/subscriber",
  ops: "/ops",
  fraud: "/fraud",
  dev: "/simulator",
  admin: "/ops",
  marketing: "/ops",
};

type Step = "identifier" | "otp";

function Login() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("identifier");
  const [identifier, setIdentifier] = useState("");
  const [normalizedIdentifier, setNormalizedIdentifier] = useState("");
  const [otp, setOtp] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  // P19: server state via TanStack Query useMutation (spec Task 4 / Dev Notes §1.9.3).
  const initiateMutation = useMutation({
    mutationFn: (id: string) => initiateLogin(id),
    onSuccess: () => {
      setStep("otp");
    },
  });

  const verifyMutation = useMutation({
    mutationFn: ({ id, code }: { id: string; code: string }) =>
      verifyLoginOtp(id, code),
    onSuccess: (tokens) => {
      saveToken(tokens.access_token);
      const role = getRole();
      // P18: guard unknown role — don't navigate to '/' which wildcard-redirects to /login.
      const route = role !== null ? (ROLE_ROUTE[role] ?? null) : null;
      if (route === null) {
        return; // isSuccess + role === null → error message shown below
      }
      navigate(route, { replace: true });
    },
  });

  // P4: already-authenticated redirect uses <Navigate> component, not imperative
  // navigate() during render which is a React side-effect anti-pattern.
  if (isAuthenticated()) {
    const role = getRole();
    const route = role !== null ? (ROLE_ROUTE[role] ?? null) : null;
    if (route !== null) {
      return <Navigate to={route} replace />;
    }
  }

  function handleInitiate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setValidationError(null);

    const result = validateIdentifier(identifier);
    if (result.ok) {
      setNormalizedIdentifier(result.value);
      initiateMutation.mutate(result.value);
    } else {
      setValidationError(result.error);
    }
  }

  function handleVerify(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    verifyMutation.mutate({ id: normalizedIdentifier, code: otp });
  }

  const error =
    validationError !== null
      ? validationError
      : initiateMutation.isError
        ? (() => {
            const apiErr = toApiError(initiateMutation.error);
            if (apiErr?.code === ERROR_CODES.ACCOUNT_NOT_FOUND) {
              return apiErr.message;
            }
            return "Failed to initiate login. Check your Registration ID or MSISDN.";
          })()
        : verifyMutation.isError
          ? "OTP verification failed — check the code and try again."
          : verifyMutation.isSuccess && getRole() === null
            ? "Unrecognized account role — contact support."
            : null;

  const loading = initiateMutation.isPending || verifyMutation.isPending;

  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-sm ring-1 ring-neutral-200">
        <h1 className="mb-1 text-2xl font-bold text-neutral-900">Sign in</h1>
        <p className="mb-6 text-sm text-neutral-500">
          {step === "identifier"
            ? "Enter your Registration ID or mobile number."
            : "Enter the OTP from the Notification Portal."}
        </p>

        {error !== null && (
          <p
            role="alert"
            className="mb-4 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700"
          >
            {error}
          </p>
        )}

        {step === "identifier" ? (
          <form onSubmit={handleInitiate} noValidate>
            <label
              className="mb-1 block text-sm font-medium text-neutral-700"
              htmlFor="identifier"
            >
              Registration ID or MSISDN
            </label>
            <input
              id="identifier"
              type="text"
              autoComplete="username"
              required
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="REG-YYYYMMDD-xxxxxxxx or 9876543210"
              className="mb-4 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={loading || identifier.trim() === ""}
              className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Sending OTP…" : "Continue"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerify} noValidate>
            <label
              className="mb-1 block text-sm font-medium text-neutral-700"
              htmlFor="otp"
            >
              One-time passcode
            </label>
            <input
              id="otp"
              type="text"
              autoComplete="one-time-code"
              inputMode="numeric"
              required
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              placeholder="6-digit code"
              maxLength={6}
              className="mb-4 w-full rounded-lg border border-neutral-300 px-3 py-2 text-center text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={loading || otp.length !== 6}
              className="mb-3 w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Verifying…" : "Sign in"}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep("identifier");
                setOtp("");
                initiateMutation.reset();
                verifyMutation.reset();
              }}
              className="w-full text-sm text-neutral-500 hover:text-neutral-700"
            >
              Back
            </button>
          </form>
        )}
      </div>
    </main>
  );
}

export { Login };
