// The action plan (stage 4): cards over the results of every test. The plan is the first few candidates that met the
// bar, in the order the report ranks them; everything else sits under it with the reason it is not on the plan. Each card carries the owner's
// state (to review, investigating, done, keep current design) and their reasoning, recorded in the store: a decision,
// never a verification. The architect's proposals (and any the owner adds by hand) sit apart, in their own section
// with a double amber border and a provenance pill, and carry no state until the owner takes them on.
import React, { useCallback, useEffect, useState } from 'react'
import { ago, api, fmtN, json, when, PROV_LABEL, STATE_LABEL, STATE_PILL, type Citation, type ObjRef, type Plan, type PlanCard, type Proposal } from '../api'
import { depsHref, href, useApp } from '../App'
import { CiteChip, Obj, type NameIndex } from '../objects'

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && !v.length))
  if (!shown.length) return null
  return <div className="kv">{shown.map(([k, v], i) => <React.Fragment key={i}><span className="k">{k}</span><span>{v}</span></React.Fragment>)}</div>
}

const ObjChips = ({ objs, snapshot, idx }: { objs: ObjRef[]; snapshot: string | null; idx: NameIndex }) =>
  <span className="row-chips" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>{objs.map((o, i) => o.kind && o.id
    ? <CiteChip key={i} c={{ id: o.id, kind: o.kind, model: o.model, ref: o.ref, name: o.ref, snapshot_id: snapshot || '', provenance: 'observed', tool: '' } as Citation} idx={idx} />
    : <code key={i}>{o.ref}</code>)}</span>

const StatePill = ({ s, none }: { s: string | null; none?: boolean }) => s
  ? <span className={'pill ' + (STATE_PILL[s] ?? 'dim')}>{STATE_LABEL[s] || s}{none ? ' (no decision yet)' : ''}</span>
  : <span className="pill amber">unconfirmed</span>

/** The state control every card carries: a state, the owner's reasoning, and who recorded it when. */
function StateBox({ stateKey, state, reason, by, updated, snapshot, planSnapshot, onSaved }:
  { stateKey: string; state: string | null; reason: string; by: string | null; updated: string | null; snapshot: string | null; planSnapshot: string | null; onSaved: () => void }) {
  const { route, toast } = useApp()
  const [st, setSt] = useState(state || 'to_review')
  const [why, setWhy] = useState(reason || '')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setSt(state || 'to_review'); setWhy(reason || '') }, [state, reason])
  const dirty = state === null || st !== state || why !== (reason || '')
  async function save() {
    setBusy(true)
    try { await api(`/api/estates/${route.eid}/plan/state`, json('PUT', { key: stateKey, state: st, reason: why })); onSaved() }
    catch (e: any) { toast(e.message) } finally { setBusy(false) }
  }
  return <>
    <div className="state">
      <select value={st} onChange={e => setSt(e.target.value)}>{Object.entries(STATE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      <textarea value={why} placeholder="Your reasoning: kept with the decision, read by the architect" onChange={e => setWhy(e.target.value)} />
      <button className="primary small" disabled={busy || !dirty} onClick={save}>{state === null ? 'Take it on' : 'Record'}</button>
    </div>
    <div className="meta">{state === null ? 'No decision recorded: a proposal, not yet on the plan.' : updated ? `${STATE_LABEL[state] || state} · ${by || 'local'} · ${ago(updated)} (${when(updated)})${snapshot && planSnapshot && snapshot !== planSnapshot ? ' · recorded on an earlier snapshot' : ''}` : 'No decision recorded yet: to review by default.'} A decision verifies nothing in Anaplan.</div>
  </>
}

function Card({ c, plan, onSaved }: { c: PlanCard; plan: Plan; onSaved: () => void }) {
  const { route, idx, summary } = useApp()
  const eid = route.eid!
  const sid = plan.snapshot
  const deps = c.depends_on.map(k => plan.actions.find(a => a.key === k)).filter(Boolean) as PlanCard[]
  const anchor = 'a-' + encodeURIComponent(c.key)
  return (
    <div className={'acard' + (c.on_plan ? '' : ' below')} id={anchor}>
      <div className="ahead">
        <span className="rank">{c.rank_reason.split(':')[0]}</span>
        <span className="pill dim">{c.kind}</span>
        <span className={'pill ' + (c.on_plan ? '' : c.worth ? 'dim' : 'amber')} title={c.on_plan ? 'On the plan: evidenced, bounded, material, and among the first by rank' : c.why_not}>{c.on_plan ? 'on the plan' : c.worth ? 'met the bar' : 'below the bar'}</span>
        <span className="pill dim" title="Provenance: the findings behind this card were observed in the exports">{PROV_LABEL.observed}</span>
        <StatePill s={c.state.state} none={c.state.default} />
        <span className="grow" />
        <Obj text={c.model} idx={idx} />
      </div>
      <h3>{c.title}</h3>
      {!c.on_plan && c.why_not && <div className="notice">Not on the plan: {c.why_not}.</div>}
      <div className="why">{c.why}</div>
      <ol>{c.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      <KV rows={[
        ['Done when', c.done_when], ['Who', c.role],
        ['Footprint', c.footprint_measured ? [c.footprint_cells ? `${fmtN(c.footprint_cells)} cells` : '', c.footprint_effort ? `${c.footprint_effort.toFixed(1)}% of its model's measured effort` : ''].filter(Boolean).join(' · ') : 'not measured from the exports'],
        ['Evidence', c.strength === 'confirmed' ? 'confirmed against the exports' : c.strength === 'partial' ? 'partial: pages, views and subsets are not in the exports' : 'inferred: a hypothesis to test'],
        ['Tests', (c.tests_named || []).map(t => `${t.num} ${t.title}`).join(' · ')],
        ['Objects', c.objects_resolved.length ? <ObjChips objs={c.objects_resolved} snapshot={sid} idx={idx} /> : ''],
        ['Findings', c.findings.length ? <span>{c.findings.map(f => <span key={f.id} style={{ display: 'block' }}>{f.id} · {f.title} <span className="row-chips" style={{ display: 'inline-flex', gap: 4 }}>{f.rules.map(r => <CiteChip key={r.ref} c={{ id: r.id, kind: 'finding', model: '', ref: r.ref, name: r.ref, snapshot_id: sid || '', provenance: 'observed', tool: '' }} idx={idx} />)}</span></span>)}</span> : ''],
        ['Do first', deps.length ? <span>{deps.map(d => <a key={d.key} href={'#' + 'a-' + encodeURIComponent(d.key)} onClick={e => { e.preventDefault(); document.getElementById('a-' + encodeURIComponent(d.key))?.scrollIntoView({ behavior: 'smooth' }) }}>{d.title}</a>)}</span> : ''],
        ['Ranked', c.rank_reason.replace(/^#\d+:\s*/, '')],
      ]} />
      {c.notices.map((n, i) => <div key={i} className="notice">{n}</div>)}
      {c.detail.length > 0 && <details><summary>The named {c.detail_label || 'objects'} ({c.detail.length})</summary>
        <div className="scroll"><table><thead><tr><th>Object</th>{c.detail.some(d => d.role) && <th>Role</th>}<th className="num">Effort</th><th className="num">Cells</th><th>Formula</th></tr></thead><tbody>
          {c.detail.map((d, i) => <tr key={i}><td><Obj text={d.object} idx={idx} /></td>{c.detail.some(x => x.role) && <td>{d.role || ''}</td>}<td className="num">{d.effort != null ? `${d.effort}%` : ''}</td><td className="num">{d.cells ? fmtN(d.cells) : ''}</td><td style={{ fontFamily: 'var(--mono)', fontSize: 11.5, overflowWrap: 'anywhere' }}>{d.formula}</td></tr>)}
        </tbody></table></div></details>}
      <div className="links">
        {c.explorer && <a href={depsHref(eid, c.explorer.model, c.explorer.ref)}>Change impact in the explorer →</a>}
        {summary?.snapshot && <a href={`/api/estates/${eid}/report`} target="_blank" rel="noreferrer">The report's card ↗</a>}
      </div>
      <StateBox stateKey={c.state_key} state={c.state.default ? 'to_review' : c.state.state} reason={c.state.reason} by={c.state.by} updated={c.state.default ? null : c.state.updated} snapshot={c.state.snapshot_id} planSnapshot={sid} onSaved={onSaved} />
    </div>
  )
}

function ProposalCard({ p, plan, onSaved }: { p: Proposal; plan: Plan; onSaved: () => void }) {
  const { route, idx, toast } = useApp()
  const eid = route.eid!
  async function withdraw() {
    if (!confirm(`Withdraw this proposal?\n\n${p.title}\n\nIt stays in the record but leaves the plan.`)) return
    try { await api(`/api/estates/${eid}/plan/proposals/${p.id}`, { method: 'DELETE' }); onSaved() } catch (e: any) { toast(e.message) }
  }
  return (
    <div className="acard proposal">
      <div className="ahead">
        <span className="pill amber" title="Provenance">{p.origin_kind === 'chat_tool' ? PROV_LABEL.ai_proposed : 'added by the owner, not established'}</span>
        <StatePill s={p.state ? p.state.state : null} />
        <span className="muted small">{ago(p.created)}</span>
        <span className="grow" />
        {p.model && <Obj text={p.model} idx={idx} />}
      </div>
      <h3>{p.title}</h3>
      {p.why && <div className="why">{p.why}</div>}
      {p.steps.length > 0 && <ol>{p.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
      <KV rows={[['Done when', p.done_when], ['Objects', p.objects_resolved.length ? <ObjChips objs={p.objects_resolved} snapshot={plan.snapshot} idx={idx} /> : '']]} />
      <div className="links">
        {p.conversation_id && <a href={href(eid, 'chat', p.conversation_id)}>The conversation it came from →</a>}
        <a onClick={withdraw} style={{ cursor: 'pointer' }}>Withdraw</a>
      </div>
      <StateBox stateKey={p.state_key} state={p.state ? p.state.state : null} reason={p.state?.reason || ''} by={p.state?.by || null} updated={p.state?.updated || null} snapshot={p.state?.snapshot_id || null} planSnapshot={plan.snapshot} onSaved={onSaved} />
    </div>
  )
}

function AddProposal({ onDone }: { onDone: () => void }) {
  const { route, summary, toast } = useApp()
  const models = (summary?.models || []).filter(m => !m.retired)
  const [d, setD] = useState({ title: '', why: '', steps: '', done_when: '', model: models[0]?.name || '', objects: '' })
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { await api(`/api/estates/${route.eid}/plan/proposals`, json('POST', d)); onDone() } catch (e: any) { toast(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="card editor">
      <div className="row" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div><label>Title (action-led, names the object)</label><input value={d.title} onChange={e => setD({ ...d, title: e.target.value })} /></div>
        <div><label>Model</label><select value={d.model} onChange={e => setD({ ...d, model: e.target.value })}>{models.map(m => <option key={m.id} value={m.name}>{m.name}</option>)}</select></div>
      </div>
      <div style={{ marginTop: 8 }}><label className="kicker">Why</label><textarea rows={2} value={d.why} onChange={e => setD({ ...d, why: e.target.value })} /></div>
      <div style={{ marginTop: 8 }}><label className="kicker">Steps, one per line</label><textarea rows={3} value={d.steps} onChange={e => setD({ ...d, steps: e.target.value })} /></div>
      <div className="row" style={{ gridTemplateColumns: '1fr 1fr auto', marginTop: 8 }}>
        <div><label>Done when</label><input value={d.done_when} onChange={e => setD({ ...d, done_when: e.target.value })} /></div>
        <div><label>Objects (comma-separated: Module.Line Item or a module; must exist)</label><input value={d.objects} onChange={e => setD({ ...d, objects: e.target.value })} /></div>
        <div><label>&nbsp;</label><button className="primary" disabled={busy || !d.title.trim()} onClick={save}>Add</button> <button onClick={onDone}>Cancel</button></div>
      </div>
    </div>
  )
}

export function ActionPlan() {
  const { route, summary: s, toast } = useApp()
  const eid = route.eid!
  const [plan, setPlan] = useState<Plan | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [state, setState] = useState('')
  const [model, setModel] = useState('')
  const [below, setBelow] = useState(true)
  const [adding, setAdding] = useState(false)
  const load = useCallback(async () => {
    if (!eid) return
    try { setPlan(await api<Plan>(`/api/estates/${eid}/plan`)); setErr(null) } catch (e: any) { setErr(e.message); if (e.status !== 409) toast(e.message) }
  }, [eid, toast])
  useEffect(() => { load() }, [load, s?.snapshot?.id])
  if (!s) return null
  const head = <><div className="kicker">Estate</div><h1>{s.name}</h1><h2>Action plan</h2></>
  if (!s.snapshot) return <div>{head}<div className="card muted">No active snapshot. Upload and activate one on Home.</div></div>
  if (!plan) return <div>{head}<div className="muted small">{err || 'Ranking the findings…'}</div></div>
  const cards = plan.actions.filter(c => (below || c.on_plan) && (!state || c.state.state === state) && (!model || c.model === model))
  const onPlan = cards.filter(c => c.on_plan), rest = cards.filter(c => !c.on_plan)
  const t = plan.tally
  return (
    <div>
      {head}
      <p className="muted small">The plan is {plan.top != null ? `the first ${plan.top} candidates` : 'every candidate'} that met the bar, picked from the results of every test and ranked as the report ranks them. Everything else is listed under it with the reason it is not on the plan. Record a state and your reasoning on any card; the architect reads them. The architect's own proposals sit apart, unconfirmed until you take them on.</p>

      <div className="tiles">
        <div className="tile"><div className="k">On the plan</div><div className="v">{plan.on_plan}</div><div className="small muted">{plan.considered} considered · {plan.met_bar} met the bar</div></div>
        <div className="tile"><div className="k">To review</div><div className="v">{t.to_review}</div></div>
        <div className="tile"><div className="k">Investigating</div><div className="v">{t.investigating}</div></div>
        <div className="tile"><div className="k">Done</div><div className="v">{t.done}</div><div className="small muted">decisions, not verifications</div></div>
        <div className="tile"><div className="k">Keep design</div><div className="v">{t.keep_current_design}</div></div>
        <div className="tile"><div className="k">Proposals</div><div className="v">{plan.proposals.length}</div><div className="small muted">{plan.unconfirmed} unconfirmed</div></div>
      </div>

      <div className="plan-filters">
        <select value={state} onChange={e => setState(e.target.value)}><option value="">any state</option>{plan.states.map(x => <option key={x} value={x}>{STATE_LABEL[x]}</option>)}</select>
        <select value={model} onChange={e => setModel(e.target.value)}><option value="">all models</option>{s.models.filter(m => !m.retired).map(m => <option key={m.id} value={m.name}>{m.name}</option>)}</select>
        <label><input type="checkbox" checked={below} onChange={e => setBelow(e.target.checked)} />everything else too</label>
        <span style={{ flex: 1 }} />
        <button className="small" onClick={() => setAdding(true)}>Add an action</button>
        <a className="small" href={`/api/estates/${eid}/report`} target="_blank" rel="noreferrer">The report's plan ↗</a>
      </div>

      {(plan.proposals.length > 0 || adding) && <>
        <h2 style={{ marginTop: 10 }}>Proposals <span className="muted small">· kept apart from the deterministic cards</span></h2>
        <p className="group-blurb">Suggestions the architect made in conversation, or actions added by hand. Each names real objects and rests on the evidence it cites, but nothing here was ranked by the findings: it carries no state until you take it on.</p>
        {adding && <AddProposal onDone={() => { setAdding(false); load() }} />}
        {plan.proposals.map(p => <ProposalCard key={p.id} p={p} plan={plan} onSaved={load} />)}
      </>}

      {plan.none && !plan.actions.length && <div className="card"><div>{plan.none.message}</div><div className="small muted" style={{ marginTop: 6 }}>Next check: {plan.none.next_check}.</div></div>}
      {plan.actions.length > 0 && !cards.length && <div className="card muted small">No card matches the filters.</div>}
      {onPlan.length > 0 && <section>
        <h2>The plan <span className="muted small">· {plan.top != null ? `the first ${plan.top} that met the bar` : 'every candidate that met the bar'}</span></h2>
        <p className="group-blurb">Ranked by evidence, scope, materiality, a change before an investigation, ease, then footprint. A prerequisite sits before the action that needs it.</p>
        {onPlan.map(c => <Card key={c.key} c={c} plan={plan} onSaved={load} />)}
      </section>}
      {rest.length > 0 && <section>
        <h2>Everything else <span className="muted small">· {rest.filter(c => c.worth).length} met the bar, {rest.filter(c => !c.worth).length} below it</span></h2>
        <p className="group-blurb">Candidates the tests also raised, each with the reason it is not on the plan. A decision can be recorded on any of them.</p>
        {rest.map(c => <Card key={c.key} c={c} plan={plan} onSaved={load} />)}
      </section>}

      <details style={{ marginTop: 20 }}><summary className="muted small">How the cards are ranked, and what meets the bar</summary>
        <ol className="small" style={{ paddingLeft: 20 }}>{plan.ranking.map((r, i) => <li key={i}>{r}</li>)}</ol>
        <ul className="small" style={{ paddingLeft: 20 }}>{plan.worth.map((r, i) => <li key={i}>{r}</li>)}</ul>
      </details>
      <ul className="gaps dim">{plan.limits.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  )
}
