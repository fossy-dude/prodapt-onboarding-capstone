import { type ReactNode } from "react";

type Variant = "verified" | "pending" | "rejected" | "neutral";

interface BadgeProps {
  readonly variant?: Variant;
  readonly children: ReactNode;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  // Badge → colour mapping (UX brief §4 note): verified→success, pending→warning, rejected→danger.
  verified: "bg-success-50 text-success-700",
  pending: "bg-warning-50 text-warning-700",
  rejected: "bg-danger-50 text-danger-700",
  neutral: "bg-neutral-100 text-neutral-600",
};

/**
 * Status chip (UX brief §3.1). The three KYC variants must exist from the start so
 * Story 1.9 can consume them unchanged.
 */
function Badge({ variant = "neutral", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${VARIANT_CLASSES[variant]}`}
    >
      {children}
    </span>
  );
}

export { Badge };
export type { BadgeProps, Variant as BadgeVariant };
