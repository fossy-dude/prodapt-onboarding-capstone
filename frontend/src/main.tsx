import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';

/**
 * Application bootstrap.
 *
 * Mounts the root <App /> component into the #root element declared by index.html.
 * The full router, providers and CopilotKit runtime are wired up in Story 1.7.
 */
const rootElement = document.getElementById('root');

if (rootElement === null) {
  throw new Error('Root element #root not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
