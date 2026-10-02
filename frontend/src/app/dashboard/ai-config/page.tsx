"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DashboardLayout, DataTable, StatusBadge, SearchInput, FilterSelect, LoadingState, ErrorState, Modal, Button, Input, Textarea } from "@/components/dashboard";

interface AIConfig {
  id: string;
  tenant_id: string;
  agent_type: string;
  instructions?: string;
  tone?: string;
  business_rules: string[];
  escalation_rules: string[];
  allowed_tools: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

const AGENT_TYPES = ["GLOBAL", "SUPPORT_AGENT", "JOB_AGENT", "INVOICE_AGENT", "TRIAGE"];

export default function AIConfigPage() {
  const [configs, setConfigs] = useState<AIConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingConfig, setEditingConfig] = useState<AIConfig | null>(null);
  const [saving, setSaving] = useState(false);

  const [formData, setFormData] = useState({
    agent_type: "SUPPORT_AGENT",
    instructions: "",
    tone: "",
    business_rules: "",
    escalation_rules: "",
    allowed_tools: "",
    is_active: true,
  });

  const fetchConfigs = async () => {
    try {
      setLoading(true);
      const data = await api.request<AIConfig[]>("/ai-config");
      setConfigs(data);
      setError(null);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to load configurations"); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { fetchConfigs(); }, []);

  const columns = [
    { key: "agent_type", header: "Agent Type" },
    { key: "is_active", header: "Status", render: (c: AIConfig) => <StatusBadge status={c.is_active ? "active" : "inactive"} /> },
    { key: "tone", header: "Tone", render: (c: AIConfig) => c.tone || "—" },
    { key: "updated_at", header: "Updated", render: (c: AIConfig) => new Date(c.updated_at).toLocaleDateString() },
  ];

  const openCreateModal = () => {
    setEditingConfig(null);
    setFormData({ agent_type: "SUPPORT_AGENT", instructions: "", tone: "", business_rules: "", escalation_rules: "", allowed_tools: "", is_active: true });
    setShowModal(true);
  };

  const openEditModal = (config: AIConfig) => {
    setEditingConfig(config);
    setFormData({
      agent_type: config.agent_type,
      instructions: config.instructions || "",
      tone: config.tone || "",
      business_rules: config.business_rules.join("\n"),
      escalation_rules: config.escalation_rules.join("\n"),
      allowed_tools: config.allowed_tools.join("\n"),
      is_active: config.is_active,
    });
    setShowModal(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        agent_type: formData.agent_type,
        instructions: formData.instructions || undefined,
        tone: formData.tone || undefined,
        business_rules: formData.business_rules.split("\n").filter(Boolean),
        escalation_rules: formData.escalation_rules.split("\n").filter(Boolean),
        allowed_tools: formData.allowed_tools.split("\n").filter(Boolean),
        is_active: formData.is_active,
      };

      if (editingConfig) {
        await api.request(`/ai-config/${editingConfig.agent_type}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api.request("/ai-config", { method: "POST", body: JSON.stringify(payload) });
      }
      setShowModal(false);
      fetchConfigs();
    } catch (err) { alert(err instanceof Error ? err.message : "Save failed"); }
    finally { setSaving(false); }
  };

  if (loading) return <DashboardLayout><LoadingState message="Loading configurations..." /></DashboardLayout>;
  if (error) return <DashboardLayout><ErrorState message={error} onRetry={fetchConfigs} /></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div><h1 className="text-2xl font-bold text-gray-900">AI Configuration</h1><p className="text-gray-600 mt-1">Manage agent instructions and settings</p></div>
          <Button onClick={openCreateModal}>+ Add Configuration</Button>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <DataTable data={configs} columns={columns} keyExtractor={(c)=>c.id} emptyMessage="No configurations found" onRowClick={openEditModal} />
        </div>

        <Modal isOpen={showModal} onClose={()=>setShowModal(false)} title={editingConfig?"Edit Configuration":"Create Configuration"} size="lg">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Type</label>
                <select value={formData.agent_type} onChange={(e)=>setFormData({...formData,agent_type:e.target.value})} disabled={!!editingConfig} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50">
                  {AGENT_TYPES.map(t=><option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Tone</label>
                <Input value={formData.tone} onChange={(e)=>setFormData({...formData,tone:e.target.value})} placeholder="professional, friendly, formal..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Active</label>
                <select value={formData.is_active.toString()} onChange={(e)=>setFormData({...formData,is_active:e.target.value==="true"})} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Instructions</label>
              <Textarea value={formData.instructions} onChange={(e)=>setFormData({...formData,instructions:e.target.value})} rows={4} placeholder="Agent instructions..." />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Business Rules (one per line)</label>
                <Textarea value={formData.business_rules} onChange={(e)=>setFormData({...formData,business_rules:e.target.value})} rows={4} placeholder="require_human_approval_for=cancel_job,update_invoice\nno_human_approval_for=search_knowledge" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Escalation Rules (one per line)</label>
                <Textarea value={formData.escalation_rules} onChange={(e)=>setFormData({...formData,escalation_rules:e.target.value})} rows={4} placeholder="escalate_on=dispute,emergency" />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Allowed Tools (one per line)</label>
              <Textarea value={formData.allowed_tools} onChange={(e)=>setFormData({...formData,allowed_tools:e.target.value})} rows={4} placeholder="get_job\ncancel_job\ncreate_job" />
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t">
              <Button type="button" variant="ghost" onClick={()=>setShowModal(false)}>Cancel</Button>
              <Button type="submit" disabled={saving}>{saving?"Saving...":editingConfig?"Update":"Create"}</Button>
            </div>
          </form>
        </Modal>
        </div>
      </DashboardLayout>
  );
}
