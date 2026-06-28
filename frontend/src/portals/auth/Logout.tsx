import { useEffect } from "react";

import { logout } from "../../lib/auth";

function Logout() {
  useEffect(() => {
    logout();
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <p className="text-sm font-medium text-neutral-600">Signing out...</p>
    </main>
  );
}

export { Logout };
