import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';

import { App } from './App';
import { createQueryClient } from './lib/queryClient';
import './globals.css';

/**
 * Application bootstrap: BrowserRouter + TanStack Query providers wrap <App />.
 * The portals layout, RoleGuard and CopilotKit runtime expand in later stories.
 */
const rootElement = document.getElementById('root');

if (rootElement === null) {
  throw new Error('Root element #root not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
