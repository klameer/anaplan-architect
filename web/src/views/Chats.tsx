import React, { useCallback, useEffect, useRef, useState } from 'react'
import { ago, api, fmtUsd, json, plain, when, type ConvHead } from '../api'
import { href, useApp } from '../App'
import { Inline } from '../objects'

export function Chats() {
  const { route, summary: s, idx, refresh, toast } = useApp()
  const [q, setQ] = useState('')
  const [archived, setArchived] = useState(false)
  const [rows, setRows] = useState<ConvHead[] | null>(null)
  const eid = route.eid!
  const seq = useRef(0)
  const load = useCallback(async () => {
    const p = new URLSearchParams(); if (q) p.set('q', q); p.set('archived', archived ? 'true' : 'false')
    const n = ++seq.current                                              // only the newest request may set the rows: a slow "cash" must not overwrite "cash flow"
    try { const r = await api<ConvHead[]>('/api/estates/' + eid + '/conversations?' + p.toString()); if (n === seq.current) setRows(r) } catch (e: any) { if (n === seq.current) toast(e.message) }
  }, [eid, q, archived, toast])
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t) }, [load])
  if (!s) return null
  async function patch(id: string, body: any) { try { await api('/api/conversations/' + id, json('PATCH', body)); await load(); await refresh() } catch (e: any) { toast(e.message) } }
  async function del(c: ConvHead) {
    if (!confirm(`Delete this conversation?\n\n${plain(c.title)}\n\nIts export moves to the estate's deleted folder.`)) return
    try { await api('/api/conversations/' + c.id, { method: 'DELETE' }); await load(); await refresh() } catch (e: any) { toast(e.message) }
  }
  const total = (rows || []).reduce((n, c) => n + (c.cost_usd || 0), 0)
  return (
    <div>
      <div className="kicker">{s.name}</div>
      <h1>Chats</h1>
      <p className="muted small">{(rows || []).length} conversation{(rows || []).length !== 1 ? 's' : ''}{archived ? ' archived' : ''}{total ? `, ${fmtUsd(total)} at list price` : ''}. Search covers titles, questions and answers. The architect resumes any of them with its history and the notes for its scope.</p>
      <div className="row" style={{ gridTemplateColumns: '2fr auto', maxWidth: 640 }}>
        <div><input placeholder="Search conversations" value={q} onChange={e => setQ(e.target.value)} /></div>
        <div><label className="small muted" style={{ fontFamily: 'var(--sans)', textTransform: 'none', letterSpacing: 0 }}><input type="checkbox" checked={archived} onChange={e => setArchived(e.target.checked)} />archived</label></div>
      </div>
      <div className="card scroll" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>Conversation</th><th>Scope</th><th className="num">Turns</th><th className="num">Cost</th><th>Last activity</th><th></th></tr></thead>
          <tbody>
            {rows === null && <tr><td colSpan={6} className="muted">Loading…</td></tr>}
            {rows && !rows.length && <tr><td colSpan={6} className="muted">{q ? 'No match.' : archived ? 'Nothing archived.' : 'None yet. Ask something on Home.'}</td></tr>}
            {(rows || []).map(c => <tr key={c.id}>
              <td><a href={href(eid, 'chat', c.id)}><Inline text={c.title} idx={idx} /></a>
                {c.branched_from && <span className="pill dim" style={{ marginLeft: 6 }} title="A re-evaluation of an earlier conversation on a newer snapshot">re-evaluation</span>}
                {c.branches ? <span className="pill dim" style={{ marginLeft: 6 }} title="Re-evaluated on a newer snapshot as a linked branch">{c.branches} branch{c.branches !== 1 ? 'es' : ''}</span> : null}
                {c.snapshot && s.snapshot && c.snapshot !== s.snapshot.id && <span className="pill amber" style={{ marginLeft: 6 }} title="Held on a snapshot the estate no longer reads; asks how to go on before it answers again">earlier snapshot</span>}</td>
              <td className="small muted">{c.scope?.model ? c.scope.model + (c.scope.module ? ' / ' + c.scope.module : '') : 'estate'}</td>
              <td className="num">{c.turns}</td><td className="num">{c.cost_usd ? fmtUsd(c.cost_usd) : (c.turns ? 'subscription' : '')}</td>
              <td className="small muted" title={when(c.updated || c.created)}>{ago(c.updated || c.created)}</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                <button className="small" onClick={() => { const t = prompt('Rename:', plain(c.title)); if (t && t.trim()) patch(c.id, { title: t.trim() }) }}>Rename</button>{' '}
                <button className="small" onClick={() => patch(c.id, { archived: !c.archived })}>{c.archived ? 'Unarchive' : 'Archive'}</button>{' '}
                <a href={`/api/conversations/${c.id}/export`} target="_blank" rel="noreferrer"><button className="small">.md</button></a>{' '}
                <button className="small" onClick={() => del(c)}>Delete</button>
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
