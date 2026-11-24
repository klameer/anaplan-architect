// The admin panel (v0.2 P5): who has logged in, when, and how much each has done. The admin creates every login here
// (there is no signup), sets its spend cap, disables it, resets its password. The admin sees counts, never the
// workspaces themselves: every figure is a count over the store.
// Teams (security review 2026-11-24): a login's team is picked from the list; a new team is its own action, so a typo
// or a look-alike name never makes a company. An admin is in no team. The admin never shares a workspace: it makes one
// private again, or names the maker of a shared one whose maker has left its team.
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

type WsRow = { id: string; name: string; created: string; archived: boolean; visibility?: string; team?: string | null; creator?: string | null; members: string[]; models: number; documents: number; chats: number; notes: number }

export function AdminPage() {
  const { me, toast, reloadEstates } = useApp()
  const [p, setP] = useState<Panel | null>(null)
  const [f, setF] = useState({ username: '', name: '', cap: '', demo: true, team: '' })
  const [made, setMade] = useState<{ username: string; password: string; what: string } | null>(null)
  const [wss, setWss] = useState<WsRow[]>([])
  const [teams, setTeams] = useState<{ id: string; name: string; logins: number; workspaces: number }[]>([])
  const [newTeam, setNewTeam] = useState('')
  const [doomed, setDoomed] = useState<Doomed | null>(null)
  const load = () => { api<{ workspaces: WsRow[] }>('/api/admin/workspaces').then(r => setWss(r.workspaces)).catch(() => {}); api<{ teams: any[] }>('/api/admin/teams').then(r => setTeams(r.teams)).catch(() => {}); return api<Panel>('/api/admin/users').then(setP).catch(e => toast(e.message)) }
  useEffect(() => { load() }, [])
  if (me?.user?.role !== 'owner') return <div className="ds-col"><p className="ds-gap">The admin panel is for the admin of this instance.</p></div>
  if (!p) return <div className="ds-col dim">Reading the logins…</div>

  async function create() {
    try {
      const r = await api<{ user: Row; password: string }>('/api/admin/users', json('POST', { username: f.username, name: f.name, demo: f.demo, ...(f.team.trim() ? { team: f.team.trim() } : {}), ...(f.cap.trim() ? { cap_usd: Number(f.cap) } : {}) }))
      setMade({ username: r.user.email, password: r.password, what: 'created' }); setF({ username: '', name: '', cap: '', demo: true, team: f.team }); load()
    } catch (e: any) { toast(e.message) }
  }
  async function patch(u: Row, body: any, what?: string) {
    try {
      const r = await api<{ user: Row; password?: string }>('/api/admin/users/' + u.id, json('PATCH', body))
      if (r.password) setMade({ username: u.email, password: r.password, what: what || 'reset' })
      load()
    } catch (e: any) { toast(e.message) }
  }
  function team(u: Row, to: string) {
    const was = (u as any).team || ''
    if (to === was) return
    const made = wss.filter(w => w.visibility === 'shared' && w.team === was && w.creator === u.name).length
    if (was && !confirm(`${u.name} loses every workspace shared with ${was}, at once. What they added there stays with ${was}.` + (made ? `\n\n${u.name} made ${made} of them. ${made === 1 ? 'It stays' : 'They stay'} with ${was} and ${made === 1 ? 'has' : 'have'} no maker until you name one, below.` : '') + '\n\nGo on?')) return
    patch(u, { team: to || null })
  }
  async function addTeam() {
    const make = (confirm_: boolean) => api<{ name: string }>('/api/admin/teams', json('POST', { name: newTeam, ...(confirm_ ? { confirm: true } : {}) }))
    try {
      let t
      try { t = await make(false) }
      catch (e: any) {                                  // reads like a team that is already here: asked, not refused
        if (e.status !== 409 || !e.detail?.confusable) throw e
        if (!confirm(`${e.detail.message}.\n\nMake "${newTeam.trim()}" as a separate team from ${e.detail.confusable}?`)) return
        t = await make(true)
      }
      toast(`Team ${t.name} made.`); setNewTeam(''); load()
    } catch (e: any) { toast(e.detail?.message || e.message) }
  }
  async function makePrivate(w: WsRow) {
    if (!confirm(`Make "${w.name}" private?\n\nEveryone in ${w.team} except ${w.creator} loses it at once. What they added stays in it.`)) return
    try { await api('/api/admin/workspaces/' + w.id, json('PATCH', { visibility: 'private' })); toast('Private again.'); load() } catch (e: any) { toast(e.message) }
  }
  async function allowSharing(w: WsRow) {
    if (!confirm(`Allow "${w.name}" to be shared with a team?\n\nIt cannot be now because ${(w as any).share_locked}. Everything in it is under ${w.creator || 'its maker'}'s name, whoever wrote it first. If you allow it, ${w.creator || 'its maker'} can share all of it with the team they are in today.`)) return
    try { await api('/api/admin/workspaces/' + w.id, json('PATCH', { allow_sharing: true })); toast('It can be shared now.'); load() } catch (e: any) { toast(e.message) }
  }
  async function nameMaker(w: WsRow, uid: string) {
    const u = p?.users.find(x => x.id === uid)
    if (!u || !confirm(`Make ${u.name} the maker of "${w.name}"?\n\nThe maker can rename it, make it private, take a backup and delete it.`)) return
    try { await api('/api/admin/workspaces/' + w.id, json('PATCH', { maker: uid })); toast(`${u.name} is its maker now.`); load() } catch (e: any) { toast(e.message) }
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
      <div className="ds-tiles"><div><div className="v">{t.logins}</div><div className="l">logins</div></div><div><div className="v">{t.workspaces}</div><div className="l">workspaces</div></div><div><div className="v">{t.questions}</div><div className="l">questions asked</div></div><div><div className="v">{usd(t.metered_usd)}</div><div className="l">metered at list price</div></div><div><div className="v">{(p as any).billed_known === false ? 'unknown' : usd(t.cost_usd)}</div><div className="l">billed</div></div></div>
      {(p as any).billed_known === false && <p className="ds-gap" data-price-unknown="1">{p.note}</p>}
      <div className="ds-fig"><div className="fb" style={{ overflowX: 'auto' }}>
        <table className="ds-admin"><thead><tr><th>Login</th><th title="The company a login belongs to. Logins in one team can open the workspaces shared with it.">Team</th><th>Last seen</th><th className="num">Sign-ins</th><th className="num">Workspaces</th><th className="num">Uploads</th><th className="num">Documents</th><th className="num">Questions</th><th className="num">Metered</th><th className="num">Cap</th><th title="What each login has chosen to send to the tracer. Each login sets its own, in its own Settings.">Tracing</th><th></th></tr></thead>
          <tbody>{p.users.map(u => <tr key={u.id} className={u.disabled ? 'off' : ''}>
            <td><div>{u.name} {u.role === 'owner' && <span className="ds-tag ok">admin</span>} {u.disabled && <span className="ds-tag mock" style={{ borderStyle: 'solid' }}>disabled</span>}</div><div className="mono dim" style={{ fontSize: 11 }}>{u.email}</div></td>
            <td data-team={(u as any).team || ''}>{u.role === 'owner' ? <span className="dim" title="An admin is in no team: a team's shared workspaces are its members' to read.">none: admin</span>
              : <select className="ds-in" style={{ maxWidth: 170, padding: '3px 6px' }} aria-label={`Team of ${u.email}`} value={(u as any).team || ''} onChange={e => team(u, e.target.value)}><option value="">none</option>{teams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select>}</td>
            <td className="dim">{u.last_seen ? ago(u.last_seen) : 'never'}</td><td className="num">{u.sign_ins}</td><td className="num">{u.workspaces}</td><td className="num">{u.uploads}</td><td className="num">{u.documents}</td>
            <td className="num barcell">{u.questions}<i style={{ width: 100 * u.questions / maxQ + '%' }} /></td>
            <td className="num" style={u.over_cap ? { color: 'var(--amber)' } : undefined}>{usd(u.metered_usd)}</td>
            <td className="num">{u.spend_cap_usd == null ? <span className="dim">none</span> : <span style={u.over_cap ? { color: 'var(--amber)' } : undefined}>{fmtUsd(u.spend_cap_usd)}{u.over_cap ? ' · reached' : ''}</span>}</td>
            <td className="dim" style={{ fontSize: 12 }}>{({ off: 'off', structure: 'structure', content: 'full' } as any)[(u as any).trace_level] || '—'}</td>
            <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}><button className="ds-btn" onClick={() => cap(u)}>Cap</button>
              {u.id !== me.user?.id && <> <button className="ds-btn" onClick={() => { if (confirm(`Give ${u.email} a new password? Every session of that login signs out.`)) patch(u, { reset_password: true }, 'reset') }}>Reset password</button> <button className="ds-btn" onClick={() => patch(u, { disabled: !u.disabled })}>{u.disabled ? 'Enable' : 'Disable'}</button></>}</td>
          </tr>)}</tbody></table></div>
        <div className="cap">Metered is what each login's tokens cost at list price; the cap counts it, even where the model route is flat-rate and nothing is billed. Uploads are sets of model exports. The admin sees these counts, never a login's workspaces. A team is a company: logins in one team can open the workspaces shared with it, and nobody else can, the admin included. Tracing is what each login chose for its own questions: it is shown here and cannot be set here.</div></div>
      {p.users.length <= 1 && <BertNote state="information" place="admin-no-logins" title="No other logins yet" size={56}>You are the only one here. Create a login below and hand over its username and password.</BertNote>}
      {made && <div className="ds-none" style={{ margin: '14px 0', borderColor: 'rgba(52,211,153,.5)' }}><div className="h" style={{ color: 'var(--accent)' }}>Login {made.what}: hand these over</div>
        <div style={{ fontSize: 14 }}>Username <span className="mono" style={{ color: 'var(--ink)' }}>{made.username}</span> · password <span className="mono" style={{ color: 'var(--ink)' }}>{made.password}</span> <button className="ds-btn" onClick={() => { navigator.clipboard?.writeText(`${made.username} / ${made.password}`); toast('Copied.') }}>Copy</button> <button className="ds-btn" onClick={() => setMade(null)}>Done</button>
          <div className="dim" style={{ fontSize: 12.5, marginTop: 4 }}>The password is shown once and is not kept in a readable form. They can change it in Settings.</div></div></div>}
      <Sec k="Workspaces" ct={`${wss.length} on this instance`} />
      <div className="ds-fig"><div className="fb" style={{ overflowX: 'auto' }}>
        <table className="ds-admin"><thead><tr><th>Workspace</th><th>Who can open it</th><th>Members</th><th className="num">Models</th><th className="num">Documents</th><th className="num">Chats</th><th className="num">Notes</th><th>Created</th><th></th></tr></thead>
          <tbody>{wss.map(w => <tr key={w.id} className={w.archived ? 'off' : ''}>
            <td>{w.name} {w.archived && <span className="ds-tag mock" style={{ borderStyle: 'solid' }}>archived</span>}</td><td data-ws-access={w.visibility}>{w.visibility === 'shared' ? <><span className="ds-tag sky">shared · {w.team}</span> {w.creator
              ? <button className="ds-btn" onClick={() => makePrivate(w)}>Make private</button>
              : <select className="ds-in" style={{ maxWidth: 190, padding: '3px 6px' }} aria-label={`Name a maker for ${w.name}`} data-no-maker="1" value="" onChange={e => e.target.value && nameMaker(w, e.target.value)}><option value="">no maker: name one…</option>{p.users.filter(u => (u as any).team === w.team && !u.disabled && u.role !== 'owner').map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select>}</> : <><span className="ds-tag">private</span>{(w as any).share_locked && <> <span className="ds-tag mock" style={{ borderStyle: 'solid' }} title={(w as any).share_locked}>cannot be shared</span> <button className="ds-btn" data-allow-sharing="1" onClick={() => allowSharing(w)}>Allow sharing</button></>}</>}</td><td className="mono dim" style={{ fontSize: 11.5 }}>{w.members.join(', ') || 'nobody'}</td>
            <td className="num">{w.models}</td><td className="num">{w.documents}</td><td className="num">{w.chats}</td><td className="num">{w.notes}</td><td className="dim">{w.created.slice(0, 10)}</td>
            <td style={{ textAlign: 'right' }}><button className="ds-btn" onClick={() => setDoomed({ id: w.id, name: w.name, models: w.models, documents: w.documents, chats: w.chats, notes: w.notes })}>Delete</button></td></tr>)}</tbody></table></div>
        <div className="cap">The admin sees each workspace's name, its members and these counts, and can delete it. Nothing inside a workspace opens for anyone but its members. Only its maker shares a workspace. A shared workspace stays with its team when its maker leaves the team: it has no maker until you name a team-mate.</div></div>
      {wss.length === 0 && <BertNote state="information" place="admin-no-workspaces" title="No workspaces on this instance yet" size={56}>A workspace appears here when a login creates one or loads the demo.</BertNote>}
      {doomed && <DeleteWorkspace ws={doomed} onClose={() => setDoomed(null)} onDone={async () => { setDoomed(null); toast('Workspace deleted.'); await reloadEstates(); load() }} toast={toast} />}
      <Sec k="Create a login" ct="there is no signup" />
      <div className="ds-list"><div className="r" style={{ alignItems: 'center', gap: 10 }}>
        <input className="ds-in" placeholder="Username (a name or an email)" value={f.username} onChange={e => setF({ ...f, username: e.target.value })} />
        <input className="ds-in" placeholder="Their name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
        <select className="ds-in" style={{ maxWidth: 170 }} aria-label="Team (their company)" value={f.team} onChange={e => setF({ ...f, team: e.target.value })}><option value="">No team</option>{teams.map(t => <option key={t.id} value={t.name}>{t.name}</option>)}</select>
        <input className="ds-in" style={{ maxWidth: 150 }} placeholder={`Cap, default $${p.default_cap_usd ?? 'none'}`} value={f.cap} onChange={e => setF({ ...f, cap: e.target.value })} />
        <label className="dim" style={{ fontSize: 12.5, display: 'flex', gap: 6, alignItems: 'center', whiteSpace: 'nowrap' }}><input type="checkbox" checked={f.demo} onChange={e => setF({ ...f, demo: e.target.checked })} />with the demo workspaces</label>
        <button className="ds-btn go" disabled={f.username.trim().length < 3} onClick={create}>Create</button></div></div>
      <Sec k="Teams" ct={`${teams.length} compan${teams.length === 1 ? 'y' : 'ies'}`} />
      <div className="ds-list">{teams.map(t => <div className="r" key={t.id} data-team-row={t.name}><span style={{ width: 220, flex: 'none' }}>{t.name}</span><span className="grow dim" style={{ fontSize: 12.5 }}>{t.logins} login{t.logins === 1 ? '' : 's'} · {t.workspaces} shared workspace{t.workspaces === 1 ? '' : 's'}</span></div>)}
        <div className="r" style={{ alignItems: 'center', gap: 10 }}>
          <input className="ds-in" style={{ maxWidth: 260 }} placeholder="A new team: the company's name" value={newTeam} onChange={e => setNewTeam(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && newTeam.trim()) addTeam() }} />
          <button className="ds-btn" disabled={!newTeam.trim()} onClick={addTeam}>New team</button>
          <span className="dim" style={{ fontSize: 12.5 }}>A team is made here, once, and then picked from the list on a login. A name that reads as one already here is refused.</span></div></div>
    </div>
  )
}
