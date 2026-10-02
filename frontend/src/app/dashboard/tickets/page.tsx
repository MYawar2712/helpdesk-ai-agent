"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, PriorityBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Ticket {
  id: string;
  tenant_id: string;
  customer_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  category: string;
  created_at: string;
  updated_at: string;
  handled_by?: string;
  related_job_id?: string;
}

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "waiting_for_customer", label: "Waiting for Customer" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
  { value: "escalated", label: "Escalated" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "All Priorities" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
];

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");

  const fetchTickets = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      });
      if (search) params.append("search", search);
      if (statusFilter) params.append("status", statusFilter);
      if (priorityFilter) params.append("priority", priorityFilter);

      const data = await api.request<PaginatedResponse<Ticket>>(`/tickets?${params}`);
      setTickets(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tickets");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchTickets();
  }, [page, pageSize, search, statusFilter, priorityFilter]);

  const columns = [
    { key: "id", header: "ID", render: (t: Ticket) => <code className="text-sm">{t.id}</code> },
    { key: "title", header: "Title" },
    { key: "status", header: "Status", render: (t: Ticket) => <StatusBadge status={t.status} /> },
    { key: "priority", header: "Priority", render: (t: Ticket) => <PriorityBadge priority={t.priority} /> },
    { key: "category", header: "Category" },
    { key: "customer_id", header: "Customer" },
    { key: "created_at", header: "Created", render: (t: Ticket) => new Date(t.created_at).toLocaleDateString() },
  ];

  if (loading) {
    return (
      <DashboardLayout>
        <LoadingState message="Loading tickets..." />
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <ErrorState message={error} onRetry={fetchTickets} />
      </DashboardLayout>
    );
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Tickets</h1>
            <p className="text-gray-600 mt-1">Manage and track support tickets</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search tickets..." />
            <FilterSelect label="Status" options={STATUS_OPTIONS} value={statusFilter} onChange={setStatusFilter} />
            <FilterSelect label="Priority" options={PRIORITY_OPTIONS} value={priorityFilter} onChange={setPriorityFilter} />
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
            data={tickets}
            columns={columns}
            keyExtractor={(t) => t.id}
            emptyMessage="No tickets found"
            onRowClick={(ticket) => window.open(`/dashboard/tickets/${ticket.id}`, "_blank")}
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
