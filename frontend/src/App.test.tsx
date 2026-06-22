import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { App } from './App';

function renderWithProviders(ui: React.ReactElement, initialEntries: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('App', () => {
  it('redirects unauthenticated users to /login from the root route (Story 1.8)', () => {
    renderWithProviders(<App />, ['/']);
    // The wildcard route now redirects to /login; Login renders a Sign in heading.
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the login form on /login', () => {
    renderWithProviders(<App />, ['/login']);
    expect(screen.getByLabelText(/registration id or msisdn/i)).toBeInTheDocument();
  });
});
