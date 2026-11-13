// The Notes tab: the knowledge base as one page. What the owner has established (notes: purposes, decisions, constraints,
// procedures, conclusions, each a working assumption until confirmed, each carrying the evidence it rests on) and what the
// owner has ruled (decisions: pattern statuses, action and proposal states, connections confirmed or retired, Size rows kept
// or done), every decision with its reason, who and when. The architect reads both.
import React, { useEffect, useState } from 'react'
import { STATE_LABEL, STATE_PILL, ago, api } from '../api'
import { href, useApp } from '../App'
import { Obj } from '../objects'
import { NotesSection } from './Knowledge'

type Decision = { key: string; kind: 'pattern' | 'action' | 'proposal' | 'connection' | 'size'; label: string; state: string; reason: string; by: string | null; updated: string
  snapshot_id: string | null; model?: string | null; to?: string | null; rule?: string | null; object: { kind: string; model: string | null; ref: string } | null }

const KIND_LABEL: Record<string, string> = { pattern: 'pattern', action: 'action', proposal: 'proposal', connection: 'connection', size: 'size row' }
const PATTERN_PILL: Record<string, string> = { deliberate: 'violet', accepted: '', fixed: '', wont_fix: 'off', incorrect: 'off', open: 'dim' }
const PATTERN_LABEL: Record<string, string> = { deliberate: 'deliberate', accepted: 'accepted', fixed: 'fixed', wont_fix: "won't fix", incorrect: 'incorrect', open: 'open' }

export function NotesPage() {
  const { summary: s } = useApp()
  if (!s) return null
  return (
    <div>
      <div className="kicker">Estate</div>
      <h1>{s.name}</h1>
      <NotesSection />
      <Decisions />
    </div>
  )
}

function statePill(d: Decision) {
  if (d.kind === 'pattern') return <span className={'pill ' + (PATTERN_PILL[d.state] ?? 'dim')}>{PATTERN_LABEL[d.state] || d.state}</span>
  if (d.kind === 'connection') return <span className={'pill ' + (d.state === 'confirmed' ? '' : 'off')}>{d.state}</span>
  return <span className={'pill ' + (STATE_PILL[d.state] ?? 'dim')}>{STATE_LABEL[d.state] || d.state}</span>
}

/** Every decision the owner has recorded on the estate, newest first, with a way to the object it is about. */
function Decisions() {
  const { route, summary: s, idx, openEvidence, toast } = useApp()
  const [rows, setRows] = useState<Decision[] | null>(null)
  const [kind, setKind] = useState('')
  const eid = route.eid!
  const sid = s?.snapshot?.id
  useEffect(() => {
    if (!sid) { setRows([]); return }
    let live = true
    api<Decision[]>(`/api/estates/${eid}/decisions`).then(r => { if (live) setRows(r) }).catch(e => toast(e.message))
    return () => { live = false }
  }, [eid, sid, toast])
  const shown = (rows || []).filter(d => !kind || d.kind === kind)
  const counts = (rows || []).reduce<Record<string, number>>((m, d) => { m[d.kind] = (m[d.kind] || 0) + 1; return m }, {})
  return (
    <div style={{ marginTop: 28 }}>
      <h2>Decisions</h2>
      <p className="muted small">What the owner has ruled, in one place: a pattern marked deliberate or accepted, an action taken on or kept as it is, a connection confirmed or retired, a Size row kept or done. Each carries the reason, who recorded it and when. The architect cites the decision, not its own memory; a decision verifies nothing in Anaplan.</p>
      <div className="deps-head">
        <div className="seg">
          <button className={kind === '' ? 'on' : ''} onClick={() => setKind('')}>all{rows ? ` (${rows.length})` : ''}</button>
          {(['pattern', 'action', 'proposal', 'connection', 'size'] as const).map(k => <button key={k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>{KIND_LABEL[k]}{counts[k] ? ` (${counts[k]})` : ''}</button>)}
        </div>
      </div>
      <div className="card scroll" style={{ padding: '2px 12px 8px' }}>
        <table>
          <thead><tr><th>What</th><th>Kind</th><th>Decision</th><th>Reason</th><th>By</th><th>When</th></tr></thead>
          <tbody>
            {rows === null && <tr><td colSpan={6} className="muted small">Loading…</td></tr>}
            {rows && !shown.length && <tr><td colSpan={6} className="muted small">{rows.length ? 'Nothing of that kind.' : 'No decisions recorded yet. Mark a pattern in the drawer, take an action on from the Action plan, confirm a connection on Home, or decide a Size row.'}</td></tr>}
            {shown.map(d => <tr key={d.key}>
              <td>
                {d.kind === 'pattern' && d.object && <a href="#" onClick={e => { e.preventDefault(); openEvidence({ ref: d.object!.ref, kind: 'pattern', model: d.object!.model }) }}>{d.label}</a>}
                {d.kind === 'pattern' && <div className="small muted">{d.rule}{d.model ? ' · ' + d.model : ''}</div>}
                {d.kind === 'connection' && <><Obj text={d.model || ''} idx={idx} /> → <Obj text={d.to || ''} idx={idx} /></>}
                {d.kind === 'size' && <><Obj text={d.label} idx={idx} /> <a className="small" href={`#/e/${eid}/size/${encodeURIComponent(d.model || '')}`}>Size →</a></>}
                {(d.kind === 'action' || d.kind === 'proposal') && <><a href={href(eid, 'plan')}>{d.label}</a>{d.model && <div className="small muted">{d.model}</div>}</>}
              </td>
              <td><span className="pill dim">{KIND_LABEL[d.kind]}</span></td>
              <td>{statePill(d)}</td>
              <td className="small" style={{ maxWidth: 360, whiteSpace: 'normal' }}>{d.reason || <span className="muted">no reason given</span>}</td>
              <td className="small muted">{d.by || 'local'}</td>
              <td className="small muted" title={d.updated}>{ago(d.updated)}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  )
}
