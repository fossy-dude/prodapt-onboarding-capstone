/**
 * RoleGuard — renders the matching route subtree for the token's role (Story 1.8).
 *
 * AC #3 / UX-DR7: a single SPA with role-based subtree routing. The JWT's
 * `cognito:groups` determines the accessible path prefix:
 *
 *   subscriber → /subscriber/*
 *   ops        → /ops/*
 *   fraud      → /fraud/*
 *   dev        → /simulator/*
 *
 * On mismatch, missing token, or expired token → redirect to /login.
 */

import { type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

import { getRole, isAuthenticated, type PortalRole } from '../../lib/auth';

interface RoleGuardProps {
  /** The role(s) that may access this subtree. */
  readonly allowedRoles: readonly PortalRole[];
  /** Content to render for authorised users. */
  readonly children: ReactNode;
}

/**
 * Render `children` if the current token's role is in `allowedRoles`.
 * Redirect to `/login` otherwise.
 */
function RoleGuard({ allowedRoles, children }: RoleGuardProps) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }

  const role = getRole();
  if (role === null || !allowedRoles.includes(role)) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

export { RoleGuard };
export type { RoleGuardProps };
