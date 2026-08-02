"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import * as authApi from "@/lib/api/auth";
import { refreshAccessToken } from "@/lib/api/client";
import type { LoginPayload, RegisterPayload, User } from "@/lib/api/types";

interface AuthContextValue {
  user: User | null;
  /** True until the initial session probe finishes — distinct from "signed out". */
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  logoutEverywhere: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const queryClient = useQueryClient();

  // The access token lives in memory only, so a reload starts with none.
  // Exchange the httpOnly refresh cookie for a fresh one to restore the
  // session; failure here just means "not signed in", which is not an error.
  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const token = await refreshAccessToken();
        if (cancelled) return;
        setUser(token ? await authApi.fetchCurrentUser() : null);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    const { user: signedIn } = await authApi.login(payload);
    setUser(signedIn);
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    const { user: created } = await authApi.register(payload);
    setUser(created);
  }, []);

  const endSession = useCallback(
    async (call: () => Promise<void>) => {
      await call();
      setUser(null);
      // Drop every cached query: the next user of this browser must not see
      // the previous one's documents flash on screen before refetching.
      queryClient.clear();
      router.replace("/login");
    },
    [queryClient, router],
  );

  const logout = useCallback(
    () => endSession(authApi.logout),
    [endSession],
  );

  const logoutEverywhere = useCallback(
    () => endSession(authApi.logoutEverywhere),
    [endSession],
  );

  return (
    <AuthContext.Provider
      value={{ user, isLoading, login, register, logout, logoutEverywhere }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return context;
}
