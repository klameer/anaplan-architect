// The v0.2 design sheet (P0, docs/DESIGN.md): the restyled shell and one answer pattern per question type, as real
// pages on the Caldergate demo estate. Reached at #/design. Nothing here writes to the store and nothing animates.
// Each page says what is live and what is mocked; a MOCK tag sits on every block that is static.
import React, { useEffect, useState } from 'react'
import { fmtC, fmtN, type PlanCard } from '../api'
import { BUILD, BUILD_EXISTING, CALDERGATE, FPA, FX_DOCS, PATTERNS, WHY_DOCS, WORKSPACES, loadLive, type DocPassage, type Live, type PatternKey } from './data'
import { BuildOrder, FeedDiagram, ReachRings, ReachSteps, Treemap } from './diagrams'
import { ContextPage, DocumentsPage, SettingsPage } from './Extras'
import { Dashboard } from './Dashboard'
import logoUrl from './brand/logo.svg'
import bertQuestion from './brand/bert-architect-question.svg'
import bertEvidence from './brand/bert-architect-evidence.svg'
import './design.css'

const Icon = ({ d, s = 16 }: { d: string; s?: number }) => <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
const link = (k?: string) => '#/design' + (k ? '/' + k : '')
const NEW_MODS = new Set(BUILD.filter(m => !BUILD_EXISTING.includes(m.name)).map(m => m.name))

/** An object name as a chip: module in sky, line item in violet with its module in sky, a new object of a plan in green. */
function C({ t }: { t: string }) {
  const i = t.indexOf('.')
  const mod = i > 0 ? t.slice(0, i) : t, nw = NEW_MODS.has(mod)
  if (i < 0) return <span className={'ds-chip ' + (/^Caldergate|Workforce Planning|Board Reporting/.test(t) ? 'model' : nw ? 'new' : 'mod')}>{t}</span>
  return <span className={'ds-chip li' + (nw ? ' new' : '')}><s>{mod}</s><em>.</em>{t.slice(i + 1)}</span>
}
const Mock = ({ what }: { what?: string }) => <span className="ds-tag mock" title={'Static in this sheet' + (what ? ': ' + what : '')}>mock</span>
const Sec = ({ k, ct, mock }: { k: string; ct?: string; mock?: boolean }) => <div className="ds-sec"><span className="k">{k}</span>{ct && <span className="ct">{ct}</span>}{mock && <Mock />}</div>

/** A formula as the grammar reads it: functions, keywords, references (a reference to an object this plan creates is green). */
function Formula({ f }: { f: string }) {
  if (!f) return <span className="ds-f in">input</span>
  const RE = /('[^']+')(\.(?:[^\s\[\]()*+\-\/,<>=:]|\s(?![*+\-\/<>=]|THEN\b|ELSE\b))+)?|\b(IF|THEN|ELSE|AND|OR|NOT)\b|\b([A-Z]{3,})(?=\()|\b(SUM|LOOKUP|SELECT)(?=:)/g
  const out: React.ReactNode[] = []; let last = 0, m: RegExpExecArray | null, k = 0
  while ((m = RE.exec(f))) {
    if (m.index > last) out.push(f.slice(last, m.index))
    if (m[1]) { const nw = NEW_MODS.has(m[1].slice(1, -1)); out.push(<span key={k++} className={nw ? 'nw' : 'm'}>{m[1]}</span>); if (m[2]) out.push(<span key={k++} className={nw ? 'nw' : 'l'}>{m[2]}</span>) }
    else if (m[3]) out.push(<span key={k++} className="kw">{m[3]}</span>)
    else out.push(<span key={k++} className="fn">{m[4] || m[5]}</span>)
    last = m.index + m[0].length
  }
  if (last < f.length) out.push(f.slice(last))
  return <span className="ds-f">{out}</span>
}

function Source({ d, n }: { d: DocPassage; n: number }) {
  return (
    <div className="ds-src">
      <div className="sh"><span className="ds-cite" style={{ margin: 0 }}>{n}</span><Icon d="M6 3h9l4 4v14H6zM15 3v4h4" s={15} /><span className="n">{d.doc}</span><span className="w">{d.where}</span><span className="grow" /><span className="ds-tag">{d.kind}</span><Mock what="project documents arrive in P1" /></div>
      <div className="sb">{d.before && <span className="ctx">{d.before} </span>}<mark>{d.quote}</mark>{d.after && <span className="ctx"> {d.after}</span>}</div>
      <div className="sf"><span>{d.date} · {d.by}</span><span className="grow" />names <span className="ds-chips">{d.names.map(x => <C key={x} t={x} />)}</span></div>
    </div>
  )
}

function Head({ p, scope, steps }: { p: PatternKey; scope: string; steps: string[] }) {
  const P = PATTERNS.find(x => x.key === p)!
  return <>
    <div className="ds-kick"><span className="type"><Icon d={P.icon} s={14} />{P.label}</span><span className="k">· {scope}</span></div>
    <h1 className="ds-q">{P.q}</h1>
    <details className="ds-steps"><summary>{steps.length} steps · read what the architect looked at</summary><ol>{steps.map(s => <li key={s}>{s}</li>)}</ol></details>
  </>
}

function Foot({ cited, note, next }: { cited: string; note?: string; next: [PatternKey, string][] }) {
  return <>
    <div className="ds-foot"><span className="ds-tag ok">verified</span><span className="mono">{cited}</span>{note && <span>· {note}</span>}<span className="grow" /><a className="ctx" href={link('context')} title="What the model was given for this answer, and the run">context 5.2k / 24k</a><button>Save as note</button><button>Copy</button><button>Export</button></div>
    <div className="ds-next">{next.map(([k, q]) => { const P = PATTERNS.find(x => x.key === k)!; return <a key={q} href={link(k)}><span className="k">{P.label}</span><span>{q}</span><span className="ar">→</span></a> })}</div>
  </>
}

// ---------- 1. why ----------
function Why({ live }: { live: Live }) {
  const card = live.plan.actions.find(c => c.objects.includes('CAL03 Opex.Forecast Opex'))
  const note = live.notes.find(n => /Forecast Opex/.test(n.title))
  return <>
    <Head p="why" scope={FPA} steps={['search_documents "Forecast Opex mapping" → 2 passages', 'get_object CAL03 Opex.Forecast Opex', 'notes scoped to CAL03 Opex.Forecast Opex → 1', 'tests on CAL03 Opex.Forecast Opex → 4.6', 'validator: 2 passages, 1 note, 3 objects cited; 0 unverified']} />
    <p className="ds-lead">It was a control decision, not a modelling one. In 2019 Finance Systems asked that planners <b>should not be able to edit the account-to-driver mapping</b>, so the partner wrote it into the formula<span className="ds-cite">1</span>. A lookup module was agreed in principle in 2024 and never scheduled<span className="ds-cite">2</span>.</p>
    <div className="ds-fig"><div className="fh"><span className="k">How it got here</span><span className="grow" /><Mock what="dates come from the documents" /></div>
      <div className="fb"><div className="ds-trail">
        <div className="st"><div className="dot" /><div className="y">Mar 2019 · decision record 4.3</div><div className="h">Mapping kept in the formula</div><div className="d">So a change to it is a model change, not a planner edit.</div></div>
        <div className="st"><div className="dot" /><div className="y">May 2024 · CR-031</div><div className="h">A thirteenth branch requested</div><div className="d">Legal fees. Lookup module agreed in principle, out of scope.</div></div>
        <div className="st now"><div className="dot" /><div className="y">Today · the estate</div><div className="h">{card ? `${card.footprint_effort}% of the model's effort` : 'Twelve IF branches'}</div><div className="d">{card ? `${fmtC(card.footprint_cells)} cells; test ${card.tests_named?.[0]?.num} flags it.` : ''}</div></div>
      </div></div>
    </div>
    <Sec k="The passages" ct="2 documents" />
    <div className="ds-bert"><img src={bertEvidence} alt="Bert, with a document chip" width="40" height="40" /><span>Found the source.</span></div>
    {WHY_DOCS.map((d, i) => <Source key={d.doc} d={d} n={i + 1} />)}
    {note && <><Sec k="Owner note that agrees" ct="live" />
      <div className="ds-src"><div className="sh"><span className="ds-cite" style={{ margin: 0 }}>3</span><span className="n">{note.title}</span><span className="grow" /><span className="ds-tag">{note.type}</span></div><div className="sb" style={{ fontSize: 13.5 }}>{note.body.replace(/`/g, '')}</div></div></>}
    <Sec k="Objects this rests on" />
    <div className="ds-chips"><C t="CAL03 Opex.Forecast Opex" /><C t="INP02 Opex Drivers" /><C t="SYS03 Account Attributes" /><C t={FPA} /></div>
    <Sec k="When nothing is recorded" ct="the same pattern, no source" />
    <div className="ds-none bert"><img src={bertQuestion} alt="Bert, with a question chip" width="48" height="48" /><div><div className="h">Not recorded</div>
      <div style={{ fontSize: 14 }}>"Why is the margin module called <C t="CAL04 Margn" />?" No document or note in this workspace gives a reason. What the estate shows: 4 line items, read by <C t="CAL07 P&L by Cost Centre" />; the name appears in no other model. The architect does not guess.</div></div></div>
    <Foot cited="2 passages · 1 note · 3 objects cited" next={[['implications', 'What would moving the mapping to a lookup module touch?'], ['plan', 'Give me a plan to build the lookup module.'], ['improve', 'What else in CAL03 Opex is worth changing?']]} />
  </>
}

// ---------- 2. build plan ----------
function BuildPlan() {
  const refs = BUILD.flatMap(m => m.items.flatMap(i => [...i.formula.matchAll(/'([^']+)'/g)].map(x => x[1])))
  const refNew = refs.filter(x => NEW_MODS.has(x)).length, refOld = refs.length - refNew
  const items = BUILD.reduce((a, m) => a + m.items.length, 0), calc = BUILD.reduce((a, m) => a + m.items.filter(i => i.formula).length, 0)
  return <>
    <Head p="plan" scope={FPA} steps={['notes scoped to CAL09 Scenario Planning → the FY27 ask', 'get_object CAL09 Scenario Planning (empty, applies to Scenarios)', 'get_object CAL01 Volumes, INP01 Volumes, CAL07 P&L by Cost Centre …', `build_plan → ${BUILD.length} modules, ${items} line items`, `grammar: ${calc} formulas parsed; ${refs.length} references resolved; order sorted; no cycle`]} />
    <p className="ds-lead">Five modules, four of them new, built in this order. Scenarios flex what the model already calculates: <b>nothing existing is edited</b>, and the IF chain in Forecast Opex is not copied.</p>
    <div className="ds-tiles"><div><div className="v">+ 4</div><div className="l">modules to add</div></div><div><div className="v">~ 1</div><div className="l">module to fill</div></div><div><div className="v">{items}</div><div className="l">line items, {calc} calculated</div></div><div><div className="v">0</div><div className="l">existing formulas changed</div></div></div>
    <div className="ds-fig"><div className="fh"><span className="k">Build order</span><span className="grow" /><div className="ds-leg"><span><i className="acc" />reads a new object</span><span><i />reads the model as it is</span></div><Mock what="the build_plan tool arrives in P3" /></div>
      <div className="fb"><BuildOrder /></div>
      <div className="cap">Left to right: nothing is built before what it refers to. A numbered box is a step of this plan.</div></div>
    <Sec k="The plan, step by step" ct={`${BUILD.length} modules`} mock />
    {BUILD.map(m => <div className="ds-mod" key={m.name}>
      <div className="mh"><span className="step">{m.step}</span><span className="n">{m.name}</span><span className={'ds-tag ' + (m.state === 'new' ? 'ok' : 'sky')}>{m.state === 'new' ? 'new' : 'exists, empty'}</span><span className="grow" /><span className="k">applies to</span><span className="ds-chips">{m.applies.map(a => <span className="ds-chip" key={a}>{a}</span>)}</span></div>
      <div className="mn">{m.note}</div>
      <table><thead><tr><th style={{ width: '22%' }}>Line item</th><th style={{ width: '11%' }}>Format</th><th style={{ width: '9%' }}>Summary</th><th>Formula</th></tr></thead>
        <tbody>{m.items.map(i => <tr key={i.name}><td>{i.name}</td><td className="dim">{i.format}</td><td className="dim">{i.summary}</td><td><Formula f={i.formula} /></td></tr>)}</tbody></table>
    </div>)}
    <Sec k="What was checked" />
    <div className="ds-list">
      <div className="r"><span className="ds-tag ok">parsed</span><span className="grow">Every formula parses with the Anaplan grammar.</span><span className="mono dim">{calc} of {calc}</span></div>
      <div className="r"><span className="ds-tag ok">resolved</span><span className="grow">Every reference names an object in the model or one this plan creates.</span><span className="mono dim">{refOld} existing · {refNew} new</span></div>
      <div className="r"><span className="ds-tag ok">ordered</span><span className="grow">The order has no cycle; each step reads only earlier steps.</span><span className="mono dim">5 steps</span></div>
      <div className="r"><span className="ds-tag">not checked</span><span className="grow dim">Cell count of the new modules: the exports do not say how big Scenarios × Cost Centres is until it exists.</span></div>
    </div>
    <Foot cited={`${BUILD_EXISTING.length} existing modules cited · ${calc} formulas parsed`} note="a plan is a proposal: nothing is built in Anaplan" next={[['implications', 'What does CAL07 P&L by Cost Centre feed today?'], ['why', 'Why is CAL09 Scenario Planning empty?'], ['overview', 'Where would these modules sit in the model?']]} />
  </>
}

// ---------- 3. overview ----------
function Overview({ live }: { live: Live }) {
  const s = live.summary, li = s.models.reduce((a, m) => a + (m.line_items || 0), 0), cells = s.models.reduce((a, m) => a + (m.cells || 0), 0)
  const what = (live.notes.find(n => n.type === 'purpose' && n.scope_labels.includes('estate'))?.body || '').split(/(?<=\.)\s+/)
  const purpose = (name: string) => (what.find(x => x.startsWith('`' + name + '`')) || '').replace(/`/g, '')
  const top = s.models.flatMap(m => (m.cells_by_module || []).map(c => ({ m: m.name, n: c[0], c: c[1] }))).sort((a, b) => b.c - a.c)[0]
  return <>
    <Head p="overview" scope="whole workspace" steps={['list_models → 4', 'material: counts, feeds, tests', 'notes: purpose notes for each model → 4', 'validator: 4 models, 6 feeds, 9 figures traced']} />
    <p className="ds-lead">Four models: a data hub feeding two planning models, and a board pack on top. Almost all of it is <b>{FPA}</b> ({fmtC(s.models.find(m => m.name === FPA)?.cells)} of {fmtC(cells)} cells), and over half of that is one module nothing reads.</p>
    <div className="ds-tiles"><div><div className="v">{s.models.length}</div><div className="l">models</div></div><div><div className="v">{fmtN(li)}</div><div className="l">line items</div></div><div><div className="v">{fmtC(cells)}</div><div className="l">cells</div></div><div><div className="v">{s.edges.length}</div><div className="l">feeds between models</div></div><div><div className="v">{s.tests?.found} / {s.tests?.total}</div><div className="l">tests found something</div></div></div>
    <div className="ds-fig"><div className="fh"><span className="k">How data moves</span><span className="grow" /><div className="ds-leg"><span><i className="acc" />confirmed by the owner</span><span><i className="dash" />inferred from import names</span><span><i className="off" />retired</span></div></div>
      <div className="fb"><FeedDiagram s={s} /></div>
      <div className="cap">The number on a line is the count of import actions behind it. A dashed line is read off action names and stays inferred until the owner confirms it.</div></div>
    <div className="ds-fig" style={{ marginTop: 14 }}><div className="fh"><span className="k">Where the cells are</span><span className="grow" /><span className="mono dim" style={{ fontSize: 11 }}>area = exported cell count</span></div>
      <div className="fb"><Treemap s={s} /></div>
      {top && <div className="cap"><C t={top.n} /> alone is {fmtC(top.c)} cells in {top.m}.</div>}</div>
    <Sec k="The models" ct="purpose from the owner's notes" />
    <table><thead><tr><th style={{ width: '24%' }}>Model</th><th>What it is for</th><th className="num">Modules</th><th className="num">Line items</th><th className="num">Cells</th></tr></thead>
      <tbody>{s.models.map(m => <tr key={m.id}><td><C t={m.name} /></td><td style={{ color: '#cdd3d0' }}>{purpose(m.name) || <span className="dim">Not recorded.</span>}</td><td className="num">{m.modules}</td><td className="num">{m.line_items}</td><td className="num">{fmtC(m.cells)}</td></tr>)}</tbody></table>
    <Sec k="What to know first" mock />
    <p className="ds-p">The hub loads NetSuite, Salesforce and Workday and feeds both planning models; the board pack reads FP&amp;A and Workforce and calculates almost nothing itself. Three different hands built the estate, which is why Workforce Planning does not follow the naming the other three share.</p>
    <p className="ds-p">The feed from FP&amp;A back into Workforce Planning is retired: the import exists and has not run since 2022. Every other feed is still inferred from action names, so the first job in a handover is to confirm them with each owner.</p>
    <Foot cited="4 models · 6 feeds · 4 notes cited" note="pages, views and dashboards are not in the exports" next={[['improve', 'How can we improve it?'], ['implications', 'What depends on the FX rates?'], ['why', 'Why is CAL05 Opex OLD still in the model?']]} />
  </>
}

// ---------- 4. improve ----------
function ImproveCard({ c, i, maxC, maxE }: { c: PlanCard; i: number; maxC: number; maxE: number }) {
  return (
    <div className="ds-card">
      <div className="rk">{String(i + 1).padStart(2, '0')}</div>
      <div><h3>{c.title}</h3><div className="why">{c.why}</div>
        <div className="meta"><span className={'ds-tag ' + (c.kind === 'change' ? 'ok' : 'sky')}>{c.kind === 'change' ? 'change' : 'investigate first'}</span><span className="ds-tag">evidence {c.strength}</span>
          {(c.tests_named || []).slice(0, 2).map(t => <span className="ds-tag violet" key={t.num}>test {t.num} · {t.title}</span>)}{(c.tests_named || []).length > 2 && <span className="ds-tag">+{c.tests_named!.length - 2}</span>}</div>
        <div className="ds-chips" style={{ marginTop: 8 }}>{c.objects.slice(0, 3).map(o => <C key={o} t={o} />)}{c.objects.length > 3 && <span className="ds-chip">+{c.objects.length - 3}</span>}</div></div>
      <div className="win">
        <div className="ds-meter"><div className="l"><span>cells</span><b>{fmtC(c.footprint_cells)}</b></div><div className="t"><i style={{ width: 100 * (c.footprint_cells || 0) / maxC + '%' }} /></div></div>
        <div className="ds-meter v"><div className="l"><span>effort share</span><b>{c.footprint_effort != null ? c.footprint_effort.toFixed(1) + '%' : 'not measured'}</b></div><div className="t"><i style={{ width: 100 * (c.footprint_effort || 0) / maxE + '%' }} /></div></div>
      </div>
    </div>
  )
}
function Improve({ live }: { live: Live }) {
  const p = live.plan, on = p.actions.filter(c => c.on_plan).slice(0, p.top || 5), rest = p.actions.filter(c => c.worth && !on.includes(c))
  const maxC = Math.max(1, ...p.actions.map(c => c.footprint_cells || 0)), maxE = Math.max(1, ...p.actions.map(c => c.footprint_effort || 0))
  const t = live.summary.tests
  return <>
    <Head p="improve" scope="whole workspace" steps={[`tests → ${t?.total} run, ${t?.found} found something`, `action_plan → ${p.considered} candidates, ${p.met_bar} met the bar`, 'notes: decisions already taken on these objects', `validator: ${on.length} cards, every figure traced to the plan`]} />
    <p className="ds-lead">{on.length} things are worth doing, in this order. The first two are changes with a proven footprint; the largest prize, <b>{fmtC(on.find(c => c.kind === 'investigation')?.footprint_cells)} cells</b>, needs a question answered before anything is removed.</p>
    <div className="ds-fig"><div className="fh"><span className="k">From tests to a plan</span><span className="grow" /></div>
      <div className="fb"><div className="ds-tiles" style={{ margin: 0, border: 0 }}>
        <div><div className="v">{t?.total}</div><div className="l">tests run</div></div><div><div className="v">{t?.found}</div><div className="l">found something</div></div><div><div className="v">{p.considered}</div><div className="l">candidate actions</div></div><div><div className="v">{p.met_bar}</div><div className="l">met the bar</div></div><div><div className="v" style={{ color: 'var(--accent)' }}>{on.length}</div><div className="l">on the plan</div></div>
      </div></div>
      <div className="cap">Ranked by evidence, then scope, then the size of what is at stake. A bar is what the objects occupy now, not a promised saving.</div></div>
    <Sec k="The plan" ct={`${on.length} of ${p.met_bar}`} />
    {on.map((c, i) => <ImproveCard key={c.key} c={c} i={i} maxC={maxC} maxE={maxE} />)}
    {rest.length > 0 && <><Sec k="Met the bar, not on the plan yet" ct={String(rest.length)} />
      <div className="ds-list">{rest.map(c => <div className="r" key={c.key}><span className="grow">{c.title}</span><span className="mono dim">{fmtC(c.footprint_cells)} cells</span></div>)}</div></>}
    <Foot cited={`${on.length} cards · ${on.reduce((a, c) => a + (c.tests_named || []).length, 0)} tests · every figure traced`} note="a state records a decision; it verifies nothing in Anaplan" next={[['why', 'Why is the mapping inside the Forecast Opex formula?'], ['implications', 'What reads DAT01 Actuals GL.Journal Cost Centre?'], ['plan', 'Give me a plan for the lookup module.']]} />
  </>
}

// ---------- 5. implications ----------
function Implications({ live, start }: { live: Live; start?: string }) {
  const r = live.reach, c = r.counts, [view, setView] = useState<'rings' | 'steps'>(start === 'steps' ? 'steps' : 'rings')      // #/design/implications/steps opens the grid
  const maxCells = Math.max(1, ...r.modules.map(m => m.cells))
  const note = live.notes.find(n => n.scope_labels.some(x => x.endsWith('::' + r.selection.ref)))
  const stale = (d: string) => d && new Date(d.replace(' ', 'T')).getTime() < Date.now() - 365 * 864e5
  return <>
    <Head p="implications" scope={FPA} steps={[`impact ${r.selection.ref} downstream → ${c.line_items} line items`, `actions touching the modules in reach → ${c.actions}`, 'search_documents "FX rates" → 2 passages', `notes scoped to ${r.selection.ref} → ${note ? 1 : 0}`, 'validator: every count traced to the reach']} />
    <p className="ds-lead">A change to the FX rates reaches <b>{c.line_items} line items in {c.modules} modules</b>, as far as the board pack, {c.max_distance} steps away. Only {c.direct} read it directly. Two exports carry the result out to another model.</p>
    <div className="ds-tiles"><div><div className="v">{c.line_items}</div><div className="l">line items · {c.direct} direct</div></div><div><div className="v">{c.modules}</div><div className="l">modules</div></div><div><div className="v">{fmtC(c.footprint_cells)}</div><div className="l">cells in reach</div></div><div><div className="v">{c.actions}</div><div className="l">actions touch it</div></div><div><div className="v">{c.models_inferred}</div><div className="l">other models, inferred</div></div></div>
    <div className="ds-fig"><div className="fh"><span className="k">Reach</span><div className="ds-seg" role="group" aria-label="Diagram"><button className={view === 'rings' ? 'on' : ''} onClick={() => setView('rings')}>Rings</button><button className={view === 'steps' ? 'on' : ''} onClick={() => setView('steps')}>Steps</button></div><span className="grow" /><div className="ds-leg"><span><u style={{ background: 'var(--sky)', borderRadius: 5 }} />a line item</span><span>ring = steps away</span></div></div>
      <div className="fb">{view === 'rings' ? <ReachRings r={r} /> : <ReachSteps r={r} />}</div>
      <div className="cap">{view === 'rings' ? 'The change at the centre. Each ring is one more formula between the change and the line item; each sector is a module.' : 'A row per module, a column per step away from the change; the number is how many line items sit there.'} Reach follows formula references: it does not prove a value will change.</div></div>
    <div className="ds-two">
      <div><Sec k="By module" ct={String(r.modules.length)} />
        <table><thead><tr><th>Module</th><th className="num">Line items</th><th className="num">From step</th><th className="num">Cells</th></tr></thead>
          <tbody>{r.modules.map(m => <tr key={m.id}><td><C t={m.ref} /></td><td className="num">{m.line_items}</td><td className="num">{m.min_distance}</td><td className="num barcell">{fmtC(m.cells)}<i style={{ width: 100 * m.cells / maxCells + '%' }} /></td></tr>)}</tbody></table></div>
      <div><Sec k="Actions" ct="linked at module level" />
        <div className="ds-list">{(r.actions?.touching || []).map(a => <div className="r" key={a.ref}><span className="ds-tag">{a.action_kind}</span><span className="grow">{a.ref}<div className="dim" style={{ fontSize: 12 }}>{a.direction} <C t={a.module} /></div></span><span className="mono" style={{ fontSize: 11.5, color: stale(a.last_run) ? 'var(--amber)' : 'var(--muted)' }}>{stale(a.last_run) ? 'last run ' : ''}{a.last_run.slice(0, 10)}</span></div>)}</div>
        <Sec k="Other models" ct="inferred" />
        <div className="ds-list">{r.feeds_inferred.map(f => <div className="r" key={f.model}><C t={f.model} /><span className="grow dim" style={{ fontSize: 12.5 }}>{f.actions} import{f.actions > 1 ? 's' : ''} into {f.targets.join(', ')}</span></div>)}</div></div>
    </div>
    <Sec k="Documents and notes that mention it" ct={`${FX_DOCS.length + (note ? 1 : 0)}`} />
    {FX_DOCS.map((d, i) => <Source key={d.doc} d={d} n={i + 1} />)}
    {note && <div className="ds-src"><div className="sh"><span className="ds-cite" style={{ margin: 0 }}>3</span><span className="n">{note.title}</span><span className="grow" /><span className="ds-tag">owner note · {note.type}</span></div><div className="sb" style={{ fontSize: 13.5 }}>{note.body.replace(/`/g, '')}</div></div>}
    <Sec k="What this cannot see" />
    {[...r.coverage, ...r.limits].map(x => <p className="ds-gap" key={x}>{x}</p>)}
    <Foot cited={`${c.line_items} line items · ${c.modules} modules · ${c.actions} actions cited`} note="2 passages, 1 note" next={[['why', 'Why is the FX file loaded by hand?'], ['improve', 'Is anything in this reach on the action plan?'], ['overview', 'Show me where these modules sit in the estate.']]} />
  </>
}

// ---------- concise mode, beside the full one ----------
const Aff = ({ children }: { children: React.ReactNode }) => <summary className="ds-aff">{children}</summary>
function ConciseFoot({ cited, ctx, full }: { cited: string; ctx: string; full: string }) {
  return <div className="ds-foot" style={{ marginTop: 16 }}><span className="ds-tag ok">verified</span><span className="mono">{cited}</span><span className="grow" /><a className="ctx" href={link('context')}>context {ctx}</a><a className="ctx" href={link(full)} title="The same answer in its Full form, without asking again">Expand to Full</a></div>
}
function ConcisePlan() {
  return <div className="ds-concise">
    <div className="ds-kick"><span className="type">Build plan</span><span className="k">· concise</span><Mock /></div>
    <h2>Give me a plan to build scenario planning for FY27…</h2>
    <details className="ds-open"><Aff>show diagram</Aff><div className="ds-fig" style={{ marginTop: 8 }}><div className="fb"><BuildOrder /></div></div></details>
    {BUILD.map(m => <div className="cs" key={m.name}>
      <div className="ch"><span className="step">{m.step}</span><span className="n">{m.name}</span><span className="dim">{m.state === 'new' ? 'new' : 'exists, empty'} · {m.applies.join(', ')}</span></div>
      {m.items.map(i => <div className="cl" key={i.name}><span className="nm">{i.name}</span><span className="fm">{i.format}</span><Formula f={i.formula} /></div>)}
      <details className="ds-open" open={m.step === 3}><Aff>explain</Aff><div className="ex">{m.note}</div></details>
    </div>)}
    <ConciseFoot cited="16 formulas parsed · order checked" ctx="3.1k / 24k" full="plan" />
  </div>
}
function ConciseImplications({ live }: { live: Live }) {
  const r = live.reach, c = r.counts, direct = r.nodes.filter(n => n.distance === 1)
  const imp = (r.actions?.touching || []).find(a => a.action_kind === 'import')
  return <div className="ds-concise">
    <div className="ds-kick"><span className="type">Implications</span><span className="k">· concise</span></div>
    <h2>What are the implications of changing {r.selection.ref}?</h2>
    <div className="ds-tiles" style={{ margin: '0 0 12px' }}><div><div className="v">{c.line_items}</div><div className="l">line items</div></div><div><div className="v">{c.modules}</div><div className="l">modules</div></div><div><div className="v">{c.max_distance}</div><div className="l">steps deep</div></div><div><div className="v">{(r.actions?.touching || []).filter(a => a.action_kind === 'export').length}</div><div className="l">exports out</div></div></div>
    <ol className="lines">
      <li>{c.direct} line items read it directly: <span className="ds-chips" style={{ display: 'inline-flex' }}>{direct.map(n => <C key={n.id} t={n.ref} />)}</span>
        <div><details className="ds-open"><Aff>explain</Aff><div className="ex">Each multiplies by <C t={r.selection.ref + '.Rate to GBP'} />. Change the rate's dimensions or name and these formulas break first; change a value and they recalculate.</div></details></div></li>
      <li>From there it reaches {c.indirect} more, as far as <C t="OUT02 Board Pack" />.
        <div><details className="ds-open" open><Aff>show diagram</Aff><div className="ds-fig" style={{ marginTop: 8 }}><div className="fb"><ReachRings r={r} /></div></div></details></div></li>
      <li>It leaves the model through exports to <C t="Board Reporting" /> (inferred from import names).</li>
      {imp && <li><span style={{ color: 'var(--amber)' }}>{imp.ref} last ran {imp.last_run.slice(0, 10)}.</span>
        <div><details className="ds-open"><Aff>explain</Aff><div className="ex">The rates in the module are that old. A steering note and an owner note say why; ask "why" to read the passages.</div></details></div></li>}
    </ol>
    <ConciseFoot cited={`${c.line_items} line items · ${c.actions} actions cited`} ctx="2.4k / 24k" full="implications" />
  </div>
}
function Pair({ concise, full, to }: { concise: React.ReactNode; full: React.ReactNode; to: string }) {
  return <div className="ds-pair">
    <div><div className="ph"><span className="ds-tag ok">concise</span><span className="k">the minimum to act on</span></div>{concise}</div>
    <div><div className="ph"><span className="ds-tag sky">full</span><span className="k">the same answer, at 45%</span><span className="grow" /><a className="ds-tag" href={link(to)}>open →</a></div><div className="ds-mini"><div className="in">{full}</div></div></div>
  </div>
}
function Modes({ live }: { live: Live }) {
  return <>
    <div className="ds-kick"><span className="type">Answer modes</span><span className="k">· a switch on the composer</span></div>
    <h1 className="ds-q">Concise to act on. Full to understand. Same question, same evidence.</h1>
    <p className="ds-lead">Concise gives a builder the steps, or a few lines and the figures, and nothing else. Every step and line carries <b>explain</b> and <b>show diagram</b>, which open in place; <b>Expand to Full</b> gives the graphical answer without asking again.</p>
    <Sec k="Build plan" ct="the same question, both modes" />
    <Pair concise={<ConcisePlan />} full={<BuildPlan />} to="plan" />
    <Sec k="Implications" ct="the same question, both modes" />
    <Pair concise={<ConciseImplications live={live} />} full={<Implications live={live} />} to="implications" />
    <Sec k="What changes, and what does not" />
    <div className="ds-list">
      <div className="r"><span className="ds-tag ok">same</span><span className="grow">Validator, citations, the context view, the run timeline, "not recorded".</span></div>
      <div className="r"><span className="ds-tag sky">smaller</span><span className="grow">The context: no diagram instructions, fewer sections pulled.</span><span className="mono dim">3.1k against 5.2k tokens</span><Mock /></div>
      <div className="r"><span className="ds-tag">left out</span><span className="grow dim">Diagram, explanation and document excerpts, until asked for on the step or line.</span></div>
    </div>
  </>
}

// ---------- the shell ----------
const NAV: [string, string, string, string?][] = [
  ['dashboard', 'Workspace', 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z'],
  ['new', 'Chats', 'M4 5h16v11H8l-4 4z', '5'],
  ['documents', 'Documents', 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4', '5'],
  ['implications', 'Dependencies', 'M5 6h4v4H5zM15 14h4v4h-4zM9 8h4M13 8v8h2'],
  ['improve', 'Improve', 'M4 18l5-6 4 3 7-9M15 6h5v5', '5'],
  ['', 'Notes', 'M5 4h14v12l-4 4H5zM15 20v-4h4', '19'],
]

function Compose({ ph, mode = 'full' }: { ph: string; mode?: 'concise' | 'full' }) {
  const [m, setM] = useState(mode)                                   // remembered per login in the real thing; changeable per question
  return <div className="ds-compose"><div className="box"><div className="ph">{ph}</div>
    <div className="row"><span className="ds-chip model">Whole workspace ▾</span><span className="ds-chip">+ model, module or document</span><span className="grow" />
      <div className="ds-seg" role="group" aria-label="Answer mode" title="Concise: the minimum to act on. Full: diagrams, sources, reach."><button className={m === 'concise' ? 'on' : ''} onClick={() => setM('concise')}>Concise</button><button className={m === 'full' ? 'on' : ''} onClick={() => setM('full')}>Full</button></div><span className="send"><Icon d="M5 12h14M13 6l6 6-6 6" s={15} /></span></div></div></div>
}

function Empty({ live }: { live: Live }) {
  const s = live.summary
  return <div className="ds-hello">
    <div className="k" style={{ marginBottom: 10 }}>{s.models.length} models · {s.models.reduce((a, m) => a + (m.line_items || 0), 0)} line items · 5 documents · read {s.snapshot?.activated_at?.slice(0, 10)}</div>
    <h1>Ask about {s.name}</h1>
    <div className="sub">Every answer cites the objects and passages it rests on. What is not recorded is said, not guessed.</div>
    <Compose ph="Ask why, ask for a plan, ask what a change touches…" />
    <div className="k" style={{ marginBottom: 8 }}>Five kinds of question</div>
    <div className="ds-starts">{PATTERNS.map(p => <a key={p.key} href={link(p.key)}><Icon d={p.icon} /><span className="k" style={{ color: 'var(--accent)' }}>{p.label}</span><span>{p.q}</span></a>)}</div>
  </div>
}

const MOMENTS: { n: number; t: string; to?: string; still: 'holds' | 'weak' | 'half' | ''; clip: 'holds' | ''; fix: string; phase: string }[] = [
  { n: 1, t: 'Why was it built this way: the answer with the quoted passage', to: 'why', still: 'holds', clip: 'holds', fix: 'The trail is thin; crop to the first screen.', phase: 'P1' },
  { n: 2, t: 'The clean context: what the model was given, nothing superfluous', to: 'context', still: 'holds', clip: 'holds', fix: 'Lead with the left-out figure, larger.', phase: 'P1' },
  { n: 3, t: 'A build plan in build order, concise and full', to: 'modes', still: 'weak', clip: 'holds', fix: 'Side by side is unreadable at 45%. Film the switch on one answer.', phase: 'P3' },
  { n: 4, t: 'Implications of a change: the reach diagram', to: 'implications', still: 'holds', clip: 'holds', fix: 'Rings chosen (Karim). Labels get tight past about 12 modules.', phase: 'P1' },
  { n: 5, t: 'Thousands of line items, one question, an exact count', still: '', clip: '', fix: 'Not drawn. Needs its own pattern and a larger demo model: Caldergate has 426 line items.', phase: 'P2' },
  { n: 6, t: 'How to improve: the tests and the ranked cards', to: 'improve', still: 'half', clip: 'holds', fix: 'The funnel row is five numbers, not a figure. Shorter card titles.', phase: 'restyle' },
  { n: 7, t: 'The run timeline: tools called, in sequence', to: 'context', still: 'holds', clip: 'holds', fix: 'Give it its own frame, apart from the context view.', phase: 'ARC-19' },
  { n: 8, t: 'Managing documents and switching workspaces', to: 'documents', still: 'half', clip: 'holds', fix: 'Documents hold. The switcher is small on screen: film it opening, then the workspace changing.', phase: 'P1, P5' },
  { n: 9, t: 'Running it yourself in a few minutes', still: '', clip: '', fix: 'Not a UI page: terminal to first answer.', phase: 'P6' },
  { n: 10, t: 'The estate at a glance: the workspace dashboard', to: 'dashboard', still: 'holds', clip: 'holds', fix: 'The matrix needs the real parse behind it; pick the model with the best story.', phase: 'restyle' },
]
function Index() {
  const V = ({ v }: { v: string }) => v ? <span className={'ds-tag ' + (v === 'holds' ? 'ok' : 'mock')} style={v === 'holds' ? undefined : { borderStyle: 'solid' }}>{v}</span> : <span className="ds-tag">not drawn</span>
  const drawn = MOMENTS.filter(m => m.to).length, both = MOMENTS.filter(m => m.still === 'holds' && m.clip === 'holds').length
  return <>
    <div className="ds-kick"><span className="type">Design sheet</span><span className="k">· v0.2 P0 · judged as showcase moments</span></div>
    <h1 className="ds-q">Ten moments. One screen, one question, readable in under 30 seconds.</h1>
    <p className="ds-lead">Each feature is designed from its moment backwards. <b>{drawn} of {MOMENTS.length} are drawn; {both} hold as both a still and a 20-second clip today.</b> Nothing animates in the app: a clip is a script driving the page.</p>
    <table className="ds-mom"><thead><tr><th style={{ width: 34 }}>#</th><th>Moment</th><th style={{ width: 92 }}>Still</th><th style={{ width: 92 }}>Clip</th><th style={{ width: '34%' }}>Before it is filmed</th><th style={{ width: 70 }}>Lands</th></tr></thead>
      <tbody>{MOMENTS.map(m => <tr key={m.n}><td className="mono dim">{String(m.n).padStart(2, '0')}</td>
        <td>{m.to ? <a href={link(m.to)} className="mt">{m.t} <span className="ar">→</span></a> : <span className="mt dim">{m.t}</span>}</td>
        <td><V v={m.still} /></td><td>{m.to ? <V v={m.clip} /> : null}</td><td className="dim" style={{ fontSize: 12.5 }}>{m.fix}</td><td className="mono dim" style={{ fontSize: 11 }}>{m.phase}</td></tr>)}</tbody></table>
    <Sec k="Every page of the sheet" />
    <div className="ds-idx">
      <a href={link('new')}><div className="t"><Icon d="M4 5h16v11H8l-4 4z" />New chat</div><div className="d">The empty state: the workspace in one line, the composer, five starters.</div></a>
      {PATTERNS.map(p => <a key={p.key} href={link(p.key)}><div className="t"><Icon d={p.icon} />{p.label}</div><div className="d">{p.q}</div>
        <div className="d"><b style={{ color: 'var(--accent)', fontWeight: 400 }}>Live:</b> {p.live}. <b style={{ color: 'var(--amber)', fontWeight: 400 }}>Mock:</b> {p.mock}.</div></a>)}
      <a href={link('dashboard')}><div className="t"><Icon d="M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z" />Workspace dashboard</div><div className="d">The estate at a glance: model map, tests, treemap, who reads whom, effort, functions, module roles. All live.</div></a>
      <a href={link('modes')}><div className="t"><Icon d="M4 6h7M4 12h7M4 18h7M14 5h6v14h-6z" />Concise and Full</div><div className="d">The build-plan and implications questions in both modes, side by side.</div></a>
      <a href={link('documents')}><div className="t"><Icon d="M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M9 16h4" />Documents</div><div className="d">Cards, sections, what each names, how often it is cited, replace and remove. All mocked (P1).</div></a>
      <a href={link('context')}><div className="t"><Icon d="M4 6h16M4 12h10M4 18h6" />Context and run</div><div className="d">What the model was given against a budget, what was left out, and the run step by step. All mocked.</div></a>
    </div>
  </>
}

export function DesignSheet({ args }: { args: string[] }) {
  const page = args[0] || ''
  const [live, setLive] = useState<Live | null>(null)
  const [err, setErr] = useState('')
  const [ws, setWs] = useState(false)
  useEffect(() => { loadLive().then(setLive).catch(e => setErr(e.message || String(e))) }, [])
  useEffect(() => { document.querySelector('.ds-main')?.scrollTo(0, 0); setWs(false) }, [page])

  let body: React.ReactNode
  if (err) body = <div className="ds-col"><div className="ds-none"><div className="h">The sheet needs the Caldergate demo estate</div>{err} Load anaplan-estate's examples/caldergate-estate as estate {CALDERGATE}.</div></div>
  else if (!live) body = <div className="ds-col dim">Reading Caldergate…</div>
  else if (page === 'new') body = <Empty live={live} />
  else {
    const inner = page === 'why' ? <Why live={live} /> : page === 'plan' ? <BuildPlan /> : page === 'overview' ? <Overview live={live} /> : page === 'improve' ? <Improve live={live} /> : page === 'implications' ? <Implications live={live} start={args[1]} /> : page === 'documents' ? <DocumentsPage /> : page === 'context' ? <ContextPage /> : page === 'modes' ? <Modes live={live} /> : page === 'dashboard' ? <Dashboard s={live.summary} /> : page === 'settings' ? <SettingsPage /> : <Index />
    body = <><div className={'ds-col' + (page === 'modes' || page === 'dashboard' ? ' xwide' : ['implications', 'overview', 'documents', 'context'].includes(page) ? ' wide' : '')}>{inner}</div>{page && !['documents', 'context', 'dashboard', 'settings'].includes(page) && <Compose key={page} ph="Follow up… the conversation remembers" mode={page === 'modes' ? 'concise' : 'full'} />}</>
  }
  const s = live?.summary
  return (
    <div className="ds">
      <aside className="ds-side">
        <a className="ds-brand" href={link()}>
          <img src={logoUrl} alt="" width="26" height="26" />
          <span><span className="wm"><b>/</b>architect</span><span className="by">by CodelessOps</span></span>
        </a>
        <div className="ds-ws">
          <button onClick={() => setWs(x => !x)} aria-expanded={ws}><span className="mark">CD</span><span className="grow"><div className="n">{WORKSPACES[0].name}</div><div className="s">{WORKSPACES[0].sub}</div></span><Icon d="M8 10l4-4 4 4M8 14l4 4 4-4" s={14} /></button>
          {ws && <div className="pop"><div className="k" style={{ padding: '4px 8px 6px' }}>Workspaces <Mock what="many workspaces per login arrives in P5" /></div>
            {WORKSPACES.map(w => <div key={w.name} className={'row' + (w.on ? ' on' : '')}><span className="tick">{w.on ? '✓' : ''}</span><span className="grow"><div className="n">{w.name}</div><div className="s">{w.sub}</div></span></div>)}
            <div className="add">+ New workspace</div><div className="iso">A workspace is separate: its chats, documents, notes and dependencies stay in it. Nothing is remembered across workspaces.</div></div>}
        </div>
        <nav className="ds-nav">{NAV.map(([k, label, d, ct]) => <a key={label} href={k ? link(k) : link(page)} className={k && k === page ? 'on' : ''}><Icon d={d} />{label}{ct && <span className="ct">{ct}</span>}</a>)}</nav>
        <div className="k">Chats in this workspace</div>
        <div className="ds-threads">{PATTERNS.map(p => <a key={p.key} href={link(p.key)} className={page === p.key ? 'on' : ''} title={p.q}><div className="s">{p.label}</div><div className="t">{p.q}</div></a>)}</div>
        <div className="ds-who"><span className="av">K</span><div style={{ flex: 1, minWidth: 0 }}><div className="t">Karim</div><div className="s">admin</div></div><a href={link('settings')} className={page === 'settings' ? '' : 'dim'} style={{ fontSize: 12, marginRight: 10 }}>Settings</a><a href="#/" title="Back to today's app" className="dim" style={{ fontSize: 12 }}>v0.1 ↗</a></div>
      </aside>
      <main className="ds-main">
        <div className="ds-top"><span className="crumb"><b>{s?.name || 'Caldergate'}</b>{s?.snapshot && <> · read {s.snapshot.activated_at?.slice(0, 10)}</>}</span><span className="grow" /><a href={link()} className="ds-tag">design sheet · P0</a></div>
        {body}
      </main>
    </div>
  )
}
