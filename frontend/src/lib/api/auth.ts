import { api } from "@/lib/api/client";
import { setAccessToken } from "@/lib/api/token-store";
import type {
  LoginPayload,
  RegisterPayload,
  TokenResponse,
  User,
} from "@/lib/api/types";

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/auth/login", payload);
  setAccessToken(tokens.access_token);
  return tokens;
}

export async function register(payload: RegisterPayload): Promise<TokenResponse> {
  const tokens = await api.post<TokenResponse>("/auth/register", payload);
  setAccessToken(tokens.access_token);
  return tokens;
}

export async function logout(): Promise<void> {
  try {
    await api.post<void>("/auth/logout");
  } finally {
    // Clear locally even if the request failed — a user who clicked "sign out"
    // must end up signed out of this tab regardless of what the network did.
    setAccessToken(null);
  }
}

export async function logoutEverywhere(): Promise<void> {
  try {
    await api.post<void>("/auth/logout-all");
  } finally {
    setAccessToken(null);
  }
}

export function fetchCurrentUser(): Promise<User> {
  return api.get<User>("/auth/me");
}
