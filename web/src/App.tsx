// The shell, a sidebar (brand, estate selector, nav, new chat, thread search,
// threads, who is signed in) and one main column. No top tabs, no right panel; the evidence drawer
// (stage 3) slides in over the main column when a chip is clicked and closes on Esc.
// Routes live in the hash: #/e/<estate> (home), #/e/<estate>/chats, #/e/<estate>/chat/<id>,
// #/e/<estate>/dependencies, #/e/<estate>/plan, #/settings, #/new.
// Identity gates everything. Accounts are made on the server console, never here: a server with
// no accounts is open on localhost (one person, one machine) and closed on the network.
import { Bert, BertNote } from './design/Bert'
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api, type EstateHead, type EvidenceTarget, type Me, type Summary } from './api'
import { buildIndex, emptyIndex, type NameIndex } from './objects'
import { Shell } from './shell/Shell'
import { WorkspacePage } from './views/Workspace'
import { DocumentsPage } from './views/Documents'
import { AdminPage } from './views/Admin'
import './design/design.css'
import { Chats } from './views/Chats'
import { Chat } from './views/Chat'
import { Dependencies } from './views/Dependencies'
import { ActionPlan } from './views/ActionPlan'
import { NotesPage } from './views/Notes'
import { SizePage } from './views/Size'
import { NewEstate } from './views/NewEstate'
import { Auth } from './views/Auth'
import { Settings } from './views/Settings'
import { EvidencePanel } from './views/Evidence'
import { DesignSheet } from './design/Sheet'

export type View = 'home' | 'chats' | 'chat' | 'dependencies' | 'plan' | 'size' | 'notes' | 'new' | 'settings' | 'design' | 'documents' | 'admin' | 'missing'
/** `args`: the segments after the view, decoded (the explorer's selection: model, then object). */
export type Route = { eid: string | null; view: View; cid: string | null; args: string[] }

const dec = (x: string) => { try { return decodeURIComponent(x) } catch { return x } }

export function parseHash(h: string): Route {
  const p = (h || '').replace(/^#\/?/, '').split('/').filter(Boolean)
  if (p[0] === 'new') return { eid: null, view: 'new', cid: null, args: [] }
  if (p[0] === 'design') return { eid: null, view: 'design', cid: null, args: p.slice(1) }      // the v0.2 design sheet (docs/DESIGN.md), its own shell
  if (p[0] === 'admin') return { eid: null, view: 'admin', cid: null, args: [] }
  if (p[0] === 'settings') return { eid: null, view: 'settings', cid: null, args: [] }
  if (p[0] === 'e' && p[1]) {
    const v = (p[2] || 'home') as View
    if (v === 'chat') return { eid: p[1], view: 'chat', cid: p[3] || null, args: [] }
    // a page this app does not have is said to be missing, not quietly turned into the workspace's home
    return (['home', 'chats', 'dependencies', 'plan', 'size', 'notes', 'documents'] as View[]).includes(v) ? { eid: p[1], view: v, cid: null, args: p.slice(3).map(dec) } : { eid: p[1], view: 'missing', cid: null, args: [dec(p[2])] }
  }
  return p.length ? { eid: null, view: 'missing', cid: null, args: [dec(p[0])] } : { eid: null, view: 'home', cid: null, args: [] }
}

export const href = (eid: string, view: View, cid?: string) =>
  view === 'chat' && cid ? `#/e/${eid}/chat/${cid}` : view === 'home' ? `#/e/${eid}` : `#/e/${eid}/${view}`
/** The explorer opened on one object: #/e/<estate>/dependencies/<model>/<Module.Line Item or Module>. */
export const depsHref = (eid: string, model: string, ref: string) => `#/e/${eid}/dependencies/${encodeURIComponent(model)}/${encodeURIComponent(ref)}`

export type Ctx = {
  estates: EstateHead[]; route: Route; summary: Summary | null; idx: NameIndex; loading: boolean; me: Me | null
  refresh: () => Promise<void>; reloadEstates: () => Promise<void>; reloadMe: () => Promise<void>; go: (h: string) => void; toast: (m: string) => void
  evidence: EvidenceTarget[]; openEvidence: (t: EvidenceTarget) => void; popEvidence: () => void; closeEvidence: () => void
}
export const AppCtx = createContext<Ctx>(null as unknown as Ctx)
export const useApp = () => useContext(AppCtx)

export function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash))
  const [me, setMe] = useState<Me | null>(null)
  const [estates, setEstates] = useState<EstateHead[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)                  // why the estate is still loading, when it is more than a fetch
  const [msg, setMsg] = useState<string | null>(null)
  const [needAuth, setNeedAuth] = useState(false)
  const [evidence, setEvidence] = useState<EvidenceTarget[]>([])

  useEffect(() => {
    const on = () => setRoute(parseHash(location.hash))
    window.addEventListener('hashchange', on)
    const auth = () => setNeedAuth(true)
    window.addEventListener('auth-required', auth)
    return () => { window.removeEventListener('hashchange', on); window.removeEventListener('auth-required', auth) }
  }, [])

  const toast = useCallback((m: string) => { setMsg(m); setTimeout(() => setMsg(null), 7000) }, [])
  const go = useCallback((h: string) => { location.hash = h }, [])
  const openEvidence = useCallback((t: EvidenceTarget) => setEvidence(s => [...s, t]), [])
  const popEvidence = useCallback(() => setEvidence(s => s.slice(0, -1)), [])
  const closeEvidence = useCallback(() => setEvidence([]), [])
  const argKey = route.args.join('/')
  useEffect(() => { setEvidence([]) }, [route.eid, route.view, route.cid, argKey])      // a new page (or a new selection) starts without a drawer

  const reloadMe = useCallback(async () => {
    const m = await api<Me>('/api/auth/me')
    setMe(m)
    setNeedAuth(!m.open && !m.user)
  }, [])

  const reloadEstates = useCallback(async () => {
    const es = await api<EstateHead[]>('/api/estates?archived=true')
    setEstates(es)
    if (!location.hash || location.hash === '#/' || location.hash === '#') {
      const live = es.filter(e => !e.archived)
      if (live.length) location.hash = href(live[live.length - 1].id, 'home')
      else location.hash = '#/new'
    }
  }, [])

  // One estate on screen at a time: the page starts empty on every switch, and a summary that arrives for an estate the
  // reader has since left (a slow estate, or a refresh a page captured before the switch) is dropped, never shown.
  const eidRef = useRef(route.eid); eidRef.current = route.eid
  const reqSeq = useRef(0)
  const refreshRef = useRef<() => Promise<void>>(async () => {})
  useEffect(() => { setSummary(null); setBusy(null) }, [route.eid])
  const refresh = useCallback(async () => {
    const eid = route.eid
    if (!eid) { setSummary(null); return }
    if (eidRef.current !== eid) return                                   // captured by a page that has since been left
    const seq = ++reqSeq.current
    const current = () => seq === reqSeq.current && eidRef.current === eid
    setLoading(true)
    let again = false
    try { const s = await api<Summary>('/api/estates/' + eid); if (current()) { setSummary(s); setBusy(null) } }
    catch (e: any) {
      if (!current()) return
      if (e.status === 409 && e.detail && e.detail.reparsing) {           // the parse cache is being rebuilt (a rename, a restore, a new engine): ask again in a moment
        again = true; setBusy('Re-reading the exports: the models, their names or the engine changed…')
        setTimeout(() => { if (eidRef.current === eid && seq === reqSeq.current) refreshRef.current() }, 2000)
        return
      }
      if (e.status !== 401 && e.status !== 503 && e.status !== 404) toast(e.message)
      if (e.status === 404) reloadEstates().catch(() => {})      // not here, or not one of this login's: the page says so in place (Nothing at this address)
    }
    finally { if (current() && !again) setLoading(false) }
  }, [route.eid, toast, reloadEstates])
  refreshRef.current = refresh

  const allowed = me && (me.open || me.user)
  useEffect(() => { reloadMe().catch(e => toast(e.message)) }, [reloadMe, toast])
  useEffect(() => { if (allowed) reloadEstates().catch(e => { if (e.status !== 401) toast(e.message) }) }, [allowed, reloadEstates, toast])
  useEffect(() => { if (allowed) refresh() }, [allowed, refresh])

  const idx = useMemo(() => summary ? buildIndex(summary) : emptyIndex, [summary])
  const ctx: Ctx = { estates, route, summary, idx, loading, me, refresh, reloadEstates, reloadMe, go, toast, evidence, openEvidence, popEvidence, closeEvidence }

  if (!me) return <div className="empty">Connecting…</div>
  if (me.closed || needAuth || (!me.open && !me.user)) {
    return <AppCtx.Provider value={ctx}><Auth me={me} onDone={async () => { setNeedAuth(false); await reloadMe(); await reloadEstates(); refresh() }} />{msg && <div id="toast">{msg}</div>}</AppCtx.Provider>
  }

  if (route.view === 'design') return <AppCtx.Provider value={ctx}><DesignSheet args={route.args} /></AppCtx.Provider>

  // A page drawn in the v0.2 answer column brings its own width; an older page sits in a plain padded column.
  let main: React.ReactNode
  const old = (node: React.ReactNode) => <div className="page" key={route.eid || route.view}>{node}</div>
  if (route.view === 'missing') main = <div className="ds-col"><BertNote state="question" place="not-found" title="Nothing at this address">There is no page called "{route.args[0]}". <a href={route.eid ? href(route.eid, 'home') : '#/'} style={{ color: 'var(--accent)' }}>{route.eid ? 'Back to the workspace' : 'Go to your workspaces'}</a>.</BertNote></div>
  else if (route.view === 'settings') main = <Settings />
  else if (route.view === 'admin') main = <AdminPage />
  else if (route.view === 'new' || !route.eid) main = old(<NewEstate />)
  else if (!summary) main = loading
    ? <div className="ds-col"><Bert state="processing" place="reading" size={40} line={busy || 'Reading the workspace…'} /></div>
    : <div className="ds-col"><BertNote state="question" place="not-found" title="Nothing at this address">That workspace is not here, or it is not one of yours. <a href="#/" style={{ color: 'var(--accent)' }}>Go to your workspaces</a>.</BertNote></div>
  else if (route.view === 'chat' && route.cid) main = <Chat key={route.cid} cid={route.cid} />
  else if (route.view === 'chats') main = old(<Chats />)
  else if (route.view === 'dependencies') main = old(<Dependencies />)
  else if (route.view === 'plan') main = old(<ActionPlan />)
  else if (route.view === 'size') main = old(<SizePage key={route.args[0] || ''} />)
  else if (route.view === 'notes') main = old(<NotesPage />)
  else if (route.view === 'documents') main = <div className="ds-col wide" key={route.eid}><DocumentsPage /></div>
  else main = <WorkspacePage key={route.eid} />

  return (
    <AppCtx.Provider value={ctx}>
      <Shell>{main}</Shell>
      <EvidencePanel />
      {msg && <div id="toast">{msg}</div>}
    </AppCtx.Provider>
  )
}
