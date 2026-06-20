# UX Brief: Subscriber Registration & Identity Flows

## Document Status

**Type:** Lightweight UX Brief — MVP scope only  
**Story:** 1.1 — UX Brief: Subscriber Registration & Identity Flows  
**Produced:** 2026-06-20  
**Authoritative for:** Stories 1.6, 1.7, 1.8, 1.9, 1.10

This document is the agreed design target for all Epic 1 frontend stories relating to subscriber identity. It supersedes any conflicting frontend conventions for these flows — specifically, the Feature-Sliced Design layout and SCSS modules described in `frontend/CLAUDE.md` do **not** apply to this project. See [Project Structure Notes & Conflict Callout](#project-structure-notes--conflict-callout) for the full resolution table.

---

## 1. Screen / Route Table

| Screen Name | Route | Portal Prefix | Purpose |
|---|---|---|---|
| Register | `/register` | (public) | Multi-step subscriber registration form |
| Activate | `/activate` | `/subscriber/*` | SIM activation order tracker (read-only, subscriber-facing) |
| Login | `/login` | (public) | Registration ID + OTP authentication |
| Profile | `/profile` | `/subscriber/*` | Subscriber profile overview |
| KYC Status | `/profile/kyc` | `/subscriber/*` | View KYC verification status and documents |
| Payment Methods | `/profile/payment-methods` | `/subscriber/*` | View and manage saved payment methods |

> **Portal placement note for Story 1.7:** The subscriber-facing activation tracker (`/activate`) maps to `subscriber/SimActivation.tsx`. A second `simulator/SimActivation.tsx` exists under the `/simulator/*` portal as a **dev tool** for advancing order fulfilment state — it is not subscriber-facing. Story 1.7 must implement both. See [SimActivation Placement](#simactivation-portal-placement) for the open question.

---

## 2. Route Map & Role Gating

### 2.1 Subscriber-Facing Identity Routes

| Route | Component (path from `frontend/src/`) | Notes |
|---|---|---|
| `/register` | `portals/subscriber/Register.tsx` | Public — unauthenticated access |
| `/activate` | `portals/subscriber/SimActivation.tsx` | Pre-auth; subscriber accesses after registration |
| `/login` | `portals/subscriber/Login.tsx` | Public — unauthenticated access |
| `/profile` | `portals/subscriber/Profile.tsx` | Requires `role = subscriber` JWT claim |
| `/profile/kyc` | `portals/subscriber/KycStatus.tsx` | Requires `role = subscriber` JWT claim |
| `/profile/payment-methods` | `portals/subscriber/PaymentMethods.tsx` | Requires `role = subscriber` JWT claim |

### 2.2 Role-Gated Portal Prefixes (UX-DR7, FR-67)

The application is a single SPA. The JWT `role` claim determines which route subtree is accessible. A mismatch between the user's role and the requested route prefix causes a redirect to `/login`.

| Prefix | Audience | Portal |
|---|---|---|
| `/subscriber/*` | Subscriber (end-user) | Subscriber Portal |
| `/ops/*` | Ops & Marketing team | Ops & Marketing Dashboard |
| `/fraud/*` | Fraud analyst | Fraud Management Dashboard |
| `/simulator/*` | Internal dev / QA | CDR Simulator + Notification Portal + SIM dev tools |

**Rule:** JWT `role` claim selects the accessible subtree. Any request to a protected route where the token's `role` does not match → redirect to `/login`. Implemented via the `RoleGuard` component in `frontend/src/components/layout/RoleGuard.tsx`.

### 2.3 SimActivation Portal Placement

**Open question for Story 1.7:**

The architecture monorepo layout includes `SimActivation.tsx` in **two** locations:

| File | Portal | Purpose |
|---|---|---|
| `portals/subscriber/SimActivation.tsx` | `/subscriber/*` | Subscriber-facing read-only tracker; polls `GET /api/v1/subscriber/orders/{order_id}/status` every 10 s |
| `portals/simulator/SimActivation.tsx` | `/simulator/*` | Dev tool — allows internal users to advance/simulate order fulfilment state transitions |

Story 1.7 should confirm this dual-file design and wire the `/activate` route to `portals/subscriber/SimActivation.tsx`.

---

## 3. Shared UI Component Library

### 3.1 Components (UX-DR8)

All five shared UI components live in `frontend/src/components/ui/`. They are shared across all portals and must be built with **TailwindCSS utility classes only** — no per-component CSS files.

| Component | File | Used by |
|---|---|---|
| `Button` | `Button.tsx` | All portals — primary/secondary/destructive variants |
| `Card` | `Card.tsx` | Dashboard panels, profile sections |
| `Badge` | `Badge.tsx` | KYC status indicator (see variants below), order status chips |
| `Table` | `Table.tsx` | Plan stock, order fulfilment, transaction history |
| `Modal` | `Modal.tsx` | Confirmation dialogs, form overlays |

#### Badge Variants for KYC Status (consumed by Story 1.9)

The `Badge` component **must** be built with these three named variants from the start so Story 1.9 can consume them without modification:

| Variant prop | Visual | Semantics |
|---|---|---|
| `verified` | Green background / text | KYC check passed |
| `pending` | Amber background / text | KYC submitted, awaiting result |
| `rejected` | Red background / text | KYC check failed |

Example API: `<Badge variant="verified">Verified</Badge>`

### 3.2 Naming Conventions (UX-DR8, architecture §1.11.2)

| Artefact type | Convention | Examples |
|---|---|---|
| Component files | `PascalCase.tsx` | `Button.tsx`, `BalanceCard.tsx`, `RoleGuard.tsx` |
| Hook files | `usePascalCase.ts` | `useAuth.ts`, `useBalance.ts`, `useWebSocket.ts` |
| Utility files | `camelCase.ts` | `api.ts`, `auth.ts`, `queryClient.ts` |

### 3.3 Styling Rule

**TailwindCSS utility classes only.** The only permitted CSS file is `frontend/src/globals.css` (for resets and CSS custom properties only). No per-component `.css` or `.module.scss` files. No inline `style={}` props except for dynamic values that cannot be expressed in Tailwind.

---

## 4. Tailwind Global Theme

All font, size, and colour decisions are made once in `frontend/tailwind.config.ts` under `theme.extend`. Downstream stories **must not** use ad-hoc Tailwind colour/size classes outside this palette (e.g. no `text-blue-400`, `bg-green-300`). Use only the semantic tokens defined here.

### 4.1 Font Families

| Token | Classes | Stack | Use |
|---|---|---|---|
| `sans` | `font-sans` | `['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif']` | All UI text |
| `mono` | `font-mono` | `['JetBrains Mono', 'ui-monospace', 'monospace']` | Registration ID display, code/IDs |

Inter must be loaded via `@fontsource/inter` (npm) in `main.tsx` — no Google Fonts CDN (blocked by CSP in production). JetBrains Mono via `@fontsource/jetbrains-mono`.

### 4.2 Permitted Type Scale

These are the only font-size steps in use. No intermediate sizes (e.g. no `text-[15px]`).

| Tailwind class | Size | Line height | Typical use |
|---|---|---|---|
| `text-xs` | 12 px | 16 px | Helper text, input hints, timestamps |
| `text-sm` | 14 px | 20 px | Table content, secondary body, form labels |
| `text-base` | 16 px | 24 px | Primary body, form inputs, button labels |
| `text-lg` | 18 px | 28 px | Card headings, section sub-headings |
| `text-xl` | 20 px | 28 px | Section headings |
| `text-2xl` | 24 px | 32 px | Page headings |
| `text-3xl` | 30 px | 36 px | Hero display — Registration ID prominent display (Step 3) |

### 4.3 Colour Palette

All colours are defined as custom tokens in `theme.extend.colors`. Reference them as `bg-brand-600`, `text-success-700`, etc.

#### Brand (primary interactive colour)

| Token | Hex | Use |
|---|---|---|
| `brand-50` | `#eff6ff` | Hover backgrounds, light tints |
| `brand-100` | `#dbeafe` | Focus rings, selected row tints |
| `brand-500` | `#3b82f6` | Icon fills, secondary accents |
| `brand-600` | `#2563eb` | Primary button background, links |
| `brand-700` | `#1d4ed8` | Primary button hover |
| `brand-900` | `#1e3a8a` | Dark text on light brand backgrounds |

#### Neutral (backgrounds, borders, text)

| Token | Hex | Use |
|---|---|---|
| `neutral-50` | `#f9fafb` | Page background |
| `neutral-100` | `#f3f4f6` | Card / panel background |
| `neutral-200` | `#e5e7eb` | Dividers, input borders (default) |
| `neutral-400` | `#9ca3af` | Placeholder text, disabled state |
| `neutral-600` | `#4b5563` | Secondary body text |
| `neutral-800` | `#1f2937` | Primary body text |
| `neutral-900` | `#111827` | Headings |

#### Semantic (status, feedback)

| Token | Hex | Tailwind equivalent | Use |
|---|---|---|---|
| `success-50` | `#f0fdf4` | green-50 | KYC Verified badge background |
| `success-600` | `#16a34a` | green-600 | KYC Verified badge text / icon |
| `success-700` | `#15803d` | green-700 | Success button hover, activated banner |
| `warning-50` | `#fffbeb` | amber-50 | KYC Pending badge background |
| `warning-600` | `#d97706` | amber-600 | KYC Pending badge text / icon |
| `warning-700` | `#b45309` | amber-700 | Warning emphasis |
| `danger-50` | `#fef2f2` | red-50 | KYC Rejected badge background, error field tint |
| `danger-600` | `#dc2626` | red-600 | KYC Rejected badge text, inline form error text |
| `danger-700` | `#b91c1c` | red-700 | Destructive button, error border |

> **Badge → colour mapping** (from §3.1): `verified` → `success-*`, `pending` → `warning-*`, `rejected` → `danger-*`. The Badge component must use these semantic tokens, not hardcoded Tailwind colour steps.

### 4.4 `tailwind.config.ts` Reference Snippet

Story 1.7 must apply this configuration. The `extend` pattern keeps Tailwind's reset utilities (spacing, flex, etc.) while replacing colour and typography with project tokens.

```ts
// frontend/tailwind.config.ts
import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        brand: {
          50: '#eff6ff', 100: '#dbeafe',
          500: '#3b82f6', 600: '#2563eb',
          700: '#1d4ed8', 900: '#1e3a8a',
        },
        neutral: {
          50: '#f9fafb', 100: '#f3f4f6', 200: '#e5e7eb',
          400: '#9ca3af', 600: '#4b5563',
          800: '#1f2937', 900: '#111827',
        },
        success: { 50: '#f0fdf4', 600: '#16a34a', 700: '#15803d' },
        warning: { 50: '#fffbeb', 600: '#d97706', 700: '#b45309' },
        danger:  { 50: '#fef2f2', 600: '#dc2626', 700: '#b91c1c' },
      },
    },
  },
  plugins: [],
} satisfies Config
```

---

## 5. Multi-Step Registration Form

Route: `/register` → component: `portals/subscriber/Register.tsx`

The form is a three-step wizard. The stepper component should show current step progress (e.g. `Step 1 of 3`).

### Step 1 — Personal Details

Fields:
- Full name (required)
- Email address (required, validated)
- MSISDN / mobile number being registered (required — the number to activate)
- **Alternate mobile number** (required — used for pre-activation OTP per PRD A-6, FR-4)

Error surface:
- Duplicate MSISDN (HTTP 409 `DUPLICATE_MSISDN`) maps to an **inline form error** on the MSISDN field in Step 1. Story 1.6 consumes this.

### Step 2 — TRAI CAF Fields (Customer Acquisition Form)

Fields (per TRAI Customer Acquisition Form requirements):
- Date of birth
- Address (line 1, line 2, city, state, PIN code)
- ID proof type (Aadhaar / PAN / Passport / Voter ID)
- ID proof number
- Consent checkbox (data processing consent per TRAI CAF)

### Step 3 — Registration ID Display + OTP Entry

Actions:
1. On form submit from Step 2, the backend generates and returns a `Registration ID` in format `REG-{YYYYMMDD}-{8 hex chars}` (e.g. `REG-20260620-3a7f1b2c`).
2. Step 3 **displays** this Registration ID prominently — subscribers use it as their login credential.
3. An OTP is simultaneously sent to the **alternate mobile number** provided in Step 1.
4. Step 3 contains an OTP entry field and a "Verify & Complete" button.
5. On successful OTP verification → registration complete; redirect to `/activate`.

---

## 6. SIM Activation Order Tracker

Route: `/activate` → component: `portals/subscriber/SimActivation.tsx`

### Step Indicator

The tracker shows four ordered states as a horizontal (or vertical) step indicator:

```
[ Created ] → [ KYC Pending ] → [ KYC Verified ] → [ Activated ]
```

Visual rules:
- **Current step:** highlighted (filled circle / bold label)
- **Completed steps:** checkmark icon
- **Pending steps:** unfilled / greyed

### Data Polling

- Endpoint: `GET /api/v1/subscriber/orders/{order_id}/status`
- Poll interval: **10 seconds** (no WebSocket for this flow — Story 1.7)
- The `order_id` is derived from the subscriber's session / query parameter passed from Step 3 of registration.

### Completion State

When `status = 'ACTIVATED'`:
- Display a **success banner** containing:
  - Confirmation message (e.g. "Your SIM is activated!")
  - The subscriber's MSISDN

---

## 7. Project Structure Notes & Conflict Callout

### 7.1 Authoritative Layout (use this)

The architecture-defined layout (§1.9.1, §1.11.2, §1.12.1) is authoritative for all Epic 1 frontend stories. This supersedes the Feature-Sliced Design (FSD) conventions in `frontend/CLAUDE.md`.

```
frontend/src/
├── portals/
│   ├── subscriber/     Dashboard.tsx, Balance.tsx, Recharge.tsx, Chatbot.tsx, Profile.tsx,
│   │                   SimActivation.tsx, Register.tsx, Login.tsx, KycStatus.tsx, PaymentMethods.tsx
│   ├── ops/            PlanStock.tsx, OrderFulfilment.tsx, Forecasts.tsx, Segmentation.tsx
│   ├── fraud/          AnomalyFeed.tsx, CaseQueue.tsx
│   └── simulator/      CdrSimulator.tsx, NotificationPortal.tsx, SimActivation.tsx
├── components/
│   ├── ui/             Button.tsx, Card.tsx, Badge.tsx, Table.tsx, Modal.tsx
│   ├── charts/         (Recharts wrappers)
│   └── layout/         Navbar.tsx, Sidebar.tsx, RoleGuard.tsx
├── hooks/              useBalance.ts, useWebSocket.ts, useAuth.ts
├── lib/                api.ts, auth.ts, queryClient.ts
└── types/              subscriber.ts, billing.ts, fraud.ts
```

### 7.2 Conflict Resolution Table

| Concern | **Authoritative — use this** (architecture §1.12.1) | **Superseded — do NOT use** (`frontend/CLAUDE.md`) |
|---|---|---|
| Folder layout | `src/portals/{subscriber,ops,fraud,simulator}/`, `src/components/ui/` | Feature-Sliced Design: `src/features/`, `src/entities/`, `src/shared/`, `src/routes/` |
| Styling | TailwindCSS utility classes only; `globals.css` for resets | `PascalCase.module.scss` SCSS modules |
| Page naming | `SimActivation.tsx`, `Profile.tsx` (plain PascalCase under `portals/<role>/`) | `PascalCasePage.tsx` (e.g. `ProfilePage.tsx`) |
| Hooks | `usePascalCase.ts` (`useBalance.ts`, `useAuth.ts`) | `camelCase.ts` |

### 7.3 Existing `frontend/` Scaffold

The existing `frontend/` directory may contain a scaffold that follows the superseded FSD conventions. Story 1.7 is responsible for reorganising it to match the authoritative layout above. This brief documents the target; it does not perform that reorganisation.

---

## References

- [architecture.md §1.9.1](architecture.md#191-single-spa--role-based-dashboard-routing) — Role-based routing
- [architecture.md §1.11.2](architecture.md#1112-naming-conventions) — Naming conventions (React)
- [architecture.md §1.12.1](architecture.md#1121-monorepo-layout) — Monorepo layout (frontend tree)
- [prd.md UJ-1](prds/prd-sboai_capstone-2026-06-18/prd.md) — Canonical user journey: Priya activates her SIM
- [prd.md A-6, FR-4](prds/prd-sboai_capstone-2026-06-18/prd.md) — Pre-activation OTP via alternate mobile number
- [epics.md Story 1.1](../implementation-artifacts/1-1-ux-brief-subscriber-registration-identity-flows.md) — Source story
