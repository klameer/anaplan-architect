// The evidence drawer: what a chip opens. A citation resolves to the object as its snapshot held it
// (formula, dimensions, findings, neighbours), the row of the export it was read from, whether that
// snapshot is still the one the estate reads (and what the object is now if not), and where else it is
// cited. Every neighbour is a chip that opens the same way, so the reader can walk the estate from the
// answer. Nothing here is a permanent panel: it slides in on a click and closes on Esc.
import React, { useEffect, useState } from 'react'
import { STATE_PILL, STATE_LABEL, ago, api, ApiError, fmtN, when, KIND_LABEL, PROV_LABEL, PROV_PILL, type Citation, type Evidence, type EvidenceTarget, type ExportRow, type Ref } from '../api'
import { depsHref, href, useApp } from '../App'
import { CiteChip, Markdown, Obj, citesOf, type NameIndex } from '../objects'

async function load(t: EvidenceTarget, eid: string | null): Promise<Evidence> {
  if (t.id) {
    try { return await api<Evidence>('/api/citations/' + t.id) }
    catch (e) { if (!(e instanceof ApiError && e.status === 404) || !t.ref) throw e }
  }
  if (!eid) throw new Error('pick an estate first')
  const p = new URLSearchParams({ ref: t.ref || '' })
  if (t.model) p.set('model', t.model); if (t.kind) p.set('kind', t.kind); if (t.snapshot) p.set('snapshot', t.snapshot)
  return api<Evidence>('/api/estates/' + eid + '/object?' + p.toString())
}

/** A related object as a chip: it carries an id bound to the same snapshot, and opens by name if that id was never recorded. */
function chip(r: Ref, kind: string, model: string | null | undefined, snapshot: string | null | undefined): Citation {
  return { id: r.id || '', kind, model: model || '', ref: r.ref, name: r.ref, snapshot_id: snapshot || '', provenance: 'observed', tool: '' }
}

const Chips = ({ refs, kind, model, snapshot, idx }: { refs: Ref[]; kind: string; model?: string | null; snapshot?: string | null; idx: NameIndex }) =>
  <div className="row-chips">{refs.map((r, i) => <CiteChip key={i} c={chip(r, kind, model, snapshot)} idx={idx} />)}</div>

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length))
  if (!shown.length) return null
  return <div className="kv">{shown.map(([k, v], i) => <React.Fragment key={i}><span className="k">{k}</span><span>{Array.isArray(v) ? v.join(', ') : v}</span></React.Fragment>)}</div>
}

function ExportRowView({ r }: { r: ExportRow }) {
  const [all, setAll] = useState(false)
  if (!r.row) return <div className="small muted" style={{ marginTop: 8 }}>Export {r.file} (uploaded {ago(r.uploaded_at)}) has no row for this object.</div>
  const cols = r.columns.filter(c => all || (r.row![c] || '').trim())
  return (
    <details>
      <summary>Export row · {r.file} · uploaded {ago(r.uploaded_at)}</summary>
      <div className="scroll"><table><tbody>{cols.map(c => <tr key={c}><th style={{ whiteSpace: 'nowrap' }}>{c || '(first column)'}</th><td style={{ fontFamily: 'var(--mono)', fontSize: 12, overflowWrap: 'anywhere' }}>{r.row![c]}</td></tr>)}</tbody></table></div>
      <button className="small quiet" onClick={() => setAll(!all)}>{all ? 'non-empty columns only' : `all ${r.columns.length} columns`}</button>
    </details>
  )
}

const Sev = ({ s }: { s: string }) => <span className={'pill ' + (s === 'critical' || s === 'major' ? 'off' : s === 'minor' ? 'amber' : 'dim')}>{s}</span>

function Body({ e, idx }: { e: Evidence; idx: NameIndex }) {
  const { route, openEvidence } = useApp()
  const o = e.object || {}
  const sid = e.snapshot?.id
  const m = e.model
  if (e.kind === 'document') {
    const qs: { quote: string; found: boolean }[] = o.quotes || []
    const text: string = o.text || ''
    const marks = qs.filter(q => q.found).map(q => q.quote.split(/\.\.\.|…/)[0].trim()).filter(q => q.length > 8)
    const parts: React.ReactNode[] = []
    let rest = text, k = 0
    for (const q of marks) { const i = rest.toLowerCase().replace(/\s+/g, ' ').indexOf(q.toLowerCase().replace(/\s+/g, ' ')); const j = rest.toLowerCase().indexOf(q.toLowerCase().slice(0, 24))
      if (j >= 0 && i >= 0) { parts.push(rest.slice(0, j)); parts.push(<mark key={k++} style={{ background: 'rgba(52,211,153,.14)', color: 'var(--ink)', boxShadow: '-3px 0 0 var(--accent)', padding: '1px 4px 1px 6px' }}>{rest.slice(j, j + q.length)}</mark>); rest = rest.slice(j + q.length) } }
    parts.push(rest)
    return <>
      <KV rows={[['Document', o.document?.title], ['Type', o.document?.type], ['Date', o.document?.date], ['File', o.document?.filename], ['Section', `${o.heading || 'opening'} · ${o.position?.[0]} of ${o.position?.[1]}`], ['Size', `${fmtN(o.tokens)} tokens`]]} />
      {qs.length > 0 && <><h3>Quoted in answers</h3>{qs.map((q, i) => <div key={i} className={q.found ? 'small' : 'warn'} style={{ margin: '4px 0' }}>{q.found ? '✓' : '△ not in this section:'} "{q.quote}"</div>)}</>}
      <h3>The section</h3>
      <pre style={{ fontFamily: 'var(--sans)', fontSize: 13.5, lineHeight: 1.6 }}>{parts}</pre>
      {(o.names || []).length > 0 && <><h3>Objects it names</h3><div className="row-chips">{o.names.map((n: any, i: number) => <Obj key={i} text={n.ref} idx={idx} />)}</div></>}
    </>
  }
  if (e.kind === 'line_item') return <>
    <h3>Formula</h3>
    {o.formula ? <pre>{o.formula}</pre> : <div className="small muted">No formula: an input, or an import target.</div>}
    {o.parse_error && <div className="warn">The grammar could not parse this formula: {o.parse_error}</div>}
    <KV rows={[['Module', <CiteChip c={chip({ ref: o.module, id: o.module_id }, 'module', m, sid)} idx={idx} />], ['Format', o.format], ['Applies to', o.applies_to], ['Time scale', o.time_scale], ['Time range', o.time_range],
      ['Versions', o.versions], ['Summary', o.summary], ['Cells', o.cells ? fmtN(o.cells) : ''], ['Calculation effort', o.has_effort ? `${o.calc_effort}%` : ''], ['Notes', o.notes], ['Referenced by (Anaplan)', o.referenced_by]]} />
    {o.axes && <div className="small" style={{ marginTop: 8 }}>
      <div><span className="muted">Applies to:</span> {o.axes.applied.length ? o.axes.applied.map((a: string) => <span key={a} className={'pill ' + (o.axes.extra.includes(a) ? 'amber' : 'dim')} style={{ marginRight: 4 }}>{a}</span>) : <span className="muted">no axis</span>}
        {o.axes.judged && <> <span className="muted">· its formula needs:</span> {o.axes.required.length ? o.axes.required.map((a: string) => <span key={a} className="pill dim" style={{ marginRight: 4 }}>{a}</span>) : <span className="muted">no axis</span>}</>}</div>
      {o.axes.extra.length > 0 && <div className="warn" style={{ marginTop: 4 }}>Not needed by its formula: {o.axes.extra.join(', ')}. {o.axes.saved_cells != null ? <>{fmtN(o.axes.cells)} cells would be {fmtN(o.axes.cells - o.axes.saved_cells)}: <b>{fmtN(o.axes.saved_cells)} saved</b>.</> : o.axes.partial ? 'Which one cannot be told: an aggregation targets a list the export does not name.' : 'Unpriced: no line item isolates that size.'}{o.axes.constant ? ' A constant repeated along every axis.' : ''}</div>}
      {o.axes.decision && <div style={{ marginTop: 4 }}><span className={'pill ' + (STATE_PILL[o.axes.decision.state] ?? 'dim')}>{STATE_LABEL[o.axes.decision.state] || o.axes.decision.state}</span> <span className="muted">on the Size page:</span> {o.axes.decision.reason || <span className="muted">no reason given</span>} <span className="muted">· {o.axes.decision.by || 'local'}{o.axes.decision.updated ? ' · ' + ago(o.axes.decision.updated) : ''}</span></div>}
      {o.axes.implicit.length > 0 && <div className="muted" style={{ marginTop: 4 }}>Aggregated or mapped implicitly (hierarchy, subset, summary; not in the exports): {o.axes.implicit.join(', ')}.</div>}
      {o.axes.judged && !o.axes.lists_judged && <div className="muted" style={{ marginTop: 4 }}>Module dimensions are unnamed in this export (no Modules export): lists are not compared, Time and Versions are.</div>}
      {!o.axes.judged && o.axes.reason && <div className="muted" style={{ marginTop: 4 }}>Axes not judged: {o.axes.reason}.</div>}
    </div>}
    {m && <div className="small" style={{ marginTop: 8 }}><a href={depsHref(route.eid || e.estate, m, e.ref)}>Explore its dependencies: reach, actions, graph →</a> · <a href={`#/e/${route.eid || e.estate}/size/${encodeURIComponent(m)}`}>Size of the model →</a></div>}
    {o.uses_count > 0 && <><h3>Uses ({o.uses_count})</h3><Chips refs={o.uses} kind="line_item" model={m} snapshot={sid} idx={idx} /></>}
    {o.used_by_count > 0 && <><h3>Used by ({o.used_by_count})</h3><Chips refs={o.used_by} kind="line_item" model={m} snapshot={sid} idx={idx} />{o.used_by_count > o.used_by.length && <div className="small muted">first {o.used_by.length} shown</div>}</>}
    {o.references?.length > 0 && <><h3>References in the formula</h3><div className="scroll"><table><thead><tr><th>Path</th><th>Kind</th><th>Resolves to</th></tr></thead><tbody>
      {o.references.map((r: any, i: number) => <tr key={i}><td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{r.path}</td><td>{r.kind}</td><td>{r.target ? <CiteChip c={chip({ ref: r.target, id: r.id }, 'line_item', m, sid)} idx={idx} /> : <span className="muted">{r.kind === 'unresolved' ? 'nothing in the exports' : ''}</span>}</td></tr>)}
    </tbody></table></div></>}
    {o.findings?.length > 0 && <><h3>Findings on this line item</h3>{o.findings.map((f: any, i: number) => <div key={i} className="card" style={{ marginBottom: 6, padding: '8px 12px' }}>
      <div><Sev s={f.severity} /> <CiteChip c={chip({ ref: f.rule, id: f.rule_id }, 'finding', '', sid)} idx={idx} /> <span className="muted small">{f.source}</span></div>
      <div className="small" style={{ marginTop: 4 }}>{f.message}</div>{f.fix && <div className="small muted">Fix: {f.fix}</div>}</div>)}</>}
    {o.patterns?.length > 0 && <><h3>Part of these patterns</h3>{o.patterns.map((p: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}>
      <CiteChip c={chip({ ref: p.id, id: p.cite }, 'pattern', m, sid)} idx={idx} /> <Sev s={p.severity} /> <span className="muted">{p.count} finding{p.count !== 1 ? 's' : ''} · {p.status}{p.decision?.reason ? ': ' + p.decision.reason : ''}</span></div>)}</>}
    <PlanMentions plan={o.plan} />
  </>
  if (e.kind === 'module') return <>
    <KV rows={[['Model', <CiteChip c={chip({ ref: m || '', id: null }, 'model', m, sid)} idx={idx} />], ['Functional area', o.functional_area], ['Applies to', o.applies_to?.length ? o.applies_to.join(', ') + (o.dims_inferred ? ' (inferred from its line items; no Modules export)' : '') : ''],
      ['Time scale', o.time_scale], ['Versions', o.versions], ['Cells', o.cells ? fmtN(o.cells) : ''], ['Notes', o.notes]]} />
    {m && <div className="small" style={{ marginTop: 8 }}><a href={depsHref(route.eid || e.estate, m, e.ref)}>Explore its dependencies: reach, actions, graph →</a></div>}
    <h3>Line items ({o.line_item_count})</h3>
    <div className="scroll"><table><thead><tr><th>Line item</th><th>Formula</th><th className="num">Cells</th></tr></thead><tbody>
      {o.line_items.map((x: any, i: number) => <tr key={i}><td><CiteChip c={chip({ ref: x.ref, id: x.id }, 'line_item', m, sid)} idx={idx} /></td><td style={{ fontFamily: 'var(--mono)', fontSize: 11.5, overflowWrap: 'anywhere' }}>{x.is_header ? <span className="muted">section</span> : x.formula || <span className="muted">input</span>}</td><td className="num">{x.cells ? fmtN(x.cells) : ''}</td></tr>)}
    </tbody></table></div>{o.truncated && <div className="small muted">first {o.line_items.length} shown</div>}
    {o.uses_modules?.length > 0 && <><h3>Reads from</h3><Chips refs={o.uses_modules} kind="module" model={m} snapshot={sid} idx={idx} /></>}
    {o.used_by_modules?.length > 0 && <><h3>Read by</h3><Chips refs={o.used_by_modules} kind="module" model={m} snapshot={sid} idx={idx} /></>}
    {o.imports?.length > 0 && <><h3>Imports into this module</h3>{o.imports.map((a: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip(a, 'action', m, sid)} idx={idx} /> <span className="muted">{a.last_run ? 'last run ' + a.last_run : 'never run'}</span></div>)}</>}
    <PlanMentions plan={o.plan} />
  </>
  if (e.kind === 'model') { const f = o.facts || {}; const a = o.actions; return <>
    <div className="tiles" style={{ marginTop: 8 }}>
      <div className="tile"><div className="k">Modules</div><div className="v">{fmtN(f.modules)}</div></div>
      <div className="tile"><div className="k">Line items</div><div className="v">{fmtN(f.line_items)}</div></div>
      <div className="tile"><div className="k">Cells</div><div className="v">{f.cells ? fmtN(f.cells) : '—'}</div></div>
      <div className="tile"><div className="k">Parse rate</div><div className="v">{f.parse_rate != null ? (f.parse_rate * 100).toFixed(1) + '%' : '—'}</div></div>
    </div>
    <KV rows={[['Calculated', fmtN(f.calculated)], ['Dimensions', fmtN(o.dimensions)], ['Formula references', fmtN(f.edges)], ['Patterns', `${fmtN(f.patterns)} (${fmtN(f.findings)} findings)`], ['Unreferenced', fmtN(f.unreferenced)], ['Cycles', fmtN(f.cycles)],
      ['Referenced By agreement', o.referenced_by_agreement != null ? String(o.referenced_by_agreement) : ''], ['Top 10 effort share', f.has_effort ? `${f.effort_top10_share}%` : ''],
      ['Actions', a ? `${a.imports ?? 0} imports, ${a.exports ?? 0} exports, ${a.processes ?? 0} processes; latest run ${a.latest_run || 'unknown'}; ${a.stale_count ?? 0} stale, ${a.orphan_count ?? 0} outside any process` : '']]} />
    {o.largest_modules?.length > 0 && <><h3>Largest modules</h3>{o.largest_modules.map((x: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip(x, 'module', m, sid)} idx={idx} /> <span className="muted">{fmtN(x.cells)} cells · {x.pct}%</span></div>)}</>}
    {o.hubs?.length > 0 && <><h3>Most depended-on line items</h3>{o.hubs.map((x: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip(x, 'line_item', m, sid)} idx={idx} /> <span className="muted">{x.dependents} direct dependents</span></div>)}</>}
    {o.feeds?.length > 0 && <><h3>Feeds (read off import names)</h3>{o.feeds.map((x: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip({ ref: x.model, id: x.id }, 'model', x.model, sid)} idx={idx} /> <span className="muted">{x.actions} import action{x.actions !== 1 ? 's' : ''}{x.targets?.length ? ' into ' + x.targets.join(', ') : ''}</span> <EdgePill st={x.state} /></div>)}</>}
    {o.fed_by?.length > 0 && <><h3>Fed by (read off import names)</h3>{o.fed_by.map((x: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip({ ref: x.model, id: x.id }, 'model', x.model, sid)} idx={idx} /> <span className="muted">{x.actions} import action{x.actions !== 1 ? 's' : ''}</span> <EdgePill st={x.state} /></div>)}</>}
    {(o.warnings?.length > 0 || o.missing_columns?.length > 0) && <><h3>Coverage</h3>{o.missing_columns?.length > 0 && <div className="warn">Missing columns: {o.missing_columns.join(', ')}</div>}{o.warnings?.map((w: string, i: number) => <div key={i} className="warn">{w}</div>)}</>}
  </> }
  if (e.kind === 'action') return <>
    <KV rows={[['Model', <CiteChip c={chip({ ref: m || '', id: null }, 'model', m, sid)} idx={idx} />], ['Kind', o.action_kind], ['Target', o.target ? (o.target_id ? <CiteChip c={chip({ ref: o.target, id: o.target_id }, 'module', m, sid)} idx={idx} /> : o.target) : ''],
      ['Detail', o.detail], ['Last run', o.last_run || 'never, or not in the export'], ['Duration', o.duration_ms ? `${(o.duration_ms / 1000).toFixed(1)}s` : ''], ['Notes', o.notes]]} />
    {o.processes?.length > 0 && <><h3>Used in processes</h3><Chips refs={o.processes} kind="action" model={m} snapshot={sid} idx={idx} /></>}
    {o.steps?.length > 0 && <><h3>Steps</h3><Chips refs={o.steps} kind="action" model={m} snapshot={sid} idx={idx} /></>}
    {o.action_kind === 'process' && !o.steps?.length && <div className="small muted" style={{ marginTop: 8 }}>The export lists no member actions for this process.</div>}
  </>
  if (e.kind === 'pattern') return <>
    <div style={{ margin: '8px 0' }}><Sev s={o.severity} /> <CiteChip c={chip({ ref: o.rule, id: o.rule_id }, 'finding', '', sid)} idx={idx} /> <span className={'pill ' + (o.status === 'open' ? 'dim' : '')}>{o.status}</span> <span className="muted small">{o.count} finding{o.count !== 1 ? 's' : ''} · {o.key}</span></div>
    {o.decision && <div className="small" style={{ margin: '0 0 8px' }}><span className="muted">The owner's decision:</span> {o.decision.reason || <span className="muted">no reason given</span>} <span className="muted">· {o.decision.by || 'local'}{o.decision.when ? ' · ' + ago(o.decision.when) : ''}</span></div>}
    <KV rows={[['Rule', o.title], ['Model', <CiteChip c={chip({ ref: m || '', id: null }, 'model', m, sid)} idx={idx} />], ['What', o.message], ['Fix', o.fix], ['Tests', (o.tests || []).map((t: any) => `${t.num} ${t.title}`).join(' · ')], ['Planual', o.planual]]} />
    {o.modules?.length > 0 && <><h3>Modules</h3><Chips refs={o.modules} kind="module" model={m} snapshot={sid} idx={idx} /></>}
    {o.objects?.length > 0 && <><h3>Sample objects</h3><div className="row-chips">{o.objects.map((x: any, i: number) => x.id ? <CiteChip key={i} c={chip(x, x.ref.includes('.') ? 'line_item' : 'module', m, sid)} idx={idx} /> : <code key={i}>{x.ref}</code>)}</div></>}
    <div className="small muted" style={{ marginTop: 10 }}>Marking a pattern is a decision the owner records; it verifies nothing in Anaplan.</div>
  </>
  if (e.kind === 'finding') return <>
    <div style={{ margin: '8px 0' }}><Sev s={o.severity} /> <span className="muted small">{o.source}</span></div>
    <KV rows={[['Rule', o.title], ['Description', o.description], ['Thresholds', o.thresholds && Object.keys(o.thresholds).length ? Object.entries(o.thresholds).map(([k, v]) => `${k}: ${v}`).join(', ') : ''], ['Tests', (o.tests || []).map((t: any) => `${t.num} ${t.title}`).join(' · ')], ['Planual', o.planual], ['Docs', o.docs]]} />
    <h3>In this estate</h3>
    <KV rows={Object.entries(o.in_estate || {}).map(([k, v]) => [k, fmtN(v as number)] as [string, React.ReactNode])} />
    {o.patterns?.length > 0 && <><h3>Patterns</h3>{o.patterns.map((p: any, i: number) => <div key={i} className="small" style={{ marginBottom: 4 }}><CiteChip c={chip({ ref: p.id, id: p.cite }, 'pattern', p.model, sid)} idx={idx} /> <span className="muted">{p.count} · {p.status}{p.decision?.reason ? ': ' + p.decision.reason : ''}</span></div>)}</>}
  </>
  if (e.kind === 'note') { const n = o; return <>
    <div style={{ margin: '8px 0' }}><span className="pill dim">{n.type}</span> <span className={'pill ' + (n.status === 'user_confirmed' ? '' : n.status === 'superseded' ? 'off' : 'amber')}>{n.status === 'user_confirmed' ? 'confirmed' : n.status === 'superseded' ? 'superseded' : 'working assumption'}</span> <span className="muted small">{n.origin_kind === 'answer' ? 'saved from an answer' : n.origin_kind === 'chat_tool' ? 'kept by the architect' : n.origin_kind === 'import' ? 'imported' : 'typed'} · updated {ago(n.updated)}</span></div>
    <div className="note-body"><Markdown md={n.body} idx={idx} /></div>
    <KV rows={[['Scope', n.scope_labels?.join(', ')], ['Confirmed', n.confirmed_at ? when(n.confirmed_at) : '']]} />
    {n.sources_resolved?.length > 0 && <><h3>Evidence it carries</h3><div className="row-chips">{n.sources_resolved.map((c: Citation) => <CiteChip key={c.id} c={c} idx={idx} />)}</div></>}
    {n.siblings?.length > 0 && <><h3>Also on this object, possibly disagreeing</h3>{n.siblings.map((s: any) => <div key={s.id} className="small" style={{ marginBottom: 4 }}><span className="obj note cited" role="button" onClick={() => openEvidence({ ref: s.id, kind: 'note' })}>note · {s.title}</span> <span className="muted">({s.type}, {s.status})</span></div>)}</>}
    <div className="small" style={{ marginTop: 10 }}>{n.origin_conversation_id && <a href={href(route.eid!, 'chat', n.origin_conversation_id)}>Open the conversation it came from →</a>} <a href={href(route.eid!, 'home')}>All notes →</a></div>
  </> }
  return <pre>{JSON.stringify(o, null, 1)}</pre>
}

export function EvidencePanel() {
  const { evidence, popEvidence, closeEvidence, openEvidence, route, idx, summary } = useApp()
  const t = evidence[evidence.length - 1]
  const [data, setData] = useState<Evidence | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!t) return
    let live = true; setBusy(true); setErr(null)
    load(t, route.eid).then(d => { if (live) setData(d) }).catch(e => { if (live) { setErr(e.message); setData(null) } }).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [t, route.eid])
  useEffect(() => {
    if (!t) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') closeEvidence() }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [t, closeEvidence])
  if (!t) return null
  const e = data
  const head = e ? citesOf([{ id: e.id, kind: e.kind, model: e.model || '', ref: e.ref, name: e.name, snapshot_id: e.snapshot?.id || '', provenance: e.provenance, tool: e.tool }]) : undefined
  const snapLabel = e?.snapshot ? (e.snapshot.label || e.snapshot.id) : ''
  return (
    <aside className="evidence" aria-label="Evidence">
      <div className="ehead">
        {evidence.length > 1 && <button className="small quiet" onClick={popEvidence} title="Back">←</button>}
        <span className="kicker">{e ? KIND_LABEL[e.kind] || e.kind : 'Evidence'}</span>
        <span className="grow" style={{ flex: 1 }} />
        <button className="small quiet" onClick={closeEvidence} title="Close (Esc)">×</button>
      </div>
      <div className="ebody">
        {busy && !e && <div className="muted small">Opening…</div>}
        {err && <div className="card"><div className="warn">{err}</div><div className="small muted" style={{ marginTop: 6 }}>{t.ref ? <>Named <code>{t.ref}</code>.</> : null} Only what the tools handed over, or what the estate contains, can be opened.</div></div>}
        {e && <>
          <div style={{ fontSize: 16, fontWeight: 500, overflowWrap: 'anywhere' }}>{e.kind === 'note' ? <span className="obj note" style={{ fontSize: 14 }}>note · {e.name}</span> : <Obj text={e.ref} idx={idx} cites={head} />}</div>
          <div className="row-chips" style={{ marginTop: 8 }}>
            <span className={'pill ' + (PROV_PILL[e.provenance] ?? 'dim')} title="Provenance: where this claim rests">{PROV_LABEL[e.provenance] || e.provenance}</span>
            {e.looked_up_now ? <span className="pill dim" title="No citation carried this name; it was looked up in the estate just now">looked up now</span> : e.tool ? <span className="pill dim">handed by {e.tool}</span> : null}
            {e.model && e.kind !== 'model' && <Obj text={e.model} idx={idx} />}
          </div>
          {e.snapshot && <div className="small muted" style={{ marginTop: 8 }}>Snapshot {snapLabel} · {e.snapshot.status}{e.snapshot.activated_at ? ` · activated ${ago(e.snapshot.activated_at)}` : ''}{e.current ? ' · the one the estate reads now' : ''}</div>}
          {e.snapshot_fallback && <div className="stale">The snapshot this was cited on is no longer in the store; showing the current one.</div>}
          {!e.current && e.now && <div className="stale">
            {e.now.found ? (e.now.changed ? <>The estate now reads a newer snapshot and this formula has changed since:<pre>{e.now.formula}</pre></> : <>The estate now reads a newer snapshot; this object is unchanged there.</>) : <>This object is not in the snapshot the estate reads now.</>}
            {e.now.found && <div><button className="small" onClick={() => openEvidence({ id: e.now!.id, ref: e.ref, kind: e.kind, model: e.model, snapshot: e.now!.snapshot_id })}>Open as it is now</button></div>}
          </div>}
          <Body e={e} idx={idx} />
          {e.export_row && <ExportRowView r={e.export_row} />}
          {(e.cited_in.turns.length > 0 || e.cited_in.notes.length > 0) && <>
            <h3>Cited in</h3>
            {e.cited_in.turns.map(x => <div key={x.turn_id} className="small" style={{ marginBottom: 3 }}><a href={href(route.eid || summary?.id || '', 'chat', x.conversation_id)}>{x.title || x.conversation_id}</a> <span className="muted">· turn {x.seq} · {ago(x.created)}</span></div>)}
            {e.cited_in.notes.map(x => <div key={x.id} className="small" style={{ marginBottom: 3 }}><span className="obj note cited" role="button" onClick={() => openEvidence({ ref: x.id, kind: 'note' })}>note · {x.title}</span> <span className="muted">· {x.type}, {x.status === 'user_confirmed' ? 'confirmed' : x.status}</span></div>)}
          </>}
          <div className="small muted" style={{ marginTop: 16 }}>Read from the export as uploaded. Dependency reach describes references, not whether a value changes; saved views, pages and data values are not in the exports.</div>
        </>}
      </div>
    </aside>
  )
}

/** The owner's word on a feed: confirmed, retired, or (no row) inferred from the import names alone. */
function EdgePill({ st }: { st: { state: string; reason: string; by: string | null; when: string | null } | null | undefined }) {
  if (!st) return <span className="pill amber" title="Read off the import action names; the owner has not confirmed it">inferred</span>
  return <span className={'pill ' + (st.state === 'confirmed' ? '' : 'off')} title={`${st.reason || ''} (${st.by || 'local'}${st.when ? ', ' + ago(st.when) : ''})`}>{st.state}</span>
}

/** The action-plan cards and proposals that name this object, each with the owner's decision on it. */
function PlanMentions({ plan }: { plan?: { key: string; title: string; kind: string; proposal: boolean; state: { state: string; reason: string; by: string | null; updated: string | null; default?: boolean } | null }[] }) {
  const { route } = useApp()
  if (!plan || !plan.length) return null
  return <><h3>On the action plan</h3>{plan.map(c => <div key={c.key} className="small" style={{ marginBottom: 4 }}>
    {c.proposal && <span className="pill amber" style={{ marginRight: 4 }}>proposal</span>}{c.title}{' '}
    {c.state ? <span className={'pill ' + (STATE_PILL[c.state.state] ?? 'dim')}>{STATE_LABEL[c.state.state] || c.state.state}</span> : <span className="pill amber">unconfirmed</span>}
    {c.state && !c.state.default && <span className="muted"> {c.state.reason ? c.state.reason + ' ' : ''}· {c.state.by || 'local'}{c.state.updated ? ' · ' + ago(c.state.updated) : ''}</span>}
    {c.state?.default && <span className="muted"> no decision yet</span>}
  </div>)}<div className="small"><a href={`#/e/${route.eid}/plan`}>Open the action plan →</a></div></>
}
