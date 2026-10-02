"use client";

import { TextareaHTMLAttributes, forwardRef } from "react";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className = "", disabled, ...props }, ref) => (
    <textarea
      ref={ref}
      disabled={disabled}
      className={`
        w-full rounded-lg border border-gray-300 px-3 py-2 text-sm
        placeholder:text-gray-400 resize-y min-h-[100px]
        focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
        disabled:bg-gray-50 disabled:cursor-not-allowed
        ${className}
      `}
      {...props}
    />
  )
);

Textarea.displayName = "Textarea";
