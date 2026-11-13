import React, { useEffect, useState } from 'react'
import { DeleteWorkspace } from './DeleteWorkspace'
import { ago, api, fmtN, json } from '../api'
import { href, useApp } from '../App'
import { Inline } from '../objects'
import { EstateShape } from './EstateShape'
import { TestsPanel } from './TestsPanel'
import { ModelsSection } from './Models'
import { NotesSummary } from './NotesSummary'

const KIND: Record<string, string> = { line_items: 'Line Items', actions: 'Actions', modules: 'Modules' }

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function Home() {
  const { route, summary: s, idx, me, go, toast } = useApp()
  const [q, setQ] = useState('')
  const [more, setMore] = useState(false)
  const wantUploads = route.args[0] === 'uploads'                        // #/e/<id>/home/uploads: opened to upload (New estate, "register first")
  useEffect(() => { if (wantUploads) document.getElementById('uploads')?.scrollIntoView() }, [wantUploads])
  if (!s) return null
  const eid = route.eid!

  async function start(text: string) {
    if (!s!.snapshot) { toast('Activate a snapshot first.'); return }
    if (!s!.llm) { toast('No LLM key on the server. Start it with --api-key or set ANTHROPIC_API_KEY.'); return }
    try {
      const c = await api('/api/estates/' + eid + '/conversations', json('POST', { title: text }))
      sessionStorage.setItem('ask:' + c.id, text)
      go(href(eid, 'chat', c.id))
    } catch (e: any) { toast(e.message) }
  }

  const lineItems = s.models.reduce((n, m) => n + (m.line_items || 0), 0)
  const uploads = s.models.flatMap(m => Object.entries(m.files || {}).map(([k, f]) => ({ model: m.name, kind: KIND[k], ...f }))).sort((a, b) => (b.uploaded_at || '').localeCompare(a.uploaded_at || ''))
  const last = uploads[0]?.uploaded_at
  const recent = (s.conversations || []).slice().reverse().slice(0, 5)
  const chips = s.questions.slice(0, more ? s.questions.length : 3)

  return (
    <div>
      <div className="hero">
        <div>
          <h1 className="big">{greeting()}, {me?.user?.name || s.name}</h1>
          <div className="muted">Every answer cited to the parsed estate{me?.user ? ` · ${s.name}` : ''}</div>
        </div>
      </div>

      <div className="ask">
        <input value={q} placeholder={s.snapshot ? 'Ask anything about this estate…' : 'Upload and activate a snapshot below, then ask.'} disabled={!s.snapshot}
          onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && q.trim()) start(q.trim()) }} />
        <button className="send" disabled={!s.snapshot || !q.trim()} onClick={() => start(q.trim())} title="Ask">➤</button>
      </div>
      {s.snapshot && chips.length > 0 && <div className="chips">
        {chips.map((qq, i) => <button key={i} className="chip" onClick={() => start(qq.text)} title={qq.why}><span className="k">{qq.kind}</span><span className="t"><Inline text={qq.text} idx={idx} /></span></button>)}
        {s.questions.length > 3 && <button className="chip more" onClick={() => setMore(!more)}>{more ? 'fewer' : `${s.questions.length - 3} more`}</button>}
      </div>}

      <div className="tiles">
        <div className="tile"><div className="k">Models</div><div className="v">{s.models.length}</div></div>
        <div className="tile"><div className="k">Line items</div><div className="v">{lineItems ? fmtN(lineItems) : '—'}</div></div>
        <div className="tile"><div className="k">Last upload</div><div className="v">{last ? ago(last) : '—'}</div></div>
        <div className="tile"><div className="k">Snapshot</div><div className="v">{s.snapshot ? ago(s.snapshot.activated_at) : 'none'}</div>{s.snapshot && <a className="small" href={`/api/estates/${s.id}/report`} target="_blank" rel="noreferrer">Deterministic report ↗</a>}</div>
      </div>

      {s.snapshot && <EstateShape />}
      {s.snapshot && <TestsPanel />}

      <div className="two">
        <section>
          <h3>Pick up where you left off</h3>
          <div className="card list-card">
            {!recent.length && <div className="muted small">No conversations yet.</div>}
            {recent.map(c => <a key={c.id} className="row2" href={href(eid, 'chat', c.id)}><span className="t"><Inline text={c.title} idx={idx} /></span><span className="muted small">{ago(c.created)}</span></a>)}
            {(s.conversations || []).length > 5 && <a className="row2 more" href={href(eid, 'chats')}><span>All conversations →</span><span /></a>}
          </div>
        </section>
        <section>
          <h3>Recently added</h3>
          <div className="card list-card">
            {!uploads.length && <div className="muted small">No exports uploaded yet.</div>}
            {uploads.slice(0, 5).map((u, i) => <div key={i} className="row2"><span className="t">{u.model} · {u.kind}</span><span className="small"><span className={'pill ' + (u.problem ? 'off' : '')}>{u.problem ? 'problem' : 'ready'}</span> <span className="muted">{ago(u.uploaded_at)}</span></span></div>)}
            {uploads.length > 5 && <a className="row2 more" href={href(eid, 'home')} onClick={e => { e.preventDefault(); document.getElementById('uploads')?.scrollIntoView({ behavior: 'smooth' }) }}><span>All uploads ↓</span><span /></a>}
          </div>
        </section>
      </div>

      <NotesSummary />
      <div id="uploads" />
      <ModelsSection />
      <EstateSettings />
    </div>
  )
}

export function EstateSettings() {
  const { route, summary: s, refresh, reloadEstates, go, toast } = useApp()
  const [name, setName] = useState(s?.name || '')
  const [ask, setAsk] = useState(false)
  useEffect(() => { setName(s?.name || '') }, [s?.id, s?.name])          // the box follows the estate on screen, never a previous one
  if (!s) return null
  const eid = route.eid!
  async function rename() { try { await api('/api/estates/' + eid, json('PATCH', { name })); await refresh(); await reloadEstates() } catch (e: any) { toast(e.message) } }
  async function archive() { try { await api('/api/estates/' + eid, json('PATCH', { archived: !s!.archived })); await refresh(); await reloadEstates() } catch (e: any) { toast(e.message) } }
  async function deleted() {
    setAsk(false)
    const left = await api<{ id: string; archived: boolean }[]>('/api/estates?archived=true')
    await reloadEstates()
    toast('Workspace deleted.')
    const next = left.find(w => !w.archived) || left[0]
    go(next ? href(next.id, 'home') : '#/new')          // the last one gone: the empty state
  }
  return (
    <>
      <h2>Workspace settings</h2>
      <div className="card">
        <div className="row" style={{ gridTemplateColumns: '1fr auto auto' }}>
          <div><label>Name</label><input value={name} onChange={e => setName(e.target.value)} /></div>
          <div><label>&nbsp;</label><button disabled={!name.trim() || name.trim() === s.name} onClick={rename}>Rename</button></div>
          <div><label>&nbsp;</label><button onClick={archive}>{s.archived ? 'Unarchive' : 'Archive'}</button></div>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>{s.archived ? 'This workspace is archived: listed under Archived in the workspace list. Nothing was deleted.' : 'Archiving moves the workspace under Archived in the workspace list; nothing is deleted.'}</div>
        <div className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 14 }}>
          <div><label>Backup</label><div className="small muted">One zip: the register, every snapshot with its export files, notes, conversations with their citations, decisions and proposals. No accounts, passwords or invite codes travel with it. Restore it from New estate, here or on another server; ids are kept, so every old citation still opens.</div></div>
          <div><label>&nbsp;</label><a href={`/api/estates/${eid}/backup`}><button>Download a backup</button></a></div>
        </div>
        <div className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 14 }}>
          <div><label>Delete this workspace</label><div className="small muted">Takes its {s.models.length} model{s.models.length !== 1 ? 's' : ''} and their exports, {(s as any).documents ?? 0} document{(s as any).documents === 1 ? '' : 's'}, {s.conversations?.length ?? 0} chat{s.conversations?.length === 1 ? '' : 's'} and {s.notes ?? 0} note{s.notes === 1 ? '' : 's'} with it. You type its name to confirm. There is no undo.</div></div>
          <div><label>&nbsp;</label><button onClick={() => setAsk(true)}>Delete workspace…</button></div>
        </div>
        {ask && <DeleteWorkspace ws={{ id: eid, name: s.name, models: s.models.length, documents: (s as any).documents, chats: s.conversations?.length, notes: s.notes }} onClose={() => setAsk(false)} onDone={deleted} toast={toast} />}
      </div>
    </>
  )
}
