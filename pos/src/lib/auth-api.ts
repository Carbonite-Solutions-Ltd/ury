import { call, auth } from './frappe-sdk';

type LoggedUserResponse = string | null;

interface SessionUserInfo {
  user: string;
  full_name: string;
  roles: string[];
}

export const getLoggedUser = async (): Promise<LoggedUserResponse> => {
  try {
    const response = await auth.getLoggedInUser();
    return response as LoggedUserResponse;
  } catch (error) {
    console.error('Error getting logged user:', error);
    return null;
  }
};

export const getUserRoles = async (
  _email?: string
): Promise<{ roles: string[]; full_name: string }> => {
  // Routes through the whitelisted `get_session_user_info` method
  // instead of `db.getDoc('User', email)` which requires User-doctype
  // read permission. URY Cashier / URY Captain users don't have that
  // by default, so the old REST path 403'd and silently returned an
  // empty role list — which made every role-gated UI quietly disappear.
  // The `_email` arg is kept for backward compat with callers; the
  // backend always reads `frappe.session.user`. See CLAUDE.md
  // "Fixes log" 2026-04-09.
  try {
    const res = await call.get<{ message: SessionUserInfo }>(
      'ury.ury_pos.api.get_session_user_info'
    );
    const info = res?.message;
    return {
      roles: info?.roles || [],
      full_name: info?.full_name || '',
    };
  } catch (error) {
    console.error('Error getting session user info:', error);
    return { roles: [], full_name: '' };
  }
};

export const logout = async () => {
  try {
    // Clear the in-progress cart so the next user on a shared terminal
    // doesn't inherit it (sessionStorage persists across the login
    // reload otherwise). 2026-07-15.
    try {
      sessionStorage.removeItem('ury_pos_cart');
    } catch {
      /* ignore */
    }
    return auth.logout();
  }catch(e){
    console.error('Error logging out:', e);
    return false;
  }
}