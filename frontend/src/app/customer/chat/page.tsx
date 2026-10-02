"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatWindow } from "@/components/ChatWindow";
import { ConversationList } from "@/components/ConversationList";
import { Button } from "@/components/Button";
import { useAuth } from "@/hooks/useAuth";
import { useConversation } from "@/hooks/useConversations";
import type { Conversation, Message } from "@/types";

export default function CustomerChatPage() {
  const { user, loading: authLoading, logout } = useAuth();
  const router = useRouter();
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);

  const { conversation, loading: msgLoading, refetch: refetchConversation } = useConversation(selectedConversation?.conversation_id || null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
    }
  }, [user, authLoading, router]);

  const handleSelectConversation = (conv: Conversation) => {
    setSelectedConversation(conv);
  };

  const handleNewMessage = (message: Message) => {
    if (conversation && message.conversation_id === conversation.conversation_id) {
      void refetchConversation();
    }
  };

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!user) return null;

  const isCustomer = user.role?.toUpperCase() === "CUSTOMER";

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-80 lg:w-96 hidden lg:block border-r bg-white">
        <ConversationList
          onSelect={handleSelectConversation}
          selectedId={selectedConversation?.conversation_id}
        />
      </aside>

      {/* Main Chat */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="border-b bg-white px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-gray-900">
                {selectedConversation?.subject || "Select a conversation"}
              </h1>
              <p className="text-sm text-gray-500">
                {isCustomer ? "Customer" : user.role} • {user.email}
              </p>
            </div>
            <Button variant="ghost" onClick={handleLogout} className="text-sm">
              Sign Out
            </Button>
          </div>
        </header>

        {/* Chat Area */}
        <div className="flex-1 flex flex-col min-h-0">
          {selectedConversation ? (
            msgLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
              </div>
            ) : (
              <ChatWindow
                conversationId={selectedConversation.conversation_id}
                messages={conversation?.messages || []}
                onNewMessage={handleNewMessage}
              />
            )
          ) : (
            <div className="flex-1 flex items-center justify-center bg-gray-50">
              <div className="text-center">
                <svg
                  className="mx-auto h-16 w-16 text-gray-300"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
                <h2 className="mt-4 text-lg font-medium text-gray-900">Welcome back</h2>
                <p className="mt-2 text-gray-500">
                  Select a conversation or start a new chat
                </p>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
