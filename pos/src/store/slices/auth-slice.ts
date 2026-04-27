import { StateCreator } from 'zustand';
import { getLoggedUser, getUserRoles } from '../../lib/auth-api';

export interface User {
  name: string; // This stores the user ID
  roles: string[];
  full_name?: string;
}

export interface AuthState {
  user: User | null;
  isLoading: boolean;
  error: string | null;
}

export interface AuthActions {
  checkAuth: () => Promise<void>;
  setUser: (user: User | null) => void;
  clearAuth: () => void;
}

export type AuthSlice = AuthState & AuthActions;

const initialState: AuthState = {
  user: null,
  isLoading: false,
  error: null,
};

export const createAuthSlice: StateCreator<AuthSlice> = (set, get) => ({
  ...initialState,

  checkAuth: async () => {
    try {
      set({ isLoading: true, error: null });
      const response = await getLoggedUser();
      
      if (!response) {
        // No active session — bounce to /pos so App.tsx's guest check
        // renders the URY BiometricLogin page (instead of Frappe's
        // stock /login).
        window.location.href = '/pos';
        return;
      }

      // Get user roles
      const roles = await getUserRoles(response);

      set({
        user: {
          name: response, // Store the user ID in name field
          full_name: roles.full_name,
          roles: roles.roles,
        },
        isLoading: false,
      });
    } catch (error) {
      set({ 
        error: (error as Error).message,
        isLoading: false,
        user: null,
      });
      // Auth check failed — bounce to /pos so App.tsx's guest check
      // renders the URY BiometricLogin page.
      window.location.href = '/pos';
    }
  },

  setUser: (user) => {
    set({ user });
  },

  clearAuth: () => {
    set(initialState);
  },
}); 