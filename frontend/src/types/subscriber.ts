/** Subscriber-domain frontend types (UX brief §7.1 — src/types/subscriber.ts). */

/** Step 1 + Step 2 registration payload (mirrors the backend RegisterRequest).
 *
 * MSISDN is intentionally absent — it is auto-generated at SIM activation time.
 */
export interface RegisterPayload {
  readonly full_name: string;
  readonly email: string;
  readonly alternate_mobile: string;
  readonly date_of_birth: string;
  readonly address_line1: string;
  readonly address_line2: string;
  readonly city: string;
  readonly state: string;
  readonly pin_code: string;
  readonly id_proof_type: "Aadhaar" | "PAN" | "Passport" | "Voter ID";
  readonly id_proof_number: string;
  readonly consent: boolean;
}

/** Standard success envelope (§1.11.3) returned by POST /subscriber/register. */
export interface RegisterResponseEnvelope {
  readonly data: { readonly registration_id: string; readonly status: string };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}
