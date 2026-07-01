import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Register } from "./Register";

// Mock the API module: registerSubscriber is a vi.fn per-test; toApiError reads a
// synthetic `apiCode` so we avoid constructing a real AxiosError in the test.
vi.mock("../../lib/api", () => ({
  registerSubscriber: vi.fn(),
  toApiError: (e: { apiCode?: string } | undefined) =>
    e?.apiCode ? { code: e.apiCode, message: "error", detail: {} } : null,
}));

// Imported after the mock so it resolves to the mocked implementation.
const { registerSubscriber } = await import("../../lib/api");

function renderRegister() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Register />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function fillStep1(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Full name"), "Priya Sharma");
  await user.type(screen.getByLabelText("Email"), "priya@example.com");
  await user.type(
    screen.getByLabelText("Alternate mobile (for OTP)"),
    "9123456780",
  );
}

async function fillStep2(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Date of birth"), "1995-04-12");
  await user.type(screen.getByLabelText("Address line 1"), "12 MG Road");
  await user.type(screen.getByLabelText("City"), "Bengaluru");
  await user.type(screen.getByLabelText("State"), "Karnataka");
  await user.type(screen.getByLabelText("PIN code"), "560001");
  await user.type(screen.getByLabelText("ID proof number"), "1234-5678-9012");
  await user.click(screen.getByRole("checkbox"));
}

describe("Register", () => {
  beforeEach(() => {
    vi.mocked(registerSubscriber).mockReset();
  });

  it("starts on Step 1 and blocks navigation until valid", async () => {
    const user = userEvent.setup();
    renderRegister();
    expect(screen.getByText(/Step 1 of 3/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    // Navigation blocked — still on Step 1
    expect(screen.getByText(/Step 1 of 3/)).toBeInTheDocument();
    // Per-field inline validation hints visible for each required field
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText("Valid email required")).toBeInTheDocument();
    expect(screen.getByText("10–15 digits")).toBeInTheDocument();
  });

  it("navigates Step 1 → Step 2 → back", async () => {
    const user = userEvent.setup();
    renderRegister();
    await fillStep1(user);

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/Step 2 of 3/)).toBeInTheDocument();
    expect(
      screen.getByText("TRAI Customer Acquisition Form"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText(/Step 1 of 3/)).toBeInTheDocument();
  });

  it("shows a generic error message when registration fails", async () => {
    vi.mocked(registerSubscriber).mockRejectedValueOnce({
      apiCode: "VALIDATION_ERROR",
    });
    const user = userEvent.setup();
    renderRegister();
    await fillStep1(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await fillStep2(user);

    await user.click(
      screen.getByRole("button", { name: "Submit registration" }),
    );

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("error"),
    );
  });

  it("shows the Registration ID on Step 3 on success", async () => {
    vi.mocked(registerSubscriber).mockResolvedValueOnce({
      data: {
        registration_id: "REG-20260620-deadbabe",
        status: "REGISTRATION_COMPLETE",
      },
      meta: { trace_id: "t", timestamp: "ts" },
    });
    const user = userEvent.setup();
    renderRegister();
    await fillStep1(user);
    await user.click(screen.getByRole("button", { name: "Next" }));
    await fillStep2(user);

    await user.click(
      screen.getByRole("button", { name: "Submit registration" }),
    );

    await waitFor(() =>
      expect(screen.getByLabelText("Registration ID")).toHaveTextContent(
        "REG-20260620-deadbabe",
      ),
    );
    expect(screen.getByText(/Step 3 of 3/)).toBeInTheDocument();
  });
});
