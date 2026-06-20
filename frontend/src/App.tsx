import { Navigate, Route, Routes } from 'react-router-dom';

import { Register } from './portals/subscriber/Register';

function Home() {
  return (
    <main className="px-4 py-10">
      <h1 className="text-3xl font-bold text-neutral-900">SBOAI Capstone</h1>
      <p className="mt-2 text-sm text-neutral-600">Subscriber self-care portal.</p>
    </main>
  );
}

/**
 * Route table (UX brief §2). The full role-gated router + portals are wired in
 * Story 1.7; Story 1.6 adds the public `/register` route it depends on.
 */
function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/register" element={<Register />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export { App };
