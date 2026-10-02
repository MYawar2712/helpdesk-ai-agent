"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, PriorityBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Job {
  id: string;
  tenant_id: string;
  customer_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  required_skill: string;
  service_area: string;
  assigned_engineer_id?: string;
  scheduled_at?: string;
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
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In Progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "All Priorities" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" },
];

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");

  const fetchJobs = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
      if (search) params.append("search", search);
      if (statusFilter) params.append("status", statusFilter);
      if (priorityFilter) params.append("priority", priorityFilter);
      const data = await api.request<PaginatedResponse<Job>>(`/jobs?${params}`);
      setJobs(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load jobs"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchJobs(); }, [page, pageSize, search, statusFilter, priorityFilter]);

  const columns = [
    { key: "id", header: "ID", render: (j: Job) => <code className="text-sm">{j.id}</code> },
    { key: "title", header: "Title" },
    { key: "status", header: "Status", render: (j: Job) => <StatusBadge status={j.status} /> },
    { key: "priority", header: "Priority", render: (j: Job) => <PriorityBadge priority={j.priority} /> },
    { key: "required_skill", header: "Skill" },
    { key: "service_area", header: "Area" },
    { key: "assigned_engineer_id", header: "Engineer", render: (j: Job) => j.assigned_engineer_id ? <code className="text-sm">{j.assigned_engineer_id}</code> : "—" },
    { key: "scheduled_at", header: "Scheduled", render: (j: Job) => j.scheduled_at ? new Date(j.scheduled_at).toLocaleString() : "—" },
  ];

  if (loading) return <DashboardLayout><LoadingState message="Loading jobs..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchJobs} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div><h1 className="text-2xl font-bold text-gray-900">Jobs</h1><p className="text-gray-600 mt-1">Manage service jobs</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search jobs..." />
            <FilterSelect label="Status" options={[{value:"",label:"All"},{value:"scheduled",label:"Scheduled"},{value:"in_progress",label:"In Progress"},{value:"completed",label:"Completed"},{value:"cancelled",label:"Cancelled"}]} value={statusFilter} onChange={setStatusFilter} />
            <FilterSelect label="Priority" options={[{value:"",label:"All"},{value:"low",label:"Low"},{value:"medium",label:"Medium"},{value:"high",label:"High"},{value:"critical",label:"Critical"}]} value={priorityFilter} onChange={setPriorityFilter} />
            <div className="flex items-end"><label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label><select value={pageSize} onChange={(e)=>{setPageSize(Number(e.target.value));setPage(1);}} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></div>
          </div>
          <DataTable data={jobs} columns={[{key:"id",header:"ID",render:(j:Job)=><code className="text-sm">{j.id}</code>},{key:"title",header:"Title"},{key:"status",header:"Status",render:(j:Job)=><StatusBadge status={j.status}/>},{key:"priority",header:"Priority",render:(j:Job)=><PriorityBadge priority={j.priority}/>},{key:"required_skill",header:"Skill"},{key:"service_area",header:"Area"},{key:"assigned_engineer_id",header:"Engineer",render:(j:Job)=>j.assigned_engineer_id?<code className="text-sm">{j.assigned_engineer_id}</code>:"—"},{key:"scheduled_at",header:"Scheduled",render:(j:Job)=>j.scheduled_at?new Date(j.scheduled_at).toLocaleString():"—"}]} keyExtractor={(j)=>j.id} emptyMessage="No jobs found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>
        </div>
      </DashboardLayout>
  );
}
