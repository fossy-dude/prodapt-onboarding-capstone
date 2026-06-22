/**
 * Unit tests for RoleGuard (Story 1.8; AC #3).
 *
 * Verified behaviour:
 * - Renders children for a token whose role matches `allowedRoles`.
 * - Redirects to /login for a token with a mismatched role.
 * - Redirects to /login when no token is present.
 * - Redirects to /login for an expired token.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { removeToken, saveToken } from '../../lib/auth';
import { RoleGuard } from './RoleGuard';

// ── JWT helpers (same pattern as auth.test.ts) ────────────────────────────────

function makeToken(payload: object, expiresInSeconds = 1800): string {
  const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  const exp = Math.floor(Date.now() / 1000) + expiresInSeconds;
  const body = btoa(JSON.stringify({ exp, ...payload }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `${header}.${body}.fake-sig`;
}

afterEach(() => {
  removeToken();
  vi.restoreAllMocks();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderWithRouter(initialPath: string, ui: React.ReactNode) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/subscriber" element={ui} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('RoleGuard', () => {
  it('renders children when the token role matches allowedRoles', () => {
    saveToken(makeToken({ sub: 'u1', 'cognito:groups': ['subscriber'] }));
    renderWithRouter(
      '/subscriber',
      <RoleGuard allowedRoles={['subscriber']}>
        <div>Subscriber dashboard</div>
      </RoleGuard>,
    );
    expect(screen.getByText('Subscriber dashboard')).toBeInTheDocument();
  });

  it('redirects to /login when no token is stored', () => {
    renderWithRouter(
      '/subscriber',
      <RoleGuard allowedRoles={['subscriber']}>
        <div>Subscriber dashboard</div>
      </RoleGuard>,
    );
    expect(screen.getByText('Login page')).toBeInTheDocument();
    expect(screen.queryByText('Subscriber dashboard')).not.toBeInTheDocument();
  });

  it('redirects to /login when the token role does not match allowedRoles', () => {
    saveToken(makeToken({ sub: 'u1', 'cognito:groups': ['ops'] })); // ops, not subscriber
    renderWithRouter(
      '/subscriber',
      <RoleGuard allowedRoles={['subscriber']}>
        <div>Subscriber dashboard</div>
      </RoleGuard>,
    );
    expect(screen.getByText('Login page')).toBeInTheDocument();
    expect(screen.queryByText('Subscriber dashboard')).not.toBeInTheDocument();
  });

  it('redirects to /login when the token is expired', () => {
    saveToken(makeToken({ sub: 'u1', 'cognito:groups': ['subscriber'] }, -1));
    renderWithRouter(
      '/subscriber',
      <RoleGuard allowedRoles={['subscriber']}>
        <div>Subscriber dashboard</div>
      </RoleGuard>,
    );
    expect(screen.getByText('Login page')).toBeInTheDocument();
  });

  it('allows multiple roles — renders when token role is any of them', () => {
    saveToken(makeToken({ sub: 'u1', 'cognito:groups': ['admin'] }));
    render(
      <MemoryRouter initialEntries={['/ops']}>
        <Routes>
          <Route
            path="/ops"
            element={
              <RoleGuard allowedRoles={['ops', 'admin', 'marketing']}>
                <div>Ops dashboard</div>
              </RoleGuard>
            }
          />
          <Route path="/login" element={<div>Login page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('Ops dashboard')).toBeInTheDocument();
  });
});
