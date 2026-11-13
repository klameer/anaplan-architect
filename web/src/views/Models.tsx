import React, { useEffect, useRef, useState } from 'react'
import { ago, api, day, fmtB, fmtC, fmtN, json, pct, when, type Coverage, type Edge, type ModelRow, type Snapshot } from '../api'
import { useApp } from '../App'
import { ModelChip, barStyle } from '../objects'

const KIND: Record<string, string> = { line_items: 'Line Items', actions: 'Actions', modules: 'Modules' }
const STAGEABLE = ['draft', 'processed', 'failed']
const PILL: Record<string, string> = { draft: 'dim', processing: 'amber', processed: '', active: '', failed: 'off', superseded: 'dim' }

export function ModelsSection() {
  const { route, summary: s, refresh, toast } = useApp()
  const [editing, setEditing] = useState<string | null>(null)
  const [covFor, setCovFor] = useState<string | null>(null)
  const [sid, setSid] = useState<string | null>(null)
  async function delSnap(id: string, status: string) {
    if (!confirm(status === 'superseded' ? 'Delete this superseded snapshot? Nothing points at it any more; its export files go with it if no other snapshot holds them.' : 'Delete this snapshot and its staged files?')) return
    try { const r = await api<{ blobs_removed: number }>('/api/snapshots/' + id, { method: 'DELETE' }); await refresh(); toast(`Snapshot deleted${r.blobs_removed ? `; ${r.blobs_removed} export file${r.blobs_removed !== 1 ? 's' : ''} removed` : ''}.`) } catch (e: any) { toast(e.message) }
  }
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const timer = useRef<number | null>(null)
  const eid = route.eid!

  async function openSnap(id: string) {
    setSid(id)
    try { const x = await api<Snapshot>('/api/snapshots/' + id); setSnap(x); if (x.running || x.run?.status === 'running') poll(id) } catch (e: any) { toast(e.message) }
  }
  function poll(id: string) {
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      try {
        const x = await api<Snapshot>('/api/snapshots/' + id); setSnap(x)
        if (x.running || x.run?.status === 'running') poll(id)
        else await refresh()
      } catch (e: any) { toast(e.message) }
    }, 1500)
  }
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])
  if (!s) return null

  async function addModel() {
    const name = prompt('Model name, as you want it shown (import action names that call it something else go in aliases):')
    if (!name || !name.trim()) return
    try { await api('/api/estates/' + eid + '/models', json('POST', { name })); await refresh() } catch (e: any) { toast(e.message) }
  }

  const line = s.snapshot
    ? <>Active snapshot <b>{s.snapshot.label || s.snapshot.id}</b>, activated {when(s.snapshot.activated_at)}, {s.snapshot.files} file{s.snapshot.files !== 1 ? 's' : ''}. Each model reads the files dated below; a date that differs from its neighbours is an export taken at another time.</>
    : <>No active snapshot. Register models here, then upload their exports below.</>

  const cellsTotal = s.models.filter(m => !m.retired).reduce((a, m) => a + (m.cells || 0), 0)   // the bar behind Cells: each model's share of the estate
  return (
    <div>
      <h2>Models and uploads</h2>
      <p className="muted small">{line}</p>
      <div className="card scroll">
        <table>
          <thead><tr><th>Model</th><th>Purpose</th><th>Owner</th><th>Aliases in import names</th><th>Line Items export</th><th>Actions export</th><th>Modules export</th><th className="num">Modules</th><th className="num">Line items</th><th className="num">Cells</th><th className="num">Parse</th><th className="num">Agrees</th><th>Coverage</th><th></th></tr></thead>
          <tbody>
            {!s.models.length && <tr><td colSpan={14} className="muted">No models registered.</td></tr>}
            {s.models.map(m => editing === m.id
              ? <EditRow key={m.id} m={m} onDone={async () => { setEditing(null); await refresh() }} />
              : <ModelTr key={m.id} m={m} total={cellsTotal} onEdit={() => setEditing(m.id)} onCov={() => setCovFor(covFor === m.id ? null : m.id)} />)}
          </tbody>
        </table>
        {s.snapshot && <Connections />}
        <div className="actions"><button onClick={addModel}>Add a model</button></div>
        {covFor && <CoverageView m={s.models.find(x => x.id === covFor)!} />}
      </div>

      <Upload onStaged={id => openSnap(id)} openSid={snap && STAGEABLE.includes(snap.status) ? snap.id : null} />

      {snap && sid && <SnapshotPanel snap={snap} onChange={x => setSnap(x)} onProcess={() => poll(snap.id)} onClose={() => { setSid(null); setSnap(null) }} />}

      {s.snapshots.length > 0 && <>
        <h2>Snapshot history</h2>
        <div className="card scroll"><table>
          <thead><tr><th>Snapshot</th><th>Status</th><th>Created</th><th>Activated</th><th className="num">Models / files</th><th>Last parse</th><th>Kept for</th><th></th></tr></thead>
          <tbody>{s.snapshots.map(x => (
            <tr key={x.id}>
              <td><a href="#" onClick={e => { e.preventDefault(); openSnap(x.id) }}>{x.label || x.id}</a></td>
              <td><span className={'pill ' + (PILL[x.status] || 'dim')}>{x.status}</span></td>
              <td>{when(x.created)}</td><td>{when(x.activated_at)}</td>
              <td className="num">{x.model_count} / {x.file_count}</td>
              <td className={'small ' + (x.run_status === 'failed' ? 'bad' : 'muted')}>{x.run_status || 'not run'}{x.run_error ? ': ' + x.run_error.slice(0, 90) : ''}</td>
              <td className="small muted">{x.status === 'active' ? 'the estate reads it' : x.status === 'superseded'
                ? (x.held_conversations || x.citations ? `${x.held_conversations} conversation${x.held_conversations !== 1 ? 's' : ''} held on it, ${x.citations} citation${x.citations !== 1 ? 's' : ''} read on it` : 'nothing points at it')
                : ''}</td>
              <td>{x.deletable && <button className="small" onClick={() => delSnap(x.id, x.status)}>Delete</button>}</td>
            </tr>))}</tbody>
        </table></div>
        <p className="small muted">A superseded snapshot stays while a conversation is held on it or a citation was read on it, so every old answer still opens the evidence it rests on. When nothing points at it, it can go.</p>
      </>}
    </div>
  )
}

function FileCell({ f }: { f?: { uploaded_at: string; original_name: string; bytes: number; problem: string | null } }) {
  if (!f) return <span className="muted">—</span>
  return <><span title={`${f.original_name} · ${fmtB(f.bytes)}`}>{day(f.uploaded_at)}</span>{f.problem && <span className="bad" title={f.problem}> !</span>}</>
}

function ModelTr({ m, total, onEdit, onCov }: { m: ModelRow; total: number; onEdit: () => void; onCov: () => void }) {
  const share = total && m.cells ? m.cells / total : 0
  const c = m.coverage
  const n = c ? (c.rules_skipped || []).length + (c.warnings || []).length + (c.missing_columns || []).length : 0
  return (
    <tr className={m.retired ? 'retired' : ''}>
      <td><ModelChip name={m.name} />{m.retired && <span className="pill dim" style={{ marginLeft: 6 }}>retired</span>}</td>
      <td>{m.purpose}</td><td>{m.owner}</td><td className="small muted">{(m.aliases || []).join('; ')}</td>
      <td><FileCell f={m.files?.line_items} /></td><td><FileCell f={m.files?.actions} /></td><td><FileCell f={m.files?.modules} /></td>
      <td className="num">{m.modules ?? ''}</td><td className="num">{fmtN(m.line_items)}</td><td className="num bar" style={barStyle(share)} title={share ? `${pct(share)} of the estate's cells` : undefined}>{fmtC(m.cells)}</td>
      <td className="num">{c ? pct(c.parse_rate) : ''}</td><td className="num">{c && c.referenced_by_agreement != null ? pct(c.referenced_by_agreement) : ''}</td>
      <td>{c ? <a href="#" onClick={e => { e.preventDefault(); onCov() }}>{n ? `${n} note${n !== 1 ? 's' : ''}` : 'complete'}</a> : <span className="muted">—</span>}</td>
      <td><button className="small" onClick={onEdit}>Edit</button></td>
    </tr>
  )
}

function EditRow({ m, onDone }: { m: ModelRow; onDone: () => void }) {
  const { toast } = useApp()
  const [v, setV] = useState({ name: m.name, purpose: m.purpose, owner: m.owner, aliases: (m.aliases || []).join('; '), retired: m.retired })
  async function save() {
    try { await api('/api/models/' + m.id, json('PATCH', v)); onDone() } catch (e: any) { toast(e.message) }
  }
  return (
    <tr>
      <td><input value={v.name} onChange={e => setV({ ...v, name: e.target.value })} /></td>
      <td><input value={v.purpose} placeholder="what this model is for" onChange={e => setV({ ...v, purpose: e.target.value })} autoFocus /></td>
      <td><input value={v.owner} placeholder="who owns it" onChange={e => setV({ ...v, owner: e.target.value })} /></td>
      <td><input value={v.aliases} placeholder="phrase; phrase" onChange={e => setV({ ...v, aliases: e.target.value })} /></td>
      <td colSpan={9}><label className="small muted"><input type="checkbox" checked={v.retired} onChange={e => setV({ ...v, retired: e.target.checked })} />retired (kept in history, left out of new snapshots and the picker)</label></td>
      <td style={{ whiteSpace: 'nowrap' }}><button className="small primary" onClick={save}>Save</button> <button className="small" onClick={onDone}>Cancel</button></td>
    </tr>
  )
}

function CoverageView({ m }: { m: ModelRow }) {
  const c = m.coverage as Coverage | null
  if (!c) return null
  const li = (xs: any[]) => xs && xs.length ? xs.map((x, i) => <li key={i}>{Array.isArray(x) ? x[0] + ': ' + x[1] : String(x)}</li>) : <li className="muted">none</li>
  return (
    <div className="cov">
      <h3>Coverage · {m.name}</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
        <div><div className="kicker">Files read</div><ul>{li(Object.entries(c.files || {}).filter(([, v]) => v).map(([k, v]) => KIND[k] + ': ' + v))}</ul><div className="kicker">Rules run</div><ul><li>{(c.rules_run || []).length} rules</li></ul></div>
        <div><div className="kicker">Skipped, and why</div><ul>{li(c.rules_skipped)}</ul></div>
        <div><div className="kicker">Warnings and missing columns</div><ul>{li([...(c.warnings || []), ...(c.missing_columns || [])])}</ul></div>
        <div><div className="kicker">Confirmed by the exports</div><ul>{li(c.confirmed)}</ul></div>
        <div><div className="kicker">Inferred</div><ul>{li(c.inferred)}</ul></div>
        <div><div className="kicker">Not in any export</div><ul>{li(c.missing)}</ul></div>
      </div>
    </div>
  )
}

type UpRow = { id: number; model: string; name: string; li: File | null; ac: File | null; mo: File | null }

function Upload({ onStaged, openSid }: { onStaged: (sid: string) => void; openSid: string | null }) {
  const { route, summary: s, refresh, toast } = useApp()
  const [rows, setRows] = useState<UpRow[]>([{ id: 1, model: '', name: '', li: null, ac: null, mo: null }])
  const [zip, setZip] = useState<File | null>(null)
  const [label, setLabel] = useState('')
  const [fresh, setFresh] = useState(false)
  const [busy, setBusy] = useState(false)
  const models = (s?.models || []).filter(m => !m.retired)
  const upd = (id: number, patch: Partial<UpRow>) => setRows(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))

  async function stage() {
    const used = rows.filter(r => r.li || r.ac || r.mo)
    if (!used.length && !zip) { toast('Choose at least one file'); return }
    const fd = new FormData(); fd.append('label', label); fd.append('fresh', fresh ? 'true' : 'false')
    for (const r of used) {
      fd.append('model_ids', r.model); fd.append('model_names', r.model ? '' : (r.name || (r.li ? r.li.name.replace(/\.csv$/i, '') : '')))
      fd.append('line_items', r.li || new Blob([]), r.li ? r.li.name : ''); fd.append('actions', r.ac || new Blob([]), r.ac ? r.ac.name : ''); fd.append('modules', r.mo || new Blob([]), r.mo ? r.mo.name : '')
    }
    if (zip) fd.append('zip', zip, zip.name)
    setBusy(true)
    try {
      const snap = await api<Snapshot>(openSid ? '/api/snapshots/' + openSid + '/files' : '/api/estates/' + route.eid + '/snapshots', { method: 'POST', body: fd })
      setRows([{ id: Date.now(), model: '', name: '', li: null, ac: null, mo: null }]); setZip(null)
      await refresh(); onStaged(snap.id)
    } catch (e: any) { toast(e.message) }
    finally { setBusy(false) }
  }

  return (
    <>
      <h2>Upload new exports</h2>
      <p className="muted small">Uploads go into a <b>draft snapshot</b> that starts as a copy of the active one, so one model can be refreshed on its own. Every file is checked as it arrives; the draft is then processed and, if it parses, activated. Until you activate it, the estate keeps reading the current snapshot.{openSid ? <> Files chosen now are added to the open draft.</> : null}</p>
      <div className="card up">
        {rows.map(r => (
          <div key={r.id} className="row five">
            <div><label>Model</label><select value={r.model} onChange={e => upd(r.id, { model: e.target.value })}><option value="">New model…</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></div>
            <div hidden={!!r.model}><label>New model name</label><input value={r.name} placeholder="as it should be shown" onChange={e => upd(r.id, { name: e.target.value })} /></div>
            <div><label>Line Items.csv</label><input type="file" accept=".csv" onChange={e => upd(r.id, { li: e.target.files?.[0] || null })} /></div>
            <div><label>Actions.csv</label><input type="file" accept=".csv" onChange={e => upd(r.id, { ac: e.target.files?.[0] || null })} /></div>
            <div><label>Modules.csv</label><input type="file" accept=".csv" onChange={e => upd(r.id, { mo: e.target.files?.[0] || null })} /></div>
            <button onClick={() => setRows(rs => rs.filter(x => x.id !== r.id))}>×</button>
          </div>
        ))}
        <div><button onClick={() => setRows(rs => [...rs, { id: Date.now(), model: '', name: '', li: null, ac: null, mo: null }])}>Add a row</button></div>
        <div className="row" style={{ gridTemplateColumns: '1.2fr 1fr 1.4fr auto' }}>
          <div><label>Or a zip of the whole estate (one folder per model)</label><input type="file" accept=".zip" onChange={e => setZip(e.target.files?.[0] || null)} /></div>
          <div><label>Label</label><input value={label} placeholder="e.g. October exports" onChange={e => setLabel(e.target.value)} /></div>
          <div><label>&nbsp;</label><label className="small muted" style={{ fontFamily: 'var(--sans)', textTransform: 'none', letterSpacing: 0 }}><input type="checkbox" checked={fresh} onChange={e => setFresh(e.target.checked)} />Start empty: do not copy the active snapshot's files</label></div>
          <div><button className="primary" disabled={busy} onClick={stage}>{busy ? 'Checking files…' : openSid ? 'Add to the draft' : 'Stage files'}</button></div>
        </div>
      </div>
    </>
  )
}

function SnapshotPanel({ snap, onChange, onProcess, onClose }: { snap: Snapshot; onChange: (s: Snapshot) => void; onProcess: () => void; onClose: () => void }) {
  const { refresh, toast } = useApp()
  const busy = snap.running || snap.run?.status === 'running'
  const stageable = STAGEABLE.includes(snap.status)
  const can = stageable && !(snap.ready || []).length && !busy
  const run = snap.run
  async function process() { try { await api('/api/snapshots/' + snap.id + '/process', { method: 'POST' }); onChange(await api('/api/snapshots/' + snap.id)); onProcess() } catch (e: any) { toast(e.message) } }
  async function cancel() { try { await api('/api/snapshots/' + snap.id + '/cancel', { method: 'POST' }); toast('Cancel requested: the result of this run will be discarded when the engine returns.') } catch (e: any) { toast(e.message) } }
  async function activate() { try { await api('/api/snapshots/' + snap.id + '/activate', { method: 'POST' }); await refresh(); onClose(); toast('Activated. The estate now reads this snapshot.') } catch (e: any) { toast(e.message) } }
  async function del() { if (!confirm('Delete this draft snapshot and its staged files?')) return; try { await api('/api/snapshots/' + snap.id, { method: 'DELETE' }); await refresh(); onClose() } catch (e: any) { toast(e.message) } }
  async function unstage(mid: string, kind: string) { try { onChange(await api('/api/snapshots/' + snap.id + '/files/' + mid + '?kind=' + kind, { method: 'DELETE' })) } catch (e: any) { toast(e.message) } }
  return (
    <>
      <h2>Snapshot · {snap.label || snap.id} <span className={'pill ' + (PILL[snap.status] || 'dim')}>{snap.status}</span></h2>
      <div className="card">
        <div className="small muted">Created {when(snap.created)}{snap.activated_at ? ' · activated ' + when(snap.activated_at) : ''}{snap.superseded_at ? ' · superseded ' + when(snap.superseded_at) : ''}{snap.note ? ' · ' + snap.note : ''}</div>
        <div className="scroll"><table style={{ marginTop: 8 }}>
          <thead><tr><th>Model</th><th>Export</th><th>File</th><th className="num">Size</th><th>Uploaded</th><th>Check</th><th></th></tr></thead>
          <tbody>
            {!snap.files.length && <tr><td colSpan={7} className="muted">No files yet.</td></tr>}
            {snap.files.map(f => <tr key={f.model_id + f.kind}>
              <td><ModelChip name={f.model} /></td><td>{KIND[f.kind]}</td><td className="small muted">{f.original_name}</td><td className="num">{fmtB(f.bytes)}</td><td>{when(f.uploaded_at)}</td>
              <td>{f.problem ? <span className="bad">{f.problem}</span> : <span className="muted">ok</span>}</td>
              <td>{stageable && <button className="small" onClick={() => unstage(f.model_id, f.kind)}>remove</button>}</td>
            </tr>)}
          </tbody>
        </table></div>
        {(snap.ready || []).length > 0 && <div className="warn" style={{ marginTop: 8 }}>Cannot process yet:<ul>{snap.ready.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
        {busy && <p className="kicker" style={{ marginTop: 10 }}>Parsing every formula and building the graph…</p>}
        {!busy && run?.status === 'failed' && <p className="bad" style={{ marginTop: 10 }}>Parse failed: {run.error}. The previously active snapshot is still serving.</p>}
        {!busy && run?.status === 'ok' && run.coverage && <>
          <h3>Coverage of this snapshot</h3>
          <div className="scroll"><table>
            <thead><tr><th>Model</th><th className="num">Parse</th><th className="num">Agrees with Referenced By</th><th className="num">Rules run</th><th>Skipped, and why</th><th>Warnings and missing columns</th></tr></thead>
            <tbody>{Object.entries(run.coverage).map(([name, c]) => <tr key={name}>
              <td><ModelChip name={name} /></td><td className="num">{pct(c.parse_rate)}</td><td className="num">{c.referenced_by_agreement != null ? pct(c.referenced_by_agreement) : <span className="muted">n/a</span>}</td><td className="num">{(c.rules_run || []).length}</td>
              <td className="small">{(c.rules_skipped || []).length ? c.rules_skipped.map((x, i) => <div key={i}>{x[0]}: {x[1]}</div>) : <span className="muted">none</span>}</td>
              <td className="small">{[...(c.warnings || []), ...(c.missing_columns || [])].length ? [...(c.warnings || []), ...(c.missing_columns || [])].map((x, i) => <div key={i}>{x}</div>) : <span className="muted">none</span>}</td>
            </tr>)}</tbody>
          </table></div>
        </>}
        <div className="actions">
          {stageable && <button className="primary" disabled={!can} onClick={process}>{snap.status === 'processed' ? 'Process again' : 'Process'}</button>}
          {snap.status === 'processed' && <button className="primary" onClick={activate}>Activate: make it the snapshot the estate reads</button>}
          {busy && <button onClick={cancel}>Cancel</button>}
          {stageable && !busy && <button onClick={del}>Delete draft</button>}
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </>
  )
}

/** How the models connect: every feed is read off the import action names, so it is inferred until the owner confirms it
 * (real and used) or retires it (the import survives, the feed is dead). The state and the reason reach the architect. */
function Connections() {
  const { route, summary: s, refresh, toast } = useApp()
  const [open, setOpen] = useState<string | null>(null)
  const [st, setSt] = useState('confirmed')
  const [why, setWhy] = useState('')
  const [busy, setBusy] = useState(false)
  if (!s || !s.snapshot) return null
  const key = (e: Edge) => e.from + '\u2192' + e.to
  async function save(e: Edge) {
    setBusy(true)
    try { await api(`/api/estates/${route.eid}/edges`, json('PUT', { from: e.from, to: e.to, state: st, reason: why })); setOpen(null); await refresh() }
    catch (err: any) { toast(err.message) } finally { setBusy(false) }
  }
  return <div style={{ marginTop: 14 }}>
    <h3 style={{ margin: '0 0 4px' }}>How the models connect</h3>
    <div className="small muted" style={{ marginBottom: 6 }}>Every feed below is read off the import action names, so it is inferred until you say otherwise. Confirm one that is real and used; retire one whose import survives but nobody runs. The architect reads the state and your reason, and draws confirmed feeds solid, inferred or retired ones dashed.</div>
    {!s.edges.length && <div className="small muted">None read off the action names.</div>}
    {s.edges.length > 0 && <table>
      <thead><tr><th>From</th><th>To</th><th>Imports</th><th>State</th><th>Reason</th><th /></tr></thead>
      <tbody>{s.edges.map(e => { const k = key(e); const x = e.state; return <React.Fragment key={k}>
        <tr>
          <td><ModelChip name={e.from} /></td><td><ModelChip name={e.to} /></td>
          <td className="small muted">{e.actions} into {e.targets.slice(0, 3).join(', ')}{e.targets.length > 3 ? '\u2026' : ''}</td>
          <td><span className={'pill ' + (x?.state === 'confirmed' ? '' : x?.state === 'retired' ? 'off' : 'amber')}>{x?.state || 'inferred'}</span></td>
          <td className="small">{x ? <>{x.reason}<span className="muted">{' \u00b7 '}{x.by || 'local'}{x.when ? ' \u00b7 ' + ago(x.when) : ''}</span></> : <span className="muted">no decision: the import names alone</span>}</td>
          <td><button className="small" onClick={() => { setOpen(open === k ? null : k); setSt(x?.state || 'confirmed'); setWhy(x?.reason || '') }}>{open === k ? 'Close' : x ? 'Change' : 'Confirm or retire'}</button></td>
        </tr>
        {open === k && <tr><td colSpan={6}>
          <div className="state">
            <select value={st} onChange={ev => setSt(ev.target.value)}>
              <option value="confirmed">confirmed: real and used</option>
              <option value="retired">retired: the import survives, the feed is dead</option>
              <option value="inferred">inferred: back to the import names</option>
            </select>
            <textarea value={why} placeholder="Your reason: kept with the decision, read by the architect" onChange={ev => setWhy(ev.target.value)} />
            <button className="primary small" disabled={busy || (st !== 'inferred' && !why.trim())} onClick={() => save(e)}>Record</button>
          </div>
          <div className="meta">A state records your word; it verifies nothing in Anaplan.</div>
        </td></tr>}
      </React.Fragment> })}</tbody>
    </table>}
  </div>
}
