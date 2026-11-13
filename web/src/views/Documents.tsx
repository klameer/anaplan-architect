// The workspace's project documents (v0.2 P1): a card per document, not a file list. Each card shows what the architect
// always sees of it (title, type, date, headings, the summary written at upload, the objects it names) and how it has
// been used: one bar per section, green where an answer has quoted it. Replace with a new version, or remove.
import { Bert, BertNote } from '../design/Bert'
import React, { useEffect, useRef, useState } from 'react'
import { api, fmtB, fmtN, withCsrf } from '../api'
import { useApp } from '../App'
import { Obj } from '../objects'
import { Sec } from './Answer'

type Sect = { id: string; seq: number; heading: string; level: number; tokens: number; cited: number }
type Doc = { id: string; title: string; doc_type: string; filename: string; ext: string; bytes: number; doc_date: string | null; summary: string; summary_by: string; words: number; version: number
  problem: string | null; uploaded_at: string; sections: Sect[]; objects: { model: string; kind: string; ref: string; n: number }[]; tokens: number; sections_cited: number; answers: number }
type Payload = { documents: Doc[]; totals: { documents: number; sections: number; tokens: number }; limits: { documents: number; bytes: number; note: string }; results?: { ok: boolean; filename: string; error?: string }[] }

export function DocumentsPage() {
  const { route, idx, toast, refresh, openEvidence } = useApp()
  const eid = route.eid!
  const [d, setD] = useState<Payload | null>(null)
  const [busy, setBusy] = useState('')
  const pick = useRef<HTMLInputElement>(null)
  const repl = useRef<HTMLInputElement>(null)
  const [replacing, setReplacing] = useState<Doc | null>(null)
  const [openDoc, setOpenDoc] = useState<string | null>(null)
  useEffect(() => { setD(null); api<Payload>(`/api/estates/${eid}/documents`).then(setD).catch(e => toast(e.message)) }, [eid])

  async function upload(files: FileList | null, replaces?: string) {
    if (!files || !files.length) return
    const fd = new FormData()
    for (const f of Array.from(files)) fd.append('files', f)
    if (replaces) fd.append('replaces', replaces)
    setBusy(replaces ? 'Reading the new version…' : `Reading ${files.length} file${files.length !== 1 ? 's' : ''}: splitting into sections, linking the objects named…`)
    try {
      const r = await fetch(`/api/estates/${eid}/documents`, withCsrf({ method: 'POST', body: fd }))
      const j = await r.json()
      if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'the upload failed')
      setD(j)
      const bad = (j.results || []).filter((x: any) => !x.ok)
      if (bad.length) toast(bad.map((x: any) => x.error).join(' · '))
      await refresh()
    } catch (e: any) { toast(e.message) } finally { setBusy(''); setReplacing(null); if (pick.current) pick.current.value = ''; if (repl.current) repl.current.value = '' }
  }
  async function remove(doc: Doc) {
    if (!confirm(`Remove "${doc.title}" from this workspace?\n\nIts sections go with it. Answers that quoted it keep the quote, but the passage will no longer open.`)) return
    try { setD(await api<Payload>('/api/documents/' + doc.id, { method: 'DELETE' })); await refresh() } catch (e: any) { toast(e.message) }
  }

  if (!d) return <div className="dim">Reading the documents…</div>
  const docs = d.documents, cited = docs.reduce((a, x) => a + x.sections_cited, 0), full = docs.length >= d.limits.documents
  return <>
    <div className="ds-kick"><span className="type">Documents</span><span className="k">· {docs.length} of {d.limits.documents}</span></div>
    <h1 className="ds-q">The project's own documents, read section by section.</h1>
    <p className="ds-lead">Each document becomes a card and a set of sections. The architect always sees the cards; it opens a section only when a question needs it, and quotes the passage it used.</p>
    <div className="ds-tiles"><div><div className="v">{docs.length} <span className="dim" style={{ fontSize: 13 }}>/ {d.limits.documents}</span></div><div className="l">documents</div></div><div><div className="v">{d.totals.sections}</div><div className="l">sections</div></div><div><div className="v">{fmtN(d.totals.tokens)}</div><div className="l">tokens, if all were sent</div></div><div><div className="v">{cited}</div><div className="l">sections quoted so far</div></div></div>
    <div className="ds-drop" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!full) upload(e.dataTransfer.files) }}>
      <span>{busy ? <Bert state="processing" place="document-upload" size={32} line={busy} /> : <><b>{full ? 'This workspace is full.' : 'Add a document.'}</b> {d.limits.note}</>}</span><span className="grow" />
      <input ref={pick} type="file" multiple hidden onChange={e => upload(e.target.files)} />
      <input ref={repl} type="file" hidden onChange={e => upload(e.target.files, replacing?.id)} />
      <button disabled={!!busy || full} onClick={() => pick.current?.click()}>Choose files</button>
    </div>
    {docs.length === 0 && <BertNote state="information" place="empty-documents" title="No documents yet">Until there are, a question about why something was built is answered "not recorded" unless an owner note covers it.</BertNote>}
    <div className="ds-docs">{docs.map(doc => { const heads = doc.sections.filter(s => s.heading).map(s => s.heading), maxT = Math.max(1, ...doc.sections.map(s => s.tokens))
      return <div className="ds-doc" key={doc.id}>
        <div className="dh"><span className="ds-tag">{doc.doc_type}</span>{doc.version > 1 && <span className="ds-tag sky">version {doc.version}</span>}<span className="grow" /><span className="f">{doc.doc_date || 'undated'} · {fmtB(doc.bytes)}</span></div>
        <div><div className="t">{doc.title}</div><div className="f">{doc.filename}</div></div>
        {doc.problem ? <p className="ds-gap" style={{ margin: 0 }}>{doc.problem}</p> : <div className="sum">{doc.summary}{doc.summary_by === 'extract' && <span className="dim"> (its opening lines)</span>}</div>}
        {doc.sections.length > 0 && <div><div className="strip" role="img" aria-label={`${doc.sections.length} sections, ${doc.sections_cited} quoted`}>{doc.sections.map(s => <i key={s.id} className={s.cited ? 'c' : ''} title={`${s.heading || 'opening'} · ${fmtN(s.tokens)} tokens${s.cited ? ` · quoted in ${s.cited} answer${s.cited !== 1 ? 's' : ''}` : ''}`} style={{ height: 4 + Math.round(10 * s.tokens / maxT), cursor: 'pointer' }} onClick={() => openEvidence({ ref: s.id, kind: 'document' })} />)}</div>
          <div className="sl"><span>{doc.sections.length} section{doc.sections.length !== 1 ? 's' : ''} · {fmtN(doc.tokens)} tokens</span><span>{doc.sections_cited ? <><b>{doc.sections_cited} quoted</b> in {doc.answers} answer{doc.answers !== 1 ? 's' : ''}</> : 'not quoted yet'}</span></div></div>}
        {heads.length > 0 && <div className="hd">{(openDoc === doc.id ? heads : heads.slice(0, 5)).join('  ·  ')}{heads.length > 5 && <> <button className="ds-aff" onClick={() => setOpenDoc(openDoc === doc.id ? null : doc.id)}>{openDoc === doc.id ? 'fewer' : `+${heads.length - 5}`}</button></>}</div>}
        {doc.objects.length > 0 && (() => { const refs = Array.from(new Set(doc.objects.map(o => o.ref))); return <div className="ds-chips">{refs.slice(0, 4).map(r => <Obj key={r} text={r} idx={idx} />)}{refs.length > 4 && <span className="ds-chip">+{refs.length - 4} objects</span>}</div> })()}
        <div className="da"><span>read {doc.uploaded_at.slice(0, 10)}</span><span className="grow" /><button disabled={!!busy} onClick={() => { setReplacing(doc); setTimeout(() => repl.current?.click(), 0) }}>Replace with a new version</button><button disabled={!!busy} onClick={() => remove(doc)}>Remove</button></div>
      </div> })}</div>
    <Sec k="How a document is used" />
    <div className="ds-list">
      <div className="r"><span className="ds-tag ok">always</span><span className="grow">The card: title, type, date, headings, a summary written once at upload, the objects it names.</span></div>
      <div className="r"><span className="ds-tag sky">per question</span><span className="grow">Only the sections that bear on the question, found by keyword and by the objects they name. The context view on each answer lists them.</span></div>
      <div className="r"><span className="ds-tag">never</span><span className="grow dim">A whole document by default. No embeddings and no vector store: a document is indexed inside the workspace's own SQLite file.</span></div>
    </div>
  </>
}
