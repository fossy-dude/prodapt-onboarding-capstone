import { type ReactNode } from "react";
import { SimulatorSidebar } from "./SimulatorSidebar";

interface SimulatorLayoutProps {
  readonly children: ReactNode;
}

function SimulatorLayout({ children }: SimulatorLayoutProps) {
  return (
    <div className="flex h-screen bg-neutral-50">
      <SimulatorSidebar />
      <div className="flex-1 overflow-y-auto">{children}</div>
    </div>
  );
}

export { SimulatorLayout };
