"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, FilterSelect, Pagination, LoadingState, ErrorState, Modal } from "@/components/dashboard";

interface Approval {
  id: string;
  tenant_id: string;
  conversation_id: string;
  ticket_id?: string;
  requested_by: string;
  agent_type: string;
  action_type: string;
  resource_type: string;
  resource_id?: string;
  reason?: string;
  risk_level: string;
  status: string;
  reviewed_by?: string;
  review_comment?: string;
  expires_at?: string;
  created_at: string;
}

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "PENDING", label: "Pending" },
  { value: "APPROVED", label: "Approved" },
  { value: "REJECTED", label: "Rejected" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "EXPIRED", label: "Expired" },
  { value: "EXECUTED", label: "Executed" },
  { value: "FAILED", label: "Failed" },
];

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [selectedApproval, setSelectedApproval] = useState<Approval | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchApprovals = async () => {
    try {
      setLoading(true);
      // Backend doesn't support pagination for approvals
      const params = new URLSearchParams({ limit: "100" });
      if (statusFilter) params.append("status", statusFilter);
      const data = await api.request<Approval[]>(`/approvals?${params}`);
      // Apply client-side filtering and pagination
      let filtered = data;
      setTotal(filtered.length);
      const start = (page - 1) * pageSize;
      const end = start + pageSize;
      setApprovals(filtered.slice(start, end));
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load approvals"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchApprovals(); }, [page, pageSize, statusFilter]);

  const columns = [
    { key: "id", header: "ID", render: (a: Approval) => <code className="text-sm">{a.id}</code> },
    { key: "action_type", header: "Action" },
    { key: "resource_type", header: "Resource" },
    { key: "resource_id", header: "Resource ID", render: (a: Approval) => a.resource_id ? <code className="text-sm">{a.resource_id}</code> : "—" },
    { key: "risk_level", header: "Risk" },
    { key: "status", header: "Status", render: (a: Approval) => <StatusBadge status={a.status} /> },
    { key: "requested_by", header: "Requested By" },
    { key: "created_at", header: "Created", render: (a: Approval) => new Date(a.created_at).toLocaleString() },
  ];

  const handleApproveClick = (approval: Approval) => {
    if (approval.status === "PENDING") {
      setSelectedApproval(approval);
      setShowApproveModal(true);
    }
  };

  const handleRejectClick = (approval: Approval) => {
    if (approval.status === "PENDING") {
      setSelectedApproval(approval);
      setRejectReason("");
      setShowRejectModal(true);
    }
  };

  const handleApprove = async () => {
    if (!selectedApproval || submitting) return;
    setSubmitting(true);
    try {
      await api.request(`/approvals/${selectedApproval.id}/approve`, { method: "POST", body: JSON.stringify({}) });
      setShowApproveModal(false);
      setSelectedApproval(null);
      fetchApprovals();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to approve"); }
    finally { setSubmitting(false); }
  };

  const handleReject = async () => {
    if (!selectedApproval || submitting) return;
    setSubmitting(true);
    try {
      await api.request(`/approvals/${selectedApproval.id}/reject`, { method: "POST", body: JSON.stringify({ comment: rejectReason }) });
      setShowRejectModal(false);
      setSelectedApproval(null);
      setRejectReason("");
      fetchApprovals();
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to reject"); }
    finally { setSubmitting(false); }
  };

  if (loading) return <DashboardLayout><LoadingState message="Loading approvals..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchApprovals} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div><h1 className="text-2xl font-bold text-gray-900">Approvals</h1><p className="text-gray-600 mt-1">Review and decide on pending approval requests</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <FilterSelect label="Status" options={[{value:"",label:"All"},{value:"PENDING",label:"Pending"},{value:"APPROVED",label:"Approved"},{value:"REJECTED",label:"Rejected"},{value:"CANCELLED",label:"Cancelled"},{value:"EXPIRED",label:"Expired"},{value:"EXECUTED",label:"Executed"},{value:"FAILED",label:"Failed"}]} value={statusFilter} onChange={setStatusFilter} />
            <div className="flex items-end"><label className="block text-sm font-medium text-gray-700 mb-1">Page Size</label><select value={pageSize} onChange={(e)=>{setPageSize(Number(e.target.value));setPage(1);}} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"><option value={10}>10</option><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></div>
          </div>
          <DataTable data={approvals} columns={[
            {key:"id",header:"ID",render:(a:Approval)=><code className="text-sm">{a.id}</code>},
            {key:"action_type",header:"Action"},
            {key:"resource_type",header:"Resource"},
            {key:"resource_id",header:"Resource ID",render:(a:Approval)=>a.resource_id?<code className="text-sm">{a.resource_id}</code>:"—"},
            {key:"risk_level",header:"Risk"},
            {key:"status",header:"Status",render:(a:Approval)=><StatusBadge status={a.status}/>},
            {key:"requested_by",header:"Requested By"},
            {key:"created_at",header:"Created",render:(a:Approval)=>new Date(a.created_at).toLocaleString()},
          ]} keyExtractor={(a)=>a.id} emptyMessage="No approvals found" onRowClick={(a)=>a.status==="PENDING"&&handleApproveClick(a)} />
          <Pagination currentPage={page} totalPages={Math.ceil(total/pageSize)} onPageChange={setPage} showPageSize pageSize={pageSize} onPageSizeChange={setPageSize} />
        </div>

        <Modal isOpen={showApproveModal} onClose={()=>setShowApproveModal(false)} title="Approve Request" size="sm">
          <p className="text-gray-600">Are you sure you want to approve this request?</p>
          <div className="mt-4 p-4 bg-gray-50 rounded-lg text-sm">
            <p><strong>Action:</strong> {selectedApproval?.action_type}</p>
            <p><strong>Resource:</strong> {selectedApproval?.resource_type} {selectedApproval?.resource_id||""}</p>
            <p><strong>Reason:</strong> {selectedApproval?.reason||"—"}</p>
            <p><strong>Risk:</strong> {selectedApproval?.risk_level}</p>
          </div>
          <div className="mt-6 flex justify-end gap-3">
            <button onClick={()=>setShowApproveModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
            <button onClick={handleApprove} disabled={submitting} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50">{submitting?"Approving...":"Approve"}</button>
          </div>
        </Modal>

        <Modal isOpen={showRejectModal} onClose={()=>{setShowRejectModal(false);setRejectReason("");}} title="Reject Request" size="sm">
          <p className="text-gray-600">Are you sure you want to reject this request?</p>
          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Rejection Reason</label>
            <textarea value={rejectReason} onChange={(e)=>setRejectReason(e.target.value)} rows={3} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="Enter reason for rejection" required />
          </div>
          <div className="mt-6 flex justify-end gap-3">
            <button onClick={()=>{setShowRejectModal(false);setRejectReason("");}} className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">Cancel</button>
            <button onClick={handleReject} disabled={submitting||!rejectReason.trim()} className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg disabled:opacity-50">{submitting?"Rejecting...":"Reject"}</button>
          </div>
        </Modal>
        </div>
      </DashboardLayout>
  );
}
