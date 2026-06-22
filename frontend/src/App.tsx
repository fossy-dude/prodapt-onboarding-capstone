import { Navigate, Route, Routes } from 'react-router-dom';

import { RoleGuard } from './components/layout/RoleGuard';
import { Login } from './portals/auth/Login';
import { SimActivation as SimActivationSimulator } from './portals/simulator/SimActivation';
import { Register } from './portals/subscriber/Register';
import { SimActivation } from './portals/subscriber/SimActivation';

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
        element={<RoleGuard allowedRoles={['subscriber']}><Routes>
          <Route path="activate" element={<SimActivation />} />
          <Route path="*" element={<PortalPlaceholder role="Subscriber" />} />
        </Routes></RoleGuard>}
      />
      <Route
        path="/ops/*"
        element={
          <RoleGuard allowedRoles={['ops', 'admin', 'marketing']}>
            <PortalPlaceholder role="Ops" />
          </RoleGuard>
        }
      />
      <Route
        path="/fraud/*"
        element={
          <RoleGuard allowedRoles={['fraud']}>
            <PortalPlaceholder role="Fraud" />
          </RoleGuard>
        }
      />
      <Route
        path="/simulator/*"
        element={<RoleGuard allowedRoles={['dev']}><Routes>
          <Route path="activate" element={<SimActivationSimulator />} />
          <Route path="*" element={<PortalPlaceholder role="Simulator" />} />
        </Routes></RoleGuard>}
      />

      {/* Default: redirect unauthenticated traffic to /login */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

export { App };
