import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../lib/api", () => ({
  ERROR_CODES: { ACCOUNT_NOT_FOUND: "ACCOUNT_NOT_FOUND" },
  initiateLogin: vi.fn(),
  toApiError: vi.fn(),
  verifyLoginOtp: vi.fn(),
}));

import { removeToken, saveToken } from "../../lib/auth";
import { initiateLogin, verifyLoginOtp } from "../../lib/api";
import { Login } from "./Login";

function makeToken(role: string): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  const body = btoa(
    JSON.stringify({
      exp: Math.floor(Date.now() / 1000) + 1800,
      sub: "u1",
      "cognito:groups": [role],
    }),
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `${header}.${body}.fake-sig`;
}

function renderLogin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/ops" element={<div>Ops portal</div>} />
          <Route path="/ops/dashboard" element={<div>Ops dashboard</div>} />
          <Route
            path="/subscriber/dashboard"
            element={<div>Subscriber dashboard</div>}
          />
          <Route
            path="/subscriber/activate"
            element={<div>SIM Activation Status</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  removeToken();
  vi.clearAllMocks();
});

describe("Login", () => {
  it("redirects an authenticated ops user to the ops dashboard", () => {
    saveToken(makeToken("ops"));

    renderLogin();

    expect(screen.getByText("Ops dashboard")).toBeInTheDocument();
  });

  it.each(["admin", "marketing"])(
    "redirects an authenticated %s user to the ops dashboard",
    (role) => {
      saveToken(makeToken(role));

      renderLogin();

      expect(screen.getByText("Ops dashboard")).toBeInTheDocument();
    },
  );

  it("routes subscriber registration ID login to SIM activation status", async () => {
    vi.mocked(initiateLogin).mockResolvedValue(undefined);
    vi.mocked(verifyLoginOtp).mockResolvedValue({
      access_token: makeToken("subscriber"),
      refresh_token: "refresh-token",
      id_token: "id-token",
      token_type: "Bearer",
    });

    renderLogin();

    fireEvent.change(screen.getByLabelText(/Registration ID or MSISDN/i), {
      target: { value: "REG-20260622-ab12cd34" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fireEvent.change(await screen.findByLabelText(/One-time passcode/i), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Sign in/i }));

    expect(
      await screen.findByText("SIM Activation Status"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Subscriber dashboard")).not.toBeInTheDocument();
    expect(verifyLoginOtp).toHaveBeenCalledWith(
      "REG-20260622-ab12cd34",
      "123456",
    );
  });
});
