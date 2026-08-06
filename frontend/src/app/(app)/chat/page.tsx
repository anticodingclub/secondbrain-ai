"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, MessagesSquare, Send, Square } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  askQuestion,
  getConversation,
  listConversations,
} from "@/lib/api/chat";
import { openDocument } from "@/lib/api/documents";
import type { ChatCitation, ChatMessage } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "What did I decide about authentication?",
  "Summarise my deployment notes",
  "When does my internship start?",
];

/** Renders `[1]` markers as chips that scroll to the matching source. */
function WithCitationMarkers({
  text,
  citations,
}: {
  text: string;
  citations: ChatCitation[];
}) {
  const parts = text.split(/(\[\d{1,2}\])/g);

  return (
    <>
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d{1,2})\]$/);
        if (!match) return <span key={index}>{part}</span>;

        const number = Number(match[1]);
        const citation = citations.find((item) => item.number === number);
        if (!citation) return <span key={index}>{part}</span>;

        return (
          <button
            key={index}
            type="button"
            onClick={() => void openDocument(citation.document_id)}
            title={`${citation.document_title}${
              citation.page_number ? ` · page ${citation.page_number}` : ""
            }`}
            className="mx-0.5 rounded bg-accent/15 px-1.5 py-0.5 align-baseline text-[11px] font-medium text-accent transition-colors hover:bg-accent/25"
          >
            {number}
          </button>
        );
      })}
    </>
  );
}

function Sources({ citations }: { citations: ChatCitation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-3 space-y-1.5 border-t border-border pt-3">
      <p className="text-xs font-medium text-subtle">
        {citations.length === 1 ? "Source" : "Sources"}
      </p>
      {citations.map((citation) => (
        <button
          key={citation.chunk_id}
          type="button"
          onClick={() => void openDocument(citation.document_id)}
          className="flex w-full items-start gap-2.5 rounded-sb px-2 py-1.5 text-left transition-colors hover:bg-surface-hover"
        >
          <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded bg-accent/15 text-[11px] font-medium text-accent">
            {citation.number}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 text-xs font-medium">
              <FileText className="size-3 shrink-0 text-subtle" />
              <span className="truncate">
                {citation.document_title || citation.filename}
              </span>
              {(citation.page_number || citation.section_title) && (
                <span className="shrink-0 text-subtle">
                  {citation.page_number ? `p.${citation.page_number}` : citation.section_title}
                </span>
              )}
            </span>
            <span className="mt-0.5 line-clamp-2 text-xs text-subtle">
              {citation.snippet}
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "animate-fade-up max-w-[85%] rounded-sb px-4 py-3",
          isUser ? "bg-accent text-accent-contrast" : "border border-border bg-surface",
        )}
      >
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
          {isUser ? (
            message.content
          ) : (
            <WithCitationMarkers text={message.content} citations={message.citations} />
          )}
        </div>
        {!isUser && <Sources citations={message.citations} />}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamed, setStreamed] = useState("");
  const [citations, setCitations] = useState<ChatCitation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);

  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: listConversations,
  });

  // Follows the answer as it streams. `streamed` is in the dependency list so
  // it re-runs per token, which is what keeps the newest text in view.
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streamed]);

  const ask = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || streaming) return;

      setError(null);
      setQuestion("");
      setStreamed("");
      setCitations([]);
      setStreaming(true);
      setMessages((current) => [
        ...current,
        {
          id: `local-${Date.now()}`,
          ordinal: current.length,
          role: "user",
          content: trimmed,
          citations: [],
          model: null,
          latency_ms: null,
          created_at: new Date().toISOString(),
        },
      ]);

      controller.current = new AbortController();
      let answer = "";
      let finalCitations: ChatCitation[] = [];

      await askQuestion({
        question: trimmed,
        conversationId: conversationId ?? undefined,
        signal: controller.current.signal,
        onToken: (token) => {
          answer += token;
          setStreamed(answer);
        },
        onCitations: (received) => {
          finalCitations = received;
          setCitations(received);
        },
        onDone: ({ conversationId: id }) => {
          setConversationId(id);
          setMessages((current) => [
            ...current,
            {
              id: `answer-${Date.now()}`,
              ordinal: current.length,
              role: "assistant",
              content: answer,
              citations: finalCitations,
              model: null,
              latency_ms: null,
              created_at: new Date().toISOString(),
            },
          ]);
          setStreamed("");
          setCitations([]);
          void queryClient.invalidateQueries({ queryKey: ["conversations"] });
        },
        onError: setError,
      });

      setStreaming(false);
      controller.current = null;
    },
    [conversationId, streaming, queryClient],
  );

  async function openConversation(id: string) {
    const detail = await getConversation(id);
    setConversationId(id);
    setMessages(detail.messages);
    setStreamed("");
    setError(null);
  }

  function startNew() {
    controller.current?.abort();
    setConversationId(null);
    setMessages([]);
    setStreamed("");
    setCitations([]);
    setError(null);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void ask(question);
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)]">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border lg:flex">
        <div className="p-3">
          <Button onClick={startNew} className="w-full justify-center">
            New conversation
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations.data?.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => void openConversation(conversation.id)}
              className={cn(
                "w-full truncate rounded-sb px-2.5 py-2 text-left text-sm transition-colors",
                conversation.id === conversationId
                  ? "bg-surface text-foreground"
                  : "text-muted hover:bg-surface-hover hover:text-foreground",
              )}
            >
              <span className="block truncate">{conversation.title}</span>
              <span className="block text-xs text-subtle">
                {formatRelativeTime(conversation.updated_at)}
              </span>
            </button>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
          <div className="mx-auto max-w-2xl space-y-4">
            {messages.length === 0 && !streaming && (
              <div className="animate-fade-up py-16 text-center">
                <span className="mx-auto grid size-11 place-items-center rounded-full bg-surface text-muted">
                  <MessagesSquare className="size-5" />
                </span>
                <h1 className="mt-4 text-lg font-medium">Chat with your documents</h1>
                <p className="mt-1.5 text-sm text-muted">
                  Answers come only from what you have uploaded, with citations.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => void ask(example)}
                      className="rounded-full border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-border-strong hover:text-foreground"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message) => (
              <Bubble key={message.id} message={message} />
            ))}

            {streaming && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-sb border border-border bg-surface px-4 py-3">
                  {streamed ? (
                    <>
                      <div className="whitespace-pre-wrap text-sm leading-relaxed">
                        <WithCitationMarkers text={streamed} citations={citations} />
                        <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom" />
                      </div>
                      <Sources citations={citations} />
                    </>
                  ) : (
                    <span className="flex items-center gap-2 text-sm text-muted">
                      <span className="size-3.5 animate-spin rounded-full border-2 border-border border-t-accent" />
                      Searching your documents…
                    </span>
                  )}
                </div>
              </div>
            )}

            {error && (
              <Card className="border-danger/40 bg-danger/5">
                <CardContent className="p-3.5">
                  <p role="alert" className="text-sm text-danger">
                    {error}
                  </p>
                </CardContent>
              </Card>
            )}

            <div ref={bottom} />
          </div>
        </div>

        <form onSubmit={onSubmit} className="border-t border-border px-4 py-3 md:px-8">
          <div className="mx-auto flex max-w-2xl items-center gap-2">
            <Input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask anything about your documents…"
              aria-label="Ask a question"
              disabled={streaming}
              className="h-11"
            />
            {streaming ? (
              <Button
                type="button"
                variant="danger"
                onClick={() => controller.current?.abort()}
                aria-label="Stop generating"
              >
                <Square className="size-4" />
              </Button>
            ) : (
              <Button
                type="submit"
                variant="primary"
                disabled={!question.trim()}
                aria-label="Send"
              >
                <Send className="size-4" />
              </Button>
            )}
          </div>
          <p className="mx-auto mt-2 max-w-2xl text-center text-xs text-subtle">
            Answers are grounded in your documents. Check the citations.
          </p>
        </form>
      </div>
    </div>
  );
}
