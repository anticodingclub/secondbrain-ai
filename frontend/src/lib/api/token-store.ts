/**
 * In-memory access token.
 *
 * Deliberately *not* localStorage or a readable cookie: anything JavaScript can
 * read, an XSS payload can exfiltrate. Keeping the access token in a module
 * variable means it dies with the tab, and the only persistent credential is
 * the httpOnly refresh cookie the browser will not hand to script at all.
 *
 * The cost is that a page reload starts with no access token — recovered by
 * calling /auth/refresh once on mount, which is what `AuthProvider` does.
 */

let accessToken: string | null = null;

/** Subscribers notified when the session is established or lost. */
const listeners = new Set<(token: string | null) => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  for (const listener of listeners) listener(token);
}

export function onAccessTokenChange(
  listener: (token: string | null) => void,
): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Single-flight refresh.
 *
 * A page that fires several queries at once will get several simultaneous
 * 401s. Without this, each would trigger its own /auth/refresh — and because
 * refresh tokens rotate, the second one to arrive would present a token the
 * first had already consumed, which the backend correctly treats as replay and
 * punishes by revoking the whole session. Sharing one in-flight promise is not
 * an optimisation here; it is what stops the client from logging itself out.
 */
let inFlightRefresh: Promise<string | null> | null = null;

export function refreshOnce(refresh: () => Promise<string | null>): Promise<string | null> {
  inFlightRefresh ??= refresh().finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}
