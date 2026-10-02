"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Invoice {
  id: string;
  tenant_id: string;
  customer_id: string;
  job_id?: string;
  amount: number;
  status: string;
  due_date: string;
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
  { value: "unpaid", label: "Unpaid" },
  { value: "paid", label: "Paid" },
  { value: "overdue", label: "Overdue" },
  { value: "partial", label: "Partial" },
];

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const fetchInvoices = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() });
      if (search) params.append("search", search);
      if (statusFilter) params.append("status", statusFilter);
      const data = await api.request<PaginatedResponse<Invoice>>(`/api/v1/invoices?${params}`);
      setInvoices(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load invoices"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchInvoices(); }, [page, pageSize, search, statusFilter]);

  const columns = [
    { key: "id", header: "ID", render: (i: Invoice) => <code className="text-sm">{i.id}</code> },
    { key: "customer_id", header: "Customer" },
    { key: "amount", header: "Amount", render: (i: Invoice) => <span className="font-medium">${i.amount.toFixed(2)}</span> },
    { key: "status", header: "Status", render: (i: Invoice) => <StatusBadge status={i.status} /> },
    { key: "due_date", header: "Due Date", render: (i: Invoice) => new Date(i.due_date).toLocaleDateString() },
    { key: "created_at", header: "Created", render: (i: Invoice) => new Date(i.created_at).toLocaleDateString() },
  ];

  if (loading) return <DashboardLayout><LoadingState message="Loading invoices..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchInvoices} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div><h1 className="text-2xl font-bold text-gray-900">Invoices</h1><p className="text-gray-600 mt-1">Manage billing and payments</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search invoices..." />
            <FilterSelect label="Status" options={[{value:"",label:"All"},{value:"unpaid",label:"Unpaid"},{value:"paid",label:"Paid"},{value:"overdue",label:"Overdue"},{value:"partial",label:"Partial"}]} value={statusFilter} onChange={setStatusFilter} />
            <div className="flex items-end"><label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label><select value={pageSize} onChange={(e)=>{setPageSize(Number(e.target.value));setPage(1);}} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></div>
          </div>
          <DataTable data={invoices} columns={[{key:"id",header:"ID",render:(i:Invoice)=><code className="text-sm">{i.id}</code>},{key:"customer_id",header:"Customer"},{key:"amount",header:"Amount",render:(i:Invoice)=><span className="font-medium">${i.amount.toFixed(2)}</span>},{key:"status",header:"Status",render:(i:Invoice)=><StatusBadge status={i.status}/>},{key:"due_date",header:"Due Date",render:(i:Invoice)=>new Date(i.due_date).toLocaleDateString()},{key:"created_at",header:"Created",render:(i:Invoice)=>new Date(i.created_at).toLocaleDateString()}]} keyExtractor={(i)=>i.id} emptyMessage="No invoices found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>
        </div>
      </DashboardLayout>
  );
}
