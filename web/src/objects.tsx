// Anaplan object names, one convention everywhere (the v0.1 plan, "Object names"):
// text writes names in backticks; this file styles them by kind with the brand kit's
// citation-chip device. module = Data Sky, line item = Analyst Violet (module part in Sky),
// model = foreground on the rule, a name the estate does not contain = Caution Amber, dashed.
// Stage 3: a chip is evidence. One the tools handed this conversation (a citation) is underlined
// and opens the object as its snapshot held it; a real name the architect never looked up is
// dotted and opens a lookup made now; an id the tools never handed is amber, dashed, and opens nothing.
import React, { useEffect, useMemo, useRef } from 'react'
import { marked } from 'marked'
import { sanitize } from './sanitize'
import { KIND_LABEL, PROV_LABEL, type Citation, type EvidenceTarget, type Summary, type Turn } from './api'
import { useApp } from './App'

export type NameIndex = { models: Set<string>; mods: Set<string>; modList: string[] }

export const emptyIndex: NameIndex = { models: new Set(), mods: new Set(), modList: [] }

export function buildIndex(s: Summary | null): NameIndex {
  if (!s) return emptyIndex
  const all = new Set<string>()
  for (const m of s.models) for (const x of m.module_names || []) all.add(x)
  const modList = [...all].sort((a, b) => b.length - a.length)
  return { models: new Set(s.models.map(m => m.name.toLowerCase())), mods: new Set(modList.map(x => x.toLowerCase())), modList }
}

export type Kind = { kind: 'model' } | { kind: 'mod' } | { kind: 'li'; mod: string; item: string } | null

export function objKind(text: string, idx: NameIndex): Kind {
  const t = text.trim(), l = t.toLowerCase()
  if (idx.models.has(l)) return { kind: 'model' }
  if (idx.mods.has(l)) return { kind: 'mod' }
  for (const m of idx.modList) if (t.length > m.length + 1 && l.startsWith(m.toLowerCase() + '.')) return { kind: 'li', mod: t.slice(0, m.length), item: t.slice(m.length + 1) }
  return null
}

// ---------- citations a turn (or a note) carries, by every name they may be written under ----------
export type CiteMap = Map<string, Citation>
export const noCites: CiteMap = new Map()

export function citesOf(list?: Citation[] | null): CiteMap {
  const m: CiteMap = new Map()
  for (const c of list || []) {
    for (const k of [c.name, c.ref, c.as_written, c.id]) if (k) m.set(String(k).trim().toLowerCase(), c)
    if (c.kind === 'note') m.set('note:' + c.ref.toLowerCase(), c)
  }
  return m
}
export const buildCites = (t?: Turn | null): CiteMap => citesOf(t?.citations)

export const KIND_CLASS: Record<string, string> = { model: 'model', module: 'mod', line_item: 'li', action: 'act', pattern: 'pat', finding: 'rule', note: 'note', document: 'note' }
const kindOf = (k: Kind) => k?.kind === 'model' ? 'model' : k?.kind === 'mod' ? 'module' : k?.kind === 'li' ? 'line_item' : undefined

type Desc = { cls: string; title: string; target: EvidenceTarget | null; parts: { mod?: string; item?: string; text: string } }

/** How a backticked name (or a bare id) renders, and what it opens. Null when it is plain code: a formula, a function, a keyword. */
export function describe(text: string, idx: NameIndex, cites?: CiteMap, unverified?: string[], unchecked?: string[], phantom?: string[]): Desc | null {
  const t = text.trim(); const low = t.toLowerCase()
  const c = cites?.get(low) || cites?.get(low.replace(/^'|'$/g, ''))
  const k = objKind(t, idx)
  if (c) {
    const target = { id: c.id, ref: c.ref, model: c.model || undefined, kind: c.kind, snapshot: c.snapshot_id }
    const title = `${KIND_LABEL[c.kind] || c.kind} · handed by ${c.tool || 'the tools'} · ${PROV_LABEL[c.provenance] || c.provenance} · click to open`
    const cls = `obj ${KIND_CLASS[c.kind] || 'model'} cited`
    if (c.kind === 'note') return { cls, title, target, parts: { text: 'note · ' + (c.name || c.ref) } }
    if (c.kind === 'document') return { cls: 'obj doc cited', title: (c.name || c.ref) + ' · click to open the passage', target, parts: { text: '¶ ' + ((c.name || c.ref).split(' · ').pop() || 'passage') } }
    if (k && k.kind === 'li') return { cls, title, target, parts: { mod: k.mod, item: k.item, text: t } }
    if (c.kind === 'line_item' && c.ref.includes('.')) { const i = c.ref.lastIndexOf('.'); return { cls, title, target, parts: { mod: c.ref.slice(0, i), item: c.ref.slice(i + 1), text: t } } }
    return { cls, title, target, parts: { text: t } }
  }
  if ((phantom || []).includes(t)) return { cls: 'obj unknown phantom', title: 'an id the tools never handed: not evidence', target: null, parts: { text: t } }
  if (k) {
    const un = (unchecked || []).includes(t)
    const kind = kindOf(k)!
    const title = un ? `${KIND_LABEL[kind]} · named without being looked up this conversation · click to look it up now` : `${KIND_LABEL[kind]} · click to look it up`
    return { cls: `obj ${k.kind}` + (un ? ' unchecked' : ' known'), title, target: { ref: t, kind }, parts: k.kind === 'li' ? { mod: k.mod, item: k.item, text: t } : { text: t } }
  }
  if ((unverified || []).includes(t)) return { cls: 'obj unknown', title: 'not found in the estate', target: null, parts: { text: t } }
  return null
}

const esc = (s: string) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string))

function chipHtml(d: Desc): string {
  const t = d.target
  const attrs = t ? ` data-open="1"${t.id ? ` data-cite="${esc(t.id)}"` : ''} data-ref="${esc(t.ref || '')}" data-kind="${esc(t.kind || '')}"${t.model ? ` data-model="${esc(t.model)}"` : ''}${t.snapshot ? ` data-snapshot="${esc(t.snapshot)}"` : ''} role="button" tabindex="0"` : ''
  const inner = d.parts.mod != null ? `<span class="mod">${esc(d.parts.mod)}</span><span class="dot">.</span>${esc(d.parts.item || '')}` : esc(d.parts.text)
  return `<span class="${d.cls}" title="${esc(d.title)}"${attrs}>${inner}</span>`
}

function targetOf(el: HTMLElement): EvidenceTarget {
  return { id: el.getAttribute('data-cite') || undefined, ref: el.getAttribute('data-ref') || undefined, kind: el.getAttribute('data-kind') || undefined,
    model: el.getAttribute('data-model') || undefined, snapshot: el.getAttribute('data-snapshot') || undefined }
}

export type ObjProps = { text: string; idx: NameIndex; unverified?: string[]; cites?: CiteMap; unchecked?: string[]; phantom?: string[] }

export function Obj({ text, idx, unverified, cites, unchecked, phantom }: ObjProps) {
  const { openEvidence } = useApp()
  const d = describe(text, idx, cites, unverified, unchecked, phantom)
  if (!d) return <code>{text}</code>
  const open = d.target ? (e: React.SyntheticEvent) => { e.preventDefault(); e.stopPropagation(); openEvidence(d.target!) } : undefined
  const inner = d.parts.mod != null ? <><span className="mod">{d.parts.mod}</span><span className="dot">.</span>{d.parts.item}</> : d.parts.text
  return <span className={d.cls} title={d.title} onClick={open} onKeyDown={open ? e => { if (e.key === 'Enter' || e.key === ' ') open(e) } : undefined} role={open ? 'button' : undefined} tabIndex={open ? 0 : undefined}>{inner}</span>
}

export const ModelChip = ({ name }: { name: string }) => <span className="obj model">{name}</span>

/** One citation as a chip that opens it (a note's sources, a turn's evidence row). */
export const CiteChip = ({ c, idx }: { c: Citation; idx: NameIndex }) => <Obj text={c.ref} idx={idx} cites={citesOf([c])} />

/** Prose with backticked names: each becomes a chip. */
export function Inline({ text, idx, cites }: { text: string; idx: NameIndex; cites?: CiteMap }) {
  const parts = String(text || '').split(/`([^`]{1,160})`/g)
  return <>{parts.map((p, i) => i % 2 ? <Obj key={i} text={p} idx={idx} cites={cites} /> : <React.Fragment key={i}>{p}</React.Fragment>)}</>
}

const ID_RE = /\b(?:c[0-9a-f]{10}|n-[0-9a-f]{10}|s-[0-9a-f]{10})\b/

/** Inline style for a td.bar: the bar's length as a share (0..1). */
export const barStyle = (w: number | null | undefined): React.CSSProperties => ({ ['--w' as string]: String(Math.max(0, Math.min(1, w || 0))) } as React.CSSProperties)

const NUM_CELL = /^\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*([%KMBkmb]?)\s*$/
const BLANK_CELL = /^\s*(?:|[-—–]|n\/a)\s*$/i
const numOf = (s: string): number | null => {
  const m = NUM_CELL.exec(s); if (!m) return null
  const v = parseFloat(m[1].replace(/,/g, '')); if (!isFinite(v)) return null
  const u = m[2].toUpperCase(); return v * (u === 'K' ? 1e3 : u === 'M' ? 1e6 : u === 'B' ? 1e9 : 1)
}
/** Sizes and amounts compared by eye: in every table, a column whose cells are all numbers (blanks allowed) gets a faint
 * bar behind each figure, proportional to the column's largest, and a bare integer of five or more digits gets thousands
 * separators (the digits are unchanged; a figure already wrapped, untraced or a chip, is left as written). Years are left alone. */
function tableBars(d: HTMLElement) {
  for (const t of Array.from(d.querySelectorAll('table'))) {
    const rows = Array.from(t.querySelectorAll('tbody tr')).map(r => Array.from(r.children) as HTMLElement[])
    if (rows.length < 2) continue
    for (let k = 0; k < Math.max(...rows.map(r => r.length)); k++) {
      const cells = rows.map(r => r[k]).filter(Boolean)
      const text = cells.map(c => c.textContent || '')
      if (text.some(s => !BLANK_CELL.test(s) && numOf(s) == null)) continue          // a column with any word in it is not compared
      const vals = text.map(s => BLANK_CELL.test(s) ? null : numOf(s))
      const nums = vals.filter((v): v is number => v != null)
      if (nums.length < 2) continue
      const max = Math.max(...nums.map(Math.abs))
      if (!(max > 0) || nums.every(v => v === nums[0])) continue                       // nothing to compare
      if (nums.every(v => Number.isInteger(v) && v >= 1900 && v <= 2100)) continue    // a column of years
      const th = t.querySelectorAll('thead th')[k]; if (th) th.classList.add('num')
      cells.forEach((c, i) => {
        const v = vals[i]; if (v == null) return
        c.classList.add('bar'); c.style.setProperty('--w', String(Math.abs(v) / max))
        if (!c.children.length && /^\s*\d{5,}\s*$/.test(text[i])) c.textContent = v.toLocaleString()
      })
    }
  }
}
const escRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Markdown from the architect: code spans that name objects become chips; bare citation ids become chips;
 * figures no tool returned are marked. Clicks on any chip open the evidence drawer. */
export function Markdown({ md, idx, unverified, cites, unchecked, phantom, untraced, streaming }: { md: string; idx: NameIndex; unverified?: string[]; cites?: CiteMap; unchecked?: string[]; phantom?: string[]; untraced?: string[]; streaming?: boolean }) {
  const { openEvidence } = useApp()
  const html = useMemo(() => {
    let out: string
    // marked keeps raw HTML as it is; DOMPurify drops it (and javascript: links) before an answer, or a note any member typed, reaches the page
    try { out = sanitize(marked.parse(md || '', { async: false }) as string) } catch { out = '<pre>' + esc(md || '') + '</pre>' }
    const d = document.createElement('div'); d.innerHTML = out
    for (const c of streaming ? [] : Array.from(d.querySelectorAll('pre > code.language-mermaid'))) {      // a diagram: drawn once the answer is complete, never from a half-streamed fence; names in it unchecked
      const box = document.createElement('div'); box.className = 'mermaid-box'; box.dataset.src = c.textContent || ''
      box.innerHTML = '<pre class="mermaid-fallback">' + esc(c.textContent || '') + '</pre>'
      c.closest('pre')!.replaceWith(box)
    }
    for (const c of Array.from(d.querySelectorAll('code'))) {
      if (c.closest('pre')) continue
      const desc = describe(c.textContent || '', idx, cites, unverified, unchecked, phantom)
      if (!desc) continue
      const w = document.createElement('span'); w.innerHTML = chipHtml(desc)
      c.replaceWith(w.firstChild as Node)
    }
    foldSections(d, !!streaming)
    tableBars(d)
    const marks = (untraced || []).filter(Boolean).map(escRe)
    const wantIds = (cites && cites.size > 0) || (phantom && phantom.length > 0)
    const alts = [...(wantIds ? [ID_RE.source] : []), ...(marks.length ? ['(?<![\\w.,:/-])(?:' + marks.join('|') + ')(?![\\w.,:/-]*\\w)'] : [])]
    if (alts.length) {
      const re = new RegExp(alts.join('|'), 'g')
      const walker = document.createTreeWalker(d, NodeFilter.SHOW_TEXT)
      const nodes: Text[] = []
      for (let n = walker.nextNode(); n; n = walker.nextNode()) if (!(n.parentElement && n.parentElement.closest('code,pre,a,.obj'))) nodes.push(n as Text)
      for (const node of nodes) {
        const s = node.nodeValue || ''
        const frag = document.createDocumentFragment(); let last = 0; let changed = false; let m: RegExpExecArray | null
        re.lastIndex = 0
        while ((m = re.exec(s))) {
          const tok = m[0]; let el: HTMLElement | null = null
          if (ID_RE.test(tok) && tok.length <= 12) {
            const desc = describe(tok, idx, cites, [], [], phantom)
            if (desc) { const w = document.createElement('span'); w.innerHTML = chipHtml(desc); el = w.firstChild as HTMLElement }
          } else {
            el = document.createElement('span'); el.className = 'fig untraced'; el.title = 'no tool returned this figure this turn; treat with care'; el.textContent = tok
          }
          if (!el) continue
          frag.append(s.slice(last, m.index)); frag.append(el); last = m.index + tok.length; changed = true
        }
        if (changed) { frag.append(s.slice(last)); node.replaceWith(frag) }
      }
    }
    return d.innerHTML
  }, [md, idx, unverified, cites, unchecked, phantom, untraced, streaming])
  const onClick = (e: React.MouseEvent) => {
    const bar = (e.target as HTMLElement).closest('[data-secs]') as HTMLElement | null
    if (bar) {                                                       // expand or collapse every section of this answer
      e.preventDefault()
      const root = bar.closest('.md') as HTMLElement | null
      const secs = Array.from(root?.querySelectorAll('details.sec') || []) as HTMLDetailsElement[]
      const open = secs.some(s => !s.open)
      for (const s of secs) s.open = open
      bar.textContent = open ? 'Collapse all' : 'Expand all'
      return
    }
    const el = (e.target as HTMLElement).closest('[data-open]') as HTMLElement | null
    if (!el) return
    e.preventDefault(); openEvidence(targetOf(el))
  }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    const el = (e.target as HTMLElement).closest('[data-open]') as HTMLElement | null
    if (!el) return
    e.preventDefault(); openEvidence(targetOf(el))
  }
  const box = useRef<HTMLDivElement>(null)
  const opened = useRef<Set<string>>(new Set())                          // the headings the reader opened: a re-render (every streamed token) rebuilds the details closed
  useEffect(() => {
    const root = box.current
    if (!root) return
    const onToggle = (e: Event) => {
      const d = e.target as HTMLDetailsElement
      if (!(d instanceof HTMLDetailsElement) || !d.classList.contains('sec')) return
      const k = d.querySelector('summary .t')?.textContent || ''
      if (d.open) opened.current.add(k); else opened.current.delete(k)
    }
    root.addEventListener('toggle', onToggle, true)                    // toggle does not bubble; capture reaches the ancestor
    return () => root.removeEventListener('toggle', onToggle, true)
  }, [])
  useEffect(() => {
    const root = box.current
    if (!root) return
    const secs = Array.from(root.querySelectorAll('details.sec')) as HTMLDetailsElement[]
    for (const s of secs) if (opened.current.has(s.querySelector('summary .t')?.textContent || '')) s.open = true
    const bar = root.querySelector('[data-secs]')
    if (bar && secs.length) bar.textContent = secs.every(s => s.open) ? 'Collapse all' : 'Expand all'
    drawDiagrams(root)
  }, [html])
  return <div className="md" ref={box} onClick={onClick} onKeyDown={onKey} dangerouslySetInnerHTML={{ __html: html }} />
}

/** The answer contract, rendered: the first section (the Brief, or whatever comes before the first `##`) stays open;
 * every later `##` section folds under its heading with its first sentence as a teaser, so the reader decides from the
 * Brief and opens only what they need. While an answer streams, the section still being written stays open too. One
 * answer with fewer than two `##` sections is left as it is. Chips inside a folded section keep working when it opens. */
function foldSections(d: HTMLElement, streaming: boolean) {
  const kids = Array.from(d.childNodes)
  const groups: { head: HTMLElement | null; body: Node[] }[] = [{ head: null, body: [] }]
  for (const k of kids) {
    if (k instanceof HTMLElement && k.tagName === 'H2') groups.push({ head: k, body: [] })
    else groups[groups.length - 1].body.push(k)
  }
  const secs = groups.filter(g => g.head)
  if (secs.length < 2) return
  const keepOpen = new Set<number>([1])                              // the first `##` section (the Brief) is always open
  if (streaming) keepOpen.add(groups.length - 1)                     // and so is the one still being written
  const bar = document.createElement('div'); bar.className = 'secbar'
  bar.innerHTML = '<button class="small quiet" type="button" data-secs="1">Expand all</button>'
  let inserted = false
  groups.forEach((g, i) => {
    if (!g.head || keepOpen.has(i)) return
    const det = document.createElement('details'); det.className = 'sec'
    const sum = document.createElement('summary')
    const t = document.createElement('span'); t.className = 't'; t.innerHTML = g.head.innerHTML
    const tease = document.createElement('span'); tease.className = 'tease'; tease.textContent = teaserOf(g.body)
    sum.append(t, tease); det.append(sum)
    if (!inserted) { g.head.before(bar); inserted = true }
    g.head.replaceWith(det)
    for (const n of g.body) det.append(n)
  })
}

/** The first sentence of a section's first prose block: subheadings are skipped, and a full stop after a bare number
 * (`1.` in a numbered heading) does not end a sentence. */
function teaserOf(body: Node[]): string {
  for (const n of body) {
    if (n instanceof HTMLElement && /^H[1-6]$/.test(n.tagName)) continue
    const text = (n.textContent || '').replace(/\s+/g, ' ').trim()
    if (!text) continue
    const first = text.split(/(?<=[^\d\s][.!?])\s/)[0]
    return first.length > 140 ? first.slice(0, 137) + '…' : first
  }
  return ''
}

let mermaidReady: Promise<any> | null = null
let diagramSeq = 0
/** Mermaid, loaded on demand the first time an answer carries a diagram. A diagram is drawn from the fence as written; the
 * names inside it are not checked against the estate (the chips in the prose are), and the caption under it says so. */
async function drawDiagrams(root: HTMLElement | null) {
  if (!root) return
  const boxes = Array.from(root.querySelectorAll('.mermaid-box[data-src]:not([data-done])')) as HTMLElement[]
  if (!boxes.length) return
  for (const b of boxes) b.dataset.done = '1'
  try {
    if (!mermaidReady) mermaidReady = import('mermaid').then(m => { m.default.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict', fontFamily: 'inherit', suppressErrorRendering: true }); return m.default })
    const mermaid = await mermaidReady
    for (const b of boxes) {
      const src = b.dataset.src || ''
      try {
        await mermaid.parse(src)                                     // a diagram that will not parse shows its source; Mermaid draws nothing of its own
        const { svg } = await mermaid.render('mmd-' + (++diagramSeq), src)
        b.innerHTML = svg + '<div class="cap">Diagram drawn as written: names in it are not checked against the estate; the chips in the text are.</div>'
      } catch (e: any) {
        b.innerHTML += '<div class="cap warn">The diagram could not be drawn' + (e && e.message ? ': ' + esc(String(e.message).split(String.fromCharCode(10))[0]) : '') + '. Its source is shown instead.</div>'
      }
    }
  } catch (e: any) {
    for (const b of boxes) b.innerHTML += '<div class="cap warn">Mermaid could not be loaded; the diagram source is shown instead.</div>'
  }
}
