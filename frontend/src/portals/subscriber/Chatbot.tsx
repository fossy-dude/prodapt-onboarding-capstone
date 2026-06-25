import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotReadable, useCopilotAction } from "@copilotkit/react-core";

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
  "regulations. Never reveal PII beyond the MSISDN last-4.";

// Storage key for the chat conversation id — persisted across reloads so the
// Valkey-backed conversation context (Story 5.4 AC #3) survives a refresh.
const CHAT_SESSION_STORAGE_KEY = "sboai_chat_session_id";

/**
 * Return the persisted chat session id, creating + storing one on first use.
 *
 * ``crypto.randomUUID`` requires a secure context (https or localhost); on a
 * plain-HTTP deploy it is undefined, so we fall back to a ``Math.random``-based
 * id rather than throwing. The id is stable for the browser session (survives
 * reloads and component remounts) so the backend can key conversation memory.
 */
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

  return (
    <div className="fixed bottom-6 right-6 z-[1000] w-[min(380px,92vw)]">
      <CopilotChat
        className="h-[520px] rounded-xl shadow-2xl border border-neutral-200 bg-white"
        instructions={SUPPORT_INSTRUCTIONS}
        labels={{
          title: "Billing Assistant",
          initial: "Hi! Ask me about your balance, plan or usage.",
          placeholder: "Ask about your balance, plan or usage…",
        }}
      />
    </div>
  );
}

export { Chatbot, getOrCreateChatSessionId };
