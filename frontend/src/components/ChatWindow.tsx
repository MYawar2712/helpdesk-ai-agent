"use client";

import { useState } from "react";
import { Textarea } from "./Textarea";
import { Button } from "./Button";
import { MessageBubble } from "./MessageBubble";
import { useChat } from "@/hooks/useChat";
import type { Message } from "@/types";

interface ChatWindowProps {
  conversationId: string;
  messages: Message[];
  onNewMessage: (message: Message) => void;
}

export function ChatWindow({ conversationId, messages, onNewMessage }: ChatWindowProps) {
  const [input, setInput] = useState("");
  const { sendMessage, sending, error } = useChat(conversationId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || sending) return;

    const content = input;
    setInput("");

    const localMessageId = `local-${Date.now()}`;
    onNewMessage({
      message_id: localMessageId,
      conversation_id: conversationId,
      sender_type: "CUSTOMER",
      content,
      created_at: new Date().toISOString(),
    });

    const response = await sendMessage(content);
    if (response) {
      onNewMessage({
        message_id: response.message_id,
        conversation_id: response.conversation_id,
        sender_type: "AI",
        content: response.content,
        created_at: response.created_at,
      });
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 py-12">
            <p className="text-lg font-medium">Start a conversation</p>
            <p className="text-sm mt-1">Send a message to get help</p>
          </div>
        ) : (
          messages.map((message) => (
            <MessageBubble key={message.message_id} message={message} />
          ))
        )}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl rounded-tl-none px-4 py-2">
              <div className="flex space-x-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: "0ms"}} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: "150ms"}} />
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{animationDelay: "300ms"}} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t p-4">
        {error && (
          <p className="mb-2 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type your message..."
            disabled={sending}
            rows={1}
            className="flex-1"
          />
          <Button type="submit" disabled={sending || !input.trim()}>
            {sending ? "Sending..." : "Send"}
          </Button>
        </div>
      </form>
    </div>
  );
}
