// Home: what the knowledge base holds, in a glance, with the way to the Notes tab.
import React, { useEffect, useState } from 'react'
import { ago, api, type Note } from '../api'
import { href, useApp } from '../App'
import { Inline } from '../objects'

const STATUS: Record<string, [string, string]> = { user_confirmed: ['confirmed', ''], working_assumption: ['assumption', 'amber'], superseded: ['superseded', 'off'] }

export function NotesSummary() {
  const { route, summary: s, idx, toast } = useApp()
  const [notes, setNotes] = useState<Note[] | null>(null)
  const eid = route.eid!
  const total = s?.notes || 0
  const flagged = s?.notes_flagged || 0
  useEffect(() => {
    if (!s?.snapshot) { setNotes([]); return }
    let live = true
    api<Note[]>(`/api/estates/${eid}/notes`).then(r => { if (live) setNotes(r) }).catch(e => toast(e.message))
    return () => { live = false }
  }, [eid, total, flagged, toast, s?.snapshot])
  if (!s) return null
  const confirmed = (notes || []).filter(n => n.status === 'user_confirmed').length
  const assumptions = (notes || []).filter(n => n.status === 'working_assumption').length
  const latest = (notes || []).slice(0, 5)
  return (
    <section style={{ marginTop: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>Notes</h3>
        <a className="small" href={href(eid, 'notes')}>All notes and decisions →</a>
      </div>
      <div className="card list-card">
        <div className="small" style={{ padding: '6px 0 8px' }}>
          {total ? <>{total} note{total !== 1 ? 's' : ''} the architect reads by scope: <b>{confirmed}</b> confirmed, <b>{assumptions}</b> working assumption{assumptions !== 1 ? 's' : ''}{flagged ? <>, <span className="pill amber">{flagged} need{flagged === 1 ? 's' : ''} review</span> after the snapshot changed</> : ''}.</> : <span className="muted">No notes yet. Save an answer as a note from any conversation, tell the architect something worth keeping, or add one on the Notes tab.</span>}
        </div>
        {latest.map(n => <a key={n.id} className="row2" href={href(eid, 'notes')} title={n.title}>
          <span className="t"><Inline text={n.title} idx={idx} /></span>
          <span className="small"><span className="pill dim">{n.type}</span> <span className={'pill ' + (STATUS[n.status]?.[1] ?? 'dim')}>{STATUS[n.status]?.[0] || n.status}</span> <span className="muted">{ago(n.updated)}</span></span>
        </a>)}
      </div>
    </section>
  )
}
