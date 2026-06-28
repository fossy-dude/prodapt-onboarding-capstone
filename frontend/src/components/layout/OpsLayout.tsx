import { type ReactNode } from "react";

import { OpsSidebar } from "./OpsSidebar";

interface OpsLayoutProps {
  readonly children: ReactNode;
}

function OpsLayout({ children }: OpsLayoutProps) {
  return (
    <div className="flex h-screen bg-neutral-50">
      <OpsSidebar />
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

export { OpsLayout };
