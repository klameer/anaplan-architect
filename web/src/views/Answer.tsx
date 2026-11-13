// One answer, in the fixed order of docs/DESIGN.md: kind, question, the steps (closed), the answer in a few lines, the
// figure and evidence for its question type, the rest of the prose, what was flagged, the verdict, the context it was given.
// The figure and the evidence are drawn from blocks the server computed (checked passages, the reach the impact tool read,
// the action plan), never from the model's own words. Concise shows the lead and the figures only; the rest opens in place.
import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtC, fmtN, fmtUsd, type Plan, type PlanCard, type Reach, type Turn } from '../api'
import { useApp } from '../App'
import { Markdown, Obj, buildCites } from '../objects'
import { FeedDiagram, ReachRings, ReachSteps, Treemap } from '../design/diagrams'
import { PlanBlock } from './PlanBlock'
import bertQuestion from '../design/brand/bert-architect-question.svg'

const KIND: Record<string, [string, string]> = {
  why: ['Why', 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4'], plan: ['Build plan', 'M4 5h6v5H4zM14 14h6v5h-6zM10 7.5h3.5v9H14'],
  overview: ['Overview', 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z'], improve: ['Improve', 'M4 18l5-6 4 3 7-9M15 6h5v5'],
  implications: ['Implications', 'M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19z'],
  count: ['Count', 'M5 20V10M10 20V4M15 20v-7M20 20v-12'],
  general: ['Answer', 'M4 5h16v11H8l-4 4z'],
}
export const Icon = ({ d, s = 16 }: { d: string; s?: number }) => <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
export const Sec = ({ k, ct, children }: { k: string; ct?: string; children?: React.ReactNode }) => <div className="ds-sec"><span className="k">{k}</span>{ct && <span className="ct">{ct}</span>}{children}</div>

/** The Brief is the lead; everything after it is the rest. An answer with no Brief heading is all lead. */
export function splitBrief(md: string): { lead: string; rest: string } {
  const m = /^##\s+Brief\s*$/im.exec(md || '')
  if (!m) { const i = (md || '').search(/^##\s+/m); return i > 0 ? { lead: md.slice(0, i), rest: md.slice(i) } : { lead: md || '', rest: '' } }
  const after = md.slice(m.index + m[0].length)
  const j = after.search(/^##\s+/m)
  return { lead: (md.slice(0, m.index) + (j >= 0 ? after.slice(0, j) : after)).trim(), rest: j >= 0 ? after.slice(j) : '' }
}

// ---------- blocks ----------
type Quote = { quote: string; found: boolean; before?: string; after?: string }
type Passage = { section: string; citation: string; document: string; document_id?: string; type?: string; date?: string; heading?: string; position?: [number, number]; names?: string[]; quotes: Quote[] }

export function Passages({ items }: { items: Passage[] }) {
  const { idx, openEvidence } = useApp()
  return <>
    <Sec k={items.length === 1 ? 'The passage' : 'The passages'} ct={`${new Set(items.map(p => p.document)).size} document${new Set(items.map(p => p.document)).size !== 1 ? 's' : ''}`} />
    {items.map((p, i) => <div className="ds-src" key={p.section}>
      <div className="sh" role="button" tabIndex={0} style={{ cursor: 'pointer' }} title="Open the whole section" onClick={() => openEvidence({ id: p.citation, ref: p.section, kind: 'document' })}
        onKeyDown={e => { if (e.key === 'Enter') openEvidence({ id: p.citation, ref: p.section, kind: 'document' }) }}>
        <span className="ds-cite" style={{ margin: 0 }}>{i + 1}</span><Icon d="M6 3h9l4 4v14H6zM15 3v4h4" s={15} /><span className="n">{p.document}</span>
        <span className="w">{p.heading}{p.position?.[1] ? ` · section ${p.position[0]} of ${p.position[1]}` : ''}</span><span className="grow" />{p.type && <span className="ds-tag">{p.type}</span>}</div>
      <div className="sb">{p.quotes.length === 0 && <span className="ctx">Cited without a quoted passage. Open the section to read it.</span>}
        {p.quotes.map((q, j) => q.found
          ? <p key={j} style={{ margin: j ? '10px 0 0' : 0 }}>{q.before && <span className="ctx">{q.before} </span>}<mark>{q.quote}</mark>{q.after && <span className="ctx"> {q.after}</span>}</p>
          : (q as any).checked === false
            ? <p key={j} style={{ margin: j ? '10px 0 0' : 0 }}><span className="ds-tag" style={{ marginRight: 8 }} title="A word or two in quotes, or a single-quoted or italic phrase, that is not in this section word for word. It may not be a quotation at all, so it is neither verified nor flagged.">not checked</span><span className="ctx">{q.quote}</span></p>
            : <p key={j} style={{ margin: j ? '10px 0 0' : 0 }}><span className="ds-tag mock" style={{ borderStyle: 'solid', marginRight: 8 }}>quote not found in this section</span><span className="ctx" style={{ textDecoration: 'line-through' }}>{q.quote}</span></p>)}</div>
      <div className="sf"><span>{p.date || 'undated'}</span><span className="grow" />{(p.names || []).length > 0 && <>names <span className="ds-chips">{p.names!.slice(0, 5).map(n => <Obj key={n} text={n} idx={idx} />)}</span></>}</div>
    </div>)}
  </>
}

// The frame of a Not recorded answer, above and outside the answer's own text: the one place Bert stands beside an answer.
export const NotRecorded = () => <div className="ds-none bert" style={{ margin: '0 0 18px' }}><span className="ds-bert-fig" data-bert="question" data-bert-place="not-recorded"><img src={bertQuestion} alt="" aria-hidden="true" width="56" height="48" /></span><div><div className="h">Not recorded</div>
  <div style={{ fontSize: 14 }}>No document or note in this workspace gives a reason. The answer says only what the estate itself shows. The architect does not guess.</div></div></div>

function ReachBlock({ eid, b, full, figure }: { eid: string; b: any; full: boolean; figure: boolean }) {
  const { idx } = useApp()
  const [r, setR] = useState<Reach | null>(null)
  const [err, setErr] = useState('')
  const [view, setView] = useState<'rings' | 'steps'>('rings')
  useEffect(() => { api<Reach>(`/api/estates/${eid}/deps/reach?model=${encodeURIComponent(b.model)}&ref=${encodeURIComponent(b.ref)}&direction=${b.direction || 'downstream'}`).then(setR).catch(e => setErr(e.message)) }, [eid, b.model, b.ref, b.direction])
  if (err) return <p className="ds-gap">The reach could not be drawn: {err}</p>
  if (!r) return <div className="dim">Reading the reach…</div>
  const c = r.counts, maxCells = Math.max(1, ...r.modules.map(m => m.cells))
  const stale = (d: string) => d && new Date(d.replace(' ', 'T')).getTime() < Date.now() - 365 * 864e5
  return <>
    <div className="ds-tiles"><div><div className="v">{c.line_items}</div><div className="l">line items · {c.direct} direct</div></div><div><div className="v">{c.modules}</div><div className="l">modules</div></div><div><div className="v">{fmtC(c.footprint_cells)}</div><div className="l">cells in reach</div></div><div><div className="v">{c.actions ?? '—'}</div><div className="l">actions touch it</div></div><div><div className="v">{c.models_inferred}</div><div className="l">other models, inferred</div></div></div>
    {figure && c.line_items > 0 && <div className="ds-fig"><div className="fh"><span className="k">Reach · {r.direction}</span><div className="ds-seg" role="group" aria-label="Diagram"><button className={view === 'rings' ? 'on' : ''} onClick={() => setView('rings')}>Rings</button><button className={view === 'steps' ? 'on' : ''} onClick={() => setView('steps')}>Steps</button></div><span className="grow" /><div className="ds-leg"><span><u style={{ background: 'var(--sky)', borderRadius: 5 }} />a line item</span></div></div>
      <div className="fb">{view === 'rings' ? <ReachRings r={r} /> : <ReachSteps r={r} />}</div>
      <div className="cap">{view === 'rings' ? 'The change at the centre. Each ring is one more formula away; each sector is a module.' : 'A row per module, a column per step away; the number is how many line items sit there.'} Reach follows formula references: it does not prove a value will change.</div></div>}
    {full && <><div className="ds-two">
      <div><Sec k="By module" ct={String(r.modules.length)} />
        <table><thead><tr><th>Module</th><th className="num">Line items</th><th className="num">From step</th><th className="num">Cells</th></tr></thead>
          <tbody>{r.modules.map(m => <tr key={m.id}><td><Obj text={m.ref} idx={idx} /></td><td className="num">{m.line_items}</td><td className="num">{m.min_distance}</td><td className="num barcell">{fmtC(m.cells)}<i style={{ width: 100 * m.cells / maxCells + '%' }} /></td></tr>)}</tbody></table></div>
      <div><Sec k="Actions" ct="linked at module level" />
        <div className="ds-list">{(r.actions?.touching || []).length === 0 && <div className="r dim">{r.actions ? 'None touch the reach.' : 'No Actions export for this model: actions are not shown.'}</div>}
          {(r.actions?.touching || []).map(a => <div className="r" key={a.ref}><span className="ds-tag">{a.action_kind}</span><span className="grow">{a.ref}<div className="dim" style={{ fontSize: 12 }}>{a.direction} <Obj text={a.module} idx={idx} /></div></span><span className="mono" style={{ fontSize: 11.5, color: stale(a.last_run) ? 'var(--amber)' : 'var(--muted)' }}>{stale(a.last_run) ? 'last run ' : ''}{(a.last_run || '').slice(0, 10)}</span></div>)}</div>
        {r.feeds_inferred.length > 0 && <><Sec k="Other models" ct="inferred" />
          <div className="ds-list">{r.feeds_inferred.map(f => <div className="r" key={f.model}><span className="ds-chip model">{f.model}</span><span className="grow dim" style={{ fontSize: 12.5 }}>{f.actions} import{f.actions > 1 ? 's' : ''} into {f.targets.join(', ')}</span></div>)}</div></>}</div>
    </div>
    <Sec k="What this cannot see" />
    {[...r.coverage, ...r.limits].map(x => <p className="ds-gap" key={x}>{x}</p>)}</>}
  </>
}

function ImproveBlock({ eid, full }: { eid: string; full: boolean }) {
  const { idx, summary } = useApp()
  const [p, setP] = useState<Plan | null>(null)
  useEffect(() => { api<Plan>(`/api/estates/${eid}/plan`).then(setP).catch(() => {}) }, [eid])
  if (!p) return <div className="dim">Reading the action plan…</div>
  const on = p.actions.filter(c => c.on_plan).slice(0, p.top || 5), t = summary?.tests
  const maxC = Math.max(1, ...p.actions.map(c => c.footprint_cells || 0)), maxE = Math.max(1, ...p.actions.map(c => c.footprint_effort || 0))
  const card = (c: PlanCard, i: number) => <div className="ds-card" key={c.key}>
    <div className="rk">{String(i + 1).padStart(2, '0')}</div>
    <div><h3>{c.title}</h3>{full && <div className="why">{c.why}</div>}
      <div className="meta"><span className={'ds-tag ' + (c.kind === 'change' ? 'ok' : 'sky')}>{c.kind === 'change' ? 'change' : 'investigate first'}</span><span className="ds-tag">evidence {c.strength}</span>
        {(c.tests_named || []).slice(0, 2).map(x => <span className="ds-tag violet" key={x.num}>test {x.num} · {x.title}</span>)}</div>
      {full && <div className="ds-chips" style={{ marginTop: 8 }}>{c.objects.slice(0, 3).map(o => <Obj key={o} text={o} idx={idx} />)}{c.objects.length > 3 && <span className="ds-chip">+{c.objects.length - 3}</span>}</div>}</div>
    <div className="win">
      <div className="ds-meter"><div className="l"><span>cells</span><b>{fmtC(c.footprint_cells)}</b></div><div className="t"><i style={{ width: 100 * (c.footprint_cells || 0) / maxC + '%' }} /></div></div>
      <div className="ds-meter v"><div className="l"><span>effort share</span><b>{c.footprint_effort != null ? c.footprint_effort.toFixed(1) + '%' : 'not measured'}</b></div><div className="t"><i style={{ width: 100 * (c.footprint_effort || 0) / maxE + '%' }} /></div></div>
    </div></div>
  return <>
    <div className="ds-fig"><div className="fh"><span className="k">From tests to a plan</span></div><div className="fb"><div className="ds-tiles" style={{ margin: 0, border: 0 }}>
      <div><div className="v">{t?.total ?? '—'}</div><div className="l">tests run</div></div><div><div className="v">{t?.found ?? '—'}</div><div className="l">found something</div></div><div><div className="v">{p.considered}</div><div className="l">candidate actions</div></div><div><div className="v">{p.met_bar}</div><div className="l">met the bar</div></div><div><div className="v" style={{ color: 'var(--accent)' }}>{on.length}</div><div className="l">on the plan</div></div></div></div>
      <div className="cap">Ranked by evidence, then scope, then the size of what is at stake. A bar is what the objects occupy now, not a promised saving.</div></div>
    <Sec k="The plan" ct={`${on.length} of ${p.met_bar}`} />
    {on.length ? on.map(card) : <p className="ds-gap">{p.none?.message || 'Nothing met the bar on this snapshot.'}</p>}
  </>
}

function OverviewBlock() {
  const { summary: s } = useApp()
  if (!s) return null
  return <>
    <div className="ds-fig"><div className="fh"><span className="k">How data moves</span><span className="grow" /><div className="ds-leg"><span><i className="acc" />confirmed</span><span><i className="dash" />inferred from import names</span><span><i className="off" />retired</span></div></div>
      <div className="fb"><FeedDiagram s={s} /></div><div className="cap">The number on a line is the count of import actions behind it.</div></div>
    <div className="ds-fig" style={{ marginTop: 14 }}><div className="fh"><span className="k">Where the cells are</span><span className="grow" /><span className="mono dim" style={{ fontSize: 11 }}>area = exported cell count</span></div><div className="fb"><Treemap s={s} /></div></div>
  </>
}

/** An exact count from the line-item index: the number, what was counted, the split by model, the first rows. */
function CountBlock({ b, full }: { b: any; full: boolean }) {
  const { idx } = useApp()
  const models = Object.entries(b.by_model || {}) as [string, number][], max = Math.max(1, ...models.map(m => m[1]))
  const filters = Object.entries(b.filters || {}).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`)
  return <>
    <div className="ds-fig"><div className="fh"><span className="k">Counted in the line-item index</span><span className="grow" /><span className="mono dim" style={{ fontSize: 10.5 }}>{filters.join(' · ') || 'every line item'}</span></div>
      <div className="fb ds-count"><div><div className="big">{fmtN(b.count)}</div><div className="l">line item{b.count !== 1 ? 's' : ''} of {fmtN(b.of)} · {fmtC(b.cells)} cells</div></div>
        <div className="bars">{models.map(([m, n]) => <div key={m} className="ds-meter"><div className="l"><span>{m}</span><b>{fmtN(n)}</b></div><div className="t"><i style={{ width: 100 * n / max + '%' }} /></div></div>)}</div></div>
      <div className="cap">Exact: every line item of every model is a row in the index, written from the same parse the engine reads. The list itself never went to the model.</div></div>
    {full && b.groups?.rows?.length > 0 && <><Sec k={`By ${b.groups.by}`} ct={String(b.groups.rows.length)} />
      <table><thead><tr><th>{b.groups.by}</th><th className="num">Line items</th><th className="num">Cells</th></tr></thead><tbody>{b.groups.rows.slice(0, 12).map((g: any) => <tr key={g.key}><td>{g.key}</td><td className="num">{fmtN(g.line_items)}</td><td className="num">{fmtC(g.cells)}</td></tr>)}</tbody></table></>}
    {full && b.rows?.length > 0 && <><Sec k={`The first ${b.rows.length}, by ${b.sorted_by || 'cells'}`} ct={`of ${fmtN(b.count)}`} />
      <table><thead><tr><th>Line item</th><th>Model</th><th className="num">Cells</th><th>Formula</th></tr></thead>
        <tbody>{b.rows.map((r: any) => <tr key={r.model + r.object}><td><Obj text={r.object} idx={idx} /></td><td className="dim">{r.model}</td><td className="num">{fmtC(r.cells)}</td><td><span className="ds-f">{r.formula}</span></td></tr>)}</tbody></table></>}
  </>
}

/** The figure and evidence for an answer, by its blocks. Full draws everything. Concise draws what the reader acts on
 * (the plan's numbered steps, a count, the key figures of a reach, Not recorded); `figs` adds the diagrams and sources. */
function Blocks({ t, eid, full, figs, onAsk }: { t: Turn; eid: string; full: boolean; figs: boolean; onAsk?: (q: string) => void }) {
  const more = full || figs
  const { openEvidence } = useApp()
  const raw: any[] = (t as any).blocks || []
  // a build plan leads; the passages and notes that record why it was wanted follow it, they do not sit on top of it
  const isPlan = raw.some(b => b.type === 'build_plan')
  const blocks = isPlan ? [...raw.filter(b => b.type !== 'passages' && b.type !== 'notes'), ...raw.filter(b => b.type === 'passages' || b.type === 'notes')] : raw
  return <>{blocks.map((b, i) => {
    if (b.type === 'not_recorded') return <NotRecorded key={i} />
    if (b.type === 'passages') return more ? <React.Fragment key={i}>{isPlan && <Sec k="Why this was wanted" ct="what the documents record" />}<Passages items={b.items} /></React.Fragment> : null
    if (b.type === 'notes' && full) return <React.Fragment key={i}><Sec k="Owner notes it rests on" ct={String(b.items.length)} />
      <div className="ds-list">{b.items.map((n: any) => <div className="r" key={n.id} role="button" tabIndex={0} style={{ cursor: 'pointer' }} onClick={() => openEvidence({ id: n.citation, ref: n.id, kind: 'note' })}><span className="ds-tag">note</span><span className="grow">{n.title}</span><span className="dim">open →</span></div>)}</div></React.Fragment>
    if (b.type === 'reach') return <ReachBlock key={i} eid={eid} b={b} full={full} figure={more} />
    if (b.type === 'improve') return more ? <ImproveBlock key={i} eid={eid} full={full} /> : null
    if (b.type === 'overview') return more ? <OverviewBlock key={i} /> : null
    if (b.type === 'count') return <CountBlock key={i} b={b} full={full} />
    if (b.type === 'build_plan') return <PlanBlock key={i} plan={b.plan} full={full} onAsk={onAsk} turn={t.id} />
    if (b.type === 'plan_rejected') return <div className="ds-none" key={i} style={{ marginBottom: 18 }}><div className="h">No plan passed the checks</div><div style={{ fontSize: 14 }}>The proposal was rejected by the code that parses the formulas and resolves the references, so no plan is shown.{(b.rejected || []).slice(0, 4).map((r: any, j: number) => <div key={j} className="dim" style={{ fontSize: 12.5, marginTop: 4 }}>{r.what}: {r.why}</div>)}</div></div>
    return null
  })}</>
}

// ---------- the context it was given, and what it did ----------
const CK: Record<string, [string, string]> = { instructions: ['instructions', '#7d8985'], estate: ['the estate in brief', '#5d8a96'], cards: ['document cards', '#9aa5a0'], section: ['sections pulled', '#34d399'],
  note: ['notes', '#a78bfa'], tool: ['tool results', '#38bdf8'], conversation: ['conversation', '#5d6964'], question: ['question', '#e8ebe9'] }
const RUNC: Record<string, string> = { model: '#a78bfa', tool: '#38bdf8', check: '#34d399' }

export function ContextPanel({ t }: { t: Turn }) {
  const ctx: any = (t as any).context, run: any = (t as any).run
  if (!ctx && !run) return <p className="ds-gap">This answer was recorded before the context view existed.</p>
  const items: any[] = ctx?.items || [], left: any[] = ctx?.left_out || []
  const kinds = Object.keys(CK).map(k => ({ k, tok: items.filter(i => i.kind === k).reduce((a, i) => a + i.tokens, 0) })).filter(x => x.tok)
  const scale = Math.max(ctx?.budget || 1, ctx?.total || 1), max = Math.max(1, ...items.map(i => i.tokens)), leftTok = left.reduce((a, i) => a + (i.tokens || 0), 0)
  const end = Math.max(0.001, run?.seconds || 0)
  return <div className="ds-ctxpanel">
    {ctx && <><div className="ds-fig"><div className="fh"><span className="k">Context</span><span className="mono dim" style={{ fontSize: 10.5 }}>what the model was given for this answer</span></div>
      <div className="fb">
        <div className="ds-big"><span className="v" style={ctx.over ? { color: 'var(--amber)' } : undefined}>{fmtN(ctx.total)}</span><span className="of">of {fmtN(ctx.budget)} tokens · {Math.round(100 * ctx.total / ctx.budget)}% of the budget{leftTok ? ` · ${fmtN(leftTok)} left out` : ''}</span></div>
        <div className="ds-budget" role="img" aria-label={'Context by kind: ' + kinds.map(b => `${CK[b.k][0]} ${b.tok}`).join(', ')}>{kinds.map(b => <i key={b.k} title={`${CK[b.k][0]} · ${fmtN(b.tok)} tokens`} style={{ width: 100 * b.tok / scale + '%', background: CK[b.k][1] }} />)}</div>
        <div className="ds-bk">{kinds.map(b => <span key={b.k}><u style={{ background: CK[b.k][1] }} />{CK[b.k][0]} {fmtN(b.tok)}</span>)}</div>
      </div>
      <div className="cap">{ctx.over ? 'Over the budget: what every answer starts with is already larger, so each tool result was held to a short one. ' : 'The budget is enforced in code: a tool result that would break it is cut to a count and its first rows. '}{ctx.estimate}.</div></div>
    <Sec k="Given to the model" ct={`${items.length} items`} />
    <table className="ds-ctx"><thead><tr><th style={{ width: '17%' }}>Kind</th><th style={{ width: '36%' }}>Item</th><th>Why it is here</th><th className="num" style={{ width: '9%' }}>Tokens</th></tr></thead>
      <tbody>{items.map((c, i) => <tr key={i}><td><span className="ds-tag" style={{ color: CK[c.kind]?.[1], borderColor: (CK[c.kind]?.[1] || '#9aa5a0') + '88' }}>{CK[c.kind]?.[0] || c.kind}</span></td><td>{c.label}</td><td className="why">{c.why}</td><td className="num barcell">{fmtN(c.tokens)}<i style={{ width: 100 * c.tokens / max + '%', background: CK[c.kind]?.[1] }} /></td></tr>)}</tbody></table>
    {left.length > 0 && <><Sec k="Left out" ct={`${fmtN(leftTok)} tokens not sent`} />
      <table className="ds-ctx"><tbody>{left.map((c, i) => <tr className="out" key={i}><td style={{ width: '17%' }}><span className="ds-tag">not sent</span></td><td style={{ width: '36%' }} className="it">{c.label}</td><td className="why">{c.why}</td><td className="num" style={{ width: '9%' }}>{fmtN(c.tokens)}</td></tr>)}</tbody></table></>}</>}
    {run && <div className="ds-fig" style={{ marginTop: 26 }}><div className="fh"><span className="k">Run</span><span className="grow" /><div className="ds-leg"><span><u style={{ background: RUNC.model }} />model call</span><span><u style={{ background: RUNC.tool }} />tool call</span><span><u style={{ background: RUNC.check }} />validator</span></div></div>
      <div className="fb"><div className="ds-run">{(run.steps || []).map((r: any, i: number) => <React.Fragment key={i}>
        <div className="n">{String(i + 1).padStart(2, '0')}</div>
        <div><span className="ds-tag" style={{ color: RUNC[r.kind], borderColor: RUNC[r.kind] + '88' }}>{r.kind}</span></div>
        <div style={{ overflow: 'hidden' }}><span className="nm">{r.name}</span> <span className="a">{r.kind === 'model' ? `${fmtN(r.tokens_in)} tokens in, ${fmtN(r.tokens_out)} out` : r.args}{r.out ? ` → ${r.out}` : ''}</span></div>
        <div><div className="tl"><i style={{ left: 100 * r.t0 / end + '%', width: Math.max(0.6, 100 * (r.ms / 1000) / end) + '%', background: RUNC[r.kind] }} /></div></div>
        <div className="d">{r.ms < 1000 ? r.ms + ' ms' : (r.ms / 1000).toFixed(1) + ' s'}</div>
      </React.Fragment>)}</div></div>
      <div className="cap">{run.model_calls} model call{run.model_calls !== 1 ? 's' : ''}, {run.tool_calls} tool call{run.tool_calls !== 1 ? 's' : ''}, 1 check · {run.seconds} s · {fmtN(run.tokens_in)} tokens in, {fmtN(run.tokens_out)} out{run.cost_usd ? ` · ${fmtUsd(run.cost_usd)}` : ''} · {run.model}. Kept with the answer: no outside account is needed to see it.</div></div>}
  </div>
}

// ---------- one turn ----------
export function TurnView({ t, eid, first, onSave, onAsk }: { t: Turn; eid: string; first: boolean; onSave: () => void; onAsk: (q: string, mode?: string) => void }) {
  const { idx } = useApp()
  const x = t as any
  const kind: string = x.kind && KIND[x.kind] ? x.kind : 'general'
  const concise = x.mode === 'concise'
  const [full, setFull] = useState(!concise)
  const [figs, setFigs] = useState(false)
  const [ctxOpen, setCtxOpen] = useState(false)
  const cites = useMemo(() => buildCites(t), [t])
  const v = t.verification, f = v?.figures
  const untraced = f?.untraced || [], phantom = v?.phantom || []
  const { lead, rest } = useMemo(() => splitBrief(t.a), [t.a])
  const steps: any[] = x.run?.steps || []
  const blocks: any[] = x.blocks || []
  const hasFigure = blocks.some(b => ['reach', 'improve', 'overview'].includes(b.type))            // a plan and a count carry their own
  const hasSources = blocks.some(b => b.type === 'passages')
  const parts = [`${v?.cited ?? 0} cited`]
  const qs = (v as any)?.quotes
  if (qs?.checked) parts.push(`${qs.found}/${qs.checked} quote${qs.checked !== 1 ? 's' : ''} found`)
  if (qs?.unchecked) parts.push(`${qs.unchecked} quote${qs.unchecked !== 1 ? 's' : ''} not checked`)
  if (v?.unchecked) parts.push(`${v.unchecked} unchecked`)
  if (v?.unverified) parts.push(`${v.unverified} not found`)
  if (phantom.length) parts.push(`${phantom.length} phantom id${phantom.length !== 1 ? 's' : ''}`)
  if (f?.checked) parts.push(`figures ${f.traced + f.derived}/${f.checked} traced`)
  const md = (text: string) => <Markdown md={text} idx={idx} unverified={t.unverified} cites={cites} unchecked={t.unchecked} phantom={phantom} untraced={untraced} />
  return (
    <article className="ds-turn">
      <div className="ds-kick"><span className="type"><Icon d={KIND[kind][1]} s={14} />{KIND[kind][0]}</span><span className="k">· {concise ? 'concise' : 'full'}</span></div>
      {first ? <h1 className="ds-q">{t.q}</h1> : <h2 className="ds-q" style={{ fontSize: 21 }}>{t.q}</h2>}
      {steps.length > 0 && <details className="ds-steps"><summary>{steps.length} steps · read what the architect did</summary>
        <ol>{steps.map((s, i) => <li key={i}>{s.kind === 'model' ? `model: ${s.name}` : s.kind === 'check' ? `validator: ${s.args}` : `${s.name}(${s.args || ''})`} → {s.out}</li>)}</ol></details>}
      {kind === 'plan' && full && <div className="ds-sec" style={{ marginTop: 4 }}><span className="k">Overview</span></div>}
      <div className="ds-lead md-lead">{md(lead)}</div>
      <Blocks t={t} eid={eid} full={full} figs={figs} onAsk={q => onAsk(q, x.mode)} />
      {!full && <div className="ds-affs">
        {(hasFigure || hasSources) && <button className="ds-aff" onClick={() => setFigs(s => !s)}>{figs ? (hasFigure ? 'hide diagram' : 'hide sources') : (hasFigure ? 'show diagram' : 'show sources')}</button>}
        <button className="ds-aff" onClick={() => onAsk('Explain that answer in more detail.', 'full')}>explain</button>
        <button className="ds-aff" onClick={() => setFull(true)} title="The figures, sources and tables for this answer, without asking again">expand to Full</button></div>}
      {full && rest.trim() && <div className="ds-rest">{md(rest)}</div>}
      {(t.unverified?.length || phantom.length || untraced.length || qs?.missing?.length) ? <div className="ds-flags">
        {t.unverified && t.unverified.length > 0 && <p className="ds-gap">Names not found in the estate: {t.unverified.map((n, i) => <React.Fragment key={i}>{i ? ' ' : ''}<code className="obj unknown">{n}</code></React.Fragment>)}</p>}
        {phantom.length > 0 && <p className="ds-gap">Ids the tools never handed: {phantom.join(', ')}</p>}
        {untraced.length > 0 && <p className="ds-gap">Figures no tool returned this turn: {untraced.join(', ')}</p>}
        {qs?.missing?.length > 0 && <p className="ds-gap">{qs.missing.length} quoted passage{qs.missing.length !== 1 ? 's are' : ' is'} not in the section named: marked on the source card.</p>}
      </div> : null}
      {t.unchecked && t.unchecked.length > 0 && full && <p className="small muted" style={{ marginTop: 10 }}>Named without being looked up (click to look up now): {t.unchecked.map((n, i) => <React.Fragment key={i}>{i ? ' ' : ''}<Obj text={n} idx={idx} unchecked={t.unchecked} /></React.Fragment>)}</p>}
      <div className="ds-foot">
        {v ? <span className={'ds-tag ' + (v.clean ? 'ok' : 'mock')} style={v.clean ? undefined : { borderStyle: 'solid' }} title={v.clean ? 'Every name was handed by a tool, every figure traces to a tool result, every quote is in its section' : 'Something in this answer could not be tied to the workspace: it is marked above'}>{v.clean ? 'verified' : 'flagged'}</span> : <span className="ds-tag">not checked</span>}
        <span className="mono">{parts.join(' · ')}</span><span className="grow" />
        {x.context && <button className="ctx" onClick={() => setCtxOpen(o => !o)} aria-expanded={ctxOpen} title="What the model was given for this answer, and the steps it took">context {(x.context.total / 1000).toFixed(1)}k / {Math.round(x.context.budget / 1000)}k</button>}
        <button onClick={onSave} title="Keep this answer as a note the architect reads next time; it carries this turn's citations">Save as note</button>
      </div>
      {ctxOpen && <ContextPanel t={t} />}
    </article>
  )
}
