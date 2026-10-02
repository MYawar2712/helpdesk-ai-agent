"use client";

interface PriorityBadgeProps {
  priority: string;
  size?: "sm" | "md";
}

const PRIORITY_COLORS: Record<string, { bg: string; text: string }> = {
  low: { bg: "bg-green-100", text: "text-green-800" },
  medium: { bg: "bg-yellow-100", text: "text-yellow-800" },
  high: { bg: "bg-orange-100", text: "text-orange-800" },
  critical: { bg: "bg-red-100", text: "text-red-800" },
  urgent: { bg: "bg-red-100", text: "text-red-800" },
};

export function PriorityBadge({ priority, size = "md" }: PriorityBadgeProps) {
  const normalized = priority.toLowerCase();
  const colors = PRIORITY_COLORS[normalized] || { bg: "bg-gray-100", text: "text-gray-800" };
  const sizes = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-2.5 py-1 text-xs",
  };

  return (
    <span className={`inline-flex items-center rounded-full font-medium ${colors.bg} ${colors.text} ${sizes[size]}`}>
      {priority.charAt(0).toUpperCase() + priority.slice(1).toLowerCase()}
    </span>
  );
}
