import React, { useCallback, useEffect, useRef, useState } from 'react'
import { ago, api, json, when, NOTE_STATUSES, NOTE_TYPES, type Note, type ReviewSource } from '../api'
import { href, useApp } from '../App'
import { CiteChip, Inline, Markdown, Obj, citesOf, type NameIndex } from '../objects'

const STATUS_LABEL: Record<string, string> = { working_assumption: 'working assumption', user_confirmed: 'confirmed', superseded: 'superseded' }
const REVIEW_LABEL: Record<string, string> = { changed: 'formula changed', gone: 'gone from the new snapshot', renamed: 'renamed', deleted: 'source deleted', superseded: 'cited note superseded', unknown: 'could not compare', unchanged: 'unchanged' }

/** One cited source as the review found it: a chip that opens the object as its snapshot held it, its status, and what changed. */
function ReviewRow({ s, idx }: { s: ReviewSource; idx: NameIndex }) {
  const chip = s.ref ? <Obj text={s.ref} idx={idx} cites={citesOf([{ id: s.id, kind: s.kind || '', model: s.model || '', ref: s.ref, name: s.name || s.ref, snapshot_id: s.snapshot_id || '', provenance: 'observed', tool: '' }])} />
    : <code className="obj unknown deleted" title="no turn or note records this citation any more">{s.id}</code>
  const formula = s.status === 'changed' && (s.was != null || s.now != null)          // a line item: the formula before and after
  const label = s.status === 'changed' && !formula ? (s.kind === 'module' ? 'line items changed' : 'changed') : (REVIEW_LABEL[s.status] || s.status)
  return (
    <li>
      {chip} <span className={'pill ' + (s.status === 'unchanged' ? 'dim' : 'amber')}>{label}</span>
      {formula && <div className="small muted">was <code>{s.was}</code><br />now <code>{s.now}</code></div>}
      {!formula && s.detail && <div className="small muted">{s.detail}</div>}
    </li>
  )
}

export type Draft = { id?: string; title: string; body: string; type: string; status: string; scopes: string; origin_kind?: string; conversation_id?: string; turn_id?: string; sources?: string[] }

/** The editor for a new note or an existing one. Scopes are typed as 'estate', 'model:Name', 'Model::Module', 'Model::Module.Line Item' or 'rule:ID', separated by commas. */
export function NoteEditor({ draft, onSaved, onCancel }: { draft: Draft; onSaved: (n: Note) => void; onCancel: () => void }) {
  const { route, summary, toast } = useApp()
  const [d, setD] = useState<Draft>(draft)
  const [busy, setBusy] = useState(false)
  const models = summary?.models || []
  async function save() {
    setBusy(true)
    try {
      const objects = d.scopes.split(',').map(s => s.trim()).filter(Boolean)
      const body = { title: d.title, body: d.body, type: d.type, status: d.status, objects: objects.length ? objects : ['estate'],
        origin_kind: d.origin_kind, conversation_id: d.conversation_id, turn_id: d.turn_id, sources: d.sources }
      const n = d.id ? await api<Note>('/api/notes/' + d.id, json('PATCH', body)) : await api<Note>('/api/estates/' + route.eid + '/notes', json('POST', body))
      onSaved(n)
    } catch (e: any) { toast(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="card editor">
      <div className="row" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
        <div><label>Title</label><input value={d.title} onChange={e => setD({ ...d, title: e.target.value })} placeholder="one line" /></div>
        <div><label>Type</label><select value={d.type} onChange={e => setD({ ...d, type: e.target.value })}>{NOTE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}</select></div>
        <div><label>Status</label><select value={d.status} onChange={e => setD({ ...d, status: e.target.value })}>{NOTE_STATUSES.filter(s => s !== 'superseded' || d.status === 'superseded').map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></div>
      </div>
      <div style={{ marginTop: 8 }}><label className="kicker">Body</label><textarea value={d.body} rows={6} onChange={e => setD({ ...d, body: e.target.value })} /></div>
      <div className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 8 }}>
        <div><label>Scope (comma-separated: estate, model:Name, Model::Module, Model::Module.Line Item, rule:ID)</label>
          <input value={d.scopes} list="scope-hints" onChange={e => setD({ ...d, scopes: e.target.value })} placeholder="estate" />
          <datalist id="scope-hints"><option value="estate" />{models.map(m => <option key={m.id} value={'model:' + m.name} />)}</datalist></div>
        <div><label>&nbsp;</label><button className="primary" disabled={busy || !d.body.trim()} onClick={save}>{d.id ? 'Save' : 'Add note'}</button> <button onClick={onCancel}>Cancel</button></div>
      </div>
      {d.sources && d.sources.length > 0 && <div className="small muted" style={{ marginTop: 6 }}>Carries {d.sources.length} citation{d.sources.length !== 1 ? 's' : ''} from the answer it came from.</div>}
    </div>
  )
}

function NoteCard({ n, onChange, onEdit }: { n: Note; onChange: () => void; onEdit: () => void }) {
  const { route, idx, toast } = useApp()
  const [open, setOpen] = useState(false)
  async function patch(body: any) { try { await api('/api/notes/' + n.id, json('PATCH', body)); onChange() } catch (e: any) { toast(e.message) } }
  async function supersede() { if (!confirm('Mark this note superseded? It stays in the record but stops reaching the architect.')) return; try { await api('/api/notes/' + n.id + '/supersede', json('POST', {})); onChange() } catch (e: any) { toast(e.message) } }
  async function del() { if (!confirm('Delete this note? There is no undo.')) return; try { await api('/api/notes/' + n.id, { method: 'DELETE' }); onChange() } catch (e: any) { toast(e.message) } }
  async function reviewed() { try { await api('/api/notes/' + n.id + '/reviewed', json('POST', {})); onChange() } catch (e: any) { toast(e.message) } }
  const sibs = n.siblings || []
  const rv = n.review_flag && n.review ? n.review : null
  const moved = rv ? rv.sources.filter(s => s.status !== 'unchanged') : []
  return (
    <div className={'note' + (n.status === 'superseded' ? ' faded' : '')}>
      <div className="note-head">
        <span className="t"><Inline text={n.title} idx={idx} /></span>
        <span className="pill dim">{n.type}</span>
        <span className={'pill ' + (n.status === 'user_confirmed' ? '' : n.status === 'superseded' ? 'off' : 'amber')}>{STATUS_LABEL[n.status]}</span>
        {n.review_flag && <span className="pill amber" title="Evidence this note cites moved when the estate went to a newer snapshot">needs review</span>}
        {n.scope_labels.map((s, i) => <span key={i} className="scope">{s.startsWith('model:') ? <Obj text={s.slice(6)} idx={idx} /> : s.includes('::') ? <Obj text={s.split('::')[1]} idx={idx} /> : <code>{s}</code>}</span>)}
        <span className="muted small grow" title={when(n.updated)}>{ago(n.updated)} · {n.origin_kind === 'answer' ? 'saved from an answer' : n.origin_kind === 'chat_tool' ? 'kept by the architect' : n.origin_kind === 'import' ? 'imported' : 'typed'}</span>
        <button className="small quiet" onClick={() => setOpen(!open)}>{open ? 'less' : 'more'}</button>
      </div>
      <div className={'note-body' + (open ? '' : ' clamp')}><Markdown md={n.body} idx={idx} /></div>
      {rv && <div className="review">
        <div className="warn" style={{ fontSize: 12.5 }}>{rv.flag === 'gone' ? 'What this note cites is gone' : 'A formula this note cites changed'} when the estate went to snapshot <code>{rv.snapshot_id}</code> ({ago(rv.at)}). Read what moved, then keep the note as it is, edit it, or supersede it.</div>
        <ul className="small">{moved.map(s => <ReviewRow key={s.id} s={s} idx={idx} />)}</ul>
        <div className="actions" style={{ marginTop: 6 }}>
          <button className="small" onClick={reviewed} title="Clear the flag; the next activation compares from this snapshot">Reviewed: keep as it is</button>
          <button className="small" onClick={onEdit}>Edit</button>
          {n.status !== 'superseded' && <button className="small" onClick={supersede}>Supersede</button>}
        </div>
      </div>}
      {open && <>
        {n.origin_conversation_id && <div className="small"><a href={href(route.eid!, 'chat', n.origin_conversation_id)}>Open the conversation it came from →</a></div>}
        {(n.sources_resolved || []).length > 0 && <div className="cites small"><span className="muted">Evidence it carries:</span>{n.sources_resolved!.map(c => <CiteChip key={c.id} c={c} idx={idx} />)}</div>}
        {(n.sources_missing || []).length > 0 && <div className="cites small"><span className="muted">Sources deleted since:</span>{n.sources_missing!.map(id => <code key={id} className="obj unknown deleted" title="No turn or note records this citation any more; the conversation it came from was deleted before the note kept its own copy">{id}</code>)}</div>}
        {n.reviewed_at && !n.review_flag && <div className="small muted">Reviewed {ago(n.reviewed_at)}{n.reviewed_snapshot_id ? <> against snapshot <code>{n.reviewed_snapshot_id}</code></> : null}.</div>}
        {sibs.length > 0 && <div className="small" style={{ marginTop: 6 }}><span className="muted">Also on this object, and possibly disagreeing:</span>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{sibs.map(s => <li key={s.id}><Inline text={s.title} idx={idx} /> <span className="muted">({s.type}, {STATUS_LABEL[s.status]})</span></li>)}</ul></div>}
        <div className="actions">
          {n.status === 'working_assumption' && <button className="small" onClick={() => patch({ status: 'user_confirmed' })}>Confirm</button>}
          {n.status === 'user_confirmed' && <button className="small" onClick={() => patch({ status: 'working_assumption' })}>Back to assumption</button>}
          <button className="small" onClick={onEdit}>Edit</button>
          {n.status !== 'superseded' && <button className="small" onClick={supersede}>Supersede</button>}
          <button className="small" onClick={del}>Delete</button>
        </div>
      </>}
    </div>
  )
}

export function NotesSection() {
  const { route, summary, refresh, toast } = useApp()
  const [notes, setNotes] = useState<Note[] | null>(null)
  const [q, setQ] = useState('')
  const [type, setType] = useState('')
  const [status, setStatus] = useState('')
  const [showSuperseded, setShowSuperseded] = useState(false)
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const [editing, setEditing] = useState<Draft | null>(null)
  const eid = route.eid
  const flagged = summary?.notes_flagged || 0
  const seq = useRef(0)
  const load = useCallback(async () => {
    if (!eid) return
    const p = new URLSearchParams(); if (q) p.set('q', q); if (type) p.set('type', type); if (status) p.set('status', status); if (showSuperseded) p.set('superseded', 'true'); if (flaggedOnly) p.set('flagged', 'true')
    const n = ++seq.current                                              // only the newest request may set the notes
    try { const r = await api<Note[]>('/api/estates/' + eid + '/notes?' + p.toString()); if (n === seq.current) setNotes(r) } catch (e: any) { if (n === seq.current) toast(e.message) }
  }, [eid, q, type, status, showSuperseded, flaggedOnly, toast])
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t) }, [load])
  useEffect(() => { if (!flagged) setFlaggedOnly(false) }, [flagged])
  const fresh = (): Draft => ({ title: '', body: '', type: 'conclusion', status: 'working_assumption', scopes: 'estate', origin_kind: 'user' })
  const toDraft = (n: Note): Draft => ({ id: n.id, title: n.title, body: n.body, type: n.type, status: n.status, scopes: n.scope_labels.join(', ') })
  const reload = () => { load(); refresh() }
  return (
    <div>
      <h2>Notes</h2>
      <p className="muted small">What the owner has established about the estate: purposes, decisions, constraints, procedures, conclusions. Each is a working assumption until confirmed. The architect reads the ones for the scope of every question; two that disagree both stay and both show. When the estate moves to a new snapshot, a note whose cited formula changed or whose cited object disappeared is flagged for review; it keeps reaching the architect, flagged, until you have looked.</p>
      {flagged > 0 && <div className="warn" style={{ marginBottom: 8 }}>{flagged} note{flagged !== 1 ? 's' : ''} cite{flagged === 1 ? 's' : ''} evidence that moved since the snapshot changed. <a href="#" onClick={e => { e.preventDefault(); setFlaggedOnly(!flaggedOnly) }}>{flaggedOnly ? 'Show all notes' : 'Show only those →'}</a></div>}
      <div className="row" style={{ gridTemplateColumns: '2fr 1fr 1fr auto auto', marginBottom: 10 }}>
        <div><input placeholder="Search notes" value={q} onChange={e => setQ(e.target.value)} /></div>
        <div><select value={type} onChange={e => setType(e.target.value)}><option value="">any type</option>{NOTE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}</select></div>
        <div><select value={status} onChange={e => setStatus(e.target.value)}><option value="">current</option>{NOTE_STATUSES.map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></div>
        <div><label className="small muted" style={{ fontFamily: 'var(--sans)', textTransform: 'none', letterSpacing: 0 }}><input type="checkbox" checked={showSuperseded} onChange={e => setShowSuperseded(e.target.checked)} />superseded too</label></div>
        <div><button onClick={() => setEditing(fresh())} disabled={!summary?.snapshot}>New note</button></div>
      </div>
      {editing && !editing.id && <NoteEditor draft={editing} onSaved={() => { setEditing(null); reload() }} onCancel={() => setEditing(null)} />}
      <div className="notes">
        {notes === null && <div className="muted small">Loading…</div>}
        {notes && !notes.length && <div className="card muted small">No notes{q || type || status || flaggedOnly ? ' match' : ' yet'}. Save an answer as a note from any conversation, tell the architect something worth keeping, or add one here.</div>}
        {(notes || []).map(n => editing && editing.id === n.id
          ? <NoteEditor key={n.id} draft={editing} onSaved={() => { setEditing(null); reload() }} onCancel={() => setEditing(null)} />
          : <NoteCard key={n.id} n={n} onChange={reload} onEdit={() => setEditing(toDraft(n))} />)}
      </div>
    </div>
  )
}
