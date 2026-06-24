import { useMemo } from "react";

import { CopilotChat } from "@copilotkit/react-ui";
import { useCopilotReadable } from "@copilotkit/react-core";

import "@copilotkit/react-ui/styles.css";

import { useActivePlan } from "../../hooks/useActivePlan";
import { useBalance } from "../../hooks/useBalance";

/**
 * Floating billing assistant chat panel for the subscriber portal (Story 5.4;
 * ARCH-23).
 *
 * Streams the Support Agent's replies token-by-token over the CopilotKit
 * runtime (AG-UI). ``useCopilotReadable`` exposes the live balance, active plan
 * and chat session id to the agent graph so it can answer without extra API
 * calls (AC #4). The panel floats bottom-right over the portal (AC #7).
 *
 * Must be rendered inside a ``<CopilotKit runtimeUrl>`` provider — see App.tsx.
 */

const SUPPORT_INSTRUCTIONS =
  "You are a billing and account assistant for an MVNO. Answer only billing, " +
  "plan, usage, and account queries. Use tools to fetch real data. Follow TRAI " +
  "regulations. Never reveal PII beyond the MSISDN last-4.";

function Chatbot() {
  // One stable session id per Chatbot mount keys the Valkey conversation context.
  const sessionId = useMemo(() => crypto.randomUUID(), []);
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

export { Chatbot };
