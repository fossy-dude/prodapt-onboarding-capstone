import { useState, useCallback, type ReactNode } from "react";
import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotReadable, useCopilotAction } from "@copilotkit/react-core";
import { useNavigate } from "react-router-dom";

import "@copilotkit/react-ui/styles.css";

import { useActivePlan } from "../../hooks/useActivePlan";
import { useBalance } from "../../hooks/useBalance";
import { PlanRecommendationCard } from "./components/PlanRecommendationCard";
import { ChargeBreakdownTable } from "./components/ChargeBreakdownTable";
import { TicketConfirmationBanner } from "./components/TicketConfirmationBanner";

/**
 * Floating billing assistant chat panel for the subscriber portal (Story 5.4;
 * ARCH-23).
 *
 * Streams the Support Agent's replies token-by-token over the CopilotKit
 * runtime (AG-UI). ``useCopilotReadable`` exposes the live balance, active plan
 * and chat session id to the agent graph so it can answer without extra API
 * calls (AC #4). The panel floats bottom-right over the portal (AC #7).
 *
 * Must be rendered inside a ``<CopilotKit runtimeUrl>`` provider — see App.tsx,
 * which owns the session id (persisted across reloads) and passes it down.
 */

const SUPPORT_INSTRUCTIONS =
  "You are a billing and account assistant for an MVNO. Answer only billing, " +
  "plan, usage, and account queries. Use tools to fetch real data. Follow TRAI " +
  "regulations. Never reveal PII beyond the MSISDN last-4. Format final answers " +
  "as concise Markdown using short paragraphs, bullets, and simple tables only.";

const CHAT_MINIMIZED_KEY = "sboai_chat_minimized";

interface ChatbotProps {
  /** Stable chat session id (owned by App.tsx) — keys the Valkey context. */
  readonly sessionId: string;
}

interface PlanCardResult {
  readonly plan_id: string;
  readonly name: string;
  readonly price_inr: string;
  readonly data_limit_mb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
  readonly recharge_url: string;
  readonly comparison?: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function ToolResultShell({ children }: { readonly children: ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-700 shadow-sm">
      {children}
    </div>
  );
}

function planCardsFromResult(result: unknown): PlanCardResult[] {
  if (!isRecord(result) || !Array.isArray(result.plans)) {
    return [];
  }
  return result.plans.filter(isRecord).flatMap((plan) => {
    const planId = stringValue(plan.plan_id);
    const name = stringValue(plan.name);
    const priceInr = stringValue(plan.price_inr);
    if (planId === null || name === null || priceInr === null) {
      return [];
    }
    return [
      {
        plan_id: planId,
        name,
        price_inr: priceInr,
        data_limit_mb: numberValue(plan.data_limit_mb),
        voice_minutes: numberValue(plan.voice_minutes),
        sms_count: numberValue(plan.sms_count),
        recharge_url:
          stringValue(plan.recharge_url) ??
          `/subscriber/recharge?plan_id=${planId}`,
        comparison: stringValue(plan.comparison),
      },
    ];
  });
}

function Chatbot({ sessionId }: ChatbotProps) {
  const { data: balance } = useBalance();
  const { data: activePlan } = useActivePlan();
  const navigate = useNavigate();

  const [isMinimized, setIsMinimized] = useState<boolean>(() => {
    try {
      return localStorage.getItem(CHAT_MINIMIZED_KEY) === "true";
    } catch {
      return false;
    }
  });

  const handleMinimize = useCallback(() => {
    setIsMinimized(true);
    try {
      localStorage.setItem(CHAT_MINIMIZED_KEY, "true");
    } catch {
      // Best-effort
    }
  }, []);

  const handleMaximize = useCallback(() => {
    setIsMinimized(false);
    try {
      localStorage.setItem(CHAT_MINIMIZED_KEY, "false");
    } catch {
      // Best-effort
    }
  }, []);

  // ARCH-23: expose live subscriber context to the agent graph (AC #4).
  useCopilotReadable({
    description: "subscriber_balance",
    value: balance ?? null,
  });
  useCopilotReadable({
    description: "active_plan",
    value: activePlan ?? null,
  });
  useCopilotReadable({
    description: "chat_session",
    value: { session_id: sessionId },
  });

  // Story 5.6 AC #3: render plan recommendation cards when list_plans tool is called.
  useCopilotAction({
    name: "list_plans",
    available: "disabled",
    render: ({ result }) => {
      const plans = planCardsFromResult(result);
      return (
        <div className="plan-cards flex flex-col gap-3">
          {plans.map((plan) => (
            <PlanRecommendationCard key={plan.plan_id} {...plan} />
          ))}
        </div>
      );
    },
  });

  useCopilotAction({
    name: "recommend_plan",
    available: "disabled",
    render: ({ result }) => {
      if (isRecord(result) && result.needs_clarification === true) {
        return <></>;
      }
      const plans = planCardsFromResult(result);
      if (plans.length === 0) {
        return <></>;
      }
      return (
        <div className="plan-cards flex flex-col gap-3">
          {plans.map((plan) => (
            <PlanRecommendationCard key={plan.plan_id} {...plan} />
          ))}
        </div>
      );
    },
  });

  useCopilotAction({
    name: "balance_lookup",
    available: "disabled",
    render: ({ result }) => {
      if (!isRecord(result)) {
        return <></>;
      }
      const balanceInr = stringValue(result.balance_inr);
      const message = stringValue(result.message);
      return (
        <ToolResultShell>
          <p className="font-medium text-neutral-900">Wallet balance</p>
          <p>{balanceInr ?? message ?? "Balance is unavailable right now."}</p>
        </ToolResultShell>
      );
    },
  });

  useCopilotAction({
    name: "get_balance",
    available: "disabled",
    render: ({ result }) => {
      if (!isRecord(result)) {
        return <></>;
      }
      return (
        <ToolResultShell>
          <p className="font-medium text-neutral-900">Wallet balance</p>
          <p>
            {stringValue(result.balance_inr) ??
              "Balance is unavailable right now."}
          </p>
        </ToolResultShell>
      );
    },
  });

  useCopilotAction({
    name: "get_plan",
    available: "disabled",
    render: ({ result }) => {
      if (!isRecord(result) || !isRecord(result.active_plan)) {
        return <></>;
      }
      const plan = result.active_plan;
      return (
        <ToolResultShell>
          <p className="font-medium text-neutral-900">
            {stringValue(plan.plan_name) ?? "Active plan"}
          </p>
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
            <dt className="text-neutral-500">Validity</dt>
            <dd>{stringValue(plan.validity_expiry) ?? "Not available"}</dd>
            <dt className="text-neutral-500">Data</dt>
            <dd>{numberValue(plan.data_limit_mb) ?? "Unlimited"} MB</dd>
            <dt className="text-neutral-500">Voice</dt>
            <dd>{numberValue(plan.voice_minutes) ?? "Unlimited"} min</dd>
            <dt className="text-neutral-500">SMS</dt>
            <dd>{numberValue(plan.sms_count) ?? "Unlimited"}</dd>
          </dl>
        </ToolResultShell>
      );
    },
  });

  useCopilotAction({
    name: "get_usage",
    available: "disabled",
    render: ({ result }) => {
      if (!isRecord(result)) {
        return <></>;
      }
      return (
        <ToolResultShell>
          <p className="font-medium text-neutral-900">Usage summary</p>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <span>Data: {numberValue(result.data_mb) ?? 0} MB</span>
            <span>Voice: {numberValue(result.voice_minutes) ?? 0} min</span>
            <span>SMS: {numberValue(result.sms_count) ?? 0}</span>
            <span>Roaming: {numberValue(result.roaming_mb) ?? 0} MB</span>
          </div>
        </ToolResultShell>
      );
    },
  });

  useCopilotAction({
    name: "recharge_flow",
    available: "disabled",
    render: ({ result }) => {
      if (!isRecord(result)) {
        return <></>;
      }
      const url = stringValue(result.url);
      const message = stringValue(result.message);
      return (
        <ToolResultShell>
          <p>{message ?? "Recharge link is ready."}</p>
          {url !== null && (
            <button
              type="button"
              onClick={() => navigate(url)}
              className="mt-2 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-700"
            >
              Continue recharge
            </button>
          )}
        </ToolResultShell>
      );
    },
  });

  useCopilotAction({
    name: "rag_search_tool",
    available: "disabled",
    render: () => <></>,
  });

  // Story 5.7 AC #3: render charge breakdown table when charge_explain tool is called.

  useCopilotAction({
    name: "charge_explain",
    available: "disabled",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render: (({ result }: { readonly result: any }) => {
      if (!result?.found || !result?.breakdown) {
        return null;
      }

      return <ChargeBreakdownTable {...result.breakdown} />;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }) as any,
  });

  // Story 5.8 AC #2/#3: render ticket confirmation banner when ticket_create tool is called.

  useCopilotAction({
    name: "ticket_create",
    available: "disabled",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render: (({ result }: { readonly result: any }) => {
      if (!result?.ticket_id) {
        return null;
      }

      return (
        <TicketConfirmationBanner
          ticket_id={result.ticket_id}
          message={result.message ?? ""}
        />
      );
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }) as any,
  });

  if (isMinimized) {
    return (
      <div className="fixed bottom-6 right-6 z-[1000]">
        <button
          onClick={handleMaximize}
          className="flex items-center gap-2 rounded-full border border-neutral-200 bg-white px-4 py-3 text-sm font-medium text-neutral-700 shadow-2xl transition-colors hover:bg-neutral-50"
          aria-label="Open billing assistant"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          Billing Assistant
        </button>
      </div>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-[1000] w-[min(380px,92vw)]">
      <div className="relative">
        <button
          onClick={handleMinimize}
          className="absolute right-10 top-3 z-10 flex h-6 w-6 items-center justify-center rounded text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
          aria-label="Minimize chat"
          title="Minimize"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M5 15l7 7 7-7" />
          </svg>
        </button>
        <CopilotChat
          className="sboai-chatbot-panel h-[520px] rounded-xl border border-neutral-200 bg-white shadow-2xl"
          instructions={SUPPORT_INSTRUCTIONS}
          labels={{
            title: "Billing Assistant",
            initial: "Hi! Ask me about your balance, plan or usage.",
            placeholder: "Ask about your balance, plan or usage…",
          }}
        />
      </div>
    </div>
  );
}

export { Chatbot };
