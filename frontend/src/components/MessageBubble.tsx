"use client";

import type { Message } from "@/types";

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isCustomer = message.sender_type === "CUSTOMER";

  return (
    <div
      className={`flex ${isCustomer ? "justify-end" : "justify-start"} mb-3`}
    >
      <div
        className={`
          max-w-[80%] rounded-2xl px-4 py-2 text-sm
          ${isCustomer
            ? "bg-blue-600 text-white rounded-tr-none"
            : "bg-gray-100 text-gray-900 rounded-tl-none"}
        `}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        <p
          className={`mt-1 text-xs ${isCustomer ? "text-blue-100" : "text-gray-500"}`}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>
    </div>
  );
}
