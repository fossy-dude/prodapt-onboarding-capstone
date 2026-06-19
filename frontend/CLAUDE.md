# Project Rules & Standards

> This document defines the engineering standards and conventions for this React project. All contributors must follow these rules to maintain consistency, quality, and maintainability.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [File & Folder Conventions](#2-file--folder-conventions)
3. [Naming Conventions](#3-naming-conventions)
4. [TypeScript Rules](#4-typescript-rules)
5. [React Rules](#5-react-rules)
6. [Styling Rules](#6-styling-rules)
7. [Testing Rules](#7-testing-rules)
8. [Git & Commit Standards](#8-git--commit-standards)
9. [Code Quality & Enforcement](#9-code-quality--enforcement)
10. [Performance](#10-performance)
11. [Accessibility](#11-accessibility)
12. [Documentation](#12-documentation)
13. [Dependencies](#13-dependencies)
14. [Environment & Configuration](#14-environment--configuration)

---

## 1. Architecture

### 1.1 Feature-Based Structure

This project uses a **domain-heavy enterprise architecture** inspired by Feature-Sliced Design. The codebase is organized into layers with strict dependency rules.

```
src/
  app/           → Application shell: root component, providers, global layout
  features/      → Feature slices: each feature is self-contained
    [feature]/
      pages/     → Page-level components for this feature
      components/→ Feature-specific components
      hooks/     → Feature-specific hooks
      api/       → Feature-specific API calls
      types/     → Feature-specific types
      utils/     → Feature-specific utilities
      index.ts   → Public API (barrel export)
  entities/      → Business entities: shared domain models and logic
  shared/        → Shared infrastructure: UI kit, generic hooks, utilities
    ui/          → Reusable UI components (Button, Input, Modal, etc.)
    hooks/       → Generic reusable hooks
    lib/         → Third-party library configurations, helpers
    types/       → Shared TypeScript types and interfaces
    config/      → Shared configuration constants
  routes/        → Route definitions and route-level components
  styles/        → Global styles, design tokens, CSS reset
  types/         → Global type declarations
  test/          → Test utilities and setup
```

### 1.2 Dependency Rules

Dependencies must only point **downward**:

- `app` → may import from `features`, `entities`, `shared`, `routes`
- `features` → may import from `entities`, `shared`
- `entities` → may import from `shared` only
- `shared` → may not import from any other layer
- `routes` → may import from `features`, `shared`

**Cross-feature imports are forbidden.** Feature A must not import from Feature B. If shared logic is needed, extract it to `entities` or `shared`.

### 1.3 Barrel Exports

Every module, feature, and shared unit must have an `index.ts` barrel file that defines its public API. Consumers must import from the barrel, not from internal files.

```typescript
// ✅ Correct
import { Button } from '@/shared/ui';

// ❌ Wrong
import { Button } from '@/shared/ui/Button/Button';
```

---

## 2. File & Folder Conventions

### 2.1 File Naming

| Type             | Pattern               | Example                            |
| ---------------- | --------------------- | ---------------------------------- |
| Component        | `PascalCase.tsx`      | `Button.tsx`, `UserProfile.tsx`    |
| Component test   | `PascalCase.test.tsx` | `Button.test.tsx`                  |
| Hook             | `camelCase.ts`        | `useDocumentTitle.ts`              |
| Hook test        | `camelCase.test.ts`   | `useDocumentTitle.test.ts`         |
| Utility          | `camelCase.ts`        | `formatDate.ts`                    |
| Type declaration | `camelCase.d.ts`      | `vite-env.d.ts`                    |
| Barrel export    | `index.ts`            | `index.ts`                         |
| Page component   | `PascalCasePage.tsx`  | `HomePage.tsx`, `SettingsPage.tsx` |

### 2.2 File Structure (Component)

Each component file should follow this order:

```typescript
// 1. Imports
import { type ReactNode } from 'react';

// 2. Types
interface ComponentProps {
  readonly children: ReactNode;
}

// 3. Component
function Component({ children }: ComponentProps) {
  return <div className="flex flex-col">{children}</div>;
}

// 4. Named exports (no default exports)
export { Component };
export type { ComponentProps };
```

### 2.3 File Size Limits

- **Component files**: Maximum 200 lines. If larger, split into sub-components.
- **Hook files**: Maximum 100 lines.
- **Utility files**: Maximum 150 lines.
- **Test files**: No hard limit, but prefer focused, descriptive test cases.

---

## 3. Naming Conventions

### 3.1 General

- Use **descriptive, intention-revealing names**. Avoid abbreviations except widely-known ones (`url`, `id`, `api`).
- Boolean variables and props use `is`, `has`, `should`, `can` prefixes: `isLoading`, `hasError`, `shouldRetry`.

### 3.2 Components

- PascalCase: `Button`, `UserAvatar`, `NavigationMenu`
- Name files the same as the component: `UserAvatar.tsx` exports `UserAvatar`

### 3.3 Functions & Variables

- camelCase: `handleSubmit`, `userData`, `isActive`
- Prefix event handlers with `handle`: `handleClick`, `handleFormSubmit`
- Prefix boolean getters with `is/has/should`: `isValid`, `hasPermission`

### 3.4 Types & Interfaces

- PascalCase for types and interfaces: `UserProfile`, `ApiError`, `ButtonProps`
- Suffix props interfaces with `Props`: `ButtonProps`, `CardProps`
- Suffix event handler types with `Handler`: `ClickHandler`, `ChangeHandler`
- Use `type` for unions and primitives, `interface` for objects:

```typescript
// ✅ type for unions/primitives
type Status = 'idle' | 'loading' | 'success' | 'error';
type ID = string;

// ✅ interface for object shapes
interface UserProfile {
  readonly id: ID;
  readonly name: string;
  readonly email: string;
}
```

### 3.5 Constants

- SCREAMING_SNAKE_CASE for true constants: `MAX_RETRIES`, `API_BASE_URL`
- camelCase for configuration objects: `defaultTheme`, `routeConfig`

### 3.6 CSS Classes (Tailwind)

- Use Tailwind utility classes directly in JSX `className`.
- Use semantic, descriptive component names even when classes are utilities: a `HeroSection` component is clear regardless of its utilities.
- Extract repeated utility combinations into components or `@apply` in `src/styles/` only when reuse is genuinely needed.

---

## 4. TypeScript Rules

### 4.1 Strict Mode

TypeScript strict mode is enabled with additional strictness flags:

- `strict: true`
- `noUnusedLocals: true`
- `noUnusedParameters: true`
- `noFallthroughCasesInSwitch: true`
- `noUncheckedIndexedAccess: true`
- `forceConsistentCasingInFileNames: true`

### 4.2 Type Safety

- **Never use `any`.** Use `unknown` and narrow with type guards, or define a proper type.
- **Never use `@ts-ignore` or `@ts-expect-error`** without a comment explaining why.
- Use `readonly` for props interfaces and data that should not mutate.
- Prefer `type` imports: `import { type UserProfile } from '@/entities/user'`.
- Avoid type assertions (`as`). Use type guards or proper typing instead.

### 4.3 Null & Undefined

- Always handle `null` and `undefined` cases explicitly.
- Use optional chaining (`?.`) and nullish coalescing (`??`).
- Prefer explicit `undefined` over implicit `undefined`.

### 4.4 Enums

- Avoid TypeScript `enum`. Use string literal unions instead:

```typescript
// ✅ Preferred
type Status = 'idle' | 'loading' | 'success' | 'error';

// ❌ Avoid
enum Status {
  Idle,
  Loading,
  Success,
  Error,
}
```

### 4.5 Generics

- Use descriptive generic names for more than one type parameter: `TInput`, `TOutput`.
- Single-letter generics (`T`, `K`, `V`) are acceptable for simple cases.

---

## 5. React Rules

### 5.1 Component Patterns

- **Function components only.** No class components.
- **Named exports only.** No default exports. This ensures consistent imports and better refactoring.
- **One component per file.** Small helper sub-components are acceptable within the same file if closely coupled.
- Keep components **focused and composable**. Each component should have a single responsibility.

### 5.2 Props

- Define props with `interface` or `type` and suffix with `Props`.
- Use `readonly` modifier for all prop interface fields.
- Destructure props in the function signature.
- Provide default values via destructuring defaults, not with `defaultProps`.

```typescript
// ✅ Correct
interface ButtonProps {
  readonly variant?: 'primary' | 'secondary';
  readonly disabled?: boolean;
  readonly children: React.ReactNode;
}

function Button({ variant = 'primary', disabled = false, children }: ButtonProps) {
  // ...
}
```

### 5.3 State Management

- **Start with React's built-in state** (`useState`, `useReducer`).
- Lift state up to the nearest common ancestor.
- Only reach for external state management (Zustand, Jotai, etc.) when React's built-in state becomes insufficient.
- Never store derived state — compute it on render.

### 5.4 Effects

- **Minimize `useEffect`.** Most effects can be replaced with:
  - Derived state (compute during render)
  - Event handlers (handle in response to user actions)
  - `useSyncExternalStore` (subscribe to external stores)
- When `useEffect` is necessary, keep it focused on one concern.
- Always specify the dependency array. Never omit it.
- Use cleanup functions to prevent memory leaks.

### 5.5 Keys

- **Always use stable, unique keys** for list rendering.
- Never use array indices as keys when the list can be reordered, added to, or removed from.
- Use meaningful IDs from your data.

### 5.6 Rendering

- Avoid unnecessary re-renders:
  - Move static objects and arrays outside components or use `useMemo` when truly needed.
  - Pass stable callbacks with `useCallback` only when the callback is a dependency of a memoized child.
- **Do not premature optimize.** Use React DevTools Profiler to identify actual bottlenecks.
- Keep rendering predictable — avoid side effects during render.

### 5.7 Error Handling

- Use Error Boundaries for graceful error recovery.
- Always handle loading and error states in data-fetching components.
- Never silently swallow errors — at minimum, log them.

---

## 6. Styling Rules

### 6.1 Tailwind CSS

- **Use Tailwind utility classes** for all component styling via `className`.
- **Never use inline styles** except for truly dynamic, computed values (e.g. `style={{ width: dynamicWidth }}`).
- **Never introduce CSS Modules or global CSS class names** for component-specific styles.

### 6.2 Design Tokens

- **Extend the Tailwind theme** in `tailwind.config.ts` to define colors, spacing, typography, and other design tokens.
- **Never hard-code** raw color hex values, pixel sizes, or font sizes outside the Tailwind config.
- Reference tokens via Tailwind classes: `text-brand-primary`, `p-spacing-md`, etc.

### 6.3 Organization

- Global base styles and Tailwind directives belong in `src/styles/global.css`.
- Use `@layer base`, `@layer components`, `@layer utilities` when authoring custom CSS.
- Keep custom CSS minimal — prefer Tailwind utilities and theme extensions.

### 6.4 Responsive Design

- Use Tailwind's responsive prefixes: `sm:`, `md:`, `lg:`, `xl:`, `2xl:`.
- Design mobile-first: base classes target mobile, prefixed classes scale up.
- Use Tailwind's spacing scale (`p-4`, `mt-6`) rather than raw `rem`/`px` values.

### 6.5 Naming

- Use semantic component names and props, not visual utility names.
- If `@apply` is used (sparingly), keep class names semantic: `.errorMessage`, not `.redText`.
- Prefer composing components over duplicating long utility strings.

---

## 7. Testing Rules

### 7.1 Testing Stack

- **Vitest** as the test runner.
- **React Testing Library** for component testing.
- **jsdom** as the test environment.
- **`@testing-library/user-event`** for simulating user interactions.

### 7.2 Testing Philosophy

- **Test behavior, not implementation.** Focus on what the user sees and does.
- Write tests from the user's perspective using accessible queries:
  - `getByRole`, `getByLabelText`, `getByText`, `getByPlaceholderText`
- Avoid testing internal state, class names (except for variant verification), or implementation details.

### 7.3 Coverage

- **Minimum 80% coverage** for lines, functions, branches, and statements.
- Coverage is enforced through `vitest` threshold configuration.
- Coverage reports are generated in `coverage/` (gitignored).

### 7.4 Test File Organization

- Test files are co-located with the source: `Button.tsx` → `Button.test.tsx`.
- Use `describe` blocks to group related tests.
- Use descriptive test names: `it('renders the submit button as disabled when form is invalid')`.

### 7.5 Test Structure (AAA Pattern)

```typescript
it('disables the button when loading', () => {
  // Arrange
  const handleClick = vi.fn();

  // Act
  render(<Button onClick={handleClick} disabled>Submit</Button>);

  // Assert
  expect(screen.getByRole('button')).toBeDisabled();
});
```

### 7.6 Mocking

- Minimize mocking. Prefer real implementations.
- Mock external APIs and browser APIs only when necessary.
- Use `vi.fn()` for function mocks, `vi.mock()` for module mocks.
- Clean up mocks in `afterEach` or use `vi.restoreAllMocks()`.

---

## 8. Git & Commit Standards

### 8.1 Branch Naming

- `feature/description` — for new features
- `fix/description` — for bug fixes
- `refactor/description` — for code refactoring
- `docs/description` — for documentation changes
- `chore/description` — for maintenance tasks

### 8.2 Commit Messages

Follow the **Conventional Commits** format:

```
type(scope): subject

body (optional)

footer (optional)
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`, `perf`, `ci`

**Examples:**

```
feat(auth): add login form component
fix(button): resolve disabled state styling
refactor(hooks): extract useDocumentTitle to shared
test(button): add accessibility tests
chore(deps): update React to v19.1
```

**Rules:**

- Use imperative mood: "add", not "added" or "adds".
- Keep the subject line under 72 characters.
- Do not end the subject with a period.

### 8.3 Pre-commit Hooks

Husky + lint-staged will automatically:

- Run ESLint with `--fix` on staged `.ts`/`.tsx`/`.js`/`.jsx` files.
- Run Prettier with `--write` on staged `.ts`/`.tsx`/`.js`/`.jsx`/`.css`/`.json`/`.md` files.

**Do not bypass pre-commit hooks** with `--no-verify` unless absolutely necessary.

---

## 9. Code Quality & Enforcement

### 9.1 Validation Commands

All commands should pass before pushing:

```bash
npm run typecheck     # TypeScript type checking
npm run lint          # ESLint static analysis
npm run format:check  # Prettier formatting check
npm run test          # Vitest unit tests
npm run validate      # Runs all of the above
```

### 9.2 ESLint

- ESLint is configured with:
  - `eslint:recommended`
  - `@typescript-eslint/recommended`
  - `react-hooks` (rules of hooks)
  - `react-refresh` (fast refresh compatibility)
- Custom rules:
  - Unused variables prefixed with `_` are allowed.
  - Consistent type imports are enforced.
- Fix auto-fixable issues with `npm run lint:fix`.

### 9.3 Prettier

- Prettier formatting is enforced on all source files.
- Configuration is in `.prettierrc`.
- Run `npm run format` to auto-format.
- Run `npm run format:check` to verify formatting in CI.

### 9.4 IDE

- Use VS Code (recommended).
- Install recommended extensions: ESLint, Prettier.
- Enable "Format on Save" in VS Code settings.

---

## 10. Performance

### 10.1 Bundle Size

- **Tree-shake imports.** Import only what you need.
- **Lazy-load routes** with `React.lazy` and `Suspense`.
- **Analyze bundle** periodically with `npx vite-bundle-visualizer`.

### 10.2 Rendering Performance

- Avoid unnecessary state — derive values during render when possible.
- Use `React.memo` only when profiling shows a real benefit.
- Avoid creating new objects/arrays in render. Move them outside or use `useMemo`.
- Keep effects minimal and focused.

### 10.3 Asset Optimization

- Use modern image formats (WebP, AVIF).
- Lazy-load below-the-fold images.
- Use the `loading="lazy"` attribute on images and iframes.

### 10.4 Network

- Minimize API calls. Batch when possible.
- Use proper HTTP caching headers.
- Implement optimistic updates where appropriate.

---

## 11. Accessibility

### 11.1 Requirements

- All interactive elements must be reachable by keyboard.
- Use semantic HTML elements: `<button>`, `<nav>`, `<main>`, `<article>`, etc.
- All images must have `alt` text (empty `alt=""` for decorative images).
- All form inputs must have associated `<label>` elements.
- Use ARIA attributes only when semantic HTML is insufficient.
- Ensure sufficient color contrast (WCAG AA minimum).

### 11.2 Testing

- Test with keyboard navigation.
- Test with screen readers (VoiceOver, NVDA).
- Use `getByRole` in tests to verify accessibility.

---

## 12. Documentation

### 12.1 Code Comments

- **Code should be self-documenting.** Clear naming and structure replace most comments.
- Use JSDoc for exported functions, hooks, and utilities:
  ```typescript
  /**
   * Formats a date string into a human-readable format.
   * @param date - ISO 8601 date string
   * @returns Formatted date string (e.g., "Jan 1, 2025")
   */
  ```
- Use inline comments sparingly and only to explain **why**, not **what**.

### 12.2 README

- Keep `README.md` up to date with setup instructions, architecture overview, and available scripts.
- Document any special environment setup required.

### 12.3 Changelog

- Maintain a `CHANGELOG.md` for user-facing changes.
- Follow the changelog format from [Keep a Changelog](https://keepachangelog.com/).

---

## 13. Dependencies

### 13.1 Adding Dependencies

- **Justify every new dependency.** Prefer built-in browser APIs and React features.
- Evaluate: bundle size, maintenance status, community size, license, security.
- Add production dependencies to `dependencies` in `package.json`.
- Add development-only dependencies to `devDependencies`.

### 13.2 Updating Dependencies

- Run `npm outdated` periodically.
- Update dependencies in a dedicated commit.
- Run full test suite after updating.

### 13.3 Prohibited

- Do not install `jquery` or jQuery plugins.
- Do not install `moment.js` — use `Intl` or `date-fns`.
- Do not install `lodash` unless a specific utility is truly needed (prefer native methods).
- Do not install CSS-in-JS libraries (styled-components, Emotion, etc.) — use Tailwind CSS.

---

## 14. Environment & Configuration

### 14.1 Environment Variables

- Use `VITE_` prefix for environment variables (Vite requirement).
- Define all variables in `.env.example` (committed to git).
- Actual `.env` files are gitignored.
- Access via `import.meta.env.VITE_*`.
- Never expose secrets in environment variables that reach the client.

### 14.2 Configuration

- Keep configuration centralized in `src/shared/config/`.
- Use TypeScript constants, not environment-specific logic scattered throughout the codebase.
- Differentiate between build-time and runtime configuration.

---

## Quick Reference

| Command                 | Description                                       |
| ----------------------- | ------------------------------------------------- |
| `npm run dev`           | Start development server                          |
| `npm run build`         | Type-check and build for production               |
| `npm run preview`       | Preview production build                          |
| `npm run lint`          | Run ESLint                                        |
| `npm run lint:fix`      | Run ESLint with auto-fix                          |
| `npm run format`        | Format code with Prettier                         |
| `npm run format:check`  | Check formatting without writing                  |
| `npm run test`          | Run tests                                         |
| `npm run test:watch`    | Run tests in watch mode                           |
| `npm run test:coverage` | Run tests with coverage report                    |
| `npm run typecheck`     | Run TypeScript type checking                      |
| `npm run validate`      | Run all checks (typecheck + lint + format + test) |

---

_This document is the single source of truth for project standards. When in doubt, refer to this file. All pull requests are expected to comply with these rules._
