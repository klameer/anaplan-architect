import React, { useState } from 'react'
import { api, ago, plain } from '../api'
import { href, useApp, type View } from '../App'

const NAV: [View, string, string][] = [
  ['home', 'Home', 'M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z'],
  ['chats', 'Chats', 'M4 5h16v11H8l-4 4z'],
  ['notes', 'Notes', 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h6'],
  ['dependencies', 'Dependencies', 'M5 6h4v4H5zM15 14h4v4h-4zM9 8h4M13 8v8h2'],
  ['plan', 'Action plan', 'M5 6h14M5 12h14M5 18h9M4 6l1 1 2-2'],
  ['size', 'Size', 'M4 20V4M4 20h16M7 16l4-5 3 3 6-8'],
]

const Icon = ({ d }: { d: string }) => <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>

export function Sidebar() {
  const { estates, route, summary, me, go, refresh, reloadMe, toast } = useApp()
  const [q, setQ] = useState('')
  const eid = route.eid
  const convs = (summary?.conversations || []).slice().reverse().filter(c => !q || plain(c.title).toLowerCase().includes(q.toLowerCase()))

  /** A blank conversation page with the composer; the conversation is created when the first question is sent. */
  function newChat() {
    if (!eid || !summary) { toast('Pick an estate first.'); return }
    if (!summary.snapshot) { toast('Activate a snapshot first.'); return }
    if (!summary.llm) { toast('No model is set up on the server. Copy .env.example to .env, fill in one block, and restart.'); return }
    go(href(eid, 'chat', 'new'))
  }
  async function del(id: string, title: string) {
    if (!confirm(`Delete this conversation?\n\n${plain(title)}\n\nThe transcript moves to the estate's deleted folder; it will not be listed or read again.`)) return
    try { await api('/api/conversations/' + id, { method: 'DELETE' }); if (route.cid === id) go(href(eid!, 'home')); await refresh() } catch (e: any) { toast(e.message) }
  }
  async function signOut() { try { await api('/api/auth/logout', { method: 'POST' }); await reloadMe() } catch (e: any) { toast(e.message) } }

  return (
    <aside className="side">
      <div className="brand">
        <svg viewBox="0 0 100 100" aria-hidden="true"><path d="M50 2 98 50 50 98 2 50z" fill="#10b981" /><rect x="33" y="33" width="34" height="34" rx="4" fill="#0a0a0c" /><circle cx="43" cy="46" r="3.5" fill="#10b981" /><circle cx="57" cy="46" r="3.5" fill="#10b981" /><rect x="41" y="56" width="18" height="2.5" fill="#10b981" /><rect x="41" y="60.5" width="18" height="2.5" fill="#10b981" /></svg>
        <div><div className="wm"><b>/</b>architect</div><div className="by">by CodelessOps</div></div>
      </div>

      <label className="kicker" htmlFor="estate-pick">Estate</label>
      <select id="estate-pick" value={eid || ''} onChange={e => go(e.target.value ? href(e.target.value, 'home') : '#/new')}>
        {!eid && <option value="">Choose an estate…</option>}
        {estates.filter(e => !e.archived).map(e => <option key={e.id} value={e.id}>{e.name}{e.snapshot ? '' : ' (no snapshot)'}</option>)}
        {estates.some(e => e.archived) && <optgroup label="Archived">{estates.filter(e => e.archived).map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</optgroup>}
        <option value="">+ New estate</option>
      </select>

      <nav className="nav">
        {NAV.map(([v, label, d]) => <a key={v} href={eid ? href(eid, v) : '#/new'} className={(route.view === v || (v === 'chats' && route.view === 'chat')) && eid ? 'on' : ''}><Icon d={d} />{label}{v === 'notes' && (summary?.notes_flagged || 0) > 0 && <span className="pill amber" style={{ marginLeft: 'auto' }} title="Notes whose cited evidence moved since the snapshot changed">{summary!.notes_flagged}</span>}</a>)}
        <a href="#/settings" className={route.view === 'settings' ? 'on' : ''}><Icon d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4" />Settings</a>
        <a href="#/design" title="The v0.2 design sheet: the restyled shell and one answer pattern per question type (docs/DESIGN.md)"><Icon d="M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z" />Design sheet<span className="pill dim" style={{ marginLeft: 'auto' }}>v0.2</span></a>
      </nav>

      <div className="rule" />
      <button className="newchat" onClick={newChat}><Icon d="M4 5h16v11H8l-4 4zM12 8v5M9.5 10.5h5" />New chat</button>
      <input placeholder="Search threads…" value={q} onChange={e => setQ(e.target.value)} />
      <div className="threads">
        {!eid && <div className="small muted">Pick an estate.</div>}
        {eid && !convs.length && <div className="small muted">{q ? 'No match.' : 'No conversations yet.'}</div>}
        {convs.map(c => (
          <div key={c.id} className={'thread' + (route.cid === c.id ? ' active' : '')} onClick={() => go(href(eid!, 'chat', c.id))} title={plain(c.title)}>
            <div className="t">{plain(c.title)}</div>
            <div className="s">{c.turns} turn{c.turns !== 1 ? 's' : ''} · {ago(c.created)}</div>
            <button className="x" title="Delete this conversation" onClick={e => { e.stopPropagation(); del(c.id, c.title) }}>×</button>
          </div>
        ))}
      </div>

      <div className="who">
        <span className="avatar">{(me?.user?.name || 'L').slice(0, 1).toUpperCase()}</span>
        <div className="grow">
          <div className="t">{me?.user ? me.user.name : 'Local'}</div>
          <div className="s">{me?.user ? me.user.role : 'no accounts · localhost'}{summary ? ` · ${summary.llm ? summary.provider : 'no model set up'}` : ''}</div>
        </div>
        {me?.user && <button className="quiet small" onClick={signOut} title="Sign out">↪</button>}
      </div>
    </aside>
  )
}
