"use client";

interface StatusBadgeProps {
  status: string;
  variant?: "default" | "success" | "warning" | "danger" | "info";
  size?: "sm" | "md";
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: "bg-blue-100", text: "text-blue-800" },
  closed: { bg: "bg-gray-100", text: "text-gray-800" },
  pending: { bg: "bg-yellow-100", text: "text-yellow-800" },
  in_progress: { bg: "bg-blue-100", text: "text-blue-800" },
  "in-progress": { bg: "bg-blue-100", text: "text-blue-800" },
  waiting_for_customer: { bg: "bg-purple-100", text: "text-purple-800" },
  "waiting-for-customer": { bg: "bg-purple-100", text: "text-purple-800" },
  resolved: { bg: "bg-green-100", text: "text-green-800" },
  escalated: { bg: "bg-red-100", text: "text-red-800" },
  scheduled: { bg: "bg-indigo-100", text: "text-indigo-800" },
  completed: { bg: "bg-green-100", text: "text-green-800" },
  cancelled: { bg: "bg-red-100", text: "text-red-800" },
  unpaid: { bg: "bg-orange-100", text: "text-orange-800" },
  paid: { bg: "bg-green-100", text: "text-green-800" },
  overdue: { bg: "bg-red-100", text: "text-red-800" },
  partial: { bg: "bg-yellow-100", text: "text-yellow-800" },
  draft: { bg: "bg-gray-100", text: "text-gray-800" },
  human_review: { bg: "bg-purple-100", text: "text-purple-800" },
  "human-review": { bg: "bg-purple-100", text: "text-purple-800" },
  approved: { bg: "bg-green-100", text: "text-green-800" },
  rejected: { bg: "bg-red-100", text: "text-red-800" },
  executed: { bg: "bg-green-100", text: "text-green-800" },
  failed: { bg: "bg-red-100", text: "text-red-800" },
  expired: { bg: "bg-gray-100", text: "text-gray-800" },
  available: { bg: "bg-green-100", text: "text-green-800" },
  busy: { bg: "bg-red-100", text: "text-red-800" },
  offline: { bg: "bg-gray-100", text: "text-gray-800" },
  ready: { bg: "bg-green-100", text: "text-green-800" },
  processing: { bg: "bg-blue-100", text: "text-blue-800" },
};

export function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const normalized = status.toLowerCase().replace(/\s+/g, "_");
  const colors = STATUS_COLORS[normalized] || { bg: "bg-gray-100", text: "text-gray-800" };
  const sizes = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-2.5 py-1 text-xs",
  };

  return (
    <span className={`inline-flex items-center rounded-full font-medium ${colors.bg} ${colors.text} ${sizes[size]}`}>
      {status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
    </span>
  );
}
