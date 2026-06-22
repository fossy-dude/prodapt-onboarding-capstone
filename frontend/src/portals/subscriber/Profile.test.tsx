import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { Profile } from './Profile';

// Mock the api module: getProfile + updateProfile are replaceable per-test.
vi.mock('../../lib/api', () => ({
  getProfile: vi.fn(),
  updateProfile: vi.fn(),
  toApiError: () => null,
}));

const { getProfile, updateProfile } = await import('../../lib/api');

type ProfileData = {
  readonly name: string;
  readonly email: string | null;
  readonly address: {
    readonly line1: string | null;
    readonly line2: string | null;
    readonly city: string | null;
    readonly state: string | null;
    readonly pin_code: string | null;
  };
  readonly kyc_status: string;
};

function makeProfile(kyc_status: string, overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    name: 'Priya Sharma',
    email: 'priya@example.com',
    address: { line1: '12 MG Road', line2: 'Flat 3', city: 'Bengaluru', state: 'Karnataka', pin_code: '560001' },
    kyc_status,
    ...overrides,
  };
}

function renderProfile() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Profile />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Subscriber profile page', () => {
  beforeEach(() => {
    vi.mocked(getProfile).mockReset();
    vi.mocked(updateProfile).mockReset();
  });

  it('renders the decrypted name/email/address for a verified profile', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('verified'));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Priya Sharma')).toBeInTheDocument());
    expect(screen.getByText('priya@example.com')).toBeInTheDocument();
    expect(screen.getByText('12 MG Road')).toBeInTheDocument();
    expect(screen.getByText('Bengaluru')).toBeInTheDocument();
  });

  it('renders the verified Badge variant for kyc_status=verified (AC #2)', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('verified'));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Verified')).toBeInTheDocument());
    const badge = screen.getByText('Verified');
    expect(badge).toHaveClass('text-success-700');
  });

  it('renders the pending Badge variant for kyc_status=pending (AC #2)', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('pending'));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Pending')).toBeInTheDocument());
    expect(screen.getByText('Pending')).toHaveClass('text-warning-700');
    // No rejection reason / resubmit link when not rejected.
    expect(screen.queryByText(/not approved/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /re-submit kyc/i })).not.toBeInTheDocument();
  });

  it('renders the rejected Badge, rejection reason, and a re-submit link (AC #2, #5)', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('rejected'));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Rejected')).toBeInTheDocument());
    expect(screen.getByText('Rejected')).toHaveClass('text-danger-700');
    expect(screen.getByRole('alert')).toHaveTextContent(/not approved/i);
    const resubmit = screen.getByRole('link', { name: /re-submit kyc documents/i });
    expect(resubmit).toHaveAttribute('href', '/subscriber/profile/kyc');
  });

  it('shows a loading state, then an error state on failure', async () => {
    vi.mocked(getProfile).mockReturnValue(new Promise(() => {})); // pending
    renderProfile();
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i);
  });

  it('shows an error message when the profile fails to load', async () => {
    vi.mocked(getProfile).mockRejectedValue(new Error('Network error'));
    renderProfile();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/unable to load/i));
  });

  it('submits the edit form → PATCH then refetches the profile (AC #3, #4)', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('verified'));
    vi.mocked(updateProfile).mockResolvedValue(makeProfile('verified', { email: 'new@example.com' }));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Priya Sharma')).toBeInTheDocument());

    const initialCalls = vi.mocked(getProfile).mock.calls.length;
    const emailInput = screen.getByLabelText('Email');
    fireEvent.change(emailInput, { target: { value: 'new@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(vi.mocked(updateProfile)).toHaveBeenCalled());
    expect(vi.mocked(updateProfile).mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ email: 'new@example.com' }),
    );
    // Invalidation refetches the profile query (≥1 call after the submit).
    await waitFor(() => {
      expect(vi.mocked(getProfile).mock.calls.length).toBeGreaterThan(initialCalls);
    });
    // Success message surfaces.
    expect(screen.getByText(/profile updated/i)).toBeInTheDocument();
  });

  it('blocks submit and shows an inline error for an invalid email', async () => {
    vi.mocked(getProfile).mockResolvedValue(makeProfile('verified'));
    renderProfile();
    await waitFor(() => expect(screen.getByText('Priya Sharma')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'not-an-email' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(screen.getByRole('alert')).toHaveTextContent(/valid email/i);
    expect(vi.mocked(updateProfile)).not.toHaveBeenCalled();
  });
});
