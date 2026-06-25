/**
 * TicketConfirmationBanner — green confirmation banner for a created dispute
 * ticket (Story 5.8 AC #2, AC #3).
 *
 * Rendered by the ``ticket_create`` CopilotKit action when the Support Agent
 * creates a billing-dispute ticket at the end of the dispute flow. Displays the
 * SLA message returned by the ``ticket_create`` tool plus the ticket id.
 */

import { CheckCircle2 } from "lucide-react";

interface TicketConfirmationBannerProps {
  readonly ticket_id: string;
  readonly message: string;
}

function TicketConfirmationBanner({
  ticket_id,
  message,
}: TicketConfirmationBannerProps) {
  return (
    <div
      role="status"
      className="rounded-lg bg-success-50 border border-success-600/30 px-4 py-3 flex items-start gap-3"
    >
      <CheckCircle2
        className="text-success-600 shrink-0"
        size={20}
        aria-hidden="true"
      />
      <div className="flex flex-col gap-0.5 min-w-0">
        <p className="text-sm font-medium text-success-700">{message}</p>
        <p className="text-xs text-success-700/80 font-mono break-all">
          Ticket #{ticket_id}
        </p>
      </div>
    </div>
  );
}

export { TicketConfirmationBanner };
export type { TicketConfirmationBannerProps };
