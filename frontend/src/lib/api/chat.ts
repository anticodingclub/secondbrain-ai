import { api, refreshAccessToken } from "@/lib/api/client";
import { getAccessToken } from "@/lib/api/token-store";
import type {
  ChatCitation,
  ConversationDetail,
  ConversationSummary,
} from "@/lib/api/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface AskOptions {
  question: string;
  conversationId?: string;
  documentIds?: string[];
  onToken: (text: string) => void;
  onCitations: (citations: ChatCitation[]) => void;
  onDone: (info: { conversationId: string; messageId: string }) => void;
  onError: (message: string) => void;
  signal?: AbortSignal;
}

/**
 * Stream an answer over Server-Sent Events.
 *
 * Uses fetch with a manual reader rather than `EventSource`, for one blunt
 * reason: EventSource cannot send an Authorization header, and it only does
 * GET. Putting the access token in a query string to work around that would
 * write a credential into every proxy and server log it passes through.
 */
export async function askQuestion({
  question,
  conversationId,
  documentIds,
  onToken,
  onCitations,
  onDone,
  onError,
  signal,
}: AskOptions): Promise<void> {
  // Refreshed up front: a stream cannot be replayed on a 401 the way apiFetch
  // retries an ordinary request.
  if (!getAccessToken()) await refreshAccessToken();

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/api/v1/chat/ask`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      },
      body: JSON.stringify({
        question,
        conversation_id: conversationId,
        document_ids: documentIds,
      }),
      signal,
    });
  } catch {
    onError("Could not reach the SecondBrain API. Is the backend running?");
    return;
  }

  if (!response.ok || !response.body) {
    onError(
      response.status === 401
        ? "Your session expired. Please sign in again."
        : "The request failed. Please try again.",
    );
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by a blank line. A frame can arrive split
      // across reads, so anything after the last separator stays buffered.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const event = frame.match(/^event: (.+)$/m)?.[1];
        const raw = frame.match(/^data: (.+)$/m)?.[1];
        if (!event || !raw) continue;

        let data: Record<string, unknown>;
        try {
          data = JSON.parse(raw) as Record<string, unknown>;
        } catch {
          continue;
        }

        switch (event) {
          case "token":
            onToken(String(data.text ?? ""));
            break;
          case "citations":
            onCitations((data.citations ?? []) as ChatCitation[]);
            break;
          case "done":
            onDone({
              conversationId: String(data.conversation_id),
              messageId: String(data.message_id),
            });
            break;
          case "error":
            onError(String(data.message ?? "Something went wrong."));
            break;
        }
      }
    }
  } catch (cause) {
    if (!(cause instanceof DOMException && cause.name === "AbortError")) {
      onError("The connection dropped while answering.");
    }
  } finally {
    reader.releaseLock();
  }
}

export function listConversations(): Promise<ConversationSummary[]> {
  return api.get<ConversationSummary[]>("/chat/conversations");
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return api.get<ConversationDetail>(`/chat/conversations/${id}`);
}

export function deleteConversation(id: string): Promise<void> {
  return api.delete<void>(`/chat/conversations/${id}`);
}
