import { NavLink } from "react-router-dom";
import { LayoutDashboard, LogOut } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { logout } from "../../lib/auth";

interface NavItem {
  readonly label: string;
  readonly to: string;
  readonly icon: LucideIcon;
  readonly end?: boolean;
}

const OPS_NAV: readonly NavItem[] = [
  { label: "Dashboard", to: "/ops/dashboard", icon: LayoutDashboard },
];

const ACTIVE_CLS = "bg-brand-600 text-white";
const INACTIVE_CLS =
  "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100";

function SidebarLink({ to, label, icon: Icon, end }: NavItem) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isActive ? ACTIVE_CLS : INACTIVE_CLS
        }`
      }
    >
      <Icon size={16} aria-hidden="true" />
      {label}
    </NavLink>
  );
}

function OpsSidebar() {
  return (
    <aside className="flex flex-col w-60 bg-neutral-900 flex-shrink-0">
      <div className="px-5 py-5 border-b border-neutral-800">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center flex-shrink-0">
            <span className="text-white text-xs font-bold tracking-tight">
              SB
            </span>
          </div>
          <div>
            <p className="text-white text-sm font-semibold leading-tight">
              SBoAI
            </p>
            <p className="text-neutral-500 text-xs leading-tight">Ops Portal</p>
          </div>
        </div>
      </div>

      <nav
        className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto"
        aria-label="Ops navigation"
      >
        {OPS_NAV.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}
      </nav>

      <div className="px-3 py-4 border-t border-neutral-800">
        <button
          type="button"
          onClick={logout}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${INACTIVE_CLS}`}
        >
          <LogOut size={16} aria-hidden="true" />
          Sign Out
        </button>
      </div>
    </aside>
  );
}

export { OpsSidebar };
