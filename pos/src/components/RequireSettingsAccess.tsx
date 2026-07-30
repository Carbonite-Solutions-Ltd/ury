import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useRootStore } from '../store/root-store';
import type { RootState } from '../store/root-store';
import { canAccessSettings } from '../lib/role-utils';

/**
 * Route guard for the POS Settings page — Administrator / System Manager /
 * URY Manager only.
 *
 * The Settings entry is already hidden from the avatar menu for everyone
 * else; this stops a manually-typed `/settings` URL from rendering it and
 * sends the user back to the POS. Implemented as a route WRAPPER rather
 * than an early return inside the page because Settings calls hooks after
 * the role read, and an early return there would break the Rules of Hooks
 * (same reasoning as RequireNotWaiter).
 *
 * Not a security boundary: every settings endpoint re-validates with
 * `_user_can_manage_settings` on the server.
 */
const RequireSettingsAccess = ({ children }: { children: ReactNode }) => {
  const user = useRootStore((state: RootState) => state.user);
  // `user` is null while the session is still resolving — don't bounce a
  // legitimate admin on a slow first paint.
  if (user && !canAccessSettings(user)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
};

export default RequireSettingsAccess;
