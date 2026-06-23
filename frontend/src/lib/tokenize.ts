/**
 * Client-side card tokenisation utility (Story 1.10).
 *
 * **CRITICAL SECURITY REQUIREMENT**: The raw PAN (Primary Account Number) is
 * tokenised **in the browser, before any network call**. Only the opaque token
 * and last-4 digits are ever sent to the API. The server, database, logs, and
 * telemetry spans never see a raw PAN.
 *
 * This is simulated tokenisation for MVP (no real PCI gateway). The token is
 * a UUID v4, which provides an opaque reference that reveals nothing about the
 * original card number.
 *
 * @see Architecture §1.8.2 - Security Controls
 * @see AC #1, #2 - Client-side tokenisation, zero PAN exposure
 */

/**
 * Result of tokenising a card PAN.
 *
 * Contains only the opaque token and display-safe last-4 digits. The raw PAN
 * is never included in this structure or any network request.
 */
export interface TokenizedCard {
  readonly token: string;
  readonly last4: string;
}

/**
 * Extract the last 4 digits from a PAN string.
 *
 * Handles whitespace and hyphens in the input (e.g., "4242 4242 4242 4242"
 * or "4242-4242-4242-4242"). Returns exactly 4 digits, or fewer if the
 * input has fewer than 4 digits.
 *
 * @param pan - The raw PAN string (may contain spaces/hyphens)
 * @returns The last 4 digits as a string
 */
function extractLast4(pan: string): string {
  // Strip all non-digit characters so last4 always contains only digits.
  const digits = pan.replace(/\D/g, "");
  return digits.slice(-4);
}

/**
 * Tokenise a card PAN (Primary Account Number) client-side.
 *
 * **SECURITY**: This function runs in the browser. The raw PAN exists only
 * in component state during entry and is consumed here. The returned object
 * contains ONLY the token (UUID v4) and last-4 digits — never the full PAN.
 *
 * This is simulated tokenisation for MVP. A real PCI implementation would use
 * a payment gateway's tokenisation service, but the security model is identical:
 * tokenise at point of entry, raw PAN never leaves the browser.
 *
 * @param pan - The raw card number (may contain spaces/hyphens for formatting)
 * @returns Tokenized card with opaque UUID token and last-4 digits
 *
 * @example
 * ```tsx
 * const handleAddCard = (pan: string) => {
 *   const { token, last4 } = tokenizeCard(pan);
 *   // Send ONLY { token, last4 } to API
 *   api.post('/payment-methods', { type: 'CREDIT_CARD', token, display_label: `•••• ${last4}` });
 *   // Raw PAN is never logged, stored, or transmitted
 * };
 * ```
 */
export function tokenizeCard(pan: string): TokenizedCard {
  // crypto.randomUUID() requires a secure context (HTTPS / localhost).
  // Fall back to a Math.random-based UUID v4 for plain-HTTP dev environments.
  const token =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
        });

  // Extract last-4 digits for display/verification
  const last4 = extractLast4(pan);

  return { token, last4 };
}
