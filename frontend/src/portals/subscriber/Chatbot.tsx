import { useState, useCallback } from "react";
import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotReadable, useCopilotAction } from "@copilotkit/react-core";

import "@copilotkit/react-ui/styles.css";

import { useActivePlan } from "../../hooks/useActivePlan";
import { useBalance } from "../../hooks/useBalance";
import { endChatSession } from "../../lib/api";
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
  "regulations. Never reveal PII beyond the MSISDN last-4.";

const CHAT_SESSION_STORAGE_KEY = "sboai_chat_session_id";
const CHAT_MINIMIZED_KEY = "sboai_chat_minimized";

function getOrCreateChatSessionId(): string {
  try {
    const stored = sessionStorage.getItem(CHAT_SESSION_STORAGE_KEY);
    if (stored) {
      return stored;
    }
  } catch {
    // sessionStorage may be unavailable (private mode / disabled) — derive fresh.
  }
  const id =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    sessionStorage.setItem(CHAT_SESSION_STORAGE_KEY, id);
  } catch {
    // Best-effort persistence; the in-memory id still works for this session.
  }
  return id;
}

interface ChatbotProps {
  /** Stable chat session id (owned by App.tsx) — keys the Valkey context. */
  readonly sessionId: string;
}

function Chatbot({ sessionId }: ChatbotProps) {
  const { data: balance } = useBalance();
  const { data: activePlan } = useActivePlan();

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

  // Story 5.10 AC #7: trigger Conclusion Agent when chat panel closes.
  const handleChatClose = async () => {
    try {
      await endChatSession({ session_id: sessionId });
    } catch (error) {
      // Best-effort: log failure but don't block UI
      console.error("Failed to trigger session end:", error);
    }
  };

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
      const plans = result?.plans ?? [];
      return (
        <div className="plan-cards flex flex-col gap-3">
          {plans.map(
            (plan: {
              plan_id: string;
              name: string;
              price_inr: string;
              data_limit_mb: number | null;
              voice_minutes: number | null;
              sms_count: number | null;
            }) => (
              <PlanRecommendationCard
                key={plan.plan_id}
                {...plan}
                recharge_url={`/subscriber/recharge?plan_id=${plan.plan_id}`}
              />
            ),
          )}
        </div>
      );
    },
  });

  // Story 5.7 AC #3: render charge breakdown table when charge_explain tool is called.
  useCopilotAction({
    name: "charge_explain",
    available: "disabled",
    render: ({ result }) => {
      if (!result?.found || !result?.breakdown) {
        return null;
      }
      return <ChargeBreakdownTable {...result.breakdown} />;
    },
  });

  // Story 5.8 AC #2/#3: render ticket confirmation banner when ticket_create tool is called.
  useCopilotAction({
    name: "ticket_create",
    available: "disabled",
    render: ({ result }) => {
      if (!result?.ticket_id) {
        return null;
      }
      return (
        <TicketConfirmationBanner
          ticket_id={result.ticket_id}
          message={result.message ?? ""}
        />
      );
    },
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
          className="h-[520px] rounded-xl border border-neutral-200 bg-white shadow-2xl"
          instructions={SUPPORT_INSTRUCTIONS}
          onClose={handleChatClose}
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

export { Chatbot, getOrCreateChatSessionId };
