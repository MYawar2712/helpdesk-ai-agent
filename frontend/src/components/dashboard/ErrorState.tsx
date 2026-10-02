"use client";

import { Button } from "../Button";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  size?: "sm" | "md" | "lg";
}

export function ErrorState({ message, onRetry, retryLabel = "Try again", size = "md" }: ErrorStateProps) {
  const iconSizes = {
    sm: "h-8 w-8",
    md: "h-12 w-12",
    lg: "h-16 w-16",
  };

  return (
    <div className="flex flex-col items-center justify-center p-8 text-center">
      <svg className={`mx-auto text-red-500 ${iconSizes[size]}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      <p className={`mt-3 ${size === "sm" ? "text-sm" : "text-base"} text-gray-600 max-w-md`}>{message}</p>
      {onRetry && (
        <Button onClick={onRetry} variant="primary" className="mt-4">
          {retryLabel}
        </Button>
      )}
    </div>
  );
}
