// A menu in the app's own dark theme, in place of a native <select> (whose open list is drawn by the browser: white,
// pale text, browser blue). A button showing the choice; a list that opens above or below it; the chosen row carries
// the brand accent and a tick. Keyboard: Enter or Space opens, arrows move, Enter picks, Escape closes.
import React, { useEffect, useRef, useState } from 'react'

export type MenuOption = { value: string; label: string }

export function Menu({ value, options, onPick, title, up = false, disabled = false }: { value: string; options: MenuOption[]; onPick: (v: string) => void; title?: string; up?: boolean; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState(0)
  const root = useRef<HTMLDivElement>(null), list = useRef<HTMLDivElement>(null)
  const cur = Math.max(0, options.findIndex(o => o.value === value))
  useEffect(() => {
    if (!open) return
    setAt(cur)
    const away = (e: MouseEvent) => { if (root.current && !root.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])
  useEffect(() => { if (open) list.current?.querySelector<HTMLElement>(`[data-i="${at}"]`)?.scrollIntoView({ block: 'nearest' }) }, [open, at])
  const pick = (i: number) => { setOpen(false); if (options[i] && options[i].value !== value) onPick(options[i].value) }
  function key(e: React.KeyboardEvent) {
    if (!open) { if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(e.key)) { e.preventDefault(); setOpen(true) } return }
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setAt(i => Math.min(options.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setAt(i => Math.max(0, i - 1)) }
    else if (e.key === 'Home') { e.preventDefault(); setAt(0) }
    else if (e.key === 'End') { e.preventDefault(); setAt(options.length - 1) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(at) }
    else if (e.key === 'Tab') setOpen(false)
  }
  return (
    <div className={'ds-menu' + (open ? ' open' : '') + (up ? ' up' : '')} ref={root}>
      <button type="button" className="ds-menu-b" title={title} disabled={disabled} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(o => !o)} onKeyDown={key}>
        <span className="v">{options[cur]?.label ?? ''}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {open && <div className="ds-menu-l" role="listbox" aria-label={title} ref={list}>
        {options.map((o, i) => <div key={o.value} data-i={i} role="option" aria-selected={i === cur} className={'o' + (i === cur ? ' sel' : '') + (i === at ? ' at' : '')}
          onMouseEnter={() => setAt(i)} onMouseDown={e => { e.preventDefault(); pick(i) }}>
          <span className="tick" aria-hidden="true">{i === cur ? '✓' : ''}</span><span className="t">{o.label}</span></div>)}
      </div>}
    </div>
  )
}
