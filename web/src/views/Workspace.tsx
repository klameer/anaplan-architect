// The workspace's home (v0.2): the estate at a glance. An ask box, then the dashboard (model map, what was tested, where
// the cells are, and per model who reads whom, effort, functions, module roles), then what the workspace is made of:
// the models and their exports, the notes, the workspace's own settings. Every panel can ask the chat about itself.
import { Bert } from '../design/Bert'
import React, { useState } from 'react'
import { api, json } from '../api'
import { href, useApp } from '../App'
import { Dashboard } from '../design/Dashboard'
import { ModelsSection } from './Models'
import { NotesSummary } from './NotesSummary'
import { EstateSettings } from './Home'
import { Icon, Sec } from './Answer'

export function WorkspacePage() {
  const { route, summary: s, go, toast } = useApp()
  const [q, setQ] = useState('')
  if (!s) return null
  const eid = route.eid!
  async function ask(text: string) {
    if (!text.trim()) return
    if (!s!.snapshot) { toast('Upload the exports and activate them first.'); return }
    if (!s!.llm) { toast('No model is set up on the server. Copy .env.example to .env, fill in one block, and restart.'); return }
    try {
      const c = await api('/api/estates/' + eid + '/conversations', json('POST', { title: text }))
      sessionStorage.setItem('ask:' + c.id, text)
      go(href(eid, 'chat', c.id))
    } catch (e: any) { toast(e.message) }
  }
  const wantUploads = route.args[0] === 'uploads'
  return (
    <div className="ds-col xwide">
      <div className="ds-kick"><span className="type">Workspace</span><span className="k">· the estate at a glance{s.snapshot ? ` · read ${s.snapshot.activated_at?.slice(0, 10)}` : ''}</span><span className="grow" />
        {s.snapshot && <><a className="ds-tag" href={href(eid, 'size')}>size →</a><a className="ds-tag" href={`/api/estates/${s.id}/report`} target="_blank" rel="noreferrer">deterministic report ↗</a></>}</div>
      <h1 className="ds-q">{s.name}</h1>
      <div className="ds-askrow"><Bert state="neutral" place="workspace-ask" size={40} /><div className="ds-askbar"><input value={q} placeholder={s.snapshot ? 'Ask anything about this workspace…' : 'Upload the exports below, then ask.'} disabled={!s.snapshot} onChange={e => setQ(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') ask(q) }} /><button className="send" disabled={!s.snapshot || !q.trim()} onClick={() => ask(q)} title="Ask"><Icon d="M5 12h14M13 6l6 6-6 6" s={15} /></button></div></div>
      {s.snapshot ? <Dashboard s={s} onAsk={ask} bare /> : <p className="ds-gap">Nothing is uploaded yet. A workspace is one estate: one or more models, each known from its Line Items export and, if you have them, its Modules and Actions exports.</p>}
      <Sec k="What this workspace is made of" />
      <details className="ds-fold" open={!s.snapshot || wantUploads}><summary>Models and their exports <span className="dim">· {s.models.length} model{s.models.length !== 1 ? 's' : ''} · upload a new set here</span></summary><div className="page-in" id="uploads"><ModelsSection /></div></details>
      <details className="ds-fold"><summary>Notes <span className="dim">· {s.notes ?? 0} kept{(s.notes_flagged || 0) > 0 ? ` · ${s.notes_flagged} to review` : ''}</span></summary><div className="page-in"><NotesSummary /></div></details>
      <details className="ds-fold"><summary>Workspace settings <span className="dim">· rename, archive, back up, delete</span></summary><div className="page-in"><EstateSettings /></div></details>
    </div>
  )
}
