"use client";

import { InputHTMLAttributes, forwardRef } from "react";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className = "", disabled, ...props }, ref) => (
    <input
      ref={ref}
      disabled={disabled}
      className={`
        w-full rounded-lg border border-gray-300 px-3 py-2 text-sm
        placeholder:text-gray-400
        focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
        disabled:bg-gray-50 disabled:cursor-not-allowed
        ${className}
      `}
      {...props}
    />
  )
);

Input.displayName = "Input";
