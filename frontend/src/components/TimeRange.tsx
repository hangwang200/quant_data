import { useState } from 'react'
import { cx } from './ui'

export type Preset = '1M' | '3M' | '6M' | 'YTD' | '1Y' | '3Y' | '5Y' | 'ALL' | 'CUSTOM'
export interface Win { preset: Preset; start?: string; end?: string }

const LABEL: Record<Preset, string> = { '1M': '1月', '3M': '3月', '6M': '6月', YTD: '今年', '1Y': '1年', '3Y': '3年', '5Y': '5年', ALL: '全部', CUSTOM: '自定义' }
const MONTHS: Partial<Record<Preset, number>> = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '3Y': 36, '5Y': 60 }

function iso(d: Date) { return d.toISOString().slice(0, 10) }

/** 时间窗口 → [起, 止]（含），以数据最后一天为基准 */
export function windowBounds(w: Win, lastDate: string): [string, string] {
  const last = (lastDate ?? '').slice(0, 10)
  if (w.preset === 'ALL' || !/^\d{4}-\d{2}-\d{2}$/.test(last)) return ['0000-01-01', '9999-12-31']
  if (w.preset === 'CUSTOM') return [w.start || '0000-01-01', w.end || '9999-12-31']
  if (w.preset === 'YTD') return [`${last.slice(0, 4)}-01-01`, last]
  const d = new Date(`${last}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return ['0000-01-01', '9999-12-31']
  d.setUTCMonth(d.getUTCMonth() - (MONTHS[w.preset] ?? 12))
  return [iso(d), last]
}

/** 有序日期数组在窗口内的下标区间 [i0, i1)（日期字符串 YYYY-MM-DD 可直接比较） */
export function windowIndex(dates: string[], w: Win): [number, number] {
  if (!dates.length) return [0, 0]
  const [a, b] = windowBounds(w, dates[dates.length - 1])
  let i0 = dates.findIndex(d => d.slice(0, 10) >= a)
  if (i0 < 0) i0 = dates.length
  let i1 = dates.length
  while (i1 > i0 && dates[i1 - 1].slice(0, 10) > b) i1--
  return [i0, i1]
}

/** 截取窗口；rebase 的序列（净值类）从窗口首个有效值归一到 1 */
export function sliceWindow<T extends Record<string, (number | null)[]>>(dates: string[], series: T, w: Win, rebase: (keyof T)[] = []) {
  const [i0, i1] = windowIndex(dates, w)
  const out = {} as Record<keyof T, (number | null)[]>
  for (const k of Object.keys(series) as (keyof T)[]) {
    let s = series[k].slice(i0, i1)
    if (rebase.includes(k)) {
      const base = s.find(v => v != null && v !== 0)
      s = s.map(v => (v == null || base == null ? null : +(v / base).toFixed(4)))
    }
    out[k] = s
  }
  return { dates: dates.slice(i0, i1), series: out, i0, i1 }
}

/** 窗口内最大回撤序列 */
export function drawdown(nav: (number | null)[]) {
  let peak = -Infinity
  return nav.map(v => {
    if (v == null) return null
    peak = Math.max(peak, v)
    return +(v / peak - 1).toFixed(4)
  })
}

export function TimeRange({ value, onChange, presets = ['3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'ALL'], className }: {
  value: Win; onChange: (w: Win) => void; presets?: Preset[]; className?: string
}) {
  const [open, setOpen] = useState(value.preset === 'CUSTOM')
  return (
    <div className={cx('flex flex-wrap items-center gap-1.5', className)}>
      <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
        {[...presets, 'CUSTOM' as Preset].map(p => (
          <button key={p} type="button" onClick={() => { if (p === 'CUSTOM') setOpen(true); else { setOpen(false); onChange({ preset: p }) } }}
            className={cx('h-6 cursor-pointer rounded-md px-2 text-[11.5px] font-medium transition',
              (value.preset === p || (p === 'CUSTOM' && open)) ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text')}>
            {LABEL[p]}
          </button>
        ))}
      </div>
      {open && (
        <div className="flex items-center gap-1 text-[12px] text-faint">
          <input type="date" className="field num h-7 px-1.5 text-[12px]" value={value.start ?? ''}
            onChange={e => onChange({ preset: 'CUSTOM', start: e.target.value, end: value.end })} />
          <span>—</span>
          <input type="date" className="field num h-7 px-1.5 text-[12px]" value={value.end ?? ''}
            onChange={e => onChange({ preset: 'CUSTOM', start: value.start, end: e.target.value })} />
        </div>
      )}
    </div>
  )
}
