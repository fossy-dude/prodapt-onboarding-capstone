import { type ReactNode } from "react";
import { SubscriberSidebar } from "./SubscriberSidebar";

interface SubscriberLayoutProps {
  readonly children: ReactNode;
}

function SubscriberLayout({ children }: SubscriberLayoutProps) {
  return (
    <div className="flex h-screen bg-neutral-50">
      <SubscriberSidebar />
      <div className="flex-1 overflow-y-auto">
        {children}
      </div>
    </div>
  );
}

export { SubscriberLayout };
