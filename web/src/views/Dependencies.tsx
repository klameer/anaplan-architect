// The dependency explorer (stage 4). Searchable table first: line items and modules by name, module or formula, the
// hubs when nothing is typed. Pick one and the reach of a change to it is counted the way the spec counts (unique
// line items at their shortest distance, the selection excluded, a cycle never counted twice), rolled up to modules,
// with actions listed apart at module level, other models listed apart as inferred, and the coverage gaps beside every
// count. Then the graph, grown one click at a time. Every object is a chip that opens the evidence drawer.
import React, { useEffect, useMemo, useState } from 'react'
import { ago, api, fmtN, type Citation, type DepHit, type DepSearch, type Reach } from '../api'
import { depsHref, useApp } from '../App'
import { CiteChip, Obj, type NameIndex } from '../objects'
import { DepGraph } from './DepGraph'

const cite = (ref: string, id: string | null | undefined, kind: string, model: string, snapshot: string | null | undefined): Citation =>
  ({ id: id || '', kind, model, ref, name: ref, snapshot_id: snapshot || '', provenance: 'observed', tool: '' })

const Chip = ({ r, id, kind, model, snapshot, idx }: { r: string; id?: string | null; kind: string; model: string; snapshot?: string | null; idx: NameIndex }) =>
  <CiteChip c={cite(r, id, kind, model, snapshot)} idx={idx} />

export function Dependencies() {
  const { route, summary: s, idx, go, toast } = useApp()
  const eid = route.eid!
  const [model, ref] = route.args
  const sid = s?.snapshot?.id || null
  const [q, setQ] = useState('')
  const [mf, setMf] = useState('')
  const [kf, setKf] = useState('')
  const [res, setRes] = useState<DepSearch | null>(null)
  const [searching, setSearching] = useState(false)
  const [dir, setDir] = useState<'downstream' | 'upstream'>('downstream')
  const [depth, setDepth] = useState('')
  const [reach, setReach] = useState<Reach | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    if (!sid) return
    let live = true                                                      // a result for a search the reader has since changed is dropped
    const t = setTimeout(async () => {
      setSearching(true)
      try {
        const p = new URLSearchParams({ q, limit: '60' }); if (mf) p.set('model', mf); if (kf) p.set('kind', kf)
        const r = await api<DepSearch>(`/api/estates/${eid}/deps/search?` + p.toString())
        if (live) setRes(r)
      } catch (e: any) { if (live) toast(e.message) } finally { if (live) setSearching(false) }
    }, 200)
    return () => { live = false; clearTimeout(t) }
  }, [q, mf, kf, eid, sid, toast])

  useEffect(() => {
    if (!model || !ref || !sid) { setReach(null); return }
    let live = true; setErr(null)
    const p = new URLSearchParams({ model, ref, direction: dir }); if (depth) p.set('depth', depth)
    api<Reach>(`/api/estates/${eid}/deps/reach?` + p.toString()).then(r => { if (live) setReach(r) }).catch(e => { if (live) { setErr(e.message); setReach(null) } })
    return () => { live = false }
  }, [model, ref, dir, depth, eid, sid])

  const shownNodes = useMemo(() => {
    if (!reach) return []
    const f = filter.trim().toLowerCase()
    const all = f ? reach.nodes.filter(n => n.ref.toLowerCase().includes(f) || n.formula.toLowerCase().includes(f)) : reach.nodes
    return showAll ? all : all.slice(0, 60)
  }, [reach, filter, showAll])

  if (!s) return null
  if (!s.snapshot) return <div><div className="kicker">Estate</div><h1>{s.name}</h1><h2>Dependencies</h2><div className="card muted">No active snapshot. Upload and activate one on Home.</div></div>

  const select = (h: DepHit) => go(depsHref(eid, h.model, h.ref))
  const c = reach?.counts
  const tableOpen = !reach || q.trim() !== ''
  const hasEffort = !!reach && reach.nodes.some(n => n.effort != null)

  return (
    <div>
      <div className="kicker">Estate</div>
      <h1>{s.name}</h1>
      <h2>Dependencies</h2>
      <p className="muted small">Find a line item or a module, then read the reach of a change to it: what depends on it, or what it depends on, counted once each at the shortest distance. Actions are linked at module level and other models are inferred from import names, so both are listed apart from the counts.</p>

      <div className="deps-head">
        <div className="grow"><label className="kicker">Find</label><input value={q} placeholder="Name, module or formula text… (empty: the most depended-on line items)" onChange={e => setQ(e.target.value)} /></div>
        <div><label className="kicker">Model</label><select value={mf} onChange={e => setMf(e.target.value)}><option value="">all models</option>{s.models.filter(m => !m.retired).map(m => <option key={m.id} value={m.name}>{m.name}</option>)}</select></div>
        <div><label className="kicker">Kind</label><select value={kf} onChange={e => setKf(e.target.value)}><option value="">line items and modules</option><option value="line_item">line items</option><option value="module">modules</option></select></div>
      </div>

      {tableOpen && <div className="card" style={{ padding: '4px 12px 8px', marginBottom: 16 }}>
        <div className="scroll"><table>
          <thead><tr><th>Object</th><th>Model</th><th>Kind</th><th className="num">Cells</th><th className="num">Uses</th><th className="num">Used by</th><th /></tr></thead>
          <tbody>
            {res === null && <tr><td colSpan={7} className="muted small">{searching ? 'Searching…' : ''}</td></tr>}
            {res && !res.hits.length && <tr><td colSpan={7} className="muted small">Nothing matches.</td></tr>}
            {(res?.hits || []).map(h => <tr key={h.model + '|' + h.ref} className={'sel-row' + (h.model === model && h.ref === ref ? ' on' : '')} onClick={() => select(h)} title="Read the reach of a change to this">
              <td><Chip r={h.ref} id={h.id} kind={h.kind} model={h.model} snapshot={sid} idx={idx} />{h.in === 'formula' && <span className="muted small"> · in its formula</span>}{h.in === 'hub' && <span className="muted small"> · hub</span>}</td>
              <td><Obj text={h.model} idx={idx} /></td>
              <td className="small">{h.kind === 'module' ? `module · ${h.line_items} line items` : h.calculated ? 'calculated' : 'input'}</td>
              <td className="num">{h.cells ? fmtN(h.cells) : ''}</td><td className="num">{h.uses}</td><td className="num">{h.used_by}</td>
              <td><button className="small quiet" onClick={e => { e.stopPropagation(); select(h) }}>Reach →</button></td>
            </tr>)}
          </tbody>
        </table></div>
        {res && res.truncated && <div className="small muted" style={{ marginTop: 6 }}>First {res.hits.length} of {res.total}: narrow the search.</div>}
      </div>}

      {err && <div className="card"><div className="warn">{err}</div></div>}

      {reach && c && <>
        <div className="sel-head">
          <span className="kicker">Reach of a change to</span>
          <Chip r={reach.selection.ref} id={reach.selection.id} kind={reach.selection.kind} model={reach.selection.model} snapshot={sid} idx={idx} />
          <span className="muted small">in</span><Obj text={reach.selection.model} idx={idx} />
          <span className="grow" />
          <div className="seg">
            <button className={dir === 'downstream' ? 'on' : ''} onClick={() => setDir('downstream')} title="Everything that reads it, transitively">What depends on it</button>
            <button className={dir === 'upstream' ? 'on' : ''} onClick={() => setDir('upstream')} title="Everything it reads, transitively, back to the inputs">What it depends on</button>
          </div>
          <select value={depth} onChange={e => setDepth(e.target.value)} title="How many links to follow"><option value="">every link</option><option value="1">1 link</option><option value="2">2 links</option><option value="3">3 links</option><option value="5">5 links</option></select>
        </div>

        <div className="tiles">
          <div className="tile"><div className="k">Line items</div><div className="v">{fmtN(c.line_items)}</div><div className="small muted">{c.direct} direct · {c.indirect} further</div></div>
          <div className="tile"><div className="k">Modules</div><div className="v">{fmtN(c.modules)}</div><div className="small muted">{reach.selection.kind === 'module' ? 'beyond the selection' : 'including its own'}</div></div>
          <div className="tile"><div className="k">Models</div><div className="v">{c.models}</div><div className="small muted">{c.models_inferred ? `+ ${c.models_inferred} inferred, listed apart` : 'no feed inferred'}</div></div>
          <div className="tile"><div className="k">Actions</div><div className="v">{c.actions === null ? '—' : c.actions}</div><div className="small muted">{c.actions === null ? 'not assessed: no Actions export' : 'module level, listed apart'}</div></div>
          <div className="tile"><div className="k">Footprint</div><div className="v">{c.footprint_cells ? fmtN(c.footprint_cells) : '—'}</div><div className="small muted">cells in reach</div></div>
          <div className="tile"><div className="k">Furthest</div><div className="v">{c.max_distance}</div><div className="small muted">{Object.entries(c.by_distance).map(([d, n]) => `${n} at ${d}`).join(' · ') || 'no links'}</div></div>
        </div>

        <ul className="gaps">{reach.coverage.map((x, i) => <li key={i}>{x}</li>)}</ul>

        {reach.modules.length > 0 && <div className="small" style={{ marginBottom: 10 }}><span className="muted">Modules in reach: </span>
          <span className="row-chips" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>{reach.modules.map(m => <span key={m.ref}><Chip r={m.ref} id={m.id} kind="module" model={reach.selection.model} snapshot={sid} idx={idx} /> <span className="muted">{m.line_items} at ≥{m.min_distance}</span></span>)}</span></div>}

        <div className="two">
          <section>
            <h3>Reached line items {reach.nodes.length < c.line_items ? <span className="muted small">(first {reach.nodes.length} of {c.line_items})</span> : null}</h3>
            <input value={filter} placeholder="Filter by name or formula" onChange={e => setFilter(e.target.value)} style={{ marginBottom: 6 }} />
            <div className="card" style={{ padding: '2px 12px 8px', maxHeight: 460, overflow: 'auto' }}>
              <table>
                <thead><tr><th className="num">Dist</th><th>Line item</th><th>Via</th><th className="num">Cells</th>{hasEffort && <th className="num">Effort</th>}</tr></thead>
                <tbody>
                  {!shownNodes.length && <tr><td colSpan={5} className="muted small">{c.line_items ? 'Nothing matches the filter.' : dir === 'downstream' ? 'No formula reads it.' : 'It reads nothing: an input or an import target.'}</td></tr>}
                  {shownNodes.map(n => <tr key={n.ref}>
                    <td className="num">{n.distance}</td>
                    <td><Chip r={n.ref} id={n.id} kind="line_item" model={reach.selection.model} snapshot={sid} idx={idx} />{!n.calculated && <span className="muted small"> · input</span>}</td>
                    <td>{n.via ? <Chip r={n.via.ref} id={n.via.id} kind="line_item" model={reach.selection.model} snapshot={sid} idx={idx} /> : <span className="muted small">selection</span>}</td>
                    <td className="num">{n.cells ? fmtN(n.cells) : ''}</td>
                    {hasEffort && <td className="num">{n.effort != null ? `${n.effort}%` : ''}</td>}
                  </tr>)}
                </tbody>
              </table>
              {!showAll && shownNodes.length === 60 && <button className="small quiet" onClick={() => setShowAll(true)}>show every reached line item</button>}
            </div>
          </section>
          <section>
            <h3>Actions <span className="muted small">(module level)</span></h3>
            <div className="card list-card">
              {reach.actions === null && <div className="muted small">Not assessed: this model has no Actions export.</div>}
              {reach.actions && !reach.actions.touching.length && <div className="muted small">No import writes, and no export reads, a module in reach.</div>}
              {reach.actions?.touching.map(a => <div key={a.ref} className="row2"><span className="t" style={{ whiteSpace: 'normal' }}>
                <span className="pill dim">{a.action_kind}</span> <Chip r={a.ref} id={a.id} kind="action" model={reach.selection.model} snapshot={sid} idx={idx} /> <span className="muted small">{a.direction}</span> <Chip r={a.module} id={a.module_id} kind="module" model={reach.selection.model} snapshot={sid} idx={idx} />{a.on_selection && <span className="muted small"> · the selection's module</span>}
              </span><span className="muted small" style={{ whiteSpace: 'nowrap' }}>{a.processes.length ? `in ${a.processes.join(', ')} · ` : ''}{a.last_run ? 'ran ' + ago(a.last_run) : 'no run recorded'}</span></div>)}
              {reach.actions && reach.actions.unmatched.length > 0 && <details style={{ padding: '6px 0 4px' }}><summary className="warn" style={{ cursor: 'pointer' }}>{reach.actions.unmatched.length} action{reach.actions.unmatched.length !== 1 ? 's' : ''} could not be placed: the target is not a module of this model (a list, or a module missing from the Line Items export)</summary>
                <div className="row-chips" style={{ marginTop: 6, maxHeight: 240, overflow: 'auto' }}>{reach.actions.unmatched.map(u => <span key={u.ref} className="small"><Chip r={u.ref} id={u.id} kind="action" model={reach.selection.model} snapshot={sid} idx={idx} /> <span className="muted">→ {u.target}</span></span>)}</div></details>}
            </div>
            <h3>Other models <span className="muted small">(inferred from import names)</span></h3>
            <div className="card list-card">
              {!reach.feeds_inferred.length && <div className="muted small">{dir === 'downstream' ? 'No import in another model names this one as its source.' : 'No import into this model names another model as its source.'}</div>}
              {reach.feeds_inferred.map(f => <div key={f.model} className="row2"><span className="t" style={{ whiteSpace: 'normal' }}><Chip r={f.model} id={f.id} kind="model" model={f.model} snapshot={sid} idx={idx} /> <span className="pill amber">inferred</span></span>
                <span className="muted small">{f.actions} import{f.actions !== 1 ? 's' : ''}{f.targets.length ? ' into ' + f.targets.slice(0, 3).join(', ') + (f.targets.length > 3 ? '…' : '') : ''}</span></div>)}
            </div>
            <ul className="gaps dim">{reach.limits.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </section>
        </div>

        <h3>Graph</h3>
        <DepGraph eid={eid} model={reach.selection.model} refName={reach.selection.ref} snapshot={sid} />
      </>}

      {!reach && !err && <div className="card muted small">Pick a line item or a module above to read the reach of a change to it, then grow the graph from it.</div>}
    </div>
  )
}
