/**
 * Unit tests for lib/auth.ts (Story 1.8).
 *
 * Tests JWT decoding, role extraction, expiry detection, and token CRUD.
 * No live Cognito or Valkey; uses synthetic JWT payloads.
 */

import { afterEach, describe, expect, it } from 'vitest';

import { decodeJwtPayload, getRole, getSub, isAuthenticated, removeToken, saveToken } from './auth';

// ── JWT test fixtures ────────────────────────────────────────────────────────

/** Build a minimal base64url-encoded JWT with the given payload (no real signature). */
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
  return `${header}.${body}.fake-signature`;
}

function makeExpiredToken(payload: object): string {
  return makeToken(payload, -1); // already expired
}

// ── Setup / teardown ────────────────────────────────────────────────────────

afterEach(() => {
  removeToken();
});

// ── decodeJwtPayload ────────────────────────────────────────────────────────

describe('decodeJwtPayload', () => {
  it('returns the payload from a valid JWT', () => {
    const token = makeToken({ sub: 'user-1', 'cognito:groups': ['subscriber'] });
    const payload = decodeJwtPayload(token);
    expect(payload).not.toBeNull();
    expect(payload?.sub).toBe('user-1');
    expect(payload?.['cognito:groups']).toEqual(['subscriber']);
  });

  it('returns null for a malformed token (wrong part count)', () => {
    expect(decodeJwtPayload('notavalidjwt')).toBeNull();
  });

  it('returns null for a token with invalid base64 payload', () => {
    expect(decodeJwtPayload('header.!!!.sig')).toBeNull();
  });
});

// ── isAuthenticated ──────────────────────────────────────────────────────────

describe('isAuthenticated', () => {
  it('returns false when no token is stored', () => {
    expect(isAuthenticated()).toBe(false);
  });

  it('returns true for a valid, non-expired token', () => {
    saveToken(makeToken({ sub: 'user-1', 'cognito:groups': ['subscriber'] }));
    expect(isAuthenticated()).toBe(true);
  });

  it('returns false for an expired token', () => {
    saveToken(makeExpiredToken({ sub: 'user-1', 'cognito:groups': ['subscriber'] }));
    expect(isAuthenticated()).toBe(false);
  });

  it('returns false for a syntactically invalid token string', () => {
    saveToken('garbage');
    expect(isAuthenticated()).toBe(false);
  });
});

// ── getRole ──────────────────────────────────────────────────────────────────

describe('getRole', () => {
  it('returns null when no token is stored', () => {
    expect(getRole()).toBeNull();
  });

  it('returns the first cognito:groups entry as the role', () => {
    saveToken(makeToken({ sub: 'user-1', 'cognito:groups': ['subscriber'] }));
    expect(getRole()).toBe('subscriber');
  });

  it('returns null for an expired token', () => {
    saveToken(makeExpiredToken({ sub: 'user-1', 'cognito:groups': ['subscriber'] }));
    expect(getRole()).toBeNull();
  });

  it('returns null when cognito:groups is empty', () => {
    saveToken(makeToken({ sub: 'user-1', 'cognito:groups': [] }));
    expect(getRole()).toBeNull();
  });

  it('returns null for an unknown group name', () => {
    saveToken(makeToken({ sub: 'user-1', 'cognito:groups': ['superadmin'] }));
    expect(getRole()).toBeNull();
  });

  it.each([
    ['subscriber'],
    ['ops'],
    ['fraud'],
    ['dev'],
    ['admin'],
    ['marketing'],
  ] as const)('returns "%s" for that group', (group) => {
    saveToken(makeToken({ sub: 'user-1', 'cognito:groups': [group] }));
    expect(getRole()).toBe(group);
  });
});

// ── getSub ───────────────────────────────────────────────────────────────────

describe('getSub', () => {
  it('returns the sub claim from a valid token', () => {
    saveToken(makeToken({ sub: 'abc-uuid-123', 'cognito:groups': ['subscriber'] }));
    expect(getSub()).toBe('abc-uuid-123');
  });

  it('returns null when no token is stored', () => {
    expect(getSub()).toBeNull();
  });

  it('returns null for an expired token', () => {
    saveToken(makeExpiredToken({ sub: 'abc-uuid-123' }));
    expect(getSub()).toBeNull();
  });
});
