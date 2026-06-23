/**
 * JWT auth utilities (Story 1.8; §1.8.1, §1.9.1).
 *
 * Decodes the Cognito access token stored in localStorage and exposes helpers
 * consumed by RoleGuard and the Axios interceptor in api.ts.
 *
 * Roles arrive as the `cognito:groups` claim (NOT a `role` claim — see Dev Notes).
 * The primary role for routing is the first group in the claim, mapped to the route
 * prefix: subscriber → /subscriber/*, ops → /ops/*, etc.
 */

const TOKEN_KEY = "sboai_access_token";

/** Valid portal roles — each maps to a route prefix. */
export type PortalRole =
  | "subscriber"
  | "ops"
  | "fraud"
  | "dev"
  | "admin"
  | "marketing";

interface JwtPayload {
  readonly sub: string;
  readonly "cognito:groups"?: readonly string[];
  readonly exp?: number;
  readonly iat?: number;
  readonly [key: string]: unknown;
}

/** Decode a JWT payload without verifying signature (verification happens on the backend). */
function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64 = (parts[1] ?? "").replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(base64);
    const parsed: unknown = JSON.parse(json);
    // P17: guard against non-object payloads (arrays, strings) that would cause
    // undefined property access on the JwtPayload fields downstream.
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
      return null;
    return parsed as JwtPayload;
  } catch {
    return null;
  }
}

/** Return true if the token's exp claim is in the future. */
function isExpired(payload: JwtPayload): boolean {
  // P1: a token with no exp claim is treated as expired — never unconditionally valid.
  if (payload.exp === undefined) return true;
  return Date.now() / 1000 > payload.exp;
}

/** Store the access token in localStorage. */
export function saveToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/** Remove the access token from localStorage (logout). */
export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** Return the raw JWT string from localStorage, or null if absent. */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Return true if a valid, non-expired token is present in localStorage.
 *
 * Note: this is a client-side check only — the backend re-validates on every
 * request (signature + expiry + role via Cognito JWKS).
 */
export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;
  const payload = decodeJwtPayload(token);
  if (!payload) return false;
  return !isExpired(payload);
}

/**
 * Return the effective portal role for the current token.
 *
 * Reads the first entry in `cognito:groups` and maps it to a known PortalRole.
 * Returns null if the token is absent, invalid, expired, or has no groups.
 */
export function getRole(): PortalRole | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  if (!payload || isExpired(payload)) return null;
  const groups = payload["cognito:groups"];
  if (!groups || groups.length === 0) return null;
  const first = groups[0];
  const known: readonly PortalRole[] = [
    "subscriber",
    "ops",
    "fraud",
    "dev",
    "admin",
    "marketing",
  ];
  return known.includes(first as PortalRole) ? (first as PortalRole) : null;
}

/** Return the subscriber UUID (`sub` claim), or null if not authenticated. */
export function getSub(): string | null {
  const token = getToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  if (!payload || isExpired(payload)) return null;
  return payload.sub ?? null;
}

/** Clear the token and reload to /login — use for logout. */
export function logout(): void {
  removeToken();
  window.location.href = "/login";
}

export { decodeJwtPayload };
