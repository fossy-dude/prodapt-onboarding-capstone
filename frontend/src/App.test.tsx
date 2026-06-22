import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { App } from './App';

describe('App', () => {
  it('redirects unauthenticated users to /login from the root route (Story 1.8)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    // The wildcard route now redirects to /login; Login renders a Sign in heading.
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the login form on /login', () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/registration id or msisdn/i)).toBeInTheDocument();
  });
});
