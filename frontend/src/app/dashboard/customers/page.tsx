"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState } from "@/components/dashboard";

interface Customer {
  id: string;
  tenant_id: string;
  name: string;
  email: string;
  phone: string;
  is_active: boolean;
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

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const fetchCustomers = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      });
      if (search) params.append("search", search);

      const data = await api.request<PaginatedResponse<Customer>>(`/customers?${params}`);
      setCustomers(data.items);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load customers");
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchCustomers();
  }, [page, pageSize, search]);

  const columns = [
    { key: "id", header: "ID", render: (c: Customer) => <code className="text-sm">{c.id}</code> },
    { key: "name", header: "Name" },
    { key: "email", header: "Email" },
    { key: "phone", header: "Phone" },
    { key: "is_active", header: "Status", render: (c: Customer) => <StatusBadge status={c.is_active ? "active" : "inactive"} /> },
    { key: "created_at", header: "Created", render: (c: Customer) => new Date(c.created_at).toLocaleDateString() },
  ];

  if (loading) {
    return <DashboardLayout><LoadingState message="Loading customers..." /></DashboardLayout>;
  }
  if (error) {
    return <DashboardLayout><ErrorState message={error} onRetry={fetchCustomers} /></DashboardLayout>;
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Customers</h1>
          <p className="text-gray-600 mt-1">Manage customer accounts</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search customers..." />
            <div className="flex items-end">
              <label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label>
              <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value={10}>10 per page</option>
                <option value={25}>25 per page</option>
                <option value={50}>50 per page</option>
                <option value={100}>100 per page</option>
              </select>
            </div>
          </div>
          <DataTable data={customers} columns={columns} keyExtractor={(c) => c.id} emptyMessage="No customers found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>
        </div>
      </DashboardLayout>
  );
}
