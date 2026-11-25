import { useMemo, useState, type ReactNode } from 'react'
import { cx } from './ui'
import type { Row } from '../lib/api'

export interface Col {
  key: string
  label: string
  align?: 'left' | 'right'
  render?: (row: Row) => ReactNode
  sortable?: boolean
  width?: number
}

export function DataTable({ cols, rows, onRowClick, maxHeight = 560, initialSort, pageSize = 100, rowKey = 'code' }: {
  cols: Col[]; rows: Row[]; onRowClick?: (r: Row) => void; maxHeight?: number
  initialSort?: { key: string; desc: boolean }; pageSize?: number; rowKey?: string
}) {
  const [sort, setSort] = useState(initialSort ?? null)
  const [limit, setLimit] = useState(pageSize)
  const sorted = useMemo(() => {
    if (!sort) return rows
    const m = sort.desc ? -1 : 1
    return [...rows].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key]
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      return (x > y ? 1 : x < y ? -1 : 0) * m
    })
  }, [rows, sort])
  const shown = sorted.slice(0, limit)
  return (
    <div className="overflow-auto" style={{ maxHeight }}>
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr>
            {cols.map(c => {
              const active = sort?.key === c.key
              const can = c.sortable !== false
              return (
                <th key={c.key} style={{ width: c.width }}
                  onClick={() => can && setSort(s => (s?.key === c.key ? { key: c.key, desc: !s.desc } : { key: c.key, desc: true }))}
                  className={cx('border-b border-line px-3 py-2.5 text-[12px] font-medium whitespace-nowrap select-none',
                    c.align === 'right' ? 'text-right' : 'text-left', can && 'cursor-pointer hover:text-text',
                    active ? 'text-accent-text' : 'text-muted')}>
                  {c.label}{active && (sort!.desc ? ' ↓' : ' ↑')}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={r[rowKey] ?? i} onClick={() => onRowClick?.(r)}
              className={cx('border-b border-line/70 transition-colors', onRowClick && 'cursor-pointer hover:bg-surface-2')}>
              {cols.map(c => (
                <td key={c.key} className={cx('num px-3 py-2.5 whitespace-nowrap', c.align === 'right' && 'text-right')}>
                  {c.render ? c.render(r) : (r[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > limit && (
        <button onClick={() => setLimit(l => l + pageSize)} className="w-full cursor-pointer py-3 text-[13px] text-accent-text hover:bg-surface-2">
          显示更多（{sorted.length - limit} 条）
        </button>
      )}
    </div>
  )
}
