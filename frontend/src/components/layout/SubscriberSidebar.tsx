import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Bell,
  ChevronDown,
  ChevronRight,
  CreditCard,
  History,
  LayoutDashboard,
  LogOut,
  Package,
  PackageSearch,
  Receipt,
  User,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { logout } from "../../lib/auth";

interface NavItem {
  readonly label: string;
  readonly to: string;
  readonly icon: LucideIcon;
  readonly end?: boolean;
}

const MAIN_NAV: readonly NavItem[] = [
  { label: "Dashboard", to: "/subscriber/dashboard", icon: LayoutDashboard },
  { label: "Discover Plans", to: "/subscriber/plans", icon: PackageSearch },
  { label: "Transaction History", to: "/subscriber/history", icon: History },
  { label: "Bills & Receipts", to: "/subscriber/receipts", icon: Receipt },
];

const PROFILE_NAV: readonly NavItem[] = [
  { label: "Profile", to: "/subscriber/profile", icon: User, end: true },
  { label: "My SIM Orders", to: "/subscriber/activate", icon: Package },
  {
    label: "Payment Methods",
    to: "/subscriber/profile/payment-methods",
    icon: CreditCard,
  },
  {
    label: "Notifications",
    to: "/subscriber/profile/notifications",
    icon: Bell,
  },
];

const PROFILE_PREFIXES = ["/subscriber/profile", "/subscriber/activate"];

const ACTIVE_CLS = "bg-brand-600 text-white";
const INACTIVE_CLS =
  "text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100";

function SidebarLink({ to, label, icon: Icon, end }: NavItem) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${isActive ? ACTIVE_CLS : INACTIVE_CLS
        }`
      }
    >
      <Icon size={16} aria-hidden="true" />
      {label}
    </NavLink>
  );
}

function SubscriberSidebar() {
  const location = useLocation();

  const isOnProfileRoute = PROFILE_PREFIXES.some((prefix) =>
    location.pathname.startsWith(prefix)
  );

  const [profileOpen, setProfileOpen] = useState(isOnProfileRoute);

  useEffect(() => {
    if (isOnProfileRoute) setProfileOpen(true);
  }, [isOnProfileRoute]);

  return (
    <aside className="flex flex-col w-60 bg-neutral-900 flex-shrink-0">
      {/* Brand header */}
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
            <p className="text-neutral-500 text-xs leading-tight">
              Subscriber Portal
            </p>
          </div>
        </div>
      </div>

      {/* Main navigation */}
      <nav
        className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto"
        aria-label="Main navigation"
      >
        {MAIN_NAV.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}

        <div className="pt-3 pb-1">
          <hr className="border-neutral-800" />
        </div>

        {/* My Account collapsible */}
        <button
          type="button"
          onClick={() => setProfileOpen((prev) => !prev)}
          aria-expanded={profileOpen}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${isOnProfileRoute && !profileOpen
            ? "bg-neutral-800 text-neutral-100"
            : INACTIVE_CLS
            }`}
        >
          <User size={16} aria-hidden="true" />
          <span className="flex-1 text-left">My Account</span>
          {profileOpen ? (
            <ChevronDown size={14} aria-hidden="true" />
          ) : (
            <ChevronRight size={14} aria-hidden="true" />
          )}
        </button>

        {profileOpen && (
          <div className="ml-2 border-l border-neutral-800 pl-2 space-y-0.5">
            {PROFILE_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${isActive ? ACTIVE_CLS : INACTIVE_CLS
                  }`
                }
              >
                <item.icon size={14} aria-hidden="true" />
                {item.label}
              </NavLink>
            ))}
          </div>
        )}
      </nav>

      {/* Sign out */}
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

export { SubscriberSidebar };
