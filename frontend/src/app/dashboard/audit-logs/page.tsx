"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, SearchInput, FilterSelect, DateRangePicker, Pagination, LoadingState, ErrorState, StatusBadge } from "@/components/dashboard";

interface AuditLog {
  id: string;
  tenant_id?: string;
  actor_user_id?: string;
  action: string;
  resource_type: string;
  resource_id: string;
  result?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export default function AuditLogsPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchLogs = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
      if (search) params.append("search", search);
      if (actionFilter) params.append("action", actionFilter);
      if (resourceFilter) params.append("resource_type", resourceFilter);
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);
      const logs = await api.request<AuditLog[]>(`/audit-logs?${params}`);
      // Apply client-side pagination since backend doesn't paginate
      const start = (page - 1) * pageSize;
      const end = start + pageSize;
      const paginatedLogs = logs.slice(start, end);
      setLogs(paginatedLogs);
      setTotal(logs.length);
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load audit logs"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchLogs(); }, [page, pageSize, search, actionFilter, resourceFilter, dateFrom, dateTo]);

  const columns = [
    { key: "id", header: "ID", render: (l: AuditLog) => <code className="text-sm">{l.id}</code> },
    { key: "action", header: "Action" },
    { key: "resource_type", header: "Resource Type" },
    { key: "resource_id", header: "Resource ID", render: (l: AuditLog) => <code className="text-sm">{l.resource_id}</code> },
    { key: "result", header: "Result", render: (l: AuditLog) => l.result ? <StatusBadge status={l.result} /> : "—" },
    { key: "actor_user_id", header: "Actor", render: (l: AuditLog) => l.actor_user_id ? <code className="text-sm">{l.actor_user_id}</code> : "System" },
    { key: "created_at", header: "Time", render: (l: AuditLog) => new Date(l.created_at).toLocaleString() },
    { key: "metadata", header: "Details", render: (l: AuditLog) => l.metadata ? (
      <button className="text-blue-600 hover:underline text-sm" onClick={() => alert(JSON.stringify(l.metadata, null, 2))}>View</button>
    ) : "—" },
  ];

  if (loading) return <DashboardLayout><LoadingState message="Loading audit logs..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchLogs} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div><h1 className="text-2xl font-bold text-gray-900">Audit Logs</h1><p className="text-gray-600 mt-1">View system audit trail (read-only)</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search logs..." />
            <FilterSelect label="Action" options={[{value:"",label:"All"}]} value={actionFilter} onChange={setActionFilter} />
            <FilterSelect label="Resource" options={[{value:"",label:"All"}]} value={resourceFilter} onChange={setResourceFilter} />
            <DateRangePicker label="Date Range" startDate={dateFrom} endDate={dateTo} onStartChange={setDateFrom} onEndChange={setDateTo} />
          </div>
          <DataTable data={logs} columns={columns} keyExtractor={(l)=>l.id} emptyMessage="No audit logs found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>
        </div>
      </DashboardLayout>
  );
}
