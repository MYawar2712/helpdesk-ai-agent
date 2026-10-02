import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { SendMessageResponse } from "@/types";

export function useChat(conversationId: string) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (content: string): Promise<SendMessageResponse | null> => {
      if (!content.trim()) return null;

      setSending(true);
      setError(null);

      try {
        const response = await api.sendMessage(conversationId, content.trim());
        return response;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to send message";
        setError(message);
        return null;
      } finally {
        setSending(false);
      }
    },
    [conversationId]
  );

  return { sendMessage, sending, error, setError };
}
