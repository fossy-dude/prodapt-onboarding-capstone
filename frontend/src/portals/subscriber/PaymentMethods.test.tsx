/**
 * Tests for PaymentMethods component (Story 1.10).
 *
 * Critical security requirement: when adding a credit card, the request body
 * must contain NO PAN (raw card number). Only token + last4 are sent to API.
 *
 * @see PaymentMethods.tsx
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PaymentMethods } from "./PaymentMethods";
import {
  addPaymentMethod,
  deletePaymentMethod,
  getPaymentMethods,
  setDefaultPaymentMethod,
} from "../../lib/api";
import { tokenizeCard } from "../../lib/tokenize";

// Mock the API functions
vi.mock("../../lib/api", () => ({
  addPaymentMethod: vi.fn(),
  deletePaymentMethod: vi.fn(),
  getPaymentMethods: vi.fn(),
  setDefaultPaymentMethod: vi.fn(),
}));

// Mock the tokenize utility
vi.mock("../../lib/tokenize", () => ({
  tokenizeCard: vi.fn(),
}));

const mockAddPaymentMethod = addPaymentMethod as ReturnType<typeof vi.fn>;
const mockDeletePaymentMethod = deletePaymentMethod as ReturnType<typeof vi.fn>;
const mockGetPaymentMethods = getPaymentMethods as ReturnType<typeof vi.fn>;
const mockSetDefaultPaymentMethod = setDefaultPaymentMethod as ReturnType<
  typeof vi.fn
>;
const mockTokenizeCard = tokenizeCard as ReturnType<typeof vi.fn>;

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("PaymentMethods", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("loading and error states", () => {
    it("shows loading state while fetching payment methods", () => {
      mockGetPaymentMethods.mockImplementation(() => new Promise(() => {})); // Never resolves
      renderWithQueryClient(<PaymentMethods />);

      expect(
        screen.getByText("Loading your saved payment methods..."),
      ).toBeInTheDocument();
    });

    it("shows error state when API call fails", async () => {
      mockGetPaymentMethods.mockRejectedValue(new Error("API error"));
      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() => {
        expect(
          screen.getByText("Failed to load payment methods. Please try again."),
        ).toBeInTheDocument();
      });
    });

    it("shows empty state when no payment methods exist", async () => {
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() => {
        expect(
          screen.getByText("No payment methods saved yet."),
        ).toBeInTheDocument();
      });
    });
  });

  describe("payment methods list display", () => {
    it("displays saved payment methods with icons and labels", async () => {
      const mockMethods = [
        {
          id: "1",
          subscriber_id: "sub-1",
          type: "CREDIT_CARD",
          token: "token-1",
          display_label: "•••• 4242",
          is_default: true,
        },
        {
          id: "2",
          subscriber_id: "sub-1",
          type: "UPI",
          token: "user@upi",
          display_label: "user@upi",
          is_default: false,
        },
      ];

      mockGetPaymentMethods.mockResolvedValue({
        data: mockMethods,
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() => {
        expect(screen.getByText("•••• 4242")).toBeInTheDocument();
        expect(screen.getByText("user@upi")).toBeInTheDocument();
        expect(screen.getAllByText("Credit Card")).toHaveLength(2); // One in form, one in list
        expect(screen.getAllByText("UPI ID")).toHaveLength(2); // One in form, one in list
        expect(screen.getByText("(Default)")).toBeInTheDocument();
      });
    });
  });

  describe("critical security - PAN never sent to API", () => {
    it("NEVER includes raw PAN in API request when adding credit card", async () => {
      const user = userEvent.setup();
      mockTokenizeCard.mockReturnValue({ token: "uuid-token", last4: "4242" });
      mockAddPaymentMethod.mockResolvedValue({
        data: {
          id: "1",
          subscriber_id: "sub-1",
          type: "CREDIT_CARD",
          token: "uuid-token",
          display_label: "•••• 4242",
          is_default: false,
        },
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      // Wait for initial load
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: /Add Payment Method/i }),
        ).toBeInTheDocument(),
      );

      // Fill in credit card form
      const typeSelect = screen.getByLabelText(/Type/i);
      const cardInput = screen.getByLabelText(/Card Number/i);

      await user.selectOptions(typeSelect, "CREDIT_CARD");
      await user.type(cardInput, "4242424242424242");

      // Submit form
      const addButton = screen.getByRole("button", {
        name: /Add Payment Method/i,
      });
      await user.click(addButton);

      // Wait for mutation to complete
      await waitFor(() => {
        expect(mockAddPaymentMethod).toHaveBeenCalled();
      });

      // CRITICAL SECURITY CHECK: the raw PAN must NOT be in the API request
      const addCall = mockAddPaymentMethod.mock.calls[0]![0]!;
      const serializedPayload = JSON.stringify(addCall);

      expect(serializedPayload).not.toContain("4242424242424242");
      expect(serializedPayload).not.toMatch(/\d{13,19}/); // No 13-19 digit sequence
      expect(addCall.type).toBe("CREDIT_CARD");
      expect(addCall.token).toBe("uuid-token");
      expect(addCall.display_label).toBe("•••• 4242");
    });

    it("includes tokenizeCard call with correct PAN before tokenisation", async () => {
      const user = userEvent.setup();
      const rawPAN = "4242424242424242";
      mockTokenizeCard.mockReturnValue({ token: "uuid-token", last4: "4242" });
      mockAddPaymentMethod.mockResolvedValue({
        data: {
          id: "1",
          subscriber_id: "sub-1",
          type: "CREDIT_CARD",
          token: "uuid-token",
          display_label: "•••• 4242",
          is_default: false,
        },
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: /Add Payment Method/i }),
        ).toBeInTheDocument(),
      );

      const typeSelect = screen.getByLabelText(/Type/i);
      const cardInput = screen.getByLabelText(/Card Number/i);

      await user.selectOptions(typeSelect, "CREDIT_CARD");
      await user.type(cardInput, rawPAN);

      const addButton = screen.getByRole("button", {
        name: /Add Payment Method/i,
      });
      await user.click(addButton);

      await waitFor(() => {
        expect(mockTokenizeCard).toHaveBeenCalledWith(rawPAN);
      });
    });
  });

  describe("non-card payment methods", () => {
    it("stores UPI ID as-is without tokenisation", async () => {
      const user = userEvent.setup();
      const upiId = "user@upi";
      mockAddPaymentMethod.mockResolvedValue({
        data: {
          id: "1",
          subscriber_id: "sub-1",
          type: "UPI",
          token: upiId,
          display_label: upiId,
          is_default: false,
        },
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: /Add Payment Method/i }),
        ).toBeInTheDocument(),
      );

      const typeSelect = screen.getByLabelText(/Type/i);

      // Select UPI first, then wait for label to update
      await user.selectOptions(typeSelect, "UPI");

      // Wait for the label to change from "Card Number" to "Identifier"
      await waitFor(() => {
        expect(screen.getByLabelText(/Identifier/i)).toBeInTheDocument();
      });

      const identifierInput = screen.getByLabelText(/Identifier/i);
      await user.type(identifierInput, upiId);

      const addButton = screen.getByRole("button", {
        name: /Add Payment Method/i,
      });
      await user.click(addButton);

      await waitFor(() => {
        expect(mockAddPaymentMethod).toHaveBeenCalled();
      });

      const addCall = mockAddPaymentMethod.mock.calls[0]![0]!;
      expect(addCall.type).toBe("UPI");
      expect(addCall.token).toBe(upiId); // UPI ID stored as-is
      expect(addCall.display_label).toBe(upiId);
    });
  });

  describe("set default functionality", () => {
    it("sets a payment method as default when clicking Set Default button", async () => {
      const user = userEvent.setup();
      const mockMethods = [
        {
          id: "1",
          subscriber_id: "sub-1",
          type: "CREDIT_CARD",
          token: "token-1",
          display_label: "•••• 4242",
          is_default: false,
        },
        {
          id: "2",
          subscriber_id: "sub-1",
          type: "UPI",
          token: "user@upi",
          display_label: "user@upi",
          is_default: true,
        },
      ];

      mockGetPaymentMethods.mockResolvedValue({
        data: mockMethods,
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      mockSetDefaultPaymentMethod.mockResolvedValue({
        data: { ...mockMethods[0], is_default: true },
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() =>
        expect(screen.getByText("Set Default")).toBeInTheDocument(),
      );

      const setDefaultButtons = screen.getAllByRole("button", {
        name: "Set Default",
      });
      await user.click(setDefaultButtons[0]!);

      await waitFor(() => {
        expect(mockSetDefaultPaymentMethod).toHaveBeenCalledWith("1");
      });
    });
  });

  describe("delete functionality", () => {
    it("deletes a payment method when clicking delete button", async () => {
      const user = userEvent.setup();
      const mockMethods = [
        {
          id: "1",
          subscriber_id: "sub-1",
          type: "CREDIT_CARD",
          token: "token-1",
          display_label: "•••• 4242",
          is_default: true,
        },
      ];

      mockGetPaymentMethods.mockResolvedValue({
        data: mockMethods,
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });
      mockDeletePaymentMethod.mockResolvedValue(undefined);

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() => {
        expect(screen.getByText("🗑️")).toBeInTheDocument();
      });

      const deleteButtons = screen.getAllByRole("button", { name: "🗑️" });
      await user.click(deleteButtons[0]!);

      await waitFor(() => {
        expect(mockDeletePaymentMethod).toHaveBeenCalledWith("1");
      });
    });
  });

  describe("form validation", () => {
    it("disables add button when identifier is empty", async () => {
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() => {
        const submitButton = screen
          .getAllByRole("button")
          .find((btn) => btn.textContent === "Add Payment Method");
        expect(submitButton).toBeDisabled();
      });
    });

    it("enables add button when identifier is filled", async () => {
      const user = userEvent.setup();
      mockGetPaymentMethods.mockResolvedValue({
        data: [],
        meta: { trace_id: "abc", timestamp: "2025-01-01" },
      });

      renderWithQueryClient(<PaymentMethods />);

      await waitFor(() =>
        expect(screen.getByLabelText(/Card Number/i)).toBeInTheDocument(),
      );

      const cardInput = screen.getByLabelText(/Card Number/i);
      await user.type(cardInput, "4242424242424242");

      await waitFor(() => {
        const submitButton = screen
          .getAllByRole("button")
          .find((btn) => btn.textContent === "Add Payment Method");
        expect(submitButton).not.toBeDisabled();
      });
    });
  });
});
