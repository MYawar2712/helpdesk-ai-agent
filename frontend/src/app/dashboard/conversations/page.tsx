"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Conversation {
  conversation_id: string;
  tenant_id: string;
  customer_id: string;
  ticket_id?: string;
  subject: string;
  status: string;
  created_at: string;
  updated_at: string;
}

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const fetchConversations = async () => {
    try {
      setLoading(true);
      // Backend doesn't support pagination for conversations
      const data = await api.request<Conversation[]>(`/chat/conversations`);
      // Apply client-side filtering and pagination
      let filtered = data;
      if (search) {
        const searchLower = search.toLowerCase();
        filtered = filtered.filter(c =>
          c.subject.toLowerCase().includes(searchLower) ||
          c.customer_id.toLowerCase().includes(searchLower) ||
          c.conversation_id.toLowerCase().includes(searchLower)
        );
      }
      if (statusFilter) {
        filtered = filtered.filter(c => c.status === statusFilter);
      }
      setTotal(filtered.length);
      const start = (page - 1) * pageSize;
      const end = start + pageSize;
      setConversations(filtered.slice(start, end));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load conversations");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchConversations();
  }, [page, pageSize, search, statusFilter]);

  const columns = [
    { key: "conversation_id", header: "ID", render: (c: Conversation) => <code className="text-sm">{c.conversation_id}</code> },
    { key: "subject", header: "Subject" },
    { key: "status", header: "Status", render: (c: Conversation) => <StatusBadge status={c.status} /> },
    { key: "customer_id", header: "Customer" },
    { key: "ticket_id", header: "Ticket", render: (c: Conversation) => c.ticket_id ? <code className="text-sm">{c.ticket_id}</code> : "—" },
    { key: "created_at", header: "Created", render: (c: Conversation) => new Date(c.created_at).toLocaleDateString() },
    { key: "updated_at", header: "Updated", render: (c: Conversation) => new Date(c.updated_at).toLocaleDateString() },
  ];

  if (loading) {
    return (
      <DashboardLayout>
        <LoadingState message="Loading conversations..." />
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <ErrorState message={error} onRetry={fetchConversations} />
      </DashboardLayout>
    );
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Conversations</h1>
            <p className="text-gray-600 mt-1">View and manage customer conversations</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search conversations..." />
            <FilterSelect label="Status" options={STATUS_OPTIONS} value={statusFilter} onChange={setStatusFilter} />
            <div className="flex items-end">
              <label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={10}>10 per page</option>
                <option value={25}>25 per page</option>
                <option value={50}>50 per page</option>
                <option value={100}>100 per page</option>
              </select>
            </div>
          </div>

          <DataTable
            data={conversations}
            columns={columns}
            keyExtractor={(c) => c.conversation_id}
            emptyMessage="No conversations found"
            onRowClick={(conv) => window.open(`/dashboard/conversations/${conv.conversation_id}`, "_blank")}
          />

          <Pagination
            currentPage={page}
            totalPages={Math.ceil(total / pageSize)}
            onPageChange={setPage}
            showPageSize
            pageSize={pageSize}
            onPageSizeChange={setPageSize}
          />
        </div>
      </div>
      </DashboardLayout>
  );
}
