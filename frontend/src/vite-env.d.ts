/// <reference types="vite/client" />

/**
 * Environment variables available to the frontend.
 * Vite exposes these via `import.meta.env`.
 * All custom variables must be prefixed with `VITE_` to be accessible.
 *
 * Example: VITE_API_BASE_URL in .env → import.meta.env.VITE_API_BASE_URL
 */
interface ImportMetaEnv {
  /** Application API base URL (e.g., http://localhost:8000) */
  readonly VITE_API_BASE_URL?: string;

  /** Application environment (development, staging, production) */
  readonly VITE_ENV?: 'development' | 'staging' | 'production';

  // Add more custom environment variables here as needed.
  // Example:
  // readonly VITE_FEATURE_FLAG_NEW_UI?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
