import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { NotificationPortal } from "./NotificationPortal";
import type { NotificationEvent } from "../../hooks/useNotificationsWebSocket";

vi.mock("../../hooks/useNotificationsWebSocket", () => ({
  useNotificationsWebSocket: vi.fn(),
}));

const { useNotificationsWebSocket } =
  await import("../../hooks/useNotificationsWebSocket");

const EVENT_A: NotificationEvent = {
  msisdn_suffix: "3210",
  notification_type: "SIM_ACTIVATION",
  message_preview: "Your SIM has been activated.",
  timestamp: "2026-06-23T00:00:00Z",
  trace_id: "a".repeat(32),
};

const EVENT_B: NotificationEvent = {
  msisdn_suffix: "4321",
  notification_type: "LOW_BALANCE",
  message_preview: "Your balance is low.",
  timestamp: "2026-06-23T00:01:00Z",
  trace_id: "b".repeat(32),
};

function mockHook(events: readonly NotificationEvent[], status = "open") {
  vi.mocked(useNotificationsWebSocket).mockReturnValue({
    events,
    status: status as "connecting" | "open" | "closed" | "error",
    clearEvents: vi.fn(),
  });
}

function renderComponent() {
  render(
    <MemoryRouter>
      <NotificationPortal />
    </MemoryRouter>,
  );
}

describe("NotificationPortal", () => {
  beforeEach(() => {
    vi.mocked(useNotificationsWebSocket).mockReset();
  });

  it("shows a waiting state when no notifications have arrived", () => {
    mockHook([], "open");
    renderComponent();
    expect(screen.getByText(/Waiting for notifications/i)).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("renders the live notification feed with type, preview and masked suffix", () => {
    mockHook([EVENT_B, EVENT_A], "open");
    renderComponent();
    // Notification types appear twice due to responsive design (mobile + desktop)
    expect(screen.getAllByText("SIM_ACTIVATION")).toHaveLength(2);
    expect(screen.getAllByText("LOW_BALANCE")).toHaveLength(2);
    expect(
      screen.getByText("Your SIM has been activated."),
    ).toBeInTheDocument();
    // masked MSISDN suffix (never the full number)
    expect(screen.getByText(/…3210/)).toBeInTheDocument();
  });

  it("reflects the connection status", () => {
    mockHook([], "connecting");
    renderComponent();
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("clears the feed via the Clear button", async () => {
    const clearEvents = vi.fn();
    vi.mocked(useNotificationsWebSocket).mockReturnValue({
      events: [EVENT_A],
      status: "open",
      clearEvents,
    });
    renderComponent();

    await userEvent.click(screen.getByRole("button", { name: /Clear/i }));
    expect(clearEvents).toHaveBeenCalledTimes(1);
  });
});
