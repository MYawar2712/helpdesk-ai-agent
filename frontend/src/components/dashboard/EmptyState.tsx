"use client";

import { Button } from "../Button";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  message: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  size?: "sm" | "md" | "lg";
}

export function EmptyState({ icon, title, message, action, size = "md" }: EmptyStateProps) {
  const textSizes = {
    sm: "text-sm",
    md: "text-base",
    lg: "text-lg",
  };

  const defaultIcons = {
    sm: (
      <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
    md: (
      <svg className="h-16 w-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
    lg: (
      <svg className="h-24 w-24" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  };

  return (
    <div className="flex flex-col items-center justify-center p-8 text-center">
      {icon || defaultIcons[size]}
      <h3 className={`mt-4 font-semibold text-gray-900 ${size === "sm" ? "text-base" : size === "md" ? "text-lg" : "text-xl"}`}>
        {title}
      </h3>
      <p className={`mt-2 text-gray-500 ${textSizes[size]} max-w-md`}>{message}</p>
      {action && (
        <Button onClick={action.onClick} variant="primary" className="mt-6">
          {action.label}
        </Button>
      )}
    </div>
  );
}
