import { type ReactNode } from "react";

interface CardProps {
  readonly children: ReactNode;
  readonly className?: string;
}

/**
 * Surface container for panels and form sections (UX brief §3.1).
 */
function Card({ children, className = "" }: CardProps) {
  return (
    <div
      className={`rounded-lg border border-neutral-200 bg-neutral-50 p-6 shadow-sm ${className}`}
    >
      {children}
    </div>
  );
}

interface CardSectionProps {
  readonly title: string;
  readonly children: ReactNode;
}

function CardSection({ title, children }: CardSectionProps) {
  return (
    <section className="mb-4 last:mb-0">
      <h2 className="mb-2 text-lg font-semibold text-neutral-900">{title}</h2>
      {children}
    </section>
  );
}

export { Card, CardSection };
export type { CardProps, CardSectionProps };
