import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useRootStore } from '../store/root-store';
import type { RootState } from '../store/root-store';
import { isWaiterOnly } from '../lib/role-utils';

/**
 * Route guard that keeps waiter-only users out of cashier/admin pages
 * (Reports, Waiters). Those pages are already hidden from the waiter nav;
 * this stops a manually-typed URL from loading them and bounces the waiter
 * back to her Orders list (2026-07-14).
 */
const RequireNotWaiter = ({ children }: { children: ReactNode }) => {
  const user = useRootStore((state: RootState) => state.user);
  if (isWaiterOnly(user)) {
    return <Navigate to="/orders" replace />;
  }
  return <>{children}</>;
};

export default RequireNotWaiter;
