import { useEffect, useRef, useState } from 'react'
import { api, type Row } from '../lib/api'
import { shortCode } from '../lib/format'

export function StockSearch({ onSelect, placeholder = '搜索代码或名称…', className = 'w-64' }: {
  onSelect: (r: Row) => void; placeholder?: string; className?: string
}) {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Row[]>([])
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!q.trim()) { setItems([]); return }
    const t = setTimeout(() => {
      api.get<Row[]>(`/api/stocks/search?q=${encodeURIComponent(q.trim())}&limit=12`).then(r => { setItems(r); setHi(0) }).catch(() => {})
    }, 150)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    const h = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const pick = (r: Row) => { onSelect(r); setQ(''); setItems([]); setOpen(false) }

  return (
    <div ref={box} className={`relative ${className}`}>
      <input className="field w-full" value={q} placeholder={placeholder}
        onChange={e => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(h + 1, items.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
          if (e.key === 'Enter' && items[hi]) pick(items[hi])
        }} />
      {open && items.length > 0 && (
        <ul className="card absolute z-30 mt-1 max-h-80 w-full overflow-auto py-1">
          {items.map((r, i) => (
            <li key={r.code} onMouseDown={() => pick(r)} onMouseEnter={() => setHi(i)}
              className={`flex cursor-pointer items-center justify-between px-3 py-2 text-[13px] ${i === hi ? 'bg-surface-2' : ''}`}>
              <span><span className="font-medium">{r.name}</span> <span className="num text-faint">{shortCode(r.code)}</span></span>
              <span className="text-[12px] text-faint">{r.industry}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
