// The admin panel (v0.2 P5): who has logged in, when, and how much each has done. The admin creates every login here
// (there is no signup), sets its spend cap, disables it, resets its password. The admin sees counts, never the
// workspaces themselves: every figure is a count over the store.
import { BertNote } from '../design/Bert'
import { DeleteWorkspace, type Doomed } from './DeleteWorkspace'
import React, { useEffect, useState } from 'react'
import { api, ago, fmtUsd, json } from '../api'
import { useApp } from '../App'
import { Sec } from './Answer'

type Row = { id: string; email: string; name: string; role: string; disabled: boolean; created: string; last_seen: string | null; spend_cap_usd: number | null; sign_ins: number; workspaces: number
  uploads: number; documents: number; chats: number; questions: number; last_question: string | null; cost_usd: number; metered_usd: number; over_cap: boolean }
const usd = (n?: number | null) => n ? fmtUsd(n) : '$0'
type Panel = { users: Row[]; default_cap_usd: number | null; totals: { logins: number; questions: number; cost_usd: number; metered_usd: number; workspaces: number }; note: string }

type WsRow = { id: string; name: string; created: string; archived: boolean; members: string[]; models: number; documents: number; chats: number; notes: number }

export function AdminPage() {
  const { me, toast, reloadEstates } = useApp()
  const [p, setP] = useState<Panel | null>(null)
  const [f, setF] = useState({ username: '', name: '', cap: '', demo: true })
  const [made, setMade] = useState<{ username: string; password: string; what: string } | null>(null)
  const [wss, setWss] = useState<WsRow[]>([])
  const [doomed, setDoomed] = useState<Doomed | null>(null)
  const load = () => { api<{ workspaces: WsRow[] }>('/api/admin/workspaces').then(r => setWss(r.workspaces)).catch(() => {}); return api<Panel>('/api/admin/users').then(setP).catch(e => toast(e.message)) }
  useEffect(() => { load() }, [])
  if (me?.user?.role !== 'owner') return <div className="ds-col"><p className="ds-gap">The admin panel is for the admin of this instance.</p></div>
  if (!p) return <div className="ds-col dim">Reading the logins…</div>

  async function create() {
    try {
      const r = await api<{ user: Row; password: string }>('/api/admin/users', json('POST', { username: f.username, name: f.name, demo: f.demo, ...(f.cap.trim() ? { cap_usd: Number(f.cap) } : {}) }))
      setMade({ username: r.user.email, password: r.password, what: 'created' }); setF({ username: '', name: '', cap: '', demo: true }); load()
    } catch (e: any) { toast(e.message) }
  }
  async function patch(u: Row, body: any, what?: string) {
    try {
      const r = await api<{ user: Row; password?: string }>('/api/admin/users/' + u.id, json('PATCH', body))
      if (r.password) setMade({ username: u.email, password: r.password, what: what || 'reset' })
      load()
    } catch (e: any) { toast(e.message) }
  }
  function cap(u: Row) {
    const v = prompt(`Spend cap for ${u.email}, in US dollars at list price.\nLeave empty for no cap.`, u.spend_cap_usd == null ? '' : String(u.spend_cap_usd))
    if (v === null) return
    if (v.trim() && !(Number(v) >= 0)) { toast('A cap is a number, or empty for none.'); return }
    patch(u, { cap_usd: v.trim() ? Number(v) : null })
  }
  const t = p.totals, maxQ = Math.max(1, ...p.users.map(u => u.questions))
  return (
    <div className="ds-col xwide">
      <div className="ds-kick"><span className="type">Admin</span><span className="k">· who has logged in, and how much each has done</span></div>
      <h1 className="ds-q">Logins</h1>
      <div className="ds-tiles"><div><div className="v">{t.logins}</div><div className="l">logins</div></div><div><div className="v">{t.workspaces}</div><div className="l">workspaces</div></div><div><div className="v">{t.questions}</div><div className="l">questions asked</div></div><div><div className="v">{usd(t.metered_usd)}</div><div className="l">metered at list price</div></div><div><div className="v">{usd(t.cost_usd)}</div><div className="l">billed</div></div></div>
      <div className="ds-fig"><div className="fb" style={{ overflowX: 'auto' }}>
        <table className="ds-admin"><thead><tr><th>Login</th><th>Last seen</th><th className="num">Sign-ins</th><th className="num">Workspaces</th><th className="num">Uploads</th><th className="num">Documents</th><th className="num">Questions</th><th className="num">Metered</th><th className="num">Cap</th><th title="What each login has chosen to send to the tracer. Each login sets its own, in its own Settings.">Tracing</th><th></th></tr></thead>
          <tbody>{p.users.map(u => <tr key={u.id} className={u.disabled ? 'off' : ''}>
            <td><div>{u.name} {u.role === 'owner' && <span className="ds-tag ok">admin</span>} {u.disabled && <span className="ds-tag mock" style={{ borderStyle: 'solid' }}>disabled</span>}</div><div className="mono dim" style={{ fontSize: 11 }}>{u.email}</div></td>
            <td className="dim">{u.last_seen ? ago(u.last_seen) : 'never'}</td><td className="num">{u.sign_ins}</td><td className="num">{u.workspaces}</td><td className="num">{u.uploads}</td><td className="num">{u.documents}</td>
            <td className="num barcell">{u.questions}<i style={{ width: 100 * u.questions / maxQ + '%' }} /></td>
            <td className="num" style={u.over_cap ? { color: 'var(--amber)' } : undefined}>{usd(u.metered_usd)}</td>
            <td className="num">{u.spend_cap_usd == null ? <span className="dim">none</span> : <span style={u.over_cap ? { color: 'var(--amber)' } : undefined}>{fmtUsd(u.spend_cap_usd)}{u.over_cap ? ' · reached' : ''}</span>}</td>
            <td className="dim" style={{ fontSize: 12 }}>{({ off: 'off', structure: 'structure', content: 'full' } as any)[(u as any).trace_level] || '—'}</td>
            <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}><button className="ds-btn" onClick={() => cap(u)}>Cap</button>
              {u.id !== me.user?.id && <> <button className="ds-btn" onClick={() => { if (confirm(`Give ${u.email} a new password? Every session of that login signs out.`)) patch(u, { reset_password: true }, 'reset') }}>Reset password</button> <button className="ds-btn" onClick={() => patch(u, { disabled: !u.disabled })}>{u.disabled ? 'Enable' : 'Disable'}</button></>}</td>
          </tr>)}</tbody></table></div>
        <div className="cap">Metered is what each login's tokens cost at list price; the cap counts it, even where the model route is flat-rate and nothing is billed. Uploads are sets of model exports. The admin sees these counts, never a login's workspaces. Tracing is what each login chose for its own questions: it is shown here and cannot be set here.</div></div>
      {p.users.length <= 1 && <BertNote state="information" place="admin-no-logins" title="No other logins yet" size={56}>You are the only one here. Create a login below and hand over its username and password.</BertNote>}
      {made && <div className="ds-none" style={{ margin: '14px 0', borderColor: 'rgba(52,211,153,.5)' }}><div className="h" style={{ color: 'var(--accent)' }}>Login {made.what}: hand these over</div>
        <div style={{ fontSize: 14 }}>Username <span className="mono" style={{ color: 'var(--ink)' }}>{made.username}</span> · password <span className="mono" style={{ color: 'var(--ink)' }}>{made.password}</span> <button className="ds-btn" onClick={() => { navigator.clipboard?.writeText(`${made.username} / ${made.password}`); toast('Copied.') }}>Copy</button> <button className="ds-btn" onClick={() => setMade(null)}>Done</button>
          <div className="dim" style={{ fontSize: 12.5, marginTop: 4 }}>The password is shown once and is not kept in a readable form. They can change it in Settings.</div></div></div>}
      <Sec k="Workspaces" ct={`${wss.length} on this instance`} />
      <div className="ds-fig"><div className="fb" style={{ overflowX: 'auto' }}>
        <table className="ds-admin"><thead><tr><th>Workspace</th><th>Members</th><th className="num">Models</th><th className="num">Documents</th><th className="num">Chats</th><th className="num">Notes</th><th>Created</th><th></th></tr></thead>
          <tbody>{wss.map(w => <tr key={w.id} className={w.archived ? 'off' : ''}>
            <td>{w.name} {w.archived && <span className="ds-tag mock" style={{ borderStyle: 'solid' }}>archived</span>}</td><td className="mono dim" style={{ fontSize: 11.5 }}>{w.members.join(', ') || 'nobody'}</td>
            <td className="num">{w.models}</td><td className="num">{w.documents}</td><td className="num">{w.chats}</td><td className="num">{w.notes}</td><td className="dim">{w.created.slice(0, 10)}</td>
            <td style={{ textAlign: 'right' }}><button className="ds-btn" onClick={() => setDoomed({ id: w.id, name: w.name, models: w.models, documents: w.documents, chats: w.chats, notes: w.notes })}>Delete</button></td></tr>)}</tbody></table></div>
        <div className="cap">The admin sees each workspace's name, its members and these counts, and can delete it. Nothing inside a workspace opens for anyone but its members.</div></div>
      {wss.length === 0 && <BertNote state="information" place="admin-no-workspaces" title="No workspaces on this instance yet" size={56}>A workspace appears here when a login creates one or loads the demo.</BertNote>}
      {doomed && <DeleteWorkspace ws={doomed} onClose={() => setDoomed(null)} onDone={async () => { setDoomed(null); toast('Workspace deleted.'); await reloadEstates(); load() }} toast={toast} />}
      <Sec k="Create a login" ct="there is no signup" />
      <div className="ds-list"><div className="r" style={{ alignItems: 'center', gap: 10 }}>
        <input className="ds-in" placeholder="Username (a name or an email)" value={f.username} onChange={e => setF({ ...f, username: e.target.value })} />
        <input className="ds-in" placeholder="Their name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
        <input className="ds-in" style={{ maxWidth: 150 }} placeholder={`Cap, default $${p.default_cap_usd ?? 'none'}`} value={f.cap} onChange={e => setF({ ...f, cap: e.target.value })} />
        <label className="dim" style={{ fontSize: 12.5, display: 'flex', gap: 6, alignItems: 'center', whiteSpace: 'nowrap' }}><input type="checkbox" checked={f.demo} onChange={e => setF({ ...f, demo: e.target.checked })} />with the demo workspaces</label>
        <button className="ds-btn go" disabled={f.username.trim().length < 3} onClick={create}>Create</button></div></div>
    </div>
  )
}
