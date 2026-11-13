// A build plan as the page draws it: plain instructions. What you will build, what already exists that it uses, the
// line items to build, then numbered steps a builder follows in Anaplan, ending with the existing formula that switches
// over and what to check. The plan is the build_plan tool's result: every formula was parsed by the grammar and every
// name checked before it reached the page. Concise draws the steps and what exists; "explain" opens a step's note.
import React, { useState } from 'react'
import { useApp } from '../App'
import { Obj } from '../objects'

export type PlanRef = { path: string; kind: string; module?: string | null; new?: boolean }
export type PlanItem = { name: string; format: string; summary?: string; formula: string; refs?: PlanRef[]; note?: string }
export type PlanModule = { step: number; name: string; state: 'new' | 'fill' | 'exists'; applies_to: string[]; note?: string; items: PlanItem[]; reads?: string[] }
export type BuildPlan = { model: string; title?: string; modules: PlanModule[]; existing: string[]; edges: [string, string][];
  checks: { formulas: number; parsed: number; refs_existing: number; refs_new: number; ordered: boolean; steps: number; notes?: string[] } }

const T = { ink: '#e8ebe9', muted: '#9aa5a0', rule: '#222a27', card: '#141917', accent: '#34d399', bg: '#0e1211' }
const mono = { fontFamily: 'var(--mono)' }, sans = { fontFamily: 'var(--sans)' }

/** A formula with its module references coloured: green when the module is one this plan creates, sky when it is in the model. */
export function Formula({ f, fresh }: { f: string; fresh: Set<string> }) {
  if (!f) return <span className="ds-f in">input</span>
  const RE = /('[^']+')(\.(?:[^\s\[\]()*+\-\/,<>=:]|\s(?![*+\-\/<>=]|THEN\b|ELSE\b|AND\b|OR\b))+)?|\b(IF|THEN|ELSE|AND|OR|NOT)\b|\b([A-Z]{3,})(?=\()|\b(SUM|LOOKUP|SELECT)(?=:)/g
  const out: React.ReactNode[] = []; let last = 0, m: RegExpExecArray | null, k = 0
  while ((m = RE.exec(f))) {
    if (m.index > last) out.push(f.slice(last, m.index))
    if (m[1]) { const nw = fresh.has(m[1].slice(1, -1)); out.push(<span key={k++} className={nw ? 'nw' : 'm'}>{m[1]}</span>); if (m[2]) out.push(<span key={k++} className={nw ? 'nw' : 'l'}>{m[2]}</span>) }
    else if (m[3]) out.push(<span key={k++} className="kw">{m[3]}</span>)
    else out.push(<span key={k++} className="fn">{m[4] || m[5]}</span>)
    last = m.index + m[0].length
  }
  if (last < f.length) out.push(f.slice(last))
  return <span className="ds-f">{out}</span>
}

/** Left to right: what the plan reads that is already in the model, then each step in the layer its references allow. */
export function BuildOrder({ plan }: { plan: BuildPlan }) {
  const mods = plan.modules, names = new Set(mods.map(m => m.name))
  const layer: Record<string, number> = {}
  for (const e of plan.existing) layer[e] = 0
  for (let pass = 0; pass <= mods.length; pass++) for (const m of mods) {
    const deps = plan.edges.filter(e => e[1] === m.name && names.has(e[0]) && e[0] !== m.name).map(e => layer[e[0]] ?? 1)
    layer[m.name] = Math.max(1, ...deps.map(d => d + 1))
  }
  const cols: string[][] = []
  for (const n of [...plan.existing, ...mods.map(m => m.name)]) (cols[layer[n]] ||= []).push(n)
  const NW = 178, NH = 44, EH = 30, GAP = 12, colW = Math.max(NW + 44, Math.min(250, (940 - NW) / Math.max(1, cols.length - 1)))
  const H = Math.max(120, ...cols.map((c, i) => (c || []).length * ((i ? NH : EH) + GAP))) + 34, W = 14 + (cols.length - 1) * colW + NW + 10
  const box: Record<string, { x: number; y: number; h: number }> = {}
  cols.forEach((c, i) => { const h = i ? NH : EH, total = (c || []).length * (h + GAP) - GAP; (c || []).forEach((n, j) => { box[n] = { x: 10 + i * colW, y: (H - 24 - total) / 2 + j * (h + GAP), h } }) })
  const step = Object.fromEntries(mods.map(m => [m.name, m]))
  const into: Record<string, number> = {}
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={'Build order: ' + mods.map(m => `${m.step} ${m.name}`).join(', ')} style={{ maxWidth: W }}>
      <defs>{[['m', T.muted], ['a', T.accent]].map(([id, c]) => <marker key={id} id={'pb-' + id} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1 7 4 1 7" fill="none" stroke={c} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></marker>)}</defs>
      {plan.edges.filter(e => box[e[0]] && box[e[1]] && e[0] !== e[1]).map(([f, t]) => {
        const a = box[f], b = box[t], n = plan.edges.filter(e => e[1] === t).length, i = into[t] = (into[t] ?? -1) + 1, nw = names.has(f)
        const x1 = a.x + NW, y1 = a.y + a.h / 2, x2 = b.x - 3, y2 = b.y + b.h / 2 + (i - (n - 1) / 2) * 6, dx = (x2 - x1) / 2
        return <path key={f + '>' + t} d={`M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`} fill="none" stroke={nw ? T.accent : T.muted} strokeOpacity={nw ? 0.9 : 0.45} strokeWidth="1.3" markerEnd={`url(#pb-${nw ? 'a' : 'm'})`} />
      })}
      {Object.entries(box).map(([n, b]) => { const m = step[n]
        if (!m) return <g key={n}><rect x={b.x} y={b.y} width={NW} height={b.h} rx="6" fill={T.bg} stroke={T.rule} /><text x={b.x + 10} y={b.y + 19} fontSize="10.5" fill={T.muted} style={mono}>{n.length > 27 ? n.slice(0, 26) + '…' : n}</text></g>
        const code = n.split(' ')[0], rest = n.slice(code.length + 1)
        return <g key={n}><rect x={b.x} y={b.y} width={NW} height={b.h} rx="6" fill={T.card} stroke={T.accent} strokeDasharray={m.state === 'new' ? undefined : '5 3'} />
          <rect x={b.x + 8} y={b.y + 7} width="18" height="18" rx="4" fill={T.accent} /><text x={b.x + 17} y={b.y + 20} textAnchor="middle" fontSize="10.5" fill="#05140e" style={mono}>{m.step}</text>
          <text x={b.x + 33} y={b.y + 18} fontSize="10.5" fill={T.accent} style={mono}>{rest ? code : ''}{m.state === 'new' ? '' : m.state === 'fill' ? ' · empty today' : ' · extended'}</text>
          <text x={b.x + 33} y={b.y + 34} fontSize="12" fill={T.ink} style={sans}>{(rest || n).length > 22 ? (rest || n).slice(0, 21) + '…' : (rest || n)}</text></g> })}
      <text x="10" y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">{plan.existing.length ? 'ALREADY IN THE MODEL' : ''}</text>
      {cols.slice(1).map((_, i) => <text key={i} x={10 + (i + 1) * colW} y={H - 4} fontSize="10" fill={T.muted} style={mono} letterSpacing="1.4">{i === cols.length - 2 && i ? 'LAST' : i ? 'THEN' : 'FIRST'}</text>)}
    </svg>
  )
}

type Step = { n: number; kind: 'list' | 'module' | 'open' | 'line_item' | 'change' | 'check'; text: string; module?: string; item?: string; formula?: string; old_formula?: string; note?: string }

/** The numbered instructions of a plan stored before the server wrote them (answers from before the change). */
function stepsOf(plan: BuildPlan): Step[] {
  const out: Step[] = []
  const add = (s: Omit<Step, 'n'>) => out.push({ n: out.length + 1, ...s })
  for (const m of plan.modules) {
    const dims = m.applies_to.join(', ') || 'no dimensions'
    add(m.state === 'new' ? { kind: 'module', module: m.name, text: `Create the module ${m.name} with ${m.applies_to.length ? 'dimensions ' + dims : 'no dimensions'}.` }
      : { kind: 'open', module: m.name, text: `Open the existing module ${m.name} (dimensions: ${dims}). Leave the line items it has as they are.` })
    for (const i of m.items) add({ kind: 'line_item', module: m.name, item: i.name, formula: i.formula,
      text: `In ${m.name}, add the line item ${i.name}: format ${i.format}, summary ${i.summary || 'None'}.` + (i.formula ? ' Enter its formula:' : ' No formula: it is an input.') })
  }
  return out
}

/** A build plan as instructions (the build_plan tool's result, every formula parsed and every name checked before it
 * reached the page). Full, in reading order: what you will build (each module with its line items under it, then the
 * existing formulas that change), what already exists that it uses, the numbered steps. Concise: the steps and what exists. The answer's own text above is the overview. */
export function PlanBlock({ plan, full, onAsk, turn }: { plan: BuildPlan; full: boolean; onAsk?: (q: string) => void; turn?: string }) {
  const { idx } = useApp()
  const [diagram, setDiagram] = useState(false)
  const [open, setOpen] = useState<Record<number, boolean>>({})
  const fresh = new Set(plan.modules.filter(m => m.state === 'new').map(m => m.name))
  const c = plan.checks
  const steps: Step[] = (plan as any).steps || stepsOf(plan)
  const uses: { modules: string[]; line_items: { module: string; name: string }[]; lists: string[] } = (plan as any).uses || { modules: plan.existing, line_items: [], lists: [] }
  const noteOf = (s: Step) => s.kind === 'change' ? s.note : s.kind === 'line_item' ? plan.modules.find(m => m.name === s.module)?.items.find(i => i.name === s.item)?.note
    : (s.kind === 'module' || s.kind === 'open') ? plan.modules.find(m => m.name === s.module)?.note : ''
  const tag = (m: PlanModule) => <span className={'ds-tag ' + (m.state === 'new' ? 'ok' : 'sky')}>{m.state === 'new' ? 'new' : m.state === 'fill' ? 'exists, empty today' : 'exists, you add to it'}</span>
  const figure = <div className="ds-fig"><div className="fh"><span className="k">Build order</span><span className="grow" /><div className="ds-leg"><span><i className="acc" />uses something this plan builds</span><span><i />uses the model as it is</span></div></div>
    <div className="fb"><BuildOrder plan={plan} /></div><div className="cap">Left to right: a numbered box is a module of this plan, in the order you build them.</div></div>
  const anyUse = uses.modules.length + uses.line_items.length + uses.lists.length > 0
  const existing = <div className="ds-uses">
    {uses.modules.length > 0 && <div className="u"><span className="k">Modules</span><span className="ds-chips">{uses.modules.map(n => <Obj key={n} text={n} idx={idx} />)}</span></div>}
    {uses.line_items.length > 0 && <div className="u"><span className="k">Line items</span><span className="ds-chips">{uses.line_items.map(x => <Obj key={x.module + '.' + x.name} text={`${x.module}.${x.name}`} idx={idx} />)}</span></div>}
    {uses.lists.length > 0 && <div className="u"><span className="k">Lists</span><span className="ds-chips">{uses.lists.map(n => <span className="ds-chip" key={n}>{n}</span>)}</span></div>}
    {!anyUse && <div className="dim" style={{ fontSize: 13 }}>Nothing: this build stands on its own.</div>}
  </div>
  // what the colour of a step's number says: shown only for the kinds this plan has
  const has = (k: string[]) => steps.some(x => k.includes(x.kind))
  const stepKey = <div className="ds-stepkey" aria-label="What the colour of a step number means">
    {has(['list', 'module', 'open', 'line_item']) && <span><i className="build" />build something new</span>}
    {has(['change']) && <span><i className="change" />change something that exists: the switch-over</span>}
    {has(['check']) && <span><i className="check" />check, nothing is built</span>}</div>
  const stepList = <><div>{stepKey}</div><ol className="ds-steplist">{steps.map(s => { const note = noteOf(s); return <li key={s.n} className={'st ' + s.kind}>
    <span className="num">{s.n}</span>
    <div className="body">
      <div className="tx">{s.kind === 'check' ? <><span className="ds-tag">check</span> <Markdownish text={s.text} /></> : s.text}</div>
      {s.kind === 'change' && <div className="swap"><div><span className="k">from</span>{s.old_formula ? <Formula f={s.old_formula} fresh={fresh} /> : <span className="ds-f in">no formula</span>}</div><div><span className="k">to</span><Formula f={s.formula || ''} fresh={fresh} /></div></div>}
      {s.kind === 'line_item' && s.formula && <div className="fx"><Formula f={s.formula} fresh={fresh} /></div>}
      {s.kind !== 'check' && s.kind !== 'list' && <><button className="ds-aff" onClick={() => note ? setOpen(o => ({ ...o, [s.n]: !o[s.n] })) : onAsk?.(`Explain step ${s.n} of the plan: ${s.text}`)}>explain</button>
        {open[s.n] && note && <div className="ds-open"><div className="ex">{note}</div></div>}</>}
    </div></li> })}</ol></>
  const quiet = <div className="ds-quiet">order checked: nothing is built before what it refers to · {c.parsed} of {c.formulas} formulas are valid Anaplan syntax · every name they use is in the model or built by this plan
    {(c.notes || []).map(n => <div key={n}>not checked: {n}</div>)}</div>
  if (!full) return <div className="ds-concise plan">
    <div className="ds-sec" style={{ marginTop: 0 }}><span className="k">Steps</span><span className="ct">{steps.length} · in {plan.model}</span><span className="grow" /><button className="ds-aff" onClick={() => setDiagram(d => !d)}>{diagram ? 'hide diagram' : 'show diagram'}</button></div>
    {diagram && <div style={{ marginBottom: 10 }}>{figure}</div>}
    {stepList}
    <div className="ds-sec"><span className="k">What already exists that this uses</span></div>
    {existing}
    {quiet}
  </div>
  const items = plan.modules.reduce((n, m) => n + m.items.length, 0), changes: any[] = (plan as any).changes || []
  return <>
    <Sec2 k="What you will build" ct={`${plan.modules.length} module${plan.modules.length !== 1 ? 's' : ''}, ${items} line item${items !== 1 ? 's' : ''}${changes.length ? `, ${changes.length} existing formula${changes.length !== 1 ? 's' : ''} changed` : ''} · in ${plan.model}`} />
    {plan.modules.map(m => <div className="ds-mod" key={m.name}>
      <div className="mh"><span className="step">{m.step}</span><span className="n">{m.name}</span>{tag(m)}<span className="grow" /><span className="k">dimensions</span>
        <span className="ds-chips">{m.applies_to.length ? m.applies_to.map(a => <span className="ds-chip" key={a}>{a}</span>) : <span className="dim" style={{ fontSize: 12 }}>none</span>}</span></div>
      {m.note && <Purpose text={m.note} />}
      <div className="lih">{m.items.length} line item{m.items.length !== 1 ? 's' : ''} to {m.state === 'new' ? 'build' : 'add'}</div>
      <table><thead><tr><th style={{ width: '19%' }}>Line item</th><th style={{ width: '9%' }}>Format</th><th style={{ width: '17%' }}>Dimensions</th><th style={{ width: '8%' }}>Summary</th><th>Formula</th></tr></thead>
        <tbody>{m.items.map(i => <tr key={i.name}><td className="li-n">{i.name}</td><td className="dim">{i.format}</td><td className="dim">{((i as any).applies_to || m.applies_to).join(', ') || 'none'}</td><td className="dim">{i.summary || 'None'}</td>
          <td><Formula f={i.formula} fresh={fresh} />{i.formula && <span className="ds-valid" title="This formula is valid Anaplan syntax and every name in it exists or is built by this plan">✓ valid</span>}</td></tr>)}</tbody></table>
    </div>)}
    {changes.map(ch => <div className="ds-mod chg" key={ch.module + ch.name}>
      <div className="mh"><span className="step">↺</span><span className="n">{ch.module}.{ch.name}</span><span className="ds-tag">existing formula changed</span></div>
      {ch.note && <Purpose text={ch.note} />}
      <div className="swap"><div><span className="k">from</span>{ch.old_formula ? <Formula f={ch.old_formula} fresh={fresh} /> : <span className="ds-f in">no formula</span>}</div>
        <div><span className="k">to</span><Formula f={ch.formula} fresh={fresh} /><span className="ds-valid">✓ valid</span></div></div>
    </div>)}
    <Sec2 k="What already exists that this uses" ct="click a name to open it" />
    {existing}
    <Sec2 k="Steps" ct={`${steps.length} · follow them in order in Anaplan`} />
    {stepList}
    {quiet}
    <div style={{ margin: '10px 0 0' }}><button className="ds-aff" onClick={() => setDiagram(d => !d)}>{diagram ? 'hide the build-order diagram' : 'show the build-order diagram'}</button></div>
    {diagram && <div style={{ marginTop: 8 }}>{figure}</div>}
    {turn && <div className="ds-foot" style={{ border: 0, marginTop: 10, paddingTop: 0 }}><span>Take the plan with you:</span><a href={`/api/turns/${turn}/plan?format=md`} target="_blank" rel="noreferrer"><button>Markdown</button></a><a href={`/api/turns/${turn}/plan?format=csv`}><button>CSV, one row per line item</button></a></div>}
  </>
}
/** A module's purpose: its first sentence, the rest behind "more", so the line items under it stay in view. */
function Purpose({ text }: { text: string }) {
  const [all, setAll] = useState(false)
  const cut = text.search(/[.!?](\s|$)/), first = cut > 0 && cut < text.length - 1 ? text.slice(0, cut + 1) : text
  return <div className="mn">{all ? text : first}{first !== text && <> <button className="ds-aff" onClick={() => setAll(x => !x)}>{all ? 'less' : 'more'}</button></>}</div>
}
/** A check's sentence: names the plan put in backticks are set in the mono face. */
const Markdownish = ({ text }: { text: string }) => <>{text.split(/(`[^`]+`)/).map((p, i) => p.startsWith('`') ? <code key={i}>{p.slice(1, -1)}</code> : p)}</>
const Sec2 = ({ k, ct }: { k: string; ct?: string }) => <div className="ds-sec"><span className="k">{k}</span>{ct && <span className="ct">{ct}</span>}</div>
