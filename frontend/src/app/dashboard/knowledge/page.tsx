"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, Pagination, LoadingState, ErrorState, Modal, Button } from "@/components/dashboard";

interface Document {
  id: string;
  tenant_id: string;
  name: string;
  file_path: string;
  processing_status: string;
  doc_metadata?: Record<string, unknown>;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "pending", label: "Pending" },
  { value: "processing", label: "Processing" },
  { value: "ready", label: "Ready" },
  { value: "failed", label: "Failed" },
];

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      // Backend doesn't support pagination for documents
      const data = await api.request<Document[]>(`/knowledge/documents`);
      // Apply client-side filtering and pagination
      let filtered = data;
      if (statusFilter) {
        filtered = filtered.filter(d => d.processing_status === statusFilter);
      }
      setTotal(filtered.length);
      const start = (page - 1) * pageSize;
      const end = start + pageSize;
      setDocuments(filtered.slice(start, end));
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load documents"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchDocuments();
  }, [page, pageSize, statusFilter]);

  const columns = [
    { key: "id", header: "ID", render: (d: Document) => <code className="text-sm">{d.id}</code> },
    { key: "name", header: "Name" },
    { key: "processing_status", header: "Status", render: (d: Document) => <StatusBadge status={d.processing_status} /> },
    { key: "chunk_count", header: "Chunks", render: (d: Document) => <span className="font-medium">{d.chunk_count}</span> },
    { key: "created_at", header: "Created", render: (d: Document) => new Date(d.created_at).toLocaleDateString() },
    { key: "actions", header: "Actions", render: (d: Document) => (
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => window.open(`/knowledge/documents/${d.id}/download`, "_blank")}>Download</Button>
        <Button variant="danger" size="sm" onClick={() => { if(confirm(`Delete "${d.name}"?`)) deleteDocument(d.id); }}>Delete</Button>
      </div>
      )},
  ];

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || !uploadName.trim()) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      const response = await fetch(`${api.getToken()?"":""}/knowledge/documents`, {
        method: "POST",
        headers: { Authorization: `Bearer ${api.getToken()}` },
        body: formData,
      });
      if (!response.ok) throw new Error("Upload failed");
      setShowUploadModal(false);
      setUploadFile(null);
      setUploadName("");
      fetchDocuments();
    } catch (err) { alert(err instanceof Error ? err.message : "Upload failed"); }
    finally { setUploading(false); }
  };

  const deleteDocument = async (id: string) => {
    if (!confirm("Are you sure you want to delete this document?")) return;
    try {
      await api.request(`/knowledge/documents/${id}`, { method: "DELETE" });
      fetchDocuments();
    } catch (err) { alert(err instanceof Error ? err.message : "Delete failed"); }
  };

  if (loading) return <DashboardLayout><LoadingState message="Loading documents..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchDocuments} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div><h1 className="text-2xl font-bold text-gray-900">Knowledge Base</h1><p className="text-gray-600 mt-1">Manage knowledge documents</p></div>
          <Button onClick={() => setShowUploadModal(true)}>+ Upload Document</Button>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
            <SearchInput value={search} onChange={setSearch} placeholder="Search documents..." />
            <FilterSelect label="Status" options={[{value:"",label:"All"},{value:"pending",label:"Pending"},{value:"processing",label:"Processing"},{value:"ready",label:"Ready"},{value:"failed",label:"Failed"}]} value={statusFilter} onChange={setStatusFilter} />
            <div className="flex items-end"><label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label><select value={pageSize} onChange={(e)=>{setPageSize(Number(e.target.value));setPage(1);}} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></div>
          </div>
          <DataTable data={documents} columns={columns} keyExtractor={(d)=>d.id} emptyMessage="No documents found" />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>

        <Modal isOpen={showUploadModal} onClose={()=>{setShowUploadModal(false);setUploadFile(null);setUploadName("");}} title="Upload Document" size="md">
          <form onSubmit={handleUpload} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Document Name</label>
              <input type="text" value={uploadName} onChange={(e)=>setUploadName(e.target.value)} required className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">File (PDF, MD, TXT)</label>
              <input type="file" accept=".pdf,.md,.txt" onChange={(e)=>setUploadFile(e.target.files?.[0]||null)} required className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="ghost" onClick={()=>{setShowUploadModal(false);setUploadFile(null);setUploadName("");}}>Cancel</Button>
              <Button type="submit" disabled={uploading}>{uploading?"Uploading...":"Upload"}</Button>
            </div>
          </form>
        </Modal>
        </div>
      </DashboardLayout>
  );
}
