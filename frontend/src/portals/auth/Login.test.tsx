import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { removeToken, saveToken } from "../../lib/auth";
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
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  removeToken();
});

describe("Login", () => {
  it("redirects an authenticated ops user to the ops dashboard", () => {
    saveToken(makeToken("ops"));

    renderLogin();

    expect(screen.getByText("Ops dashboard")).toBeInTheDocument();
  });

  it.each(["admin", "marketing"])(
    "preserves the existing %s landing route",
    (role) => {
      saveToken(makeToken(role));

      renderLogin();

      expect(screen.getByText("Ops portal")).toBeInTheDocument();
    },
  );
});
