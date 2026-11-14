// The v0.2 shell (docs/DESIGN.md): a sidebar led by the workspace dropdown, with that workspace's pages under it
// (Workspace, Chats, Documents, Dependencies, Improve, Notes), its chats, and the login with Settings. A workspace is
// an isolated unit: everything listed here belongs to the one selected. Branding: /architect by CodelessOps.
import { DeleteWorkspace, type Doomed } from '../views/DeleteWorkspace'
import React, { useEffect, useRef, useState } from 'react'
import { api, ago, plain } from '../api'
import { href, useApp, type View } from '../App'
import { Icon } from '../views/Answer'
import logoUrl from '../design/brand/logo.svg'

const NAV: [View, string, string][] = [
  ['home', 'Workspace', 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z'],
  ['chats', 'Chats', 'M4 5h16v11H8l-4 4z'],
  ['documents', 'Documents', 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4'],
  ['dependencies', 'Dependencies', 'M5 6h4v4H5zM15 14h4v4h-4zM9 8h4M13 8v8h2'],
  ['plan', 'Improve', 'M4 18l5-6 4 3 7-9M15 6h5v5'],
  ['notes', 'Notes', 'M5 4h14v12l-4 4H5zM15 20v-4h4'],
]
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '··'

export function Shell({ children }: { children: React.ReactNode }) {
  const { estates, route, summary, me, go, refresh, reloadMe, reloadEstates, toast } = useApp()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [doomed, setDoomed] = useState<Doomed | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const eid = route.eid
  const cur = estates.find(e => e.id === eid)
  useEffect(() => { setOpen(false) }, [eid, route.view])
  useEffect(() => {
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', off); return () => document.removeEventListener('mousedown', off)
  }, [])
  const convs = (summary?.conversations || []).slice().reverse().filter(c => !q || plain(c.title).toLowerCase().includes(q.toLowerCase()))
  const counts: Partial<Record<View, number | undefined>> = { chats: summary?.conversations?.length, documents: (summary as any)?.documents, notes: summary?.notes }

  function newChat() {
    if (!eid || !summary) { toast('Pick a workspace first.'); return }
    if (!summary.snapshot) { toast('Upload the exports and activate them first.'); return }
    if (!summary.llm) { toast('No model is set up on the server. Copy .env.example to .env, fill in one block, and restart.'); return }
    go(href(eid, 'chat', 'new'))
  }
  async function del(id: string, title: string) {
    if (!confirm(`Delete this chat?\n\n${plain(title)}`)) return
    try { await api('/api/conversations/' + id, { method: 'DELETE' }); if (route.cid === id) go(href(eid!, 'home')); await refresh() } catch (e: any) { toast(e.message) }
  }
  async function signOut() { try { await api('/api/auth/logout', { method: 'POST' }); await reloadMe() } catch (e: any) { toast(e.message) } }
  const live = estates.filter(e => !e.archived), archived = estates.filter(e => e.archived)
  const bin = (w: typeof estates[number]) => <button className="del" title={'Delete ' + w.name} aria-label={'Delete the workspace ' + w.name}
    onClick={e => { e.preventDefault(); e.stopPropagation(); setOpen(false); setDoomed({ id: w.id, name: w.name, models: w.models.length, documents: w.documents, chats: w.chats, notes: w.notes }) }}><Icon d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" s={13} /></button>
  async function deleted() {
    const gone = doomed!.id
    setDoomed(null)
    const left = await api<{ id: string; archived: boolean }[]>('/api/estates?archived=true')
    await reloadEstates()
    toast('Workspace deleted.')
    if (gone === eid || !left.length) { const next = left.find(w => !w.archived) || left[0]; go(next ? href(next.id, 'home') : '#/new') }
  }

  return (
    <div className={'ds app' + (new URLSearchParams(location.search).has('capture') ? ' capture' : '')}>
      <aside className="ds-side">
        <a className="ds-brand" href={eid ? href(eid, 'home') : '#/'}><img src={logoUrl} alt="" width="26" height="26" /><span><span className="wm"><b>/</b>architect</span><span className="by">by CodelessOps</span></span></a>
        <div className="ds-ws" ref={box}>
          <button onClick={() => setOpen(o => !o)} aria-expanded={open} aria-haspopup="listbox" title="Switch workspace">
            <span className="mark">{initials(cur?.name || summary?.name || '')}</span>
            <span className="grow"><div className="n">{cur?.name || summary?.name || 'Choose a workspace'}</div><div className="s">{cur ? `${cur.models.length} model${cur.models.length !== 1 ? 's' : ''}${(summary as any)?.documents != null && summary?.id === eid ? ` · ${(summary as any).documents} document${(summary as any).documents !== 1 ? 's' : ''}` : ''}` : `${live.length} workspace${live.length !== 1 ? 's' : ''}`}</div></span>
            <Icon d="M8 10l4-4 4 4M8 14l4 4 4-4" s={14} /></button>
          {open && <div className="pop" role="listbox"><div className="k" style={{ padding: '4px 8px 6px' }}>Workspaces</div>
            {live.map(w => <a key={w.id} href={href(w.id, 'home')} className={'row' + (w.id === eid ? ' on' : '')} role="option" aria-selected={w.id === eid}><span className="tick">{w.id === eid ? '✓' : ''}</span><span className="grow"><div className="n">{w.name}</div><div className="s">{w.models.length} model{w.models.length !== 1 ? 's' : ''}{w.snapshot ? '' : ' · nothing uploaded yet'}</div></span>{bin(w)}</a>)}
            {archived.length > 0 && <><div className="k" style={{ padding: '8px 8px 4px' }}>Archived</div>{archived.map(w => <a key={w.id} href={href(w.id, 'home')} className="row"><span className="tick" /><span className="grow"><div className="n dim">{w.name}</div></span>{bin(w)}</a>)}</>}
            <a className="add" href="#/new">+ New workspace</a>
            <div className="iso">A workspace is separate: its chats, documents, notes and dependencies stay in it. Nothing is remembered across workspaces.</div></div>}
        </div>
        <nav className="ds-nav">{NAV.map(([v, label, d]) => <a key={v} href={eid ? href(eid, v) : '#/new'} className={(route.view === v || (v === 'chats' && route.view === 'chat') || (v === 'home' && route.view === 'size')) && eid ? 'on' : ''}><Icon d={d} />{label}
          {v === 'notes' && (summary?.notes_flagged || 0) > 0 ? <span className="ct" style={{ color: 'var(--amber)' }} title="Notes whose cited evidence moved since the last upload">{summary!.notes_flagged} to review</span> : counts[v] ? <span className="ct">{counts[v]}</span> : null}</a>)}</nav>
        <button className="ds-new" onClick={newChat}><Icon d="M12 5v14M5 12h14" s={14} />New chat</button>
        <div className="k">Chats in this workspace</div>
        {(summary?.conversations || []).length > 6 && <input className="ds-find" placeholder="Find a chat…" value={q} onChange={e => setQ(e.target.value)} />}
        <div className="ds-threads">
          {eid && !convs.length && <div className="dim" style={{ fontSize: 12, padding: '4px 10px' }}>{q ? 'No match.' : 'None yet.'}</div>}
          {convs.map(c => <a key={c.id} href={href(eid!, 'chat', c.id)} className={route.cid === c.id ? 'on' : ''} title={plain(c.title)}>
            <div className="t">{plain(c.title)}</div><div className="s">{c.turns} turn{c.turns !== 1 ? 's' : ''} · {ago(c.updated || c.created)}</div>
            <button className="x" title="Delete this chat" onClick={e => { e.preventDefault(); e.stopPropagation(); del(c.id, c.title) }}>×</button></a>)}
        </div>
        <div className="ds-who"><span className="av">{(me?.user?.name || 'L').slice(0, 1).toUpperCase()}</span>
          <div style={{ flex: 1, minWidth: 0 }}><div className="t">{me?.user ? me.user.name : 'Local'}</div><div className="s">{me?.user ? (me.user.role === 'owner' ? 'admin' : 'member') : 'no accounts'}</div></div>
          {me?.user?.role === 'owner' && <a href="#/admin" className={route.view === 'admin' ? '' : 'dim'} style={{ fontSize: 12 }}>Admin</a>}
          <a href="#/settings" className={route.view === 'settings' ? '' : 'dim'} style={{ fontSize: 12 }}>Settings</a>
          {me?.user && <button className="x2" onClick={signOut} title="Sign out">↪</button>}</div>
      </aside>
      <main className="ds-main">
        <div className="ds-top"><span className="crumb"><b>{summary?.name || (route.view === 'settings' ? 'Settings' : route.view === 'admin' ? 'Admin' : route.view === 'new' ? 'New workspace' : '')}</b>{summary?.snapshot && <> · read {summary.snapshot.activated_at?.slice(0, 10)}</>}</span><span className="grow" />
          {summary && <span className="mono dim" style={{ fontSize: 11 }}>{summary.llm ? `${summary.provider} · ${summary.model}` : 'no model key'}</span>}</div>
        {children}
      </main>
      {doomed && <DeleteWorkspace ws={doomed} onClose={() => setDoomed(null)} onDone={deleted} toast={toast} />}
    </div>
  )
}
