// Size (Orac backlog 18): why a model is the size it is. The sizes of lists, time ranges and versions are never
// exported; they are solved from cell counts and shown with how many line items agree. What each axis costs is the
// cells it multiplies in. An over-dimensioned line item applies to an axis its formula never varies over: it repeats
// one value along that axis, and the cells it saves are the cells it would not have without it. Where a model-level
// export leaves Applies To blank (the module's dimensions, unnamed without a Modules export), lists are not compared
// by name and only Time and Versions are judged; the page says so. Every line item is a chip that opens the drawer.
import React, { useEffect, useMemo, useState } from 'react'
import { STATE_LABEL, STATE_PILL, ago, api, fmtC, fmtN, json, pct, type Citation, type SizeItem, type SizeReport } from '../api'
import { useApp } from '../App'
import { CiteChip, Obj, barStyle, type NameIndex } from '../objects'

const cite = (ref: string, id: string | null | undefined, kind: string, model: string, snapshot: string | null | undefined): Citation =>
  ({ id: id || '', kind, model, ref, name: ref, snapshot_id: snapshot || '', provenance: 'observed', tool: '' })

const BUNDLE = /^\[dimensions of (.*)\]$/

/** An axis as a pill: a list name as code, Time and Versions as words, a module's unnamed bundle as the module chip. */
function Axis({ a, idx, tone }: { a: string; idx: NameIndex; tone?: 'amber' | 'dim' | 'sky' }) {
  const m = BUNDLE.exec(a)
  if (m) return <span className={'pill ' + (tone || 'dim')} title="This module's dimensions, unnamed in the export (no Modules export)">dims of <Obj text={m[1]} idx={idx} /></span>
  return <span className={'pill ' + (tone || 'dim')}>{a}</span>
}

const Axes = ({ list, idx, tone }: { list: string[]; idx: NameIndex; tone?: 'amber' | 'dim' | 'sky' }) =>
  <span className="row-chips" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>{list.length ? list.map(a => <Axis key={a} a={a} idx={idx} tone={tone} />) : <span className="muted small">none</span>}</span>

export function SizePage() {
  const { route, summary: s, idx, toast } = useApp()
  const eid = route.eid!
  const sid = s?.snapshot?.id || null
  const models = (s?.models || []).filter(m => !m.retired)
  const [model, setModel] = useState<string>(route.args[0] || '')
  const [rep, setRep] = useState<SizeReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)
  const [kind, setKind] = useState<'all' | 'lists' | 'time' | 'constant'>('all')
  const [showDecided, setShowDecided] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!sid) return
    let live = true; setBusy(true); setErr(null)
    const p = new URLSearchParams(); if (model) p.set('model', model)
    api<SizeReport>(`/api/estates/${eid}/size?` + p.toString()).then(r => { if (live) { setRep(r); if (!model) setModel(r.model) } })
      .catch(e => { if (live) { setErr(e.message); setRep(null) } }).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [eid, sid, model, tick])

  const rows = useMemo(() => {
    if (!rep) return []
    const f = filter.trim().toLowerCase()
    let all = rep.over
    if (kind === 'lists') all = all.filter(r => r.extra.some(a => a !== 'Time' && a !== 'Versions'))
    if (kind === 'time') all = all.filter(r => r.extra.every(a => a === 'Time' || a === 'Versions'))
    if (kind === 'constant') all = all.filter(r => r.constant)
    if (!showDecided) all = all.filter(r => !decided(r))
    if (f) all = all.filter(r => r.ref.toLowerCase().includes(f) || r.formula.toLowerCase().includes(f) || r.extra.some(a => a.toLowerCase().includes(f)))
    return showAll ? all : all.slice(0, 60)
  }, [rep, filter, kind, showAll, showDecided])

  if (!s) return null
  if (!s.snapshot) return <div><div className="kicker">Estate</div><h1>{s.name}</h1><h2>Size</h2><div className="card muted">No active snapshot. Upload and activate one on Home.</div></div>
  const o = rep?.over_summary
  const total = rep?.cells || 0

  return (
    <div>
      <div className="kicker">Estate</div>
      <h1>{s.name}</h1>
      <h2>Size</h2>
      <p className="muted small">Why a model is the size it is. List, time-range and version sizes are never exported: they are solved from cell counts and shown with how many line items agree. An over-dimensioned line item applies to an axis its formula never varies over, so it repeats one value along it; the cells it would not have without that axis are what it saves. Whether the repetition is wanted is the owner's call.</p>

      <div className="deps-head">
        <div><label className="kicker">Model</label><select value={model} onChange={e => { setModel(e.target.value); setShowAll(false) }}>{!model && <option value="">largest</option>}{models.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}</select></div>
        <div className="grow" />
        {busy && <span className="muted small">Reading the model…</span>}
      </div>

      {err && <div className="card"><div className="warn">{err}</div></div>}

      {rep && o && <>
        <div className="tiles">
          <div className="tile"><div className="k">Cells</div><div className="v">{rep.has_cells ? fmtC(total) : '—'}</div><div className="small muted">{fmtN(rep.line_items)} line items · {fmtN(rep.calculated)} calculated</div></div>
          <div className="tile"><div className="k">Over-dimensioned</div><div className="v">{fmtN(o.items)}</div><div className="small muted">{o.constant ? `${o.constant} constants · ` : ''}{fmtC(o.cells)} cells{o.decided ? ` · ${o.decided} decided` : ''}</div></div>
          <div className="tile"><div className="k">Cells to save</div><div className="v" style={{ color: o.saved ? 'var(--amber)' : undefined }}>{o.saved ? fmtC(o.saved) : '—'}</div><div className="small muted">{o.priced} priced{o.unpriced ? ` · ${o.unpriced} unpriced` : ''}{total && o.saved ? ` · ${pct(o.saved / total)} of the model` : ''}</div></div>
          <div className="tile"><div className="k">Sizes explain</div><div className="v">{rep.explained.share != null ? pct(rep.explained.share) : '—'}</div><div className="small muted">{fmtN(rep.explained.items)} of {fmtN(rep.explained.of)} cell counts reproduced exactly</div></div>
          <div className="tile"><div className="k">Lists judged</div><div className="v">{o.lists_unjudged ? fmtN(Math.max(0, rep.calculated - o.lists_unjudged)) : fmtN(rep.calculated)}</div><div className="small muted">{o.lists_unjudged ? `${fmtN(o.lists_unjudged)} on Time and Versions only` : 'every calculated line item, by name'}</div></div>
        </div>

        <ul className="gaps">{rep.coverage.map((x, i) => <li key={i}>{x}</li>)}</ul>

        <h3>What each axis costs</h3>
        <div className="card scroll" style={{ padding: '2px 12px 8px', marginBottom: 16 }}>
          <table>
            <thead><tr><th>Axis</th><th>Kind</th><th className="num">Size</th><th className="num">Line items</th><th className="num">Cells carrying it</th><th className="num">Cells it multiplies</th><th className="num">Of the model</th></tr></thead>
            <tbody>{rep.axes.slice(0, 40).map(a => <tr key={a.axis}>
              <td><Axis a={a.axis} idx={idx} tone={a.kind === 'time' || a.kind === 'versions' ? 'sky' : 'dim'} /></td>
              <td className="small muted">{a.kind === 'module' ? 'module dimensions' : a.kind}</td>
              <td className="num">{a.size != null ? fmtN(a.size) : <span className="muted">?</span>}{a.size_note && <div className="small muted" style={{ whiteSpace: 'normal' }}>{a.size_note}</div>}</td>
              <td className="num">{fmtN(a.items)}</td><td className="num">{fmtN(a.cells)}</td>
              <td className="num">{a.marginal ? fmtN(a.marginal) : <span className="muted">{a.unpriced_items ? 'unsized' : '—'}</span>}</td>
              <td className="num bar" style={barStyle(total && a.marginal ? a.marginal / total : 0)}>{total && a.marginal ? pct(a.marginal / total) : ''}</td>
            </tr>)}</tbody>
          </table>
          <div className="small muted" style={{ marginTop: 6 }}>Cells it multiplies: the cells of every line item carrying the axis, less what they would be without it. Axes overlap, so the column does not add up to the model.</div>
        </div>

        <details style={{ marginBottom: 16 }}>
          <summary className="small" style={{ cursor: 'pointer' }}>Sizes solved from cell counts ({rep.sizes.length}) · never exported; each shown with the line items that agree</summary>
          <div className="card scroll" style={{ padding: '2px 12px 8px', marginTop: 8 }}>
            <table>
              <thead><tr><th>Factor</th><th>Kind</th><th className="num">Size</th><th className="num">Line items</th><th className="num">Agree</th><th /></tr></thead>
              <tbody>{rep.sizes.map(f => <tr key={f.factor}>
                <td><Axis a={f.factor} idx={idx} /></td><td className="small muted">{f.kind === 'mod' ? 'module dimensions' : f.kind === 'dim' ? 'list' : f.kind}</td>
                <td className="num">{fmtN(f.size)}</td><td className="num">{fmtN(f.items)}</td>
                <td className="num">{f.agreement != null ? `${f.evidence} · ${pct(f.agreement)}` : <span className="muted">—</span>}</td>
                <td>{f.assumed && <span className="pill amber" title="Follows from taking a module nothing isolates as carrying no dimension">assumed</span>}{f.agreement != null && f.agreement < 0.9 && !f.assumed && <span className="pill amber" title="Line items disagree on this size: subsets, summaries or hierarchy levels in play">disputed</span>}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </details>

        <h3>Over-dimensioned line items <span className="muted small">({fmtN(o.items)}{rep.shown < o.items ? `, first ${rep.shown}` : ''})</span></h3>
        <div className="deps-head">
          <div className="grow"><input value={filter} placeholder="Filter by name, formula or axis" onChange={e => setFilter(e.target.value)} /></div>
          <div className="seg">
            <button className={kind === 'all' ? 'on' : ''} onClick={() => setKind('all')}>all</button>
            <button className={kind === 'time' ? 'on' : ''} onClick={() => setKind('time')} title="Time or Versions applied, never needed">Time / Versions</button>
            <button className={kind === 'lists' ? 'on' : ''} onClick={() => setKind('lists')} title="A list applied, never needed">lists</button>
            <button className={kind === 'constant' ? 'on' : ''} onClick={() => setKind('constant')} title="A constant or a scalar repeated along every axis">constants</button>
          </div>
          <label className="small" style={{ display: 'flex', alignItems: 'center', gap: 6 }} title="Rows you marked keep current design or done are kept apart; the architect does not raise them again"><input type="checkbox" checked={showDecided} onChange={e => setShowDecided(e.target.checked)} /> show decided{o.decided ? ` (${o.decided})` : ''}</label>
        </div>
        <div className="card scroll" style={{ padding: '2px 12px 8px' }}>
          <table>
            <thead><tr><th>Line item</th><th>Applies to</th><th>Formula needs</th><th>Not needed</th><th className="num">Cells</th><th className="num">Saved</th><th>Decision</th><th>Note</th></tr></thead>
            <tbody>
              {!rows.length && <tr><td colSpan={8} className="muted small">{o.items ? (showDecided ? 'Nothing matches.' : 'Nothing open: every row that matches carries a decision (show decided to see them).') : 'No line item applies to an axis its formula does not need.'}</td></tr>}
              {rows.map(r => <SizeRow key={r.ref} r={r} model={rep.model} snapshot={sid} idx={idx} eid={eid} onSaved={() => setTick(t => t + 1)} />)}
            </tbody>
          </table>
          {!showAll && rows.length === 60 && <button className="small quiet" onClick={() => setShowAll(true)}>show every line item</button>}
        </div>
        {Object.keys(rep.not_judged).length > 0 && <div className="small muted" style={{ marginTop: 8 }}>Not judged: {Object.entries(rep.not_judged).map(([k, v]) => `${v} ${k}`).join(' · ')}.</div>}
        <ul className="gaps dim">{rep.limits.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </>}
    </div>
  )
}

const decided = (r: SizeItem) => !!r.decision && (r.decision.state === 'keep_current_design' || r.decision.state === 'done')

function SizeRow({ r, model, snapshot, idx, eid, onSaved }: { r: SizeItem; model: string; snapshot: string | null; idx: NameIndex; eid: string; onSaved: () => void }) {
  const { toast } = useApp()
  const [open, setOpen] = useState(false)
  const [st, setSt] = useState(r.decision?.state || 'keep_current_design')
  const [why, setWhy] = useState(r.decision?.reason || '')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setSt(r.decision?.state || 'keep_current_design'); setWhy(r.decision?.reason || '') }, [r.decision?.state, r.decision?.reason])
  async function save() {
    setBusy(true)
    try { await api(`/api/estates/${eid}/size/state`, json('PUT', { model, ref: r.ref, state: st, reason: why })); setOpen(false); onSaved() }
    catch (e: any) { toast(e.message) } finally { setBusy(false) }
  }
  const d = r.decision
  return (
    <>
    <tr className={decided(r) ? 'decided' : ''}>
      <td><CiteChip c={cite(r.ref, r.id, 'line_item', model, snapshot)} idx={idx} /><div className="small muted" style={{ fontFamily: 'var(--mono)', fontSize: 11, maxWidth: 360, overflowWrap: 'anywhere' }}>{r.formula}</div></td>
      <td><Axes list={r.applied} idx={idx} /></td>
      <td><Axes list={r.required} idx={idx} /></td>
      <td><Axes list={r.extra} idx={idx} tone="amber" /></td>
      <td className="num">{fmtN(r.cells)}</td>
      <td className="num">{r.saved_cells != null ? <><b>{fmtN(r.saved_cells)}</b>{r.price_assumed && <span className="pill amber" style={{ marginLeft: 4 }} title="Rests on a size that follows from an assumption; see the sizes table">assumed</span>}</> : <span className="muted" title={r.unpriced.length ? 'unsized: ' + r.unpriced.join(', ') : 'which axis is unneeded cannot be told'}>?</span>}</td>
      <td className="small" style={{ maxWidth: 220, whiteSpace: 'normal' }}>
        {d ? <><span className={'pill ' + (STATE_PILL[d.state] ?? 'dim')}>{STATE_LABEL[d.state] || d.state}</span><div className="muted">{d.reason}{d.updated ? ` · ${d.by || 'local'} · ${ago(d.updated)}` : ''}</div></> : <span className="muted">none</span>}
        {' '}<button className="small quiet" onClick={() => setOpen(!open)}>{open ? 'Close' : d ? 'Change' : 'Decide'}</button>
      </td>
      <td className="small muted" style={{ maxWidth: 260, whiteSpace: 'normal' }}>{r.constant ? 'constant · ' : ''}{r.partial ? 'partly: ' : ''}{!r.lists_judged ? 'Time and Versions judged; lists unnamed' : ''}{r.implicit.length ? ` · aggregated implicitly: ${r.implicit.join(', ')}` : ''}{r.reason && r.lists_judged && !r.constant ? r.reason : ''}</td>
    </tr>
    {open && <tr><td colSpan={8}>
      <div className="state">
        <select value={st} onChange={e => setSt(e.target.value)}>{Object.entries(STATE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <textarea value={why} placeholder="Your reasoning: kept with the decision, read by the architect, not raised again" onChange={e => setWhy(e.target.value)} />
        <button className="primary small" disabled={busy || !why.trim()} onClick={save}>Record</button>
      </div>
      <div className="meta">Keep current design or done takes the row off the open list; the architect sees it under decided with your reason. A decision verifies nothing in Anaplan.</div>
    </td></tr>}
    </>
  )
}
