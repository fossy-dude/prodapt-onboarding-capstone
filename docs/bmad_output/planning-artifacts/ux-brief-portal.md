# UX Brief: Subscriber Self-Care Portal — Balance, Usage & Recharge Flows

## Document Status

**Type:** Lightweight UX Brief — MVP scope only
**Story:** 3.1 — UX Brief: Balance, Usage & Recharge Portal Flows
**Produced:** 2026-06-22
**Authoritative for:** Stories 3.2, 3.3, 3.4, 3.5, 3.6, 3.7

This document is the agreed design target for all Epic 3 frontend stories relating to the subscriber self-care portal. It supersedes any conflicting frontend conventions for these flows — specifically, the Feature-Sliced Design layout and SCSS modules described in `frontend/CLAUDE.md` do **not** apply to this project. See [Project Structure Notes & Conflict Callout](#project-structure-notes--conflict-callout) for the full resolution table.

---

## 1. Screen / Route Table

| Screen Name | Route | Portal Prefix | Purpose |
|---|---|---|---|
| Dashboard | `/subscriber/dashboard` | `/subscriber/*` | Balance card + usage rings (real-time) |
| Plans | `/subscriber/plans` | `/subscriber/*` | Plan catalogue with filter/sort |
| Recharge | `/subscriber/recharge` | `/subscriber/*` | 3-step flow: plan select → payment → confirmation |
| History | `/subscriber/history` | `/subscriber/*` | Transaction ledger (charge/recharge/refund) |
| Receipt | `/subscriber/receipts/:id` | `/subscriber/*` | PDF receipt download |

> **Note:** The `/subscriber/*` subtree is gated by `<RoleGuard allowedRoles={['subscriber']}>`. The subscriber role comes from the JWT `cognito:groups` claim = `"subscriber"`. See [Route Map & Role Gating](#route-map--role-gating) for details.

---

## 2. Route Map & Role Gating

### 2.1 Subscriber Portal Routes

| Route | Component (path from `frontend/src/`) | Data Source | Notes |
|---|---|---|---|
| `/subscriber/dashboard` | `portals/subscriber/Dashboard.tsx` | `GET /api/v1/subscriber/balance`, `GET /api/v1/subscriber/usage` | BalanceCard + UsageRing components |
| `/subscriber/plans` | `portals/subscriber/Plans.tsx` | `GET /api/v1/plans` | PlanCard catalogue (filter/sort) |
| `/subscriber/recharge` | `portals/subscriber/Recharge.tsx` | `GET /api/v1/plans`, `GET /api/v1/subscriber/payment-methods`, `POST /api/v1/subscriber/recharge` | 3-step wizard |
| `/subscriber/history` | `portals/subscriber/History.tsx` | `GET /api/v1/subscriber/transactions` | Transaction ledger table |
| `/subscriber/receipts/:id` | `portals/subscriber/Receipt.tsx` | `GET /api/v1/subscriber/receipts/:id` | PDF download |

### 2.2 Adjacent Routes (Already Established)

These routes are documented in [UX Brief: Subscriber Registration & Identity Flows](ux-brief-identity.md) and are referenced here for completeness:

| Route | Component | Story |
|---|---|---|
| `/subscriber/profile` | `portals/subscriber/Profile.tsx` | 1.9 |
| `/subscriber/profile/payment-methods` | `portals/subscriber/PaymentMethods.tsx` | 1.10 |
| `/subscriber/activate` | `portals/subscriber/SimActivation.tsx` | 1.7 |
| `/subscriber/orders/:id/status` | (integrated into SimActivation) | 1.7 |

### 2.3 Role-Gated Portal Prefixes

The application is a single SPA. The JWT `role` claim determines which route subtree is accessible. A mismatch between the user's role and the requested route prefix causes a redirect to `/login`.

| Prefix | Audience | Portal |
|---|---|---|
| `/subscriber/*` | Subscriber (end-user) | Subscriber Portal |
| `/ops/*` | Ops & Marketing team | Ops & Marketing Dashboard |
| `/fraud/*` | Fraud analyst | Fraud Management Dashboard |
| `/simulator/*` | Internal dev / QA | CDR Simulator + Notification Portal + SIM dev tools |

**Rule:** JWT `role` claim selects the accessible subtree. Any request to a protected route where the token's `role` does not match → redirect to `/login`. Implemented via the `RoleGuard` component in `frontend/src/components/layout/RoleGuard.tsx`.

---

## 3. Shared UI Component Library

### 3.1 Existing Components (Reuse)

All shared UI components live in `frontend/src/components/ui/`. They are shared across all portals and must be built with **TailwindCSS utility classes only** — no per-component CSS files.

| Component | File | Used by |
|---|---|---|
| `Button` | `Button.tsx` | All portals — primary/secondary/destructive variants |
| `Card` | `Card.tsx` | Dashboard panels, plan cards, profile sections |
| `Badge` | `Badge.tsx` | Status indicators (validity, current plan) |
| `Table` | `Table.tsx` | Transaction history, plan catalogue |
| `Modal` | `Modal.tsx` | Confirmation dialogs, form overlays |

### 3.2 New Components for Epic 3

| Component | File | Purpose | Story |
|---|---|---|---|
| `Input` | `Input.tsx` | Form input fields (text, email, tel) | 3.5 |
| `Select` | `Select.tsx` | Dropdown select (payment method, plan filter) | 3.5 |
| `UsageRing` | `charts/UsageRing.tsx` | Circular progress chart for usage breakdown | 3.2 |

> **Note:** `Input` and `Select` are NEW primitives required for the recharge form. They do not exist in the current `components/ui/` barrel. `UsageRing` is a NEW chart component; the `components/charts/` directory does not yet exist. These are created in Stories 3.2 and 3.5 — **not** in this doc-only story.

### 3.3 Naming Conventions

| Artefact type | Convention | Examples |
|---|---|---|
| Component files | `PascalCase.tsx` | `Button.tsx`, `BalanceCard.tsx`, `UsageRing.tsx` |
| Hook files | `usePascalCase.ts` | `useBalance.ts`, `usePlans.ts`, `useRecharge.ts` |
| Utility files | `camelCase.ts` | `api.ts`, `auth.ts`, `queryClient.ts` |

### 3.4 Styling Rule

**TailwindCSS utility classes only.** The only permitted CSS file is `frontend/src/globals.css` (for resets and CSS custom properties only). No per-component `.css` or `.module.scss` files. No inline `style={}` props except for dynamic values that cannot be expressed in Tailwind.

---

## 4. Dashboard Screen — Balance Card & Usage Rings

Route: `/subscriber/dashboard` → component: `portals/subscriber/Dashboard.tsx`

### 4.1 BalanceCard Component

**Purpose:** Display the subscriber's current wallet balance in INR with clear visual feedback for low/zero balance states.

**Visual specification:**
- Large INR balance figure (2 decimal places)
- Zero-balance state: "Balance depleted" warning banner + "Recharge Now" CTA
- Last-updated timestamp (IST timezone)
- Color coding: success (≥ ₹100), warning (₹1–₹99), danger (₹0)

**Data source:** `GET /api/v1/subscriber/balance` (Story 3.2)

**Data contract:**
```typescript
interface BalanceResponse {
  readonly balance_paise: number;  // Integer paise, rendered as INR with 2 decimals
  readonly last_updated: string;   // ISO 8601 timestamp
}
```

**Display logic:**
- Balance INR = `balance_paise / 100` (render with `Intl.NumberFormat('en-IN', { minimumFractionDigits: 2 })`)
- Timestamp formatted as `last_updated.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })`

### 4.2 UsageRing Component

**Purpose:** Circular progress ring showing consumed vs. total allowance per usage type (voice, data, SMS, roaming).

**Visual specification:**
- One ring per usage type (4 rings total)
- Ring fills proportionally: used portion in brand color, remaining portion in neutral gray
- Center label: "X / Y" (e.g., "450 / 500 min")
- "Unlimited" label when plan has no cap for that type
- Hover state: show exact percentage

**Data source:** `GET /api/v1/subscriber/usage` (Story 3.2)

**Data contract:**
```typescript
interface UsageResponse {
  readonly voice_minutes_used: number | null;
  readonly voice_minutes_allowed: number | null;  // null = unlimited
  readonly data_mb_used: number | null;
  readonly data_mb_allowed: number | null;       // null = unlimited
  readonly sms_count_used: number | null;
  readonly sms_count_allowed: number | null;       // null = unlimited
  readonly roaming_mb_used: number | null;
  readonly roaming_mb_allowed: number | null;      // null = unlimited
}
```

**Display logic:**
- When `allowed` is `null`: display "Unlimited" + used count only (no ring)
- When `allowed` is numeric: show ring fill = `used / allowed` (clamped 0–1)
- Data rendering: show GB for values ≥ 1024 MB, MB for smaller values (per FR-10)

**Implementation:** Recharts `RadialBarChart` or `PieChart` wrapper. See [architecture.md §1.12.1](architecture.md#1121-monorepo-layout) for `components/charts/` placement. The `recharts` package is NOT yet installed — it will be added in Story 3.2.

---

## 5. Plans Screen — Plan Catalogue

Route: `/subscriber/plans` → component: `portals/subscriber/Plans.tsx`

### 5.1 PlanCard Component

**Purpose:** Display an individual plan from the catalogue with key details and a recharge CTA.

**Visual specification:**
- Plan name (large, bold)
- Validity badge (e.g., "28 days", "56 days", "84 days") — reuse `Badge`
- Quota chips (data, voice, SMS) — small pills with icon + value
- Price (INR, prominent)
- "Recharge" CTA button — navigates to `/subscriber/recharge?plan_id={id}`
- Subscriber's current active plan: "Current Plan" badge (reuse `Badge`)

**Data source:** `GET /api/v1/plans` (Story 3.4)

**Data contract:**
```typescript
interface Plan {
  readonly id: string;              // UUIDv4
  readonly plan_name: string;
  readonly plan_code: string;        // e.g., "PREPAID_28D_2GB"
  readonly price_paise: number;      // Render as INR
  readonly validity_days: number;
  readonly data_limit_mb: number | null;     // null = unlimited
  readonly voice_minutes: number | null;     // null = unlimited
  readonly sms_count: number | null;         // null = unlimited
  readonly is_active: boolean;
}
```

**Display logic:**
- Price: `price_paise / 100` (formatted as INR)
- Data: `data_limit_mb` ≥ 1024 → show GB (÷ 1024), else show MB
- Voice: `voice_minutes` or "Unlimited" if `null`
- SMS: `sms_count` or "Unlimited" if `null`
- Validity: `${validity_days} days`

### 5.2 Catalogue Controls

**Filter controls:**
- Validity: 28 days / 56 days / 84 days / All
- Data cap: ≥ 1 GB / ≥ 2 GB / Unlimited

**Sort controls:**
- Price: Low to high / High to low
- Data: High to low / Low to high
- Validity: Longest first / Shortest first

**Implementation:** Filter + sort state managed in React (TanStack Query for data). `usePlans` hook (Story 3.4) encapsulates API call + client-side filtering.

---

## 6. Recharge Flow — 3-Step Wizard

Route: `/subscriber/recharge` → component: `portals/subscriber/Recharge.tsx`

**Purpose:** Guide the subscriber through plan selection, payment method choice, and confirmation.

### 6.1 Step 1 — Plan Select

**When no `?plan_id=` query param:**
- Show full plan catalogue (same as `/subscriber/plans`, but within recharge flow)
- Filter/sort controls available
- Clicking a plan card → advance to Step 2 with that plan pre-selected

**When `?plan_id=` is present (deep link from `/subscriber/plans`):**
- Skip Step 1, advance directly to Step 2 with plan pre-selected
- Display selected plan summary (name, validity, quotas, price)

**State:** Selected plan ID stored in component state (or URL search param).

### 6.2 Step 2 — Payment Method

**Purpose:** Choose a saved payment method or add a new one (card tokenisation).

**Visual specification:**
- List of saved payment methods (from `GET /api/v1/subscriber/payment-methods`)
- Each method: radio button + card label (e.g., "•••• 4242") + "Use this" button
- "Add new payment method" button → opens `Modal` with card entry form
- Card entry form: PAN input, expiry, CVV, billing address
- "Tokenise & Save" button → client-side tokenisation via `tokenizeCard` (Story 1.10)

**Data sources:**
- Saved methods: `GET /api/v1/subscriber/payment-methods` (Story 1.10)
- Tokenisation: `frontend/src/lib/tokenize.ts` `tokenizeCard` (Story 1.10)

**Data contract (saved methods):**
```typescript
interface PaymentMethod {
  readonly id: string;
  readonly type: 'CREDIT_CARD' | 'DEBIT_CARD' | 'UPI' | 'NET_BANKING' | 'MOBILE_WALLET';
  readonly display_label: string;        // e.g., "•••• 4242", "user@upi", "HDFC Bank"
  readonly is_default: boolean;
}
```

**Security requirement (FR-64):**
- Raw PAN is tokenised **in the browser** via `tokenizeCard` before any API call
- Only the opaque token (UUID v4) and last-4 digits are sent to the API
- Raw PAN never leaves the browser, is never logged or stored

**Navigation:** After selecting/adding payment method → "Continue" → Step 3.

### 6.3 Step 3 — Confirmation

**Purpose:** Show final summary and execute recharge.

**Visual specification:**
- Plan summary card (name, validity, quotas, price)
- Selected payment method (masked)
- "Confirm & Pay" button → triggers `POST /api/v1/subscriber/recharge` (Story 3.5)
- Loading state during payment simulation
- Success state:
  - Success banner ("Recharge successful!")
  - New balance display
  - Plan activation timestamp
  - "Download Receipt" button → navigates to `/subscriber/receipts/{id}`
- Error state: inline error message + "Retry" button

**Data source:**
- Recharge API: `POST /api/v1/subscriber/recharge` (Story 3.5)
- Receipt: `GET /api/v1/subscriber/receipts/:id` (Story 3.6)

**Data contract (recharge response):**
```typescript
interface RechargeResponse {
  readonly transaction_id: string;        // UUIDv7
  readonly new_balance_paise: number;
  readonly plan_activated_at: string;    // ISO 8601
  readonly receipt_url: string;          // Relative path to PDF
}
```

**Payment simulation (FR-14):**
- All payments are simulated — no real gateway integration
- API returns success after 1–2 second delay
- Frontend shows loading state during this delay

---

## 7. History Screen — Transaction Ledger

Route: `/subscriber/history` → component: `portals/subscriber/History.tsx`

**Purpose:** Display paginated transaction history (charges, recharges, refunds).

**Visual specification:**
- Table with columns: Type, Amount, Timestamp, Reference ID, Plan (for recharges)
- Pagination controls (10 / 25 / 50 per page)
- Sort by most recent first (default)
- Filter by type: All / Charge / Recharge / Refund

**Data source:** `GET /api/v1/subscriber/transactions?page=&per_page=&type=` (Story 3.3)

**Data contract:**
```typescript
interface Transaction {
  readonly id: string;                  // UUIDv7
  readonly type: 'CHARGE' | 'RECHARGE' | 'REFUND';
  readonly amount_paise: number;         // Render as INR (can be negative for refunds)
  readonly created_at: string;          // ISO 8601
  readonly reference_id: string | null; // CDR ID for charges, null for recharges
  readonly plan_name: string | null;    // Plan name for recharges, null for charges
}
```

**Display logic:**
- Amount: `amount_paise / 100` (formatted as INR with sign: + for recharge, - for charge)
- Timestamp: `created_at.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })`
- Type badge: reuse `Badge` variants (`success` for recharge, `danger` for charge, `warning` for refund)

**Empty state:** "No transactions found" message when history is empty.

---

## 8. Receipt Screen — PDF Download

Route: `/subscriber/receipts/:id` → component: `portals/subscriber/Receipt.tsx`

**Purpose:** Display receipt details and provide PDF download.

**Visual specification:**
- Receipt summary card: Transaction ID, Amount, Timestamp, Plan, Payment Method (masked)
- "Download PDF" button → triggers PDF download
- Loading state during PDF generation
- Error state: inline error message

**Data source:** `GET /api/v1/subscriber/receipts/:id` (Story 3.6)

**Data contract:**
```typescript
interface Receipt {
  readonly id: string;                  // UUIDv7
  readonly transaction_id: string;
  readonly amount_paise: number;
  readonly created_at: string;
  readonly plan_name: string;
  readonly payment_method_label: string; // Masked, e.g., "•••• 4242"
  readonly pdf_url: string;              // Relative path to PDF file
}
```

**PDF download:** `pdf_url` is a relative path (e.g., `/receipts/{id}.pdf`). Frontend fetches with `auth` header (JWT) and triggers browser download.

**Implementation:** PDF generation happens server-side (Story 3.6). Frontend only fetches and triggers download.

---

## 9. Project Structure Notes & Conflict Callout

### 9.1 Authoritative Layout

The architecture-defined layout is authoritative for all Epic 3 frontend stories. This supersedes the Feature-Sliced Design (FSD) conventions in `frontend/CLAUDE.md`.

```
frontend/src/
├── portals/
│   ├── subscriber/          # /subscriber/* (Epic 3)
│   │   ├── Dashboard.tsx    # Story 3.2
│   │   ├── Balance.tsx      # (reserved for future)
│   │   ├── Recharge.tsx     # Story 3.5
│   │   ├── Chatbot.tsx      # Epic 5 (AG-UI stream)
│   │   ├── Profile.tsx      # Story 1.9
│   │   ├── Plans.tsx        # Story 3.4
│   │   ├── History.tsx      # Story 3.3
│   │   ├── Receipt.tsx      # Story 3.6
│   │   ├── SimActivation.tsx # Story 1.7
│   │   ├── Register.tsx     # Story 1.6
│   │   ├── Login.tsx        # Story 1.8
│   │   └── PaymentMethods.tsx # Story 1.10
│   ├── ops/                 # /ops/* (Epic 7)
│   ├── fraud/               # /fraud/* (Epic 6)
│   └── simulator/           # /simulator/* (Epic 2 dev tools)
├── components/
│   ├── ui/                  # Button, Card, Badge, Table, Modal, Input, Select
│   ├── charts/              # Recharts wrappers (UsageRing.tsx — Story 3.2)
│   └── layout/              # Navbar, Sidebar, RoleGuard
├── hooks/
│   ├── useBalance.ts        # Story 3.2
│   ├── usePlans.ts          # Story 3.4
│   ├── useTransactions.ts   # Story 3.3
│   ├── useRecharge.ts       # Story 3.5
│   └── useAuth.ts           # Story 1.8
├── lib/
│   ├── api.ts               # Axios instance + error interceptor
│   ├── auth.ts              # JWT decode, role extraction
│   ├── queryClient.ts       # TanStack Query client
│   └── tokenize.ts          # Card tokenisation (Story 1.10)
└── types/
    ├── subscriber.ts
    ├── billing.ts
    └── fraud.ts
```

### 9.2 Conflict Resolution Table

| Concern | **Authoritative — use this** (architecture) | **Superseded — do NOT use** (`frontend/CLAUDE.md`) |
|---|---|---|
| Folder layout | `src/portals/{subscriber,ops,fraud,simulator}/`, `src/components/ui/`, `src/components/charts/` | Feature-Sliced Design: `src/features/`, `src/entities/`, `src/shared/`, `src/routes/` |
| Styling | TailwindCSS utility classes only; `globals.css` for resets | `PascalCase.module.scss` SCSS modules |
| Page naming | `Dashboard.tsx`, `Plans.tsx`, `History.tsx` (plain PascalCase under `portals/subscriber/`) | `PascalCasePage.tsx` (e.g., `DashboardPage.tsx`) |
| Hooks | `usePascalCase.ts` (`useBalance.ts`, `usePlans.ts`) | `camelCase.ts` |
| Chart components | `src/components/charts/` (Recharts wrappers) | Not specified |

### 9.3 Data-Naming Variances (Critical for Stories 3.2–3.4)

**These divergences between the epic AC text and the codebase/schema MUST be noted so downstream stories don't guess:**

| Epic AC / Brief | Database / Code | Resolution |
|---|---|---|
| `data_gb` (usage display) | `data_limit_mb` (DB column) | DB stores MB. UI shows GB for large values (≥ 1024) and MB for small. API should expose both `data_mb` and derived `data_gb`. |
| `plan_type` / `category` | `plan_code` / `plan_name` (DB columns) | No `plan_type` or `category` column exists. Catalogue filter is by validity (28/56/84/all) and sort by price/data. Derive `category` from `plan_code` pattern if needed, or omit from UI. |
| Money display | `balance_paise`, `price_paise` (integer paise) | All money is integer paise in DB + API. UI renders INR with 2 decimals (`paise / 100`). |
| Plan reference | `plan_id` (UUIDv4) | Use `plan_id` for all API references. `plan_code` is for display only. |

**Source:** `service_webapp/db/migrations/V1__baseline_schema.sql` (lines 107-123); `epics.md` (lines 1136, 1138); `architecture.md` (lines 1233, 1205-1206).

---

## 10. Testing Standards

This story produces a document; there is no test target. Validation is a checklist review of the brief against ACs 1–6.

For downstream Epic 3 stories (3.2–3.7):
- Frontend test tooling: Vitest + React Testing Library
- No Cypress for MVP
- Test behavior, not implementation
- Accessibility: test with keyboard navigation and screen reader queries (`getByRole`)

**Source:** `architecture.md` (lines 977, 1179); `frontend/CLAUDE.md` §7.

---

## References

- [epics.md §1.6.1 Story 3.1](epics.md) — Source epic definition
- [architecture.md §1.9.1](architecture.md#191-single-spa--role-based-dashboard-routing) — Role-based routing
- [architecture.md §1.11.2](architecture.md#1112-naming-conventions) — Naming conventions (React)
- [architecture.md §1.12.1](architecture.md#1121-monorepo-layout) — Monorepo layout (frontend tree)
- [prd.md UJ-2](prds/prd-sboai_capstone-2026-06-18/prd.md) — Canonical user journey: Rohan checks balance and recharges
- [prd.md FR-8](prds/prd-sboai_capstone-2026-06-18/prd.md) — Real-Time Balance Display
- [prd.md FR-10](prds/prd-sboai_capstone-2026-06-18/prd.md) — Usage Breakdown
- [prd.md FR-12](prds/prd-sboai_capstone-2026-06-18/prd.md) — Plan Catalogue Browse
- [prd.md FR-13](prds/prd-sboai_capstone-2026-06-18/prd.md) — Recharge Purchase
- [prd.md FR-14](prds/prd-sboai_capstone-2026-06-18/prd.md) — Multi-Gateway Payment (Simulated)
- [prd.md FR-15](prds/prd-sboai_capstone-2026-06-18/prd.md) — Invoice / Receipt Generation
- [prd.md FR-64](prds/prd-sboai_capstone-2026-06-18/prd.md) — Payment Data Tokenisation (PCI-DSS)
- [UX Brief: Subscriber Registration & Identity Flows](ux-brief-identity.md) — Canonical brief structure (mirrored)
- [frontend/src/App.tsx](frontend/src/App.tsx) — RoleGuard implementation
- [frontend/src/components/ui/index.ts](frontend/src/components/ui/index.ts) — Existing UI component barrel
- [frontend/CLAUDE.md](frontend/CLAUDE.md) — Superseded conventions (FSD)
- [service_webapp/db/migrations/V1__baseline_schema.sql](service_webapp/db/migrations/V1__baseline_schema.sql) — Plans schema (data_limit_mb, plan_code)
- Stories 1.8 (subscriber role), 1.10 (token-only payment), 3.2–3.7 (downstream consumers)
