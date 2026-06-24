/**
 * Plan types and interfaces (Story 3.4, reused in Story 3.5).
 *
 * Active plan details and plan catalogue items.
 */

/** Bundled plan quotas (null means unlimited). */
export interface PlanQuotas {
  readonly data_gb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
}

/** Active plan details returned by GET /subscriber/plan. */
export interface ActivePlanResponse {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly validity_expiry: string | null;
  readonly validity_days: number;
  readonly days_remaining: number | null;
  readonly quotas: PlanQuotas;
  readonly roaming_enabled: boolean;
}

/** One browsable plan in the catalogue (GET /plans). */
export interface PlanCatalogueItem {
  readonly id: string;
  readonly name: string;
  readonly data_gb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
  readonly validity_days: number;
  readonly price_paise: number;
  readonly plan_type: string | null;
}
