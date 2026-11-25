import React,{useState,useEffect} from 'react';
import {api} from '../services/api';

export function AccountSecurityPanel(){
 const [status,setStatus]=useState<any>(null),[password,setPassword]=useState(''),[factor,setFactor]=useState(''),[secret,setSecret]=useState(''),[codes,setCodes]=useState<string[]>([]),[key,setKey]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[sessions,setSessions]=useState<any[]>([]),[members,setMembers]=useState<any[]>([]),[email,setEmail]=useState(''),[name,setName]=useState(''),[role,setRole]=useState('member'),[write,setWrite]=useState(false),[days,setDays]=useState(30);
 const refresh=async()=>{setStatus(await api.securityStatus());setSessions(await api.securityList('/sessions'));try{setMembers(await api.securityList('/members'));}catch{setMembers([]);}};
 useEffect(()=>{refresh().catch(e=>setError(e.message));},[]);
 const action=async(path:string,payload:Record<string,unknown>={},method='POST')=>{
  setBusy(true);setError('');setMessage('');setKey('');setCodes([]);
  try{const result=await api.securityAction(path,payload,method);
    if(result.secret)setSecret(result.secret);
    if(result.recovery_codes){setCodes(result.recovery_codes);setSecret('');}
    if(result.api_key)setKey(result.api_key);
    if(result.activation_recovery_code)setCodes([result.activation_recovery_code]);
    setMessage(result.status==='staged_no_delivery'?'Email verification staged; no email was sent.':'Security operation completed.');
    setPassword('');setFactor('');
    if(path==='/sessions/revoke-all'){await api.logout().catch(()=>{});window.location.reload();return;}
    await refresh();
  }catch(e:any){setError(e.message||'Operation failed');}finally{setBusy(false);}
 };
 const reauth=()=>({password,mfa_code:factor||undefined});
 const cls="rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-xs";
 const btn="rounded-lg bg-indigo-700 px-3 py-2 disabled:opacity-40 text-xs";
 return <section className="glass-panel rounded-2xl p-6 space-y-3 text-xs">
  <h2 className="text-sm font-bold">Account security</h2>
  <p>MFA: {status?.mfa_enabled?'Enabled':'Not enabled'} · Email: {status?.email_verified?'Verified':'Unverified'} · Recovery codes remaining: {status?.recovery_codes_remaining??0}</p>
  <p className="text-slate-400">Sensitive actions require your password and, when enabled, a fresh authenticator or recovery code. Never share these values. Email delivery is not configured.</p>
  <div className="flex flex-wrap gap-2"><input className={cls} type="password" aria-label="Security password" autoComplete="current-password" placeholder="Current password" value={password} onChange={e=>setPassword(e.target.value)}/><input className={cls} aria-label="Security verification code" autoComplete="one-time-code" placeholder="Verification code" value={factor} onChange={e=>setFactor(e.target.value)}/></div>
  <div className="flex flex-wrap gap-2">
   {!status?.mfa_enabled?<><button className={btn} disabled={busy||!password} onClick={()=>action('/mfa/start',reauth())}>Start MFA setup</button>{secret&&<button className={btn} disabled={busy||!factor} onClick={()=>action('/mfa/confirm',{code:factor})}>Confirm MFA</button>}</>:<button className={btn} disabled={busy||!password||!factor} onClick={()=>action('/mfa/disable',reauth())}>Disable MFA</button>}
   <button className={btn} disabled={busy||!password} onClick={()=>action('/recovery-codes',reauth())}>Rotate recovery codes</button>
   <button className={btn} disabled={busy||!password} onClick={()=>action('/email/stage',reauth())}>Stage email verification</button>
   <button className={btn} disabled={busy||!factor} onClick={()=>action('/email/verify',{code:factor})}>Verify email code</button>
  </div>
  {secret&&<p className="break-all">Enter this setup key in your authenticator app: <code>{secret}</code></p>}
  {codes.length>0&&<div className="bg-slate-900 p-3 break-all"><p>Store these one-time codes securely. They will not be shown again.</p>{codes.map(c=><p key={c}><code>{c}</code></p>)}<button onClick={()=>setCodes([])}>Hide codes</button></div>}
  <h3 className="font-bold">Scoped API key</h3>
  <div className="flex gap-2 flex-wrap items-center"><label><input type="checkbox" checked={write} onChange={e=>setWrite(e.target.checked)}/> Allow writes</label><label> Expiry days <input aria-label="API key expiry days" className={cls} type="number" min={1} max={90} value={days} onChange={e=>setDays(Number(e.target.value))}/></label><button className={btn} disabled={busy||!password||days<1||days>90} onClick={()=>action('/api-key',{...reauth(),scopes:write?['read','write']:['read'],expires_days:days})}>Rotate scoped key</button><button className={btn} disabled={busy||!password} onClick={()=>action('/api-key/revoke',reauth())}>Revoke key</button></div>
  {key&&<p className="break-all">Copy now: <code>{key}</code> <button onClick={()=>setKey('')}>Hide key</button></p>}
  <h3 className="font-bold">Active sessions ({sessions.length})</h3>
  {sessions.map(s=><div key={s.id} className="flex gap-2 items-center"><span>Expires {s.expires_at}</span><button className={btn} disabled={busy||!password} onClick={()=>action('/sessions/'+s.id+'/revoke',reauth())}>Revoke session</button></div>)}
  <button className={btn} disabled={busy||!password} onClick={()=>action('/sessions/revoke-all',reauth())}>Revoke all sessions</button>
  {members.length>0&&<><h3 className="font-bold">Workspace members</h3>{members.map(m=><div key={m.id} className="flex flex-wrap gap-2 items-center"><span>{m.email} · {m.role} · {m.active?'Active':'Revoked'}</span><button className={btn} disabled={busy||!password||!m.active||m.role==='owner'} onClick={()=>action('/members/'+m.id+'/role',{...reauth(),role:m.role==='member'?'founder':'member'},'PUT')}>Change role</button><button className={btn} disabled={busy||!password||!m.active||m.role==='owner'} onClick={()=>action('/members/'+m.id+'/revoke',reauth())}>Revoke member</button></div>)}<div className="flex flex-wrap gap-2"><input className={cls} aria-label="Member name" value={name} onChange={e=>setName(e.target.value)} placeholder="Name"/><input className={cls} aria-label="Member email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email"/><select className={cls} aria-label="Member role" value={role} onChange={e=>setRole(e.target.value)}><option>member</option><option>founder</option></select><button className={btn} disabled={busy||!password||!email||!name} onClick={()=>action('/members',{...reauth(),email,name,role})}>Create member activation code</button></div></>}
  {message&&<p role="status" className="text-emerald-300">{message}</p>}{error&&<p role="alert" className="text-rose-300">{error}</p>}
 </section>;
}
