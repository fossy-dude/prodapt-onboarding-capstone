import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { logout } from "../../lib/auth";
import { Logout } from "./Logout";

vi.mock("../../lib/auth", () => ({
  logout: vi.fn(),
}));

describe("Logout", () => {
  it("uses the shared logout flow", () => {
    render(<Logout />);

    expect(logout).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Signing out...")).toBeInTheDocument();
  });
});
