import { Navigate, Route, Routes } from "react-router-dom";

import { RoleGuard } from "./components/layout/RoleGuard";
import { Login } from "./portals/auth/Login";
import { Dashboard } from "./portals/subscriber/Dashboard";
import { NotificationPreferences } from "./portals/subscriber/NotificationPreferences";
import { PaymentMethods } from "./portals/subscriber/PaymentMethods";
import { Plans } from "./portals/subscriber/Plans";
import { Profile } from "./portals/subscriber/Profile";
import { Recharge } from "./portals/subscriber/Recharge";
import { Transactions } from "./portals/subscriber/Transactions";
import { CdrSimulator } from "./portals/simulator/CdrSimulator";
import { NotificationPortal } from "./portals/simulator/NotificationPortal";
import { SimActivation as SimActivationOrderTool } from "./portals/simulator/SimActivation";
import { SimActivationSimulator } from "./portals/simulator/SimActivationSimulator";
import { Register } from "./portals/subscriber/Register";
import { SimActivation } from "./portals/subscriber/SimActivation";

/**
 * Placeholder dashboard rendered inside a role-gated subtree until the
 * dedicated portal story is implemented.
 */
function PortalPlaceholder({ role }: { readonly role: string }) {
  return (
    <main className="px-4 py-10">
      <h1 className="text-2xl font-bold text-neutral-900">{role} portal</h1>
      <p className="mt-2 text-sm text-neutral-500">Dashboard coming soon.</p>
    </main>
  );
}

/**
 * Route table (§1.9.1, UX-DR7).
 *
 * Public routes (no auth required):
 *   /login    — passwordless OTP login (Story 1.8)
 *   /register — subscriber registration (Story 1.6)
 *
 * Role-gated subtrees (Story 1.8 RoleGuard):
 *   /subscriber/* — role: subscriber
 *   /ops/*        — role: ops | admin | marketing
 *   /fraud/*      — role: fraud
 *   /simulator/*  — role: dev
 */
function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      {/* Role-gated subtrees */}
      <Route
        path="/subscriber/*"
        element={
          <RoleGuard allowedRoles={["subscriber"]}>
            <Routes>
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="activate" element={<SimActivation />} />
              <Route path="history" element={<Transactions />} />
              <Route path="plans" element={<Plans />} />
              <Route path="recharge" element={<Recharge />} />
              <Route path="profile" element={<Profile />} />
              <Route path="profile/notifications" element={<NotificationPreferences />} />
              <Route
                path="profile/payment-methods"
                element={<PaymentMethods />}
              />
              <Route
                path="*"
                element={<PortalPlaceholder role="Subscriber" />}
              />
            </Routes>
          </RoleGuard>
        }
      />
      <Route
        path="/ops/*"
        element={
          <RoleGuard allowedRoles={["ops", "admin", "marketing"]}>
            <PortalPlaceholder role="Ops" />
          </RoleGuard>
        }
      />
      <Route
        path="/fraud/*"
        element={
          <RoleGuard allowedRoles={["fraud"]}>
            <PortalPlaceholder role="Fraud" />
          </RoleGuard>
        }
      />
      <Route
        path="/simulator/*"
        element={
          <RoleGuard allowedRoles={["dev"]}>
            <Routes>
              {/* Story 1.7 order-advance dev tool (imported directly — the `SimActivation`
              name was previously aliased to `SimActivationSimulator`, which is now the
              distinct Story 2.9 full-activation page at /simulator/sim-activation). */}
              <Route path="activate" element={<SimActivationOrderTool />} />
              <Route
                path="sim-activation"
                element={<SimActivationSimulator />}
              />
              <Route path="notifications" element={<NotificationPortal />} />
              <Route path="cdr" element={<CdrSimulator />} />
              <Route
                path="*"
                element={<PortalPlaceholder role="Simulator" />}
              />
            </Routes>
          </RoleGuard>
        }
      />

      {/* Default: redirect unauthenticated traffic to /login */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

export { App };
