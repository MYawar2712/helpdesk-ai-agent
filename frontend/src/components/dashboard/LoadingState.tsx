"use client";

import { useMemo } from "react";

interface LoadingStateProps {
  message?: string;
  size?: "sm" | "md" | "lg";
  fullScreen?: boolean;
}

export function LoadingState({ message = "Loading...", size = "md", fullScreen = false }: LoadingStateProps) {
  const sizes: Record<string, React.CSSProperties> = {
    sm: { height: "1.5rem", width: "1.5rem" },
    md: { height: "2rem", width: "2rem" },
    lg: { height: "3rem", width: "3rem" },
  };

  const textSizes = {
    sm: "text-sm",
    md: "text-base",
    lg: "text-lg",
  };

  const containerClass = fullScreen
    ? "fixed inset-0 z-50 flex items-center justify-center bg-white/80 backdrop-blur-sm"
    : "flex flex-col items-center justify-center";

  return (
    <div className={containerClass}>
      <div className="animate-spin rounded-full border-3 border-blue-600 border-t-transparent" style={sizes[size]} />
      {message && (
        <p className={`mt-3 ${textSizes[size]} text-gray-600`}>{message}</p>
      )}
    </div>
  );
}

interface SkeletonProps {
  className?: string;
  lines?: number;
}

export function Skeleton({ className = "", lines = 1 }: SkeletonProps) {
  const widths = useMemo(() => [...Array(lines)].map((_, index) => 80 + ((index * 13) % 21)), [lines]);

  return (
    <div className={`space-y-3 ${className}`}>
      {widths.map((width, i) => (
        <div key={i} className="h-4 bg-gray-200 rounded animate-pulse" style={{ width: `${width}%` }} />
      ))}
    </div>
  );
}

interface TableSkeletonProps {
  columns?: number;
  rows?: number;
}

export function TableSkeleton({ columns = 5, rows = 5 }: TableSkeletonProps) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {[...Array(columns)].map((_, i) => (
              <th key={i} className="px-4 py-3">
                <div className="h-4 bg-gray-200 rounded animate-pulse w-full" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {[...Array(rows)].map((_, row) => (
            <tr key={row}>
              {[...Array(columns)].map((_, col) => (
                <td key={col} className="px-4 py-3">
                  <div className="h-4 bg-gray-200 rounded animate-pulse w-full" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
