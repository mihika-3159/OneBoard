import React, { useState, useEffect, lazy, Suspense } from 'react';
import {ScreenBoundary,ScreenState,AlertDialog,screenHelp} from './components/ScreenSupport';
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
  LogOut,
  UserCheck,
  Lock,
  Mail,
  Building,
} from 'lucide-react';

const OverviewTab=lazy(()=>import('./components/OverviewTab').then(m=>({default:m.OverviewTab})));
const FounderCommandTab=lazy(()=>import('./components/FounderCommandTab').then(m=>({default:m.FounderCommandTab})));
const BoardroomTab=lazy(()=>import('./components/BoardroomTab').then(m=>({default:m.BoardroomTab})));
const WorkflowStudioTab=lazy(()=>import('./components/WorkflowStudioTab').then(m=>({default:m.WorkflowStudioTab})));
const AgentStudioTab=lazy(()=>import('./components/AgentStudioTab').then(m=>({default:m.AgentStudioTab})));
const AccountabilityTab=lazy(()=>import('./components/AccountabilityTab').then(m=>({default:m.AccountabilityTab})));
const BusinessMemoryTab=lazy(()=>import('./components/BusinessMemoryTab').then(m=>({default:m.BusinessMemoryTab})));
const OperationsTab=lazy(()=>import('./components/OperationsTab').then(m=>({default:m.OperationsTab})));
const FinanceTab=lazy(()=>import('./components/FinanceTab').then(m=>({default:m.FinanceTab})));
const IntegrationsTab=lazy(()=>import('./components/IntegrationsTab').then(m=>({default:m.IntegrationsTab})));
const SettingsTab=lazy(()=>import('./components/SettingsTab').then(m=>({default:m.SettingsTab})));

import { api, UnauthorizedError, resetClientSession, sessionExpiredEvent, connectionIssueEvent } from './services/api';
import { GatewayStatus, ProactiveAlert, UserProfile, BusinessProfile } from './types';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>(()=>new URLSearchParams(window.location.search).has('provider_oauth')?'integrations':'overview');
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus | null>(null);
  const [alerts, setAlerts] = useState<ProactiveAlert[]>([]);
  const [showAlertModal, setShowAlertModal] = useState<boolean>(false);
  const [showSetup,setShowSetup]=useState(false);
  const [isResetting, setIsResetting] = useState<boolean>(false);

  // Authentication State
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [checkingSession,setCheckingSession]=useState(true),[sessionCheckError,setSessionCheckError]=useState(''),[screenRevision,setScreenRevision]=useState(0);
  const [connectionIssue,setConnectionIssue]=useState<{message:string;write:boolean;path:string}|null>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [currentBusiness, setCurrentBusiness] = useState<Partial<BusinessProfile> | null>(null);
  const [authError, setAuthError] = useState<string>('');
  const [authLoading, setAuthLoading] = useState<boolean>(false);
  const [isRegisterMode, setIsRegisterMode] = useState<boolean>(false);

  // Form fields
  const [authEmail, setAuthEmail] = useState<string>('');
  const [authPassword, setAuthPassword] = useState<string>('');
  const [authFactor,setAuthFactor]=useState('');
  const [recoverMode,setRecoverMode]=useState(false);
  const [authMessage,setAuthMessage]=useState('');
  const [authName, setAuthName] = useState<string>('');
  const [authBizName, setAuthBizName] = useState<string>('');

  useEffect(()=>{
    const expired=(event:Event)=>{setIsRegisterMode(false);setRecoverMode(false);setIsAuthenticated(false);setCurrentUser(null);setCurrentBusiness(null);setGatewayStatus(null);setAlerts([]);setShowAlertModal(false);setShowSetup(false);setAuthPassword('');setAuthFactor('');setConnectionIssue(null);setAuthError((event as CustomEvent).detail||'Your session expired. Sign in again. No interrupted write was automatically replayed.');};
    const issue=(event:Event)=>{const detail=(event as CustomEvent).detail;setConnectionIssue(old=>detail.recovered?(old!==null&&old.path===detail.path&&!old.write?null:old):detail);};
    window.addEventListener(sessionExpiredEvent,expired);window.addEventListener(connectionIssueEvent,issue);
    void checkSessionAndLoad();
    return()=>{window.removeEventListener(sessionExpiredEvent,expired);window.removeEventListener(connectionIssueEvent,issue)};
  },[]);

  const checkSessionAndLoad=async()=>{
    setCheckingSession(true);setSessionCheckError('');
    try{const me=await api.getMe();setCurrentUser(me.user);setCurrentBusiness(me.business);setIsAuthenticated(true);await loadAppStatus();}
    catch(e){setIsAuthenticated(false);setCurrentUser(null);setCurrentBusiness(null);if(!(e instanceof UnauthorizedError))setSessionCheckError('Session verification unavailable. No workspace data loaded.');}
    finally{setCheckingSession(false)}
  };

  const loadAppStatus = async () => {
    try {
      const [gw, al] = await Promise.all([
        api.getGatewayStatus().catch(() => null),
        api.getAlerts().catch(() => []),
      ]);
      if (gw) setGatewayStatus(gw);
      if (al) setAlerts(al);
    } catch (e) {
      console.error('Error loading app status', e);
    }
  };

  const handleLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setAuthLoading(true);
    setAuthError('');setAuthMessage('');
    try {
      if(recoverMode){
        await api.recoverAccount(authEmail.trim(),authFactor,authPassword);
        setAuthMessage('Password reset. Sign in with your new password and another MFA code if enabled.');
        setRecoverMode(false);setAuthFactor('');setAuthPassword('');return;
      }
      resetClientSession();
      if (isRegisterMode) {
        const res = await api.register({
          name: authName.trim() || 'Founder',
          email: authEmail.trim(),
          password: authPassword,
          business_name: authBizName.trim() || undefined,
        });
        setCurrentUser(res.user);
        setCurrentBusiness(res.business);setShowSetup(true);
      } else {
        const res = await api.login(authEmail.trim(), authPassword, authFactor || undefined);
        setCurrentUser(res.user);
        setCurrentBusiness(res.business);
      }
      setIsAuthenticated(true);setIsRegisterMode(false);setRecoverMode(false);setConnectionIssue(null);setAuthPassword('');setAuthFactor('');
      await loadAppStatus();
    } catch (err: any) {
      setAuthError(err.detail || err.message || 'Authentication failed. Please check your credentials.');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch (e) {
      setAuthError('Server logout could not be confirmed. Sign in again before continuing.');
    } finally {
      resetClientSession();
      setCurrentUser(null);
      setCurrentBusiness(null);
      setIsAuthenticated(false);
      setIsRegisterMode(false);
      setAuthPassword('');
      setAlerts([]);setGatewayStatus(null);setShowAlertModal(false);setShowSetup(false);setConnectionIssue(null);setAuthFactor('');
      setActiveTab('overview');
    }
  };

  const handleResetDemo = async () => {
    setIsResetting(true);
    try {
      await api.resetDemo();
      await checkSessionAndLoad();
    } catch (e: any) {
      alert(`Reset failed: ${e.detail || e.message}`);
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

  if(checkingSession||sessionCheckError)return <div className="min-h-screen grid place-items-center p-4"><ScreenState kind={sessionCheckError?'error':'loading'} message={sessionCheckError||'Verifying session…'} retry={sessionCheckError?()=>void checkSessionAndLoad():undefined}/></div>;
  return (
    <div className="oneboard-shell flex h-screen w-screen overflow-hidden bg-[#080d1a] text-slate-100 font-sans">
    {isAuthenticated&&<>
    <a className="oneboard-skip" href="#workspace-main">Skip to workspace content</a>
      {/* Sidebar Navigation */}
      <aside aria-label="Workspace navigation" className="oneboard-sidebar w-64 shrink-0 border-r border-slate-800/80 bg-[#090e1b] flex flex-col justify-between p-4">
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
          <nav aria-label="Workspace sections" className="oneboard-nav space-y-1 overflow-y-auto max-h-[calc(100vh-250px)] pr-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  aria-current={isActive?'page':undefined}
                  onClick={()=>{setConnectionIssue(null);setActiveTab(item.id)}}
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
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-950 text-indigo-200 font-mono">
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Footer info in sidebar with Founder Identity & Logout */}
        <div className="pt-3 border-t border-slate-800/80 text-[11px] text-slate-500 space-y-2 px-2">
          {currentUser && (
            <div className="p-2 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-between">
              <div className="truncate pr-2">
                <span className="block text-slate-200 font-semibold text-[11px] truncate">{currentUser.name}</span>
                <span className="block text-slate-400 text-[10px] truncate">{currentUser.email}</span>
              </div>
              <button
                onClick={handleLogout}
                className="p-1.5 text-slate-400 hover:text-rose-400 rounded-lg hover:bg-slate-800 transition"
                aria-label="Log out and invalidate session" title="Log out and invalidate session"
              >
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
          <div className="flex items-center justify-between font-mono text-[10px]">
            <span>OneBoard OS</span>
            <span className="text-emerald-400 font-bold">Isolated Tenant</span>
          </div>
          <div className="truncate text-slate-500 text-[10px]">
            {currentBusiness?.name || 'Northstar Studio'}
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="oneboard-content flex-1 min-w-0 flex flex-col h-screen overflow-hidden">
        {/* Top Header */}
        <header className="oneboard-header h-16 shrink-0 border-b border-slate-800/80 bg-[#090e1b]/80 backdrop-blur px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider font-mono">
              {currentBusiness?.name || 'Northstar Studio'}
            </span>
            <span className="text-slate-700">•</span>
            <span className="text-xs text-slate-300 font-medium capitalize">
              {navItems.find((n) => n.id === activeTab)?.label}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Ollama Status Pill */}
            <button type="button"
              onClick={() => setActiveTab('settings')}
              className="flex items-center gap-2 px-3 py-1 rounded-full bg-slate-900 border border-slate-800 text-xs font-mono cursor-pointer hover:border-slate-700 transition"
              title="Click to view Ollama Model Gateway Settings"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  gatewayStatus?.status === 'connected' && gatewayStatus?.inference_available ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              ></span>
              <span className="text-slate-300 text-[11px]">
                {gatewayStatus?.status === 'connected' && gatewayStatus?.inference_available
                  ? 'Ollama: Ready'
                  : gatewayStatus?.status === 'connected'
                    ? 'Ollama: No Models'
                    : 'Local Fallback Simulator'}
              </span>
            </button>

            {/* Proactive Alerts Bell */}
            <button
              onClick={() => setShowAlertModal(!showAlertModal)}
              className="relative p-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 hover:text-white transition"
              aria-label="Proactive Scheduler Alerts" title="Proactive Scheduler Alerts"
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
              aria-label="Reset Demo" title="Restore clean Northstar Studio demo scenario (Scoped to Demo Tenant)"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isResetting ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Reset Demo</span>
            </button>

            {/* Logout Header Button */}
            {currentUser && (
              <button
                onClick={handleLogout}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-rose-950/40 text-slate-400 hover:text-rose-400 text-xs font-medium rounded-xl border border-slate-800 transition"
                title="Log out and end session"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Log out</span>
              </button>
            )}
          </div>
        </header>

        {/* Dynamic Tab Body */}
        <main id="workspace-main" tabIndex={-1} aria-label={navItems.find(n=>n.id===activeTab)?.label} className="oneboard-main flex-1 min-w-0 overflow-auto p-6">
    {connectionIssue&&<ScreenState retryLabel="Reload workspace view" kind="error" message={connectionIssue.message+(connectionIssue.write?' Action outcome may be unknown. Check history before retrying; no write was replayed.':' Refresh the view to retry reads.')} retry={connectionIssue.write?undefined:()=>{setConnectionIssue(null);setScreenRevision(n=>n+1)}} dismiss={()=>setConnectionIssue(null)}/>}
    {showSetup&&activeTab==='overview'&&<section className="glass-panel rounded-xl p-4 mb-3 space-y-2" aria-label="Workspace setup"><h2 className="font-bold">Set up your workspace</h2><p>Start with account protection, recorded financial data and your model connection. No sample records or external services are added automatically.</p><div className="flex flex-wrap gap-2">{[['settings','Security and models'],['finance','Record finances'],['integrations','Review integrations']].map(([id,label])=><button key={id} className="btn-primary px-3 py-2" onClick={()=>setActiveTab(id)}>{label}</button>)}<button className="btn-ghost px-3 py-2" onClick={()=>setShowSetup(false)}>Dismiss setup guide</button></div></section>}
          <span className="sr-only" role="status" aria-live="polite">{navItems.find(n=>n.id===activeTab)?.label} workspace view</span>
          <details className="oneboard-help"><summary>Help with {navItems.find(n=>n.id===activeTab)?.label}</summary><p>{screenHelp[activeTab]}</p></details>
    <ScreenBoundary key={activeTab+':'+screenRevision}><Suspense fallback={<ScreenState kind="loading" message="Loading workspace view…"/>}>
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
    </Suspense></ScreenBoundary>
        </main>
      </div>

      </>}
      {/* Proactive Alerts Modal */}
      {isAuthenticated&&showAlertModal && (
        <AlertDialog onClose={()=>setShowAlertModal(false)}>
          <div className="p-6 rounded-2xl bg-slate-900 border border-slate-700 max-w-lg w-full space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-sm font-bold text-white flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Tenant Proactive Alerts ({alerts.length})
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
                <div className="text-slate-400 text-xs text-center py-6">No active business hazards detected for your workspace.</div>
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
        </AlertDialog>
      )}

      {/* Founder Authentication Modal (when session expired or unauthenticated) */}
      {!isAuthenticated && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start sm:items-center justify-center bg-black/85 backdrop-blur-md p-4" role="main" aria-label="Authentication">
          <div className="my-auto p-4 sm:p-8 rounded-3xl bg-slate-900/95 border border-indigo-500/30 max-w-md w-full shadow-2xl space-y-6">
            <div className="text-center space-y-2">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-indigo-600 to-indigo-400 mx-auto flex items-center justify-center shadow-lg shadow-indigo-600/30">
                <Sparkles className="w-6 h-6 text-white" />
              </div>
              <h2 className="text-xl font-bold text-white tracking-tight">
                {isRegisterMode ? 'Create Founder Workspace' : 'Founder Login'}
              </h2>
              <p className="text-xs text-slate-400">
                {isRegisterMode
                  ? 'Set up an isolated enterprise workspace for your Company of One.'
                  : 'Enter your credentials or access the local Northstar Studio demo.'}
              </p>
            </div>

            {authError && (
              <div role="alert" className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{authError}</span>
              </div>
            )}

            <form onSubmit={handleLogin} className="space-y-4">
              {isRegisterMode && (
                <>
                  <div>
                    <label htmlFor="auth-name" className="block text-[11px] font-semibold text-slate-300 mb-1">Your Full Name</label>
                    <div className="relative">
                      <UserCheck className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                      <input
                        type="text"
                        id="auth-name" value={authName}
                        onChange={(e) => setAuthName(e.target.value)}
                        placeholder="e.g. Alex Founder"
                        className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-9 py-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                        required={isRegisterMode}
                      />
                    </div>
                  </div>
                  <div>
                    <label htmlFor="auth-business" className="block text-[11px] font-semibold text-slate-300 mb-1">Workspace / Business Name</label>
                    <div className="relative">
                      <Building className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                      <input
                        type="text"
                        id="auth-business" value={authBizName}
                        onChange={(e) => setAuthBizName(e.target.value)}
                        placeholder="e.g. Apex SaaS Labs"
                        className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-9 py-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                  </div>
                </>
              )}

              <div>
                <label htmlFor="auth-email" className="block text-[11px] font-semibold text-slate-300 mb-1">Founder Email</label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="email"
                    id="auth-email" value={authEmail}
                    onChange={(e) => setAuthEmail(e.target.value)}
                    placeholder="founder@example.com"
                    className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-9 py-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500 font-mono"
                    required
                  />
                </div>
              </div>

              <div>
                <label htmlFor="auth-password" className="block text-[11px] font-semibold text-slate-300 mb-1">Password</label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="password"
                    id="auth-password" value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-9 py-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
              </div>

              {!isRegisterMode && <label className="block text-xs text-slate-300">{recoverMode ? "Recovery code" : "Authenticator or recovery code (if enabled)"}<input aria-label="Authenticator or recovery code" autoComplete="one-time-code" maxLength={64} value={authFactor} onChange={e=>setAuthFactor(e.target.value)} required={recoverMode} className="block w-full rounded-xl bg-slate-950 border border-slate-800 p-2.5 mt-1" /></label>}
              {authMessage && <p role="status" className="text-xs text-emerald-300">{authMessage}</p>}
              <button
                type="submit"
                disabled={authLoading}
                className="w-full py-2.5 px-4 bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 text-white font-semibold text-xs rounded-xl shadow-lg shadow-indigo-600/30 transition flex items-center justify-center gap-2"
              >
                {authLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : recoverMode ? ('Reset password using recovery code') : isRegisterMode ? (
                  'Create Workspace & Sign In'
                ) : (
                  'Sign In to OneBoard'
                )}
              </button>
            </form>

            {!isRegisterMode && <button type="button" onClick={()=>{setRecoverMode(!recoverMode);setAuthFactor('');setAuthPassword('');setAuthError('');}} className="text-xs text-indigo-300">{recoverMode?"Return to sign in":"Recover account with code"}</button>}
            <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
              <button
                onClick={() => {
                  setRecoverMode(false);setAuthFactor('');setIsRegisterMode(!isRegisterMode);
                  setAuthError('');
                }}
                className="text-indigo-400 hover:text-indigo-300 transition"
              >
                {isRegisterMode ? 'Already have an account? Sign In' : "Don't have an account? Register"}
              </button>
              <button
                onClick={() => {
                  setAuthEmail('founder@northstar.studio');
                  setAuthPassword('');
                  setAuthError('Enter the password configured for the local demo account. Demo credentials are not bundled in the browser.');
                  setIsRegisterMode(false);
                }}
                className="text-slate-500 hover:text-slate-300 transition font-mono text-[11px]"
              >
                Use Demo Email
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
