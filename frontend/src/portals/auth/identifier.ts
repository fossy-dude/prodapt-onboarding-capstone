/**
 * Login identifier validation and normalization utilities.
 *
 * Mirrors the backend normalization logic (core/security.py:normalize_login_identifier)
 * with client-side validation to avoid unnecessary backend calls for malformed input.
 */

const REGISTRATION_ID_RE = /^REG-\d{8}-[0-9a-fA-F]{8}$/;
const USERNAME_RE = /^[A-Za-z0-9._-]{1,64}$/;
const PHONE_LIKE_RE = /^\+?\d[\d\s-]*\d$/;

export type IdentifierKind = "registration_id" | "msisdn" | "username";

/**
 * Reduce a phone-like string to bare national digits.
 *
 * Strips +, spaces, dashes; drops a leading India country-code 91 (when >10 digits
 * remain) or a trunk 0. Mirrors backend normalize_login_identifier().
 */
export function normalizeIdentifier(raw: string): string {
  const trimmed = raw.trim();
  if (REGISTRATION_ID_RE.test(trimmed)) {
    return trimmed;
  }
  if (PHONE_LIKE_RE.test(trimmed)) {
    const digits = trimmed.replace(/\D/g, "");
    if (digits.length > 10 && digits.startsWith("91")) {
      return digits.slice(2);
    }
    if (digits.length > 10 && digits.startsWith("0")) {
      return digits.slice(1);
    }
    return digits;
  }
  return trimmed;
}

/**
 * Validate + normalize a login identifier.
 *
 * Returns the value to send to the backend and its kind, or an error message.
 * Mirrors the backend acceptance rules: registration ID, MSISDN, or plain username.
 */
export function validateIdentifier(
  raw: string,
):
  | { ok: true; value: string; kind: IdentifierKind }
  | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return {
      ok: false,
      error: "Enter your Registration ID, mobile number, or username.",
    };
  }
  if (REGISTRATION_ID_RE.test(trimmed)) {
    return { ok: true, value: trimmed, kind: "registration_id" };
  }
  if (PHONE_LIKE_RE.test(trimmed)) {
    const digits = normalizeIdentifier(trimmed);
    if (/^\d{10,15}$/.test(digits)) {
      return { ok: true, value: digits, kind: "msisdn" };
    }
    return { ok: false, error: "Enter a valid 10-digit mobile number." };
  }
  if (USERNAME_RE.test(trimmed)) {
    return { ok: true, value: trimmed, kind: "username" };
  }
  return {
    ok: false,
    error: "Enter a valid Registration ID, mobile number, or username.",
  };
}
