import React, { useState, useEffect } from 'react';
import {
  LayoutDashboard,
  Terminal,
  Users,
  Workflow,
  Bot,
  ShieldCheck,
  BrainCircuit,
  Briefcase,
  DollarSign,
  Link2,
  Settings,
  Bell,
  RefreshCw,
  Sparkles,
  AlertTriangle,
} from 'lucide-react';

import { OverviewTab } from './components/OverviewTab';
import { FounderCommandTab } from './components/FounderCommandTab';
import { BoardroomTab } from './components/BoardroomTab';
import { WorkflowStudioTab } from './components/WorkflowStudioTab';
import { AgentStudioTab } from './components/AgentStudioTab';
import { AccountabilityTab } from './components/AccountabilityTab';
import { BusinessMemoryTab } from './components/BusinessMemoryTab';
import { OperationsTab } from './components/OperationsTab';
import { FinanceTab } from './components/FinanceTab';
import { IntegrationsTab } from './components/IntegrationsTab';
import { SettingsTab } from './components/SettingsTab';

import { api } from './services/api';
import { GatewayStatus, ProactiveAlert } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus | null>(null);
  const [alerts, setAlerts] = useState<ProactiveAlert[]>([]);
  const [showAlertModal, setShowAlertModal] = useState<boolean>(false);
  const [isResetting, setIsResetting] = useState<boolean>(false);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const [gw, al] = await Promise.all([api.getGatewayStatus(), api.getAlerts()]);
      setGatewayStatus(gw);
      setAlerts(al);
    } catch (e) {
      console.error('Error loading app status', e);
    }
  };

  const handleResetDemo = async () => {
    setIsResetting(true);
    try {
      await api.resetDemo();
      await loadStatus();
    } catch (e) {
      console.error('Reset failed', e);
    } finally {
      setIsResetting(false);
    }
  };

  const navItems = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'command', label: 'Founder Command', icon: Terminal },
    { id: 'boardroom', label: 'Boardroom', icon: Users, badge: '9 Agents' },
    { id: 'workflows', label: 'Workflow Studio', icon: Workflow },
    { id: 'agents', label: 'Agent Studio', icon: Bot },
    { id: 'accountability', label: 'Accountability', icon: ShieldCheck },
    { id: 'memory', label: 'Business Memory', icon: BrainCircuit },
    { id: 'operations', label: 'Operations & CRM', icon: Briefcase },
    { id: 'finance', label: 'Finance & Ledger', icon: DollarSign },
    { id: 'integrations', label: 'Integrations', icon: Link2 },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#080d1a] text-slate-100">
      {/* Sidebar Navigation */}
      <aside className="w-64 shrink-0 border-r border-slate-800/80 bg-[#090e1b] flex flex-col justify-between p-4">
        <div className="space-y-6">
          {/* Logo & Product Name */}
          <div className="flex items-center gap-3 px-2 py-1">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-400 flex items-center justify-center shadow-lg shadow-indigo-600/30">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-extrabold text-base tracking-tight text-white block">OneBoard</span>
              <span className="text-[10px] text-indigo-400 font-semibold tracking-wider uppercase block">
                Company of One OS
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-1 overflow-y-auto max-h-[calc(100vh-210px)] pr-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition ${
                    isActive
                      ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/20'
                      : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Icon className={`w-4 h-4 ${isActive ? 'text-white' : 'text-slate-400'}`} />
                    <span>{item.label}</span>
                  </div>
                  {item.badge && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono">
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Footer info in sidebar */}
        <div className="pt-3 border-t border-slate-800/80 text-[11px] text-slate-500 space-y-1 px-2">
          <div className="flex items-center justify-between font-mono">
            <span>Dubai AI 2026–27</span>
            <span className="text-emerald-400 font-bold">100% Free</span>
          </div>
          <div className="truncate text-slate-500">Northstar Studio B2B SaaS</div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        {/* Top Header */}
        <header className="h-16 shrink-0 border-b border-slate-800/80 bg-[#090e1b]/80 backdrop-blur px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider font-mono">Northstar Studio</span>
            <span className="text-slate-700">•</span>
            <span className="text-xs text-slate-300 font-medium capitalize">
              {navItems.find((n) => n.id === activeTab)?.label}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Ollama Status Pill */}
            <div
              onClick={() => setActiveTab('settings')}
              className="flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs font-mono cursor-pointer hover:border-slate-700 transition"
              title="Click to view Ollama Model Gateway Settings"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  gatewayStatus?.status === 'connected' ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              ></span>
              <span className="text-slate-300 text-[11px]">
                {gatewayStatus?.status === 'connected' ? 'Ollama: Connected' : 'Local Fallback Simulator'}
              </span>
            </div>

            {/* Proactive Alerts Bell */}
            <button
              onClick={() => setShowAlertModal(!showAlertModal)}
              className="relative p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
              title="Proactive Scheduler Alerts"
            >
              <Bell className="w-4 h-4" />
              {alerts.length > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-rose-500 text-white text-[10px] flex items-center justify-center font-bold">
                  {alerts.length}
                </span>
              )}
            </button>

            {/* Reset Demo Button */}
            <button
              onClick={handleResetDemo}
              disabled={isResetting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-xl border border-slate-700/60 transition"
              title="Restore clean Northstar Studio demo scenario"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isResetting ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Reset Demo</span>
            </button>
          </div>
        </header>

        {/* Dynamic Tab Body */}
        <main className="flex-1 overflow-y-auto p-6">
          {activeTab === 'overview' && <OverviewTab onNavigate={setActiveTab} />}
          {activeTab === 'command' && <FounderCommandTab />}
          {activeTab === 'boardroom' && <BoardroomTab />}
          {activeTab === 'workflows' && <WorkflowStudioTab />}
          {activeTab === 'agents' && <AgentStudioTab />}
          {activeTab === 'accountability' && <AccountabilityTab />}
          {activeTab === 'memory' && <BusinessMemoryTab />}
          {activeTab === 'operations' && <OperationsTab />}
          {activeTab === 'finance' && <FinanceTab />}
          {activeTab === 'integrations' && <IntegrationsTab />}
          {activeTab === 'settings' && <SettingsTab />}
        </main>
      </div>

      {/* Proactive Alerts Modal */}
      {showAlertModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="p-6 rounded-2xl bg-slate-900 border border-slate-700 max-w-lg w-full space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-sm font-bold text-white flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Active Proactive Background Alerts ({alerts.length})
              </span>
              <button
                onClick={() => setShowAlertModal(false)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Close
              </button>
            </div>

            <div className="space-y-3 max-h-[320px] overflow-y-auto">
              {alerts.length === 0 ? (
                <div className="text-slate-400 text-xs text-center py-6">No active business hazards detected.</div>
              ) : (
                alerts.map((al) => (
                  <div key={al.id} className="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700 space-y-1 text-xs">
                    <div className="flex items-center justify-between font-semibold">
                      <span className="text-white">{al.title}</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 uppercase">
                        {al.severity}
                      </span>
                    </div>
                    <p className="text-slate-400 leading-relaxed text-[11px]">{al.description}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
