// Getting started: the guide for someone who has just been handed a login. The words and the screens come from one
// spec (src/anaplan_architect/guide/spec.json); tools/guide.py takes each screen from the Caldergate demo and finds where
// each arrow points on the real page. The same guide is written out as one file to send or print.
// Every word is text: the arrows are drawn over the picture, the callouts are a list under it. Nothing moves.
import React, { useEffect, useState } from 'react'
import { api, json } from '../api'
import { useApp } from '../App'
import hello from '../design/brand/bert-architect-hello.svg'
import information from '../design/brand/bert-architect-information.svg'
import evidence from '../design/brand/bert-architect-evidence.svg'
import neutral from '../design/brand/bert-architect-neutral.svg'
import processing from '../design/brand/bert-architect-processing.svg'
import warning from '../design/brand/bert-architect-warning.svg'
import question from '../design/brand/bert-architect-question.svg'

const BERT: Record<string, string> = { hello, information, evidence, neutral, processing, warning, question }
type Callout = { n: number; x: number; y: number; tx: number; ty: number; text: string }
type Screen = { name: string; image: string; alt: string; width: number; height: number; callouts: Callout[] }
type Section = { id: string; title: string; body: string[]; bert?: string; list?: string[]; questions?: boolean; screens?: Screen[]; link?: { text: string; href: string } }
type GuideData = { title: string; lead: string; from: string; sections: Section[]; questions: { text: string; shows: string }[]; captured?: string }

/** The numbered arrows over one screen, in the screen's own pixels: a line from the number to what it points at. */
function Overlay({ s }: { s: Screen }) {
  const r = Math.max(13, Math.round(s.width * 0.0135)), id = 'ah-' + s.name
  return <svg viewBox={`0 0 ${s.width} ${s.height}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <defs><marker id={id} viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#fbbf24" /></marker></defs>
    {s.callouts.map(c => { const x = c.x * s.width, y = c.y * s.height, tx = c.tx * s.width, ty = c.ty * s.height
      return <g key={c.n}>
        <line x1={tx} y1={ty} x2={x} y2={y} stroke="#0b0e0d" strokeWidth={r * 0.5} strokeLinecap="round" opacity=".55" />
        <line x1={tx} y1={ty} x2={x} y2={y} stroke="#fbbf24" strokeWidth={Math.max(3, r * 0.22)} markerEnd={`url(#${id})`} />
        <circle cx={tx} cy={ty} r={r} fill="#fbbf24" stroke="#0b0e0d" strokeWidth="3" />
        <text x={tx} y={ty + r * 0.38} textAnchor="middle" fontFamily="system-ui,sans-serif" fontWeight="600" fontSize={r * 1.1} fill="#1a1200">{c.n}</text></g> })}
  </svg>
}

export function Guide() {
  const { go, route } = useApp()
  const [g, setG] = useState<GuideData | null>(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    api<GuideData>('/api/guide').then(setG).catch(e => setErr(e.message))
    api('/api/prefs', json('PUT', { guide_seen: true })).catch(() => {})          // opening it is seeing it: the welcome card does not come back
  }, [])
  if (err) return <div className="ds-col"><p className="ds-gap">{err}</p></div>
  if (!g) return <div className="ds-col"><p className="dim">Opening the guide…</p></div>
  return <div className="ds-col ds-guide" data-guide={g.sections.length}>
    <div className="ds-kick"><span className="type">Getting started</span><span className="k">· about ten minutes</span></div>
    <h1 className="ds-q">{g.title}</h1>
    <p className="ds-lead">{g.lead}</p>
    <p className="dim" style={{ marginTop: -14 }}>{g.from}</p>
    <nav className="toc" aria-label="In this guide"><div className="k">In this guide</div>
      <ol>{g.sections.map(s => <li key={s.id}><a href={'#/guide/' + s.id} onClick={e => { e.preventDefault(); document.getElementById('guide-' + s.id)?.scrollIntoView({ block: 'start' }) }}>{s.title}</a></li>)}</ol></nav>
    {g.sections.map((s, i) => <section key={s.id} id={'guide-' + s.id}>
      <div className="gnum">Step {i + 1} of {g.sections.length}</div>
      <div className="head">{s.bert && BERT[s.bert] && <img src={BERT[s.bert]} alt="" aria-hidden="true" width="52" height="45" data-bert={s.bert} data-bert-place={'guide-' + s.id} />}<h2>{s.title}</h2></div>
      {s.body.map((p, k) => <p key={k}>{p}</p>)}
      {s.list && <ul>{s.list.map((x, k) => <li key={k}>{x}</li>)}</ul>}
      {s.questions && g.questions.map(q => <div className="gq" key={q.text}>{q.text}<span>{q.shows}</span></div>)}
      {(s.screens || []).map(sc => <figure key={sc.name}>
        <div className="shot"><img src={'/app/guide/img/' + sc.image} alt={sc.alt} width={sc.width} height={sc.height} loading="lazy" /><Overlay s={sc} /></div>
        <ol className="calls">{sc.callouts.map(c => <li key={c.n}><b>{c.n}</b><span>{c.text}</span></li>)}</ol></figure>)}
      {s.link && <p><a href={s.link.href} target="_blank" rel="noreferrer noopener">{s.link.text} ↗</a></p>}
    </section>)}
    <p className="dim" style={{ fontSize: 12.5, marginTop: 28 }}>Every screen is from the Caldergate demo: an invented company.{g.captured ? ` Made from the app as it was on ${g.captured}.` : ''} This guide is always here: <b>Getting started</b>, beside Settings.</p>
    <p><button className="ds-btn" onClick={() => go(route.eid ? '#/e/' + route.eid : '#/')}>Back to your workspace</button></p>
  </div>
}

/** Offered once, on a login's first visit: open the guide, or not now. Either way it does not come back. */
export function GuideWelcome() {
  const { me, route, go } = useApp()
  const [show, setShow] = useState(false)
  useEffect(() => {
    if (!me?.user) return
    api<{ guide_seen: boolean }>('/api/prefs').then(p => setShow(!p.guide_seen)).catch(() => {})
  }, [me?.user?.id])
  if (!show || route.view === 'guide' || new URLSearchParams(location.search).has('capture')) return null
  const done = (open: boolean) => { setShow(false); api('/api/prefs', json('PUT', { guide_seen: true })).catch(() => {}); if (open) go('#/guide') }
  return <div className="ds-welcome" role="region" aria-label="Getting started" data-guide-welcome="1">
    <img src={hello} alt="" aria-hidden="true" width="48" height="41" />
    <div className="grow"><div className="t">New here?</div><div className="d">There is a short guide: what each screen is for, which Anaplan exports to bring, and what to ask first. About ten minutes.</div></div>
    <button className="ds-btn go" onClick={() => done(true)}>Open the guide</button><button className="ds-btn" onClick={() => done(false)}>Not now</button>
  </div>
}
