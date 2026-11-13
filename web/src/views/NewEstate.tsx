import React, { useState } from 'react'
import { Bert, BertNote } from '../design/Bert'
import { api, json, when } from '../api'
import { href, useApp } from '../App'

type Row = { id: number; name: string; li: File | null; ac: File | null; mo: File | null }
type Manifest = { estate_id: string; name: string; exported_at: string; models: string[]; counts: Record<string, number>; conflict: { id: string; name: string } | null; blobs_missing: string[]; people: { id: string; name: string; role: string }[] }

// A model's name from its Line Items file, when the file carries one ("FP&A - Line Items.csv" gives "FP&A"). A file
// named only after the export ("Line Items.csv") gives nothing, and the row then has to be named by hand: a model
// called "Line Items" is an upload named after its file.
export function modelNameFrom(file: string): string {
  const stem = file.replace(/\.csv$/i, '').replace(/[\s_.\-–(]*(line[\s_-]*items?|modules?|actions?)[\s)]*(\(\d+\))?$/i, '').trim()
  return /^(line[\s_-]*items?|modules?|actions?|export|grid)?$/i.test(stem) ? '' : stem
}

export function NewEstate() {
  const { estates, reloadEstates, go, toast } = useApp()
  const [rows, setRows] = useState<Row[]>([{ id: 1, name: '', li: null, ac: null, mo: null }, { id: 2, name: '', li: null, ac: null, mo: null }])
  const [name, setName] = useState('')
  const [aliases, setAliases] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [bk, setBk] = useState<File | null>(null)
  const [man, setMan] = useState<Manifest | null>(null)
  const [rname, setRname] = useState('')
  const upd = (id: number, patch: Partial<Row>) => setRows(rs => rs.map(r => r.id === id ? { ...r, ...patch } : r))

  async function inspect(f: File) {
    setBk(f); setMan(null)
    const fd = new FormData(); fd.append('file', f)
    try { setMan(await api<Manifest>('/api/estates/restore/inspect', { method: 'POST', body: fd })) } catch (e: any) { toast(e.message) }
  }
  async function restore() {
    if (!bk) return
    const fd = new FormData(); fd.append('file', bk); fd.append('name', rname)
    setBusy('Restoring the estate, its snapshots and export files…')
    try { const s = await api('/api/estates/restore', { method: 'POST', body: fd }); await reloadEstates(); go(href(s.id, 'home')) }
    catch (e: any) { toast(e.message) }
    finally { setBusy(null) }
  }

  async function parseAndOpen() {
    const used = rows.filter(r => r.li)
    if (!used.length) { toast('Add at least one Line Items file'); return }
    const fd = new FormData(); fd.append('name', name); fd.append('aliases', aliases)
    const unnamed = used.findIndex(r => !(r.name.trim() || modelNameFrom(r.li!.name)))
    if (unnamed >= 0) { toast(`Name the model in row ${rows.indexOf(used[unnamed]) + 1}: its file (${used[unnamed].li!.name}) is named after the export, not the model.`); return }
    for (const r of used) {
      fd.append('model_names', r.name.trim() || modelNameFrom(r.li!.name)); fd.append('line_items', r.li!)
      fd.append('actions', r.ac || new Blob([]), r.ac ? r.ac.name : ''); fd.append('modules', r.mo || new Blob([]), r.mo ? r.mo.name : '')
    }
    setBusy('Parsing every formula and building the graph…')
    try { const s = await api('/api/estates', { method: 'POST', body: fd }); await reloadEstates(); go(href(s.id, 'home')) }
    catch (e: any) { toast(e.message) }
    finally { setBusy(null) }
  }
  async function registerOnly() {
    setBusy('Registering…')
    try { const s = await api('/api/estates/create', json('POST', { name })); await reloadEstates(); go(href(s.id, 'home') + '/home/uploads') }
    catch (e: any) { toast(e.message) }
    finally { setBusy(null) }
  }

  return (
    <div>
      <h1>{estates.length ? 'New workspace' : 'No workspaces yet'}</h1>
      {!estates.length && <div id="empty-state"><BertNote state="information" place="empty-workspaces" title="Nothing here yet">Create a workspace from your exports below, restore a backup, or load the two demo workspaces from Settings.</BertNote></div>}
      <p className="muted">One row per model: the Line Items grid export and, if you have them, the Actions and Modules exports. Any number of models. Files stay on this server.</p>
      <div className="card up">
        {rows.map(r => (
          <div key={r.id} className="row five">
            <div><label>Model name</label><input value={r.name} placeholder="FP&A" onChange={e => upd(r.id, { name: e.target.value })} /></div>
            <div><label>Line Items.csv</label><input type="file" accept=".csv" onChange={e => { const f = e.target.files?.[0] || null; upd(r.id, { li: f, ...(f && !r.name.trim() ? { name: modelNameFrom(f.name) } : {}) }) }} /></div>
            <div><label>Actions.csv (optional)</label><input type="file" accept=".csv" onChange={e => upd(r.id, { ac: e.target.files?.[0] || null })} /></div>
            <div><label>Modules.csv (optional)</label><input type="file" accept=".csv" onChange={e => upd(r.id, { mo: e.target.files?.[0] || null })} /></div>
            <div />
            <button onClick={() => setRows(rs => rs.filter(x => x.id !== r.id))}>×</button>
          </div>
        ))}
        <div><button onClick={() => setRows(rs => [...rs, { id: Date.now(), name: '', li: null, ac: null, mo: null }])}>Add a model</button></div>
        <div className="row" style={{ gridTemplateColumns: '1fr 2fr' }}>
          <div><label>Estate name</label><input value={name} placeholder="e.g. Group planning" onChange={e => setName(e.target.value)} /></div>
          <div><label>Aliases (phrase=Model; phrase=Model) for import names that differ from model names</label><input value={aliases} placeholder="Headcount Model=HR; FPA=FP&A" onChange={e => setAliases(e.target.value)} /></div>
        </div>
        <div className="actions">
          <button className="primary" disabled={!!busy} onClick={parseAndOpen}>Parse and open</button>
          <button disabled={!!busy} onClick={registerOnly}>Or register the estate first and upload later</button>
          {busy ? <Bert state="processing" place="upload" size={36} line={busy} /> : <span className="small muted" />}
        </div>
      </div>

      <h2>Or restore a backup</h2>
      <div className="card">
        <p className="small muted" style={{ marginTop: 0 }}>A backup taken from Estate settings (one <code>.architect.zip</code>): the register, every snapshot with its export files, notes, conversations with their citations, decisions and proposals come back under their original ids, so every old citation still opens. Accounts never travel with a backup; authors the server does not know are left blank.</p>
        <div className="row" style={{ gridTemplateColumns: '1fr 1fr auto' }}>
          <div><label>Backup file</label><input type="file" accept=".zip" onChange={e => { const f = e.target.files?.[0]; if (f) inspect(f) }} /></div>
          <div><label>Name (optional: restore under another name)</label><input value={rname} placeholder={man?.name || ''} onChange={e => setRname(e.target.value)} /></div>
          <div><label>&nbsp;</label><button className="primary" disabled={!man || !!busy || !!man.conflict || man.blobs_missing.length > 0} onClick={restore}>Restore</button></div>
        </div>
        {man && <div className="small" style={{ marginTop: 8 }}>
          <b>{man.name}</b> · exported {when(man.exported_at)} · models: {man.models.join(', ') || 'none'} · {man.counts.snapshots || 0} snapshot{man.counts.snapshots !== 1 ? 's' : ''}, {man.counts.notes || 0} note{man.counts.notes !== 1 ? 's' : ''}, {man.counts.conversations || 0} conversation{man.counts.conversations !== 1 ? 's' : ''}, {man.counts.proposals || 0} proposal{man.counts.proposals !== 1 ? 's' : ''}{man.people.length ? ` · people named: ${man.people.map(p => p.name || p.id).join(', ')}` : ''}
          {man.conflict && <div className="warn" style={{ marginTop: 4 }}>An estate with this id is already here ({man.conflict.name}). Ids are kept on restore so old citations open, so delete that estate first, or restore on another server.</div>}
          {man.blobs_missing.length > 0 && <div className="warn" style={{ marginTop: 4 }}>{man.blobs_missing.length} export file{man.blobs_missing.length !== 1 ? 's are' : ' is'} missing from the archive; it cannot be restored.</div>}
        </div>}
      </div>
    </div>
  )
}
