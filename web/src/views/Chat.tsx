import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Bert, BertNote } from '../design/Bert'
import { Menu } from '../design/Menu'
import { ago, api, fmtUsd, json, withCsrf, type Conversation, type Turn } from '../api'
import { href, useApp } from '../App'
import { Inline, Markdown } from '../objects'
import { Icon, TurnView } from './Answer'
import { NoteEditor, type Draft } from './Knowledge'

export function Chat({ cid }: { cid: string }) {
  const { route, summary, idx, refresh, go, toast } = useApp()
  const [conv, setConv] = useState<Conversation | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [live, setLive] = useState<{ text: string; tools: string[] }>({ text: '', tools: [] })
  const [draft, setDraft] = useState('')
  const [failed, setFailed] = useState<{ message: string; cap: boolean } | null>(null)       // the last question did not get an answer: said in place, beside Bert
  const [mode, setMode] = useState<'full' | 'concise'>(() => (sessionStorage.getItem('mode') as any) || 'full')
  useEffect(() => { if (!sessionStorage.getItem('mode')) api<{ answer_mode: 'full' | 'concise' }>('/api/prefs').then(p => setMode(p.answer_mode)).catch(() => {}) }, [])
  const pickMode = (m: 'full' | 'concise') => { setMode(m); sessionStorage.setItem('mode', m) }      // for this browser session; Settings holds the login's default
  const [noteFor, setNoteFor] = useState<Draft | null>(null)
  const [replaying, setReplaying] = useState<{ left: number; of: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const mounted = useRef(true)                                          // the answer keeps streaming and is stored when the reader leaves; the page just stops drawing it
  useEffect(() => () => { mounted.current = false }, [])
  const eid = route.eid!

  useEffect(() => {
    if (cid === 'new') return                                      // a draft: nothing in the store to load
    let cancelled = false
    api<Conversation>('/api/conversations/' + cid).then(c => {
      if (cancelled) return
      setConv(c)
      const first = sessionStorage.getItem('ask:' + cid)
      if (first) { sessionStorage.removeItem('ask:' + cid); send(first, c) }
      const queue = sessionStorage.getItem('replay:' + cid)          // a branch: the original's questions, asked again on this snapshot
      if (queue) { sessionStorage.removeItem('replay:' + cid); replay(JSON.parse(queue), c) }
    }).catch(e => toast(e.message))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid])

  useEffect(() => { box.current?.scrollIntoView({ block: 'end' }) }, [conv, live, pending])

  async function replay(qs: string[], c: Conversation) {
    for (let i = 0; i < qs.length; i++) { setReplaying({ left: qs.length - i, of: qs.length }); if (!await send(qs[i], c)) break }     // one failure ends the replay
    if (mounted.current) setReplaying(null)
  }

  async function send(text: string, c: Conversation | null = conv, m?: string): Promise<boolean> {
    if (!c || !text.trim()) return false
    setPending(text); setLive({ text: '', tools: [] }); setDraft(''); setFailed(null)
    let answer = ''; const tools: string[] = []; let ok = false
    try {
      const r = await fetch('/api/conversations/' + c.id + '/stream', withCsrf({ method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text, mode: m || mode }) }))
      if (!r.ok) {
        let d: any = ''
        try { d = (await r.json()).detail } catch { /* */ }
        if (d && typeof d === 'object') {
          if (d.stale) setConv(cc => cc ? { ...cc, stale: d.stale } : cc)          // the estate moved on under this conversation: the choice is shown
          d = d.message || JSON.stringify(d)
        }
        throw new Error(d || r.statusText)
      }
      const reader = r.body!.getReader(); const dec = new TextDecoder(); let buf = ''
      while (true) {
        const { value, done } = await reader.read(); if (done) break
        buf += dec.decode(value, { stream: true })
        let i: number
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2)
          if (!line.startsWith('data: ')) continue
          const ev = JSON.parse(line.slice(6))
          if (ev.type === 'text') { answer = ev.delta === '' ? '' : answer + ev.delta; if (mounted.current) setLive({ text: answer, tools: [...tools] }) }
          else if (ev.type === 'tool') { tools.push(ev.name + (ev.args && ev.args.name ? ' ' + String(ev.args.name).slice(0, 60) : '')); if (mounted.current) setLive({ text: answer, tools: [...tools] }) }
          else if (ev.type === 'done') { ok = true; if (mounted.current) setConv(cc => cc ? { ...cc, turns: [...cc.turns, ev.turn as Turn], cost_usd: (cc.cost_usd || 0) + ((ev.turn.usage || {}).cost_usd || 0) } : cc) }
          else if (ev.type === 'error') throw new Error(ev.message)
        }
      }
    } catch (e: any) { if (mounted.current) { setFailed({ message: e.message, cap: /spend cap/i.test(e.message) }); setDraft(d => d || text) } }       // the question goes back into the box
    finally { if (mounted.current) setPending(null); refresh() }
    return ok
  }

  async function patch(body: any) {
    try { const c = await api<Conversation>('/api/conversations/' + cid, json('PATCH', body)); setConv(cc => cc ? { ...cc, ...c, turns: cc.turns } : c); await refresh() } catch (e: any) { toast(e.message) }
  }
  /** Re-evaluate on the current snapshot as a linked branch: a new conversation, the same questions asked again there. */
  async function branch() {
    if (!conv) return
    try {
      const b = await api<{ id: string; questions: string[] }>('/api/conversations/' + conv.id + '/branch', json('POST', {}))
      if (b.questions.length) sessionStorage.setItem('replay:' + b.id, JSON.stringify(b.questions))
      await refresh(); go(href(eid, 'chat', b.id))
    } catch (e: any) { toast(e.message) }
  }
  async function rename() { const t = prompt('Rename this conversation:', conv?.title || ''); if (t && t.trim()) patch({ title: t.trim() }) }
  async function del() {
    if (!conv) return
    if (!confirm('Delete this conversation? Its export moves to the estate\'s deleted folder.')) return
    try { await api('/api/conversations/' + conv.id, { method: 'DELETE' }); await refresh(); go(href(eid, 'home')) } catch (e: any) { toast(e.message) }
  }
  function saveAsNote(t: Turn) {
    setNoteFor({ title: t.q.slice(0, 120), body: t.a, type: 'conclusion', status: 'working_assumption', origin_kind: 'answer', conversation_id: cid, turn_id: t.id,
      sources: (t.citations || []).map(c => c.id), scopes: conv?.scope?.model ? (conv.scope.module ? `${conv.scope.model}::${conv.scope.module}` : 'model:' + conv.scope.model) : 'estate' })
  }

  if (cid === 'new') return <NewChat eid={eid} mode={mode} pickMode={pickMode} />
  if (!conv) return <div className="ds-col dim">Loading the chat…</div>
  const st = conv.stale || null
  const held = !!(st && !st.acked)                       // no answer until the owner has chosen
  const heldLabel = st ? (st.held ? (st.held.label || st.held.id) : (st.held_on || 'unknown')) : ''
  const activeLabel = summary?.snapshot ? (summary.snapshot.label || summary.snapshot.id) : (st?.active || '')
  const models = summary?.models || []
  const scopeModel = models.find(m => m.name === conv.scope?.model)

  return (<>
    <div className="ds-col">
      <div className="ds-convhead">
        <span className="k">{conv.turns.length} turn{conv.turns.length !== 1 ? 's' : ''}{conv.cost_usd ? ` · ${fmtUsd(conv.cost_usd)}` : ''}{conv.archived ? ' · archived' : ''}</span><span className="grow" />
        <button onClick={rename}>Rename</button><button onClick={() => patch({ archived: !conv.archived })}>{conv.archived ? 'Unarchive' : 'Archive'}</button>
        <a href={`/api/conversations/${cid}/export`} target="_blank" rel="noreferrer"><button>Export .md</button></a><button onClick={del}>Delete</button>
      </div>
      {conv.branched_from && <p className="ds-gap">Re-evaluation of {conv.origin ? <a href={href(eid, 'chat', conv.origin.id)} style={{ color: 'var(--accent)' }}><Inline text={conv.origin.title} idx={idx} /></a> : 'a chat since deleted'}: the same questions, every answer read from the current upload. Nothing from the earlier answers is carried over.</p>}
      {(conv.branches || []).length > 0 && <p className="ds-gap">Re-evaluated {conv.branches!.map((b, i) => <React.Fragment key={b.id}>{i ? ' · ' : ''}{ago(b.created)}: <a href={href(eid, 'chat', b.id)} style={{ color: 'var(--accent)' }}>open the branch →</a></React.Fragment>)}</p>}
      {held && <div className="ds-none" style={{ marginBottom: 18 }}>
        <div className="h">Held on an earlier upload</div>
        <div style={{ fontSize: 14 }}>This chat was held on <b>{heldLabel}</b>{st!.held ? '' : ' (no longer in the store)'}. The workspace now reads <b>{activeLabel}</b>. Its answers and their citations rest on the upload they were read on; the two are never mixed.</div>
        <div className="ds-foot" style={{ border: 0, marginTop: 10, paddingTop: 0 }}>
          <button className="ctx" onClick={() => patch({ continue_on_snapshot: true })}>{st!.can_continue ? 'Continue on the upload it was held on' : 'Continue on the current upload'}</button>
          <button onClick={branch}>Re-evaluate on the current upload as a linked branch</button></div>
      </div>}
      {st && st.acked && <p className="ds-gap">Held on <b>{heldLabel}</b>: answers here come from that upload, not the current one ({activeLabel}). <a href="#" style={{ color: 'var(--accent)' }} onClick={e => { e.preventDefault(); branch() }}>Re-evaluate on the current upload →</a></p>}
      {replaying && <p className="ds-gap">Re-asking the original questions on this upload: {replaying.of - replaying.left + 1} of {replaying.of}…</p>}

      {conv.turns.map((t, i) => <TurnView key={t.id || i} t={t} eid={eid} first={i === 0} onSave={() => saveAsNote(t)} onAsk={(q, m) => send(q, conv, m)} />)}
      {noteFor && <div><h3>Save as note</h3><NoteEditor draft={noteFor} onSaved={() => { setNoteFor(null); toast('Note saved. It reaches the architect on the next question in its scope.'); refresh() }} onCancel={() => setNoteFor(null)} /></div>}
      {pending && <article className="ds-turn">
        <div className="ds-kick"><span className="type"><Icon d="M4 5h16v11H8l-4 4z" s={14} />Answering</span><span className="k">· {mode}</span></div>
        {conv.turns.length ? <h2 className="ds-q" style={{ fontSize: 21 }}>{pending}</h2> : <h1 className="ds-q">{pending}</h1>}
        {!live.text && <div style={{ margin: '0 0 10px' }}><Bert state="investigating" place="thinking" size={40} line="Still investigating." /></div>}
        <div className="ds-steps" style={{ marginBottom: 14 }}><span className="mono" style={{ fontSize: 11 }}>{live.tools.length ? live.tools.join('  ·  ') : 'reading the workspace…'}</span></div>
        {live.text && <div className="ds-lead md-lead"><Markdown md={live.text} idx={idx} streaming /></div>}
      </article>}
      {failed && !pending && <BertNote state={failed.cap ? 'warning' : 'error'} place={failed.cap ? 'cap-reached' : 'question-failed'} title={failed.cap ? 'Spend cap reached' : 'That question did not get an answer'} size={56}>
        {failed.message} {failed.cap ? '' : 'Your question is back in the box: nothing was lost.'}</BertNote>}
      {/* the end of the chat is brought into view above the composer, which sticks to the bottom and would otherwise cover it */}
      <div ref={box} style={{ scrollMarginBottom: 190 }} />
    </div>
    <div className="ds-compose"><div className="box">
      <textarea value={draft} onChange={e => setDraft(e.target.value)} placeholder={held ? 'Choose above how to go on before asking again.' : 'Follow up… the chat remembers (Enter sends, Shift+Enter for a new line)'} disabled={!!pending || held} rows={2}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(draft) } }} />
      <div className="row">
        <Menu up value={conv.scope?.model || ''} onPick={v => patch({ scope: v ? { model: v } : {} })} title="Which model this chat is about"
          options={[{ value: '', label: 'Whole workspace' }, ...models.map(m => ({ value: m.name, label: m.name }))]} />
        {scopeModel && (scopeModel.module_names || []).length > 0 && <Menu up value={conv.scope?.module || ''} onPick={v => patch({ scope: { model: conv.scope!.model, ...(v ? { module: v } : {}) } })} title="Narrow to one module"
          options={[{ value: '', label: 'Any module' }, ...scopeModel.module_names!.map(m => ({ value: m, label: m }))]} />}
        <span className="grow" />
        <ModeSwitch mode={mode} pick={pickMode} />
        <button className="send" disabled={!!pending || held || !draft.trim()} onClick={() => send(draft)} title="Send"><Icon d="M5 12h14M13 6l6 6-6 6" s={15} /></button>
      </div></div></div>
  </>)
}

export const ModeSwitch = ({ mode, pick }: { mode: 'full' | 'concise'; pick: (m: 'full' | 'concise') => void }) =>
  <div className="ds-seg" role="group" aria-label="Answer mode" title="Concise: the minimum to act on. Full: diagrams, sources, reach.">
    <button className={mode === 'concise' ? 'on' : ''} onClick={() => pick('concise')}>Concise</button><button className={mode === 'full' ? 'on' : ''} onClick={() => pick('full')}>Full</button></div>

const STARTS: [string, string, string, (s: any) => string][] = [
  ['Why', 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4', 'Why was this built the way it is?', s => `Why is ${biggest(s)} built the way it is?`],
  ['Build plan', 'M4 5h6v5H4zM14 14h6v5h-6zM10 7.5h3.5v9H14', 'Give me a plan to build …', () => 'Give me a plan to build '],
  ['Overview', 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z', 'Give me an overview of the build.', () => 'Give me an overview of the build.'],
  ['Improve', 'M4 18l5-6 4 3 7-9M15 6h5v5', 'How can we improve it?', () => 'How can we improve it?'],
  ['Implications', 'M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19z', 'What are the implications of changing a module?', s => `What are the implications of changing ${biggest(s)}?`],
]
const biggest = (s: any) => { const top = (s?.models || []).flatMap((m: any) => (m.cells_by_module || []).map((c: any) => ({ n: c[0], c: c[1] }))).sort((a: any, b: any) => b.c - a.c)[0]; return top ? top.n : 'this module' }

/** A chat before its first question: the workspace in one line, the composer, five kinds of question. The chat is
 * created in the store when the question is sent and takes it as its title, so an abandoned draft leaves nothing. */
function NewChat({ eid, mode, pickMode }: { eid: string; mode: 'full' | 'concise'; pickMode: (m: 'full' | 'concise') => void }) {
  const { summary, go, toast } = useApp()
  const [draft, setDraft] = useState('')
  const [scope, setScope] = useState<{ model?: string; module?: string }>({})
  const [busy, setBusy] = useState(false)
  const ta = useRef<HTMLTextAreaElement>(null)
  const models = summary?.models || []
  const ready = !!summary?.snapshot && !!summary?.llm

  async function start(q?: string) {
    const text = (q ?? draft).trim()
    if (!text || busy || !ready) return
    setBusy(true)
    try {
      const c = await api<Conversation>('/api/estates/' + eid + '/conversations', json('POST', { title: text, scope }))
      sessionStorage.setItem('ask:' + c.id, text)
      go(href(eid, 'chat', c.id))
    } catch (e: any) { toast(e.message); setBusy(false) }
  }
  const li = models.reduce((a, m) => a + (m.line_items || 0), 0)
  return (
    <div className="ds-hello">
      <div className="k" style={{ marginBottom: 10 }}>{models.length} model{models.length !== 1 ? 's' : ''} · {li.toLocaleString()} line items · {summary?.documents ?? 0} document{summary?.documents !== 1 ? 's' : ''}{summary?.snapshot ? ` · read ${summary.snapshot.activated_at?.slice(0, 10)}` : ''}</div>
      <h1>Ask about {summary?.name}</h1>
      <div className="sub">{ready ? 'Every answer cites the objects and passages it rests on. What is not recorded is said, not guessed.'
        : !summary?.snapshot ? 'Upload the exports on the Workspace page and activate them before asking.' : 'No model is set up on the server. Copy .env.example to .env, fill in one block, and restart.'}</div>
      <div className="ds-compose"><div className="box">
        <textarea ref={ta} autoFocus value={draft} onChange={e => setDraft(e.target.value)} placeholder={ready ? 'Ask why, ask for a plan, ask what a change touches…' : 'Nothing to ask yet.'} disabled={busy || !ready} rows={2}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); start() } }} />
        <div className="row">
          <Menu up value={scope.model || ''} onPick={v => setScope(v ? { model: v } : {})} title="Which model this chat is about"
            options={[{ value: '', label: 'Whole workspace' }, ...models.map(m => ({ value: m.name, label: m.name }))]} />
          <span className="grow" /><ModeSwitch mode={mode} pick={pickMode} />
          <button className="send" disabled={busy || !ready || !draft.trim()} onClick={() => start()} title="Send"><Icon d="M5 12h14M13 6l6 6-6 6" s={15} /></button>
        </div></div></div>
      <div className="k" style={{ marginBottom: 8 }}>Five kinds of question</div>
      <div className="ds-starts">{STARTS.map(([label, icon, , make]) => { const q = make(summary)
        return <a key={label} href="#" onClick={e => { e.preventDefault(); if (q.endsWith(' ')) { setDraft(q); ta.current?.focus() } else start(q) }}><Icon d={icon} /><span className="k" style={{ color: 'var(--accent)' }}>{label}</span><span>{q.endsWith(' ') ? q + '…' : q}</span></a> })}</div>
    </div>
  )
}
