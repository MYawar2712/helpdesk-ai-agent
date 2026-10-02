"use client";

import { useState } from "react";
import { Button } from "./Button";
import { useConversations } from "@/hooks/useConversations";
import type { Conversation } from "@/types";

interface ConversationListProps {
  onSelect: (conversation: Conversation) => void;
  selectedId?: string;
}

export function ConversationList({ onSelect, selectedId }: ConversationListProps) {
  const { conversations, loading, error, createConversation } = useConversations();
  const [expanded, setExpanded] = useState<string | null>(null);

  const handleNewChat = async () => {
    const newConv = await createConversation();
    onSelect(newConv);
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-600">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-r bg-gray-50">
      <div className="p-4 border-b">
        <Button onClick={handleNewChat} className="w-full" variant="primary">
          + New Chat
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="p-4 text-center text-gray-500">
            <p className="text-sm">No conversations yet</p>
            <p className="text-xs mt-1">Click &ldquo;New Chat&rdquo; to start</p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {conversations.map((conv) => (
              <li
                key={conv.conversation_id}
                onClick={() => {
                  setExpanded(conv.conversation_id === expanded ? null : conv.conversation_id);
                  onSelect(conv);
                }}
                className={`
                  p-3 cursor-pointer transition-colors
                  ${conv.conversation_id === selectedId ? "bg-blue-50" : "hover:bg-gray-100"}
                  ${conv.conversation_id === expanded ? "bg-gray-100" : ""}
                `}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm truncate">{conv.subject || "New Conversation"}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {new Date(conv.updated_at).toLocaleDateString()}
                    </p>
                  </div>
                  {expanded === conv.conversation_id && (
                    <span className="text-blue-600">&BlackTriangledown;</span>
                  )}
                </div>
                {expanded === conv.conversation_id && (
                  <div className="mt-2 text-xs text-gray-500">
                    <p>ID: {conv.conversation_id}</p>
                    <p>Status: {conv.status}</p>
                    {conv.ticket_id && <p>Ticket: {conv.ticket_id}</p>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
