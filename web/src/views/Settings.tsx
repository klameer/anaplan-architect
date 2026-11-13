// Settings, for this login (or this machine, on a server with no logins): the answer mode, the demo workspaces,
// what leaves the machine, the password, and whose product this is.
import React, { useEffect, useState } from 'react'
import { api, json, type TraceLevel } from '../api'
import { href, useApp } from '../App'
import { Sec } from './Answer'

const TRACE_NAME: Record<TraceLevel, string> = { off: 'Off', structure: 'Structure', content: 'Full' }
const TRACE_SAYS: Record<TraceLevel, string> = {
  off: 'Off: nothing about your questions is sent to LangSmith, not even that you asked.',
  structure: 'Structure: for each question, which tools ran and in what order, sizes, tokens, cost and timings. Not the question, the answer, the passages or any object name.',
  content: 'Full: each question as a run tree with the question, the answer, every model call and every tool call with what it returned.',
}

export function Settings() {
  const { me, toast, reloadEstates, reloadMe, go } = useApp()
  const [mode, setMode] = useState<'full' | 'concise'>('full')
  const [pw, setPw] = useState({ old: '', new: '' })
  const [demo, setDemo] = useState<{ available: boolean; workspaces: { id: string; name: string; present: boolean }[] } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api<{ answer_mode: 'full' | 'concise' }>('/api/prefs').then(p => setMode(p.answer_mode)).catch(() => {}); api<any>('/api/demo').then(setDemo).catch(() => {}) }, [])
  if (!me) return null
  async function saveMode(m: 'full' | 'concise') { try { const p = await api<{ answer_mode: 'full' | 'concise' }>('/api/prefs', json('PUT', { answer_mode: m })); setMode(p.answer_mode); sessionStorage.removeItem('mode') } catch (e: any) { toast(e.message) } }
  async function changePw() { try { await api('/api/auth/password', json('POST', pw)); setPw({ old: '', new: '' }); toast('Password changed. Other sessions were signed out.') } catch (e: any) { toast(e.message) } }
  async function resetDemo() {
    if (demo?.workspaces.some(w => w.present) && !confirm('Replace the demo workspaces with a fresh copy?\n\nChats, notes and documents added to them are removed. Your other workspaces are not touched.')) return
    setBusy(true)
    try { const r = await api<{ workspaces: { id: string }[] }>('/api/demo/reset', { method: 'POST' }); await reloadEstates(); setDemo(await api<any>('/api/demo')); toast('The demo workspaces are as first written.'); go(href(r.workspaces[0].id, 'home')) }
    catch (e: any) { toast(e.message) } finally { setBusy(false) }
  }
  const tr = me.trace
  async function saveTrace(l: TraceLevel) {
    if (l !== 'off' && me!.user && me!.user.role !== 'owner' && tr?.level === 'off' &&
        !confirm(`Turn tracing on for your questions?\n\nThe person who runs this instance will be able to read ${l === 'content' ? 'your questions, the answers and the passages pulled for them' : 'that you asked, which tools ran and how large each step was'}. It is also held by LangSmith.\n\nYou can turn it off again; what was already sent is not deleted.`)) return
    try { await api('/api/prefs', json('PUT', { trace_level: l })); await reloadMe(); toast(l === 'off' ? 'Nothing more will be sent. What was already sent is not deleted.' : `From your next question: ${TRACE_NAME[l].toLowerCase()}.`) } catch (e: any) { toast(e.message) }
  }
  const prov = me.provider === 'none' ? 'no model configured' : `${me.provider} · ${me.model || ''}${(me as any).endpoint ? ' · ' + (me as any).endpoint : ''}`
  return (
    <div className="ds-col">
      <div className="ds-kick"><span className="type">Settings</span><span className="k">· {me.user ? `for ${me.user.name}` : 'for this machine'}</span></div>
      <h1 className="ds-q">Settings</h1>

      <Sec k="Answers" />
      <div className="ds-list">
        <div className="r" style={{ alignItems: 'center' }}><span style={{ width: 170, flex: 'none' }}>Answer mode</span>
          <span className="grow dim" style={{ fontSize: 12.5 }}>{mode === 'full' ? 'Full: the answer in a few lines, then the diagram, the source cards and the tables for its question type.' : 'Concise: the steps, or a few lines with the key figures. Show diagram, explain and expand to Full open in place.'} The switch on the composer changes it for one browser session.</span>
          <div className="ds-seg" role="group" aria-label="Answer mode"><button className={mode === 'full' ? 'on' : ''} onClick={() => saveMode('full')}>Full</button><button className={mode === 'concise' ? 'on' : ''} onClick={() => saveMode('concise')}>Concise</button></div></div>
        <div className="r"><span style={{ width: 170, flex: 'none' }}>Theme</span><span className="grow dim" style={{ fontSize: 12.5 }}>Dark. There is no light theme in v0.2.</span></div>
      </div>

      {demo?.available && <><Sec k="Demo workspaces" />
        <div className="ds-list">
          {demo.workspaces.map(w => <div className="r" key={w.id}><span style={{ width: 240, flex: 'none' }}>{w.name}</span><span className="grow dim" style={{ fontSize: 12.5 }}>{w.present ? 'in your workspaces' : 'not created yet'}</span>{w.present && <a className="ds-tag ok" href={href(w.id, 'home')}>open</a>}</div>)}
          <div className="r" style={{ alignItems: 'center' }}><span className="grow dim" style={{ fontSize: 12.5 }}>Two fictional workspaces to try everything on: four models with their project documents and notes, and one model of 5,403 line items. Resetting writes them exactly as first written and touches nothing else.</span>
            <button className="ds-btn" disabled={busy} onClick={resetDemo}>{busy ? 'Writing…' : demo.workspaces.some(w => w.present) ? 'Reset the demo' : 'Create the demo'}</button></div>
        </div></>}

      <Sec k="What leaves this machine" />
      <div className="ds-list">
        <div className="r"><span style={{ width: 170, flex: 'none' }}>Stored here</span><span className="grow dim" style={{ fontSize: 12.5 }}>Exports, documents, notes and chats are files and one SQLite database on this server's disk. Documents are indexed there too: no embeddings, no vector store, no indexing service.</span><span className="mono dim cap-hide" style={{ fontSize: 11 }}>{me.user?.role === 'owner' || !me.user ? me.data_dir : ''}</span></div>
        <div className="r"><span style={{ width: 170, flex: 'none' }}>Sent to the model</span><span className="grow dim" style={{ fontSize: 12.5 }}>Only when you ask: the question, a summary of the workspace (model, module and line item names, formulas, sizes), the document cards, and whatever the tools pulled for that answer. The context chip under each answer lists exactly what went.</span><span className="mono dim cap-hide" style={{ fontSize: 11 }}>{prov}</span></div>
      </div>

      <Sec k="Tracing your questions" ct={tr?.available ? 'your own choice, for your own questions' : 'not set up on this instance'} />
      <div className="ds-list" id="trace-setting">
        {!tr?.available ? <div className="r"><span className="grow dim" style={{ fontSize: 12.5 }}>Nothing is sent to an outside tracer: this instance has none set up. The run timeline under each answer is kept here and needs no outside account.{me.tracing?.error ? ` (A key was set but not accepted: ${me.tracing.error})` : ''}</span></div> : <>
          <div className="r" style={{ alignItems: 'center' }}><span style={{ width: 170, flex: 'none' }}>Send to LangSmith</span>
            <span className="grow dim" style={{ fontSize: 12.5 }}>{TRACE_SAYS[tr.level]}</span>
            <div className="ds-seg" role="group" aria-label="Tracing level">{(['off', 'structure', 'content'] as TraceLevel[]).map(l =>
              <button key={l} className={tr.level === l ? 'on' : ''} disabled={l === 'content' && tr.ceiling === 'structure'} title={l === 'content' && tr.ceiling === 'structure' ? 'This instance sends structure at most' : undefined} onClick={() => saveTrace(l)}>{TRACE_NAME[l]}</button>)}</div></div>
          <div className="r"><span className="grow dim" style={{ fontSize: 12.5 }}>
            {me.user?.role === 'owner' || !me.user
              ? <>You run this instance, so your own questions are traced in full unless you change it here. Nobody else's are: each login decides for itself, and you cannot turn it on for them. The admin panel shows what each has chosen.</>
              : <>Off unless you turn it on. If you do, <b style={{ color: 'var(--ink)' }}>the person who runs this instance will be able to read what you send</b>: with Structure, only that you asked, which tools ran, sizes, tokens and timings; with Full, your questions, the answers and the passages and formulas pulled for them. It also sits with LangSmith, a third party. You can turn it off again at any time: that stops anything further being sent, and does not delete what was already sent.</>}
            {tr.chosen ? <> You chose {TRACE_NAME[tr.chosen]} on {(tr.chosen_at || '').slice(0, 16).replace('T', ' at ')}.</> : <> You have not chosen: this is the default for your login.</>}
            {tr.ceiling === 'structure' && <> This instance sends structure at most, whatever is chosen.</>}
            {me.tracing?.host ? <> Endpoint: <span className="mono">{me.tracing.host}</span>.</> : null}
            {me.tracing?.write_only ? <> The key here can write traces and cannot read them back.</> : null}</span></div>
        </>}
      </div>

      {me.user && <><Sec k="Your password" />
        <div className="ds-list"><div className="r" style={{ alignItems: 'center', gap: 10 }}>
          <input className="ds-in" type="password" placeholder="Current" value={pw.old} autoComplete="current-password" onChange={e => setPw({ ...pw, old: e.target.value })} />
          <input className="ds-in" type="password" placeholder="New, ten characters or more" value={pw.new} autoComplete="new-password" onChange={e => setPw({ ...pw, new: e.target.value })} />
          <button className="ds-btn" disabled={!pw.old || pw.new.length < 10} onClick={changePw}>Change</button></div></div></>}

      {!me.accounts && <><Sec k="Logins" />
        <p className="ds-gap">No logins yet. This server is bound to <span className="mono">{me.bind}</span>: {me.open ? 'open to this machine only.' : 'closed until the admin exists.'} Logins are never created from the web without an admin. On the server's console: <span className="mono" style={{ color: 'var(--ink)' }}>{me.console_hint.split(': ').pop()}</span></p></>}

      <Sec k="About" />
      <div className="ds-list">
        <div className="r"><span style={{ width: 170, flex: 'none' }}>/architect</span><span className="grow dim" style={{ fontSize: 12.5 }}>Your Anaplan build buddy. Not affiliated with or endorsed by Anaplan. Built by CodelessOps · codelessops.com · MIT licence. If it helps your work, a citation is appreciated (see CITATION.cff). The name, logo and Bert ship with it; a self-run copy may replace them.</span><span className="mono dim" style={{ fontSize: 11 }}>v0.2</span></div>
        {me.notice && me.accounts && <div className="r"><span style={{ width: 170, flex: 'none' }}>This instance</span><span className="grow dim" style={{ fontSize: 12.5 }}>{me.notice}</span></div>}
      </div>
    </div>
  )
}
