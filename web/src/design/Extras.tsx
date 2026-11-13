// Two more pages of the design sheet, added with the 2026-11-13 plan changes (the v0.2 plan):
// the document management page (P1) and the context view with the run timeline (P1 and the tracing phase).
// Both are static: documents, token counts and timings are mocked; the object names are real Caldergate names.
import React, { useState } from 'react'

const Mock = () => <span className="ds-tag mock" title="Static in this sheet">mock</span>
const chip = (t: string) => { const i = t.indexOf('.'); return i < 0 ? <span key={t} className="ds-chip mod">{t}</span> : <span key={t} className="ds-chip li"><s>{t.slice(0, i)}</s><em>.</em>{t.slice(i + 1)}</span> }

// ---------- documents ----------
type Doc = { title: string; file: string; type: string; date: string; size: string; sections: number; cited: number[]; answers: number; summary: string; heads: string[]; objects: string[]; more: number }
const DOCS: Doc[] = [
  { title: 'FP&A design decision record', file: 'FP&A design decision record v1.2.docx', type: 'Design decision record', date: '14 Mar 2019', size: '412 KB', sections: 23, cited: [8, 9, 14], answers: 6,
    summary: 'The partner\'s reasons for the FP&A build: time settings, the opex forecast logic, FX, why the packs carry Versions.', heads: ['1 Scope', '4.2 Time and versions', '4.3 Opex forecast logic', '5 FX and currency', '+19'],
    objects: ['CAL03 Opex.Forecast Opex', 'SYS05 FX Rates', 'OUT02 Board Pack'], more: 11 },
  { title: 'Steering meeting notes, 2023', file: 'Steering meeting notes 2023.md', type: 'Meeting notes', date: '14 Nov 2023', size: '38 KB', sections: 12, cited: [4, 10], answers: 3,
    summary: 'Monthly steering notes for 2023: the Treasury FX file stopping, Budget v2 left unapproved, the product list falling out of date.', heads: ['Jan', 'Jun · Product master', 'Nov · Item 5 FX', '+9'],
    objects: ['SYS05 FX Rates', 'CAL02 Revenue.Revenue USD'], more: 4 },
  { title: 'Partner handover note', file: 'Partner handover note 2021.docx', type: 'Handover note', date: '30 Jun 2021', size: '96 KB', sections: 9, cited: [2], answers: 2,
    summary: 'What the second partner left behind for Workforce Planning: naming, the manual steps, the feed into INP03 Headcount.', heads: ['1 What was built', '3 Manual steps', '4 Known gaps', '+6'],
    objects: ['INP03 Headcount', 'SYS05 FX Rates'], more: 5 },
  { title: 'CR-031 Legal fees driver', file: 'CR-031 Legal fees driver.pdf', type: 'Change request', date: '02 May 2024', size: '71 KB', sections: 4, cited: [1], answers: 2,
    summary: 'A request for a thirteenth branch in Forecast Opex for legal fees. Open. Notes the lookup module agreed in principle.', heads: ['Requested change', 'Reason', 'Impact', 'Status'],
    objects: ['CAL03 Opex.Forecast Opex', 'INP02 Opex Drivers.Legal Fees'], more: 0 },
  { title: 'GL load script', file: 'netsuite_gl_load.py', type: 'Integration script', date: '09 Feb 2022', size: '14 KB', sections: 6, cited: [], answers: 0,
    summary: 'The script behind Daily Load: pulls GL transactions from NetSuite, maps source system codes, writes the hub import file.', heads: ['extract()', 'map_source_system()', 'write_import_file()', '+3'],
    objects: ['DAT01 GL Transactions', 'DAT01 GL Transactions.Source System'], more: 2 },
]

export function DocumentsPage() {
  const sections = DOCS.reduce((a, d) => a + d.sections, 0)
  return <>
    <div className="ds-kick"><span className="type">Documents</span><span className="k">· 5 of 20</span><Mock /></div>
    <h1 className="ds-q">The project's own documents, read section by section.</h1>
    <p className="ds-lead">Each document becomes a card and a set of sections. The architect always sees the cards; it opens a section only when a question needs it, and quotes the passage it used.</p>
    <div className="ds-tiles"><div><div className="v">{DOCS.length} <span className="dim" style={{ fontSize: 13 }}>/ 20</span></div><div className="l">documents</div></div><div><div className="v">{sections}</div><div className="l">sections</div></div><div><div className="v">{DOCS.reduce((a, d) => a + d.cited.length, 0)}</div><div className="l">sections cited so far</div></div><div><div className="v">{DOCS.reduce((a, d) => a + d.answers, 0)}</div><div className="l">answers that quote one</div></div></div>
    <div className="ds-drop"><span><b>Add a document.</b> PDF, Word, Markdown, text, CSV or a script. Up to 20 project documents, 10 MB each: project documents, not an archive.</span><span className="grow" /><span className="ds-chip">Choose files</span></div>
    <div className="ds-docs">{DOCS.map(d => <div className="ds-doc" key={d.file}>
      <div className="dh"><span className="ds-tag">{d.type}</span><span className="grow" /><span className="f">{d.date} · {d.size}</span></div>
      <div><div className="t">{d.title}</div><div className="f">{d.file}</div></div>
      <div className="sum">{d.summary}</div>
      <div><div className="strip" role="img" aria-label={`${d.sections} sections, ${d.cited.length} cited`}>{Array.from({ length: d.sections }, (_, i) => <i key={i} className={d.cited.includes(i) ? 'c' : ''} style={{ height: 5 + ((i * 7 + d.sections) % 9) }} />)}</div>
        <div className="sl"><span>{d.sections} sections</span><span>{d.cited.length ? <><b>{d.cited.length} cited</b> in {d.answers} answer{d.answers > 1 ? 's' : ''}</> : 'not cited yet'}</span></div></div>
      <div className="hd">{d.heads.join('  ·  ')}</div>
      <div className="ds-chips">{d.objects.map(chip)}{d.more > 0 && <span className="ds-chip">+{d.more} objects</span>}</div>
      <div className="da"><span>read 12 Nov 2026</span><span className="grow" /><span className="b">Replace with a new version</span><span className="b">Remove</span></div>
    </div>)}</div>
    <div className="ds-sec"><span className="k">How a document is used</span></div>
    <div className="ds-list">
      <div className="r"><span className="ds-tag ok">always</span><span className="grow">The card: title, type, date, headings, a summary written once at upload, the objects it names.</span><span className="mono dim">about 120 tokens each</span></div>
      <div className="r"><span className="ds-tag sky">per question</span><span className="grow">Only the sections that bear on the question, found by keyword and by the objects they name.</span><span className="mono dim">2 of {sections} for the "why" answer</span></div>
      <div className="r"><span className="ds-tag">never</span><span className="grow dim">A whole document by default. No embeddings, no vector store: nothing leaves the SQLite file to be indexed.</span></div>
    </div>
  </>
}

// ---------- context view and run timeline (one panel on an answer) ----------
const BUDGET = 24000
const KINDS: Record<string, [string, string]> = { sys: ['instructions', '#7d8985'], card: ['document cards', '#9aa5a0'], sec: ['sections pulled', '#34d399'], obj: ['objects', '#38bdf8'], note: ['notes', '#a78bfa'], tool: ['other tool results', '#fbbf24'], conv: ['conversation', '#5d6964'] }
const CTX: { k: string; item: string; why: string; tok: number }[] = [
  { k: 'sys', item: 'Instructions and the validator\'s rules', why: 'every answer', tok: 1840 },
  { k: 'card', item: '5 document cards', why: 'always in context, so the architect knows what exists', tok: 610 },
  { k: 'sec', item: 'FP&A design decision record · 4.3 Opex forecast logic', why: 'search_documents: "Forecast Opex mapping"; names CAL03 Opex.Forecast Opex', tok: 540 },
  { k: 'sec', item: 'CR-031 Legal fees driver · Requested change', why: 'linked to CAL03 Opex.Forecast Opex', tok: 210 },
  { k: 'obj', item: 'CAL03 Opex.Forecast Opex', why: 'get_object: the line item the question names (formula, dimensions, findings)', tok: 1180 },
  { k: 'obj', item: 'INP02 Opex Drivers · count and top 8 of 58 line items', why: 'referenced by the formula; a count and top rows, never the list', tok: 320 },
  { k: 'note', item: 'Forecast Opex: why the mapping is in the formula', why: 'owner note scoped to the line item', tok: 150 },
  { k: 'tool', item: 'tests on CAL03 Opex.Forecast Opex · 1 hit (4.6)', why: 'what the estate shows today', tok: 260 },
  { k: 'conv', item: 'The question', why: 'first turn; nothing earlier to carry', tok: 40 },
]
const OUT = [
  { item: 'FP&A design decision record · 22 other sections', why: 'no keyword hit, no link to the objects in the question', tok: 17900 },
  { item: '3 other documents · 27 sections', why: 'cards only; nothing in them bears on the question', tok: 9300 },
  { item: 'INP02 Opex Drivers · 50 more line items', why: 'over the row limit for one tool result', tok: 1900 },
]
const RUN: { kind: 'model' | 'tool' | 'check'; name: string; args: string; out: string; t0: number; t: number }[] = [
  { kind: 'model', name: 'plan', args: 'question + 5 cards', out: '3 tool calls', t0: 0, t: 1.4 },
  { kind: 'tool', name: 'search_documents', args: '"Forecast Opex mapping"', out: '2 sections of 54', t0: 1.4, t: 0.1 },
  { kind: 'tool', name: 'get_object', args: 'CAL03 Opex.Forecast Opex', out: '1 line item', t0: 1.5, t: 0.1 },
  { kind: 'tool', name: 'notes', args: 'scope: CAL03 Opex.Forecast Opex', out: '1 note', t0: 1.6, t: 0.05 },
  { kind: 'model', name: 'read', args: '+ 2 sections, 1 object, 1 note', out: '2 tool calls', t0: 1.65, t: 1.9 },
  { kind: 'tool', name: 'get_section', args: 'CR-031 · Requested change', out: '210 tokens', t0: 3.55, t: 0.05 },
  { kind: 'tool', name: 'tests', args: 'CAL03 Opex.Forecast Opex', out: '1 hit', t0: 3.6, t: 0.2 },
  { kind: 'model', name: 'answer', args: '5,150 tokens in', out: '380 tokens out', t0: 3.8, t: 4.6 },
  { kind: 'check', name: 'validator', args: '2 quotes, 3 objects, 2 figures', out: 'clean', t0: 8.4, t: 0.2 },
]

export function ContextPage() {
  const total = CTX.reduce((a, c) => a + c.tok, 0), left = OUT.reduce((a, c) => a + c.tok, 0), end = 8.6
  const byKind = Object.keys(KINDS).map(k => ({ k, tok: CTX.filter(c => c.k === k).reduce((a, c) => a + c.tok, 0) })).filter(x => x.tok)
  const max = Math.max(...CTX.map(c => c.tok))
  const col = { model: '#a78bfa', tool: '#38bdf8', check: '#34d399' }
  return <>
    <div className="ds-kick"><span className="type">Context and run</span><span className="k">· one panel on every answer</span><Mock /></div>
    <h1 className="ds-q">What the model was given, and what it did.</h1>
    <p className="ds-lead">For the "why" answer: <b>{total.toLocaleString()} tokens of a {BUDGET.toLocaleString()} budget</b>. Two sections of 54 were read. Everything else stayed out, and the list below says why.</p>
    <div className="ds-fig"><div className="fh"><span className="k">Context</span><span className="grow" /><a className="ds-tag" href="#/design/why">Why is the account mapping written into the Forecast Opex formula…</a></div>
      <div className="fb">
        <div className="ds-big"><span className="v">{total.toLocaleString()}</span><span className="of">of {BUDGET.toLocaleString()} tokens · {Math.round(100 * total / BUDGET)}% of the budget · {left.toLocaleString()} left out</span></div>
        <div className="ds-budget" role="img" aria-label={'Context by kind: ' + byKind.map(b => `${KINDS[b.k][0]} ${b.tok}`).join(', ')}>{byKind.map(b => <i key={b.k} title={`${KINDS[b.k][0]} · ${b.tok.toLocaleString()} tokens`} style={{ width: 100 * b.tok / BUDGET + '%', background: KINDS[b.k][1] }} />)}</div>
        <div className="ds-bk">{byKind.map(b => <span key={b.k}><u style={{ background: KINDS[b.k][1] }} />{KINDS[b.k][0]} {b.tok.toLocaleString()}</span>)}<span>· unused {(BUDGET - total).toLocaleString()}</span></div>
      </div>
      <div className="cap">The budget is enforced in code: a tool result that would break it returns a count and its top rows.</div></div>
    <div className="ds-sec"><span className="k">Given to the model</span><span className="ct">{CTX.length} items</span></div>
    <table className="ds-ctx"><thead><tr><th style={{ width: '15%' }}>Kind</th><th style={{ width: '37%' }}>Item</th><th>Why it is here</th><th className="num" style={{ width: '9%' }}>Tokens</th></tr></thead>
      <tbody>{CTX.map(c => <tr key={c.item}><td><span className="ds-tag" style={{ color: KINDS[c.k][1], borderColor: KINDS[c.k][1] + '88' }}>{KINDS[c.k][0]}</span></td><td>{c.item}</td><td className="why">{c.why}</td><td className="num barcell">{c.tok.toLocaleString()}<i style={{ width: 100 * c.tok / max + '%', background: KINDS[c.k][1] }} /></td></tr>)}</tbody></table>
    <div className="ds-sec"><span className="k">Left out</span><span className="ct">{left.toLocaleString()} tokens not sent</span></div>
    <table className="ds-ctx"><tbody>{OUT.map(c => <tr className="out" key={c.item}><td style={{ width: '15%' }}><span className="ds-tag">not sent</span></td><td style={{ width: '37%' }} className="it">{c.item}</td><td className="why">{c.why}</td><td className="num" style={{ width: '9%' }}>{c.tok.toLocaleString()}</td></tr>)}</tbody></table>

    <div className="ds-fig" style={{ marginTop: 34 }}><div className="fh"><span className="k">Run</span><span className="grow" /><div className="ds-leg"><span><u style={{ background: col.model }} />model call</span><span><u style={{ background: col.tool }} />tool call</span><span><u style={{ background: col.check }} />validator</span></div></div>
      <div className="fb"><div className="ds-run">{RUN.map((r, i) => <React.Fragment key={i}>
        <div className="n">{String(i + 1).padStart(2, '0')}</div>
        <div><span className="ds-tag" style={{ color: col[r.kind], borderColor: col[r.kind] + '88' }}>{r.kind === 'check' ? 'check' : r.kind}</span></div>
        <div style={{ overflow: 'hidden' }}><span className="nm">{r.name}</span> <span className="a">{r.args} → {r.out}</span></div>
        <div><div className="tl"><i style={{ left: 100 * r.t0 / end + '%', width: 100 * r.t / end + '%', background: col[r.kind] }} /></div></div>
        <div className="d">{r.t < 1 ? Math.round(r.t * 1000) + ' ms' : r.t.toFixed(1) + ' s'}</div>
      </React.Fragment>)}</div></div>
      <div className="cap">3 model calls, 5 tool calls, 1 check · {end} s · 5,150 tokens in, 380 out · $0.03. Built from what the turn already stores: no outside account needed.</div></div>
    <div className="ds-foot"><span className="ds-tag ok">verified</span><span className="mono">verdict clean · 2 quotes found in their sections · 0 untraced figures</span><span className="grow" /><button>Copy as text</button><button title="Shown only when LangSmith keys are set on the server">Open in LangSmith ↗</button></div>
  </>
}

// ---------- settings (answer mode, and whose product this is) ----------
export function SettingsPage() {
  const [mode, setMode] = useState<'full' | 'concise'>('full')
  return <>
    <div className="ds-kick"><span className="type">Settings</span><span className="k">· for this login</span><Mock /></div>
    <h1 className="ds-q">Settings</h1>
    <div className="ds-sec"><span className="k">Answers</span></div>
    <div className="ds-list">
      <div className="r" style={{ alignItems: 'center' }}><span style={{ width: 190, flex: 'none' }}>Answer mode</span>
        <span className="grow dim" style={{ fontSize: 12.5 }}>{mode === 'full' ? 'Full: diagrams, source cards and the reach view. The default for a new login.' : 'Concise: the steps or a few lines with the figures; explain and show diagram on each.'} Changeable per question on the composer.</span>
        <div className="ds-seg" role="group" aria-label="Answer mode"><button className={mode === 'full' ? 'on' : ''} onClick={() => setMode('full')}>Full</button><button className={mode === 'concise' ? 'on' : ''} onClick={() => setMode('concise')}>Concise</button></div></div>
      <div className="r"><span style={{ width: 190, flex: 'none' }}>Theme</span><span className="grow dim" style={{ fontSize: 12.5 }}>Dark. There is no light theme in v0.2.</span></div>
    </div>
    <div className="ds-sec"><span className="k">Workspaces</span></div>
    <div className="ds-list">
      <div className="r"><span style={{ width: 190, flex: 'none' }}>Caldergate Distribution Group</span><span className="grow dim" style={{ fontSize: 12.5 }}>4 models · 5 documents · 5 chats · 19 notes</span><span className="ds-tag ok">open</span></div>
      <div className="r"><span style={{ width: 190, flex: 'none' }}>Caldergate FY27 rebuild</span><span className="grow dim" style={{ fontSize: 12.5 }}>1 model · sandbox</span></div>
      <div className="r"><span className="grow dim" style={{ fontSize: 12.5 }}>Each workspace is separate. A chat belongs to one workspace and remembers nothing from another.</span></div>
    </div>
    <div className="ds-sec"><span className="k">About</span></div>
    <div className="ds-list">
      <div className="r"><span style={{ width: 190, flex: 'none' }}>/architect</span><span className="grow dim" style={{ fontSize: 12.5 }}>Built by CodelessOps · codelessops.com · MIT licence. The name, logo and Bert ship with it; a self-run copy may replace them.</span><span className="mono dim" style={{ fontSize: 11 }}>v0.2</span></div>
    </div>
  </>
}
