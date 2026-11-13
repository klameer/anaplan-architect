// Deleting a workspace: one dialog, used from the workspace list, the workspace's settings and the admin panel. It
// says what goes with the workspace (models, documents, chats, notes) and asks for its name typed back. There is no undo.
import React, { useEffect, useRef, useState } from 'react'
import { api, json } from '../api'

export type Doomed = { id: string; name: string; models: number; documents?: number; chats?: number; notes?: number }
const n = (k: number | undefined, one: string, many = one + 's') => `${k ?? 0} ${k === 1 ? one : many}`

export function DeleteWorkspace({ ws, onClose, onDone, toast }: { ws: Doomed; onClose: () => void; onDone: () => void | Promise<void>; toast: (m: string) => void }) {
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLInputElement>(null)
  useEffect(() => {
    box.current?.focus()
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc); return () => document.removeEventListener('keydown', esc)
  }, [])
  const ok = typed.trim() === ws.name
  async function del() {
    if (!ok || busy) return
    setBusy(true)
    try { await api('/api/estates/' + ws.id, json('DELETE', { confirm: typed.trim() })); await onDone() }
    catch (e: any) { toast(e.message); setBusy(false) }
  }
  return (
    <div className="ds-modal" role="dialog" aria-modal="true" aria-label={'Delete the workspace ' + ws.name} onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="box">
        <div className="h">Delete this workspace?</div>
        <div className="nm">{ws.name}</div>
        <div className="what"><div className="k">What goes with it</div>
          <ul><li>{n(ws.models, 'model')} and every export uploaded for {ws.models === 1 ? 'it' : 'them'}</li><li>{n(ws.documents, 'document')}</li><li>{n(ws.chats, 'chat')}, with their answers</li><li>{n(ws.notes, 'note')}</li><li>its decisions and dependencies</li></ul>
          <div className="warn">There is no undo. Download a backup from the workspace's settings first if you may want it back.</div></div>
        <label htmlFor="del-name">Type the workspace's name to confirm</label>
        <input id="del-name" ref={box} className="ds-in" value={typed} placeholder={ws.name} autoComplete="off" onChange={e => setTyped(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') del() }} />
        <div className="acts"><button className="ds-btn" onClick={onClose}>Cancel</button><button className="ds-btn danger" disabled={!ok || busy} onClick={del}>{busy ? 'Deleting…' : 'Delete workspace'}</button></div>
      </div>
    </div>
  )
}
