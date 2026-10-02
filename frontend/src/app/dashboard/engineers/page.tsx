"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Engineer {
  id: string;
  tenant_id: string;
  name: string;
  email: string;
  skills: string[];
  availability_status: string;
  created_at: string;
  updated_at: string;
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
  { value: "available", label: "Available" },
  { value: "busy", label: "Busy" },
  { value: "offline", label: "Offline" },
];

export default function EngineersPage() {
  const [engineers, setEngineers] = useState<Engineer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const fetchEngineers = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
      if (search) params.append("search", search);
      if (statusFilter) params.append("status", statusFilter);
      const data = await api.request<PaginatedResponse<Engineer>>(`/engineers?${params}`);
      setEngineers(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load engineers"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchEngineers(); }, [page, pageSize, search, statusFilter]);

  const columns = [
    { key: "id", header: "ID", render: (e: Engineer) => <code className="text-sm">{e.id}</code> },
    { key: "name", header: "Name" },
    { key: "email", header: "Email" },
    { key: "skills", header: "Skills", render: (e: Engineer) => <span className="text-sm">{e.skills.join(", ") || "—"}</span> },
    { key: "availability_status", header: "Status", render: (e: Engineer) => <StatusBadge status={e.availability_status} /> },
    { key: "created_at", header: "Created", render: (e: Engineer) => new Date(e.created_at).toLocaleDateString() },
  ];

  if (loading) return <DashboardLayout><LoadingState message="Loading engineers..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchEngineers} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div><h1 className="text-2xl font-bold text-gray-900">Engineers</h1><p className="text-gray-600 mt-1">Manage engineering staff</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search engineers..." />
            <FilterSelect label="Status" options={[{value:"",label:"All"},{value:"available",label:"Available"},{value:"busy",label:"Busy"},{value:"offline",label:"Offline"}]} value={statusFilter} onChange={setStatusFilter} />
          </div>
          <DataTable data={engineers} columns={[
            {key:"id",header:"ID",render:(e:Engineer)=><code className="text-sm">{e.id}</code>},
            {key:"name",header:"Name"},
            {key:"email",header:"Email"},
            {key:"skills",header:"Skills",render:(e:Engineer)=><span className="text-sm">{e.skills.join(", ")||"—"}</span>},
            {key:"availability_status",header:"Status",render:(e:Engineer)=><StatusBadge status={e.availability_status}/>},
            {key:"created_at",header:"Created",render:(e:Engineer)=>new Date(e.created_at).toLocaleDateString()},
          ]} keyExtractor={(e)=>e.id} emptyMessage="No engineers found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/25)} onPageChange={setPage} showPageSize pageSize={25} onPageSizeChange={setPageSize} />
        </div>
        </div>
      </DashboardLayout>
  );
}
