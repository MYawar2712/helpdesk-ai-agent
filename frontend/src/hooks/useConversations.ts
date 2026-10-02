import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Conversation, ConversationDetail } from "@/types";

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConversations = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.listConversations();
      setConversations(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load conversations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    const runFetch = async () => {
      try {
        const data = await api.listConversations();
        if (mounted) {
          setConversations(data);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load conversations");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };
    runFetch();
    return () => {
      mounted = false;
    };
  }, []);

  const createConversation = async () => {
    const newConv = await api.createConversation();
    setConversations((prev) => [newConv, ...prev]);
    return newConv;
  };

  return {
    conversations,
    loading,
    error,
    refetch: fetchConversations,
    createConversation,
  };
}

export function useConversation(conversationId: string | null) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConversation = useCallback(async () => {
    if (!conversationId) return;
    try {
      setLoading(true);
      const data = await api.getConversation(conversationId);
      setConversation(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load conversation");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId) return;
    let mounted = true;
    const runFetch = async () => {
      try {
        const data = await api.getConversation(conversationId);
        if (mounted) {
          setConversation(data);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : "Failed to load conversation");
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };
    runFetch();
    return () => {
      mounted = false;
    };
  }, [conversationId]);

  return { conversation, loading, error, refetch: fetchConversation };
}
