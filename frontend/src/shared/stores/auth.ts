import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface AuthState {
  userId: string | null;
  email: string | null;
  displayName: string | null;
  role: string | null;
  isEnterprise: boolean | null;
  setAuth: (userId: string, role: string, email: string, displayName: string) => void;
  setIsEnterprise: (value: boolean) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      userId: null,
      email: null,
      displayName: null,
      role: null,
      isEnterprise: null,
      setAuth: (userId, role, email, displayName) =>
        set({ userId, role, email, displayName }),
      setIsEnterprise: (isEnterprise) => set({ isEnterprise }),
      clearAuth: () =>
        set({ userId: null, email: null, displayName: null, role: null, isEnterprise: null }),
    }),
    {
      name: 'metronix-auth',
      storage: createJSONStorage(() => sessionStorage),
    }
  )
);
