import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge, Button, Card, ErrorBox, Field, Loading } from './ui'
import { Chart, axisStyle } from './Chart'
import { FormulaInput } from './FactorSelect'
import { TimeRange, sliceWindow, type Win } from './TimeRange'
import { api } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useColors } from '../lib/theme'
import { fmt } from '../lib/format'

interface IndMeta { label: string; unit: string; group: string }
interface Resp {
  builtin: Record<string, IndMeta>
  saved: Record<string, { label: string; expr: string }>
  dates: string[]
  series: Record<string, (number | null)[]>
}
interface Preview { ok: boolean; error?: string; dates?: string[]; values?: (number | null)[]; last?: number | null }

const DEFAULT = ['amt_top5', 'score', 'amount_yi']
const MAX = 6
const TS_FUNCS = 'ma(x,n) ema(x,n) ts_rank(x,n) ts_zscore(x,n) ts_max/ts_min/ts_std(x,n) diff(x,n) lag(x,n) pct_change(x,n) where(c,a,b) + − × ÷ > < and or'

function load(): string[] {
  try { const v = JSON.parse(localStorage.getItem('mkt_ind') ?? ''); if (Array.isArray(v) && v.length) return v } catch { /* ignore */ }
  return DEFAULT
}

/** 市场指标小多图：每个指标一行、共享时间轴（不同量纲不共用 Y 轴） */
function Multiples({ dates, rows }: { dates: string[]; rows: { key: string; label: string; unit: string; values: (number | null)[]; color: string }[] }) {
  const c = useColors()
  // 每行：标题(22px) + 图(H)，行间距 gap；标题放在网格上方，不与 Y 轴刻度重叠
  const H = 110, top0 = 4, gap = 44
  const grids = rows.map((_, i) => ({ left: 8, right: 16, top: top0 + i * (H + gap) + 30, height: H, containLabel: true }))
  return (
    <Chart height={top0 + rows.length * (H + gap) + 20} option={{
      legend: { show: false },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      tooltip: { trigger: 'axis', valueFormatter: (v: any) => (typeof v === 'number' ? fmt(v, 2) : '—') },
      title: rows.map((r, i) => {
        const last = [...r.values].reverse().find(v => v != null)
        return {
          text: last == null ? r.label : `${r.label}   最新 ${fmt(last, 2)} ${r.unit}`, left: 8, top: top0 + i * (H + gap) - 2,
          textStyle: { fontSize: 12, fontWeight: 500, color: c.muted },
        }
      }),
      grid: grids,
      xAxis: rows.map((_, i) => ({
        type: 'category' as const, data: dates, gridIndex: i, ...axisStyle(c), splitLine: { show: false },
        axisLabel: { show: i === rows.length - 1, color: c.faint, fontSize: 11 },
      })),
      yAxis: rows.map((_, i) => ({ type: 'value' as const, gridIndex: i, scale: true, ...axisStyle(c), splitNumber: 3 })),
      dataZoom: [{ type: 'inside', xAxisIndex: rows.map((_, i) => i) }],
      series: rows.map((r, i) => ({
        name: r.label, type: 'line' as const, xAxisIndex: i, yAxisIndex: i, data: r.values, showSymbol: false,
        lineStyle: { width: 1.6, color: r.color }, itemStyle: { color: r.color },
        areaStyle: { color: r.color, opacity: 0.06 },
      })),
    }} />
  )
}

export function MarketIndicators() {
  const c = useColors()
  const meta = useFetch<Resp>('/api/market/indicators')
  const [sel, setSel] = useState<string[]>(load)
  const [win, setWin] = useState<Win>({ preset: '3Y' })
  const [data, setData] = useState<Resp | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // 融合指标编辑器
  const [edit, setEdit] = useState(false)
  const [name, setName] = useState('crowd_heat')
  const [label, setLabel] = useState('拥挤度热度')
  const [expr, setExpr] = useState('ts_rank(amt_top5, 250) * 0.5 + ts_rank(turnover_med, 250) * 0.5')
  const [prev, setPrev] = useState<Preview | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => { try { localStorage.setItem('mkt_ind', JSON.stringify(sel)) } catch { /* ignore */ } }, [sel])
  useEffect(() => {
    if (!sel.length) return
    let alive = true
    api.get<Resp>(`/api/market/indicators?names=${sel.join(',')}`).then(d => alive && setData(d)).catch(e => alive && setErr(e.message))
    return () => { alive = false }
  }, [sel.join(','), meta.data]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!edit) return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      api.post<Preview>('/api/market/formula/preview', { expr }).then(setPrev).catch(e => setPrev({ ok: false, error: e.message }))
    }, 500)
    return () => window.clearTimeout(timer.current)
  }, [expr, edit])

  const m = meta.data
  const groups = useMemo(() => {
    const g: Record<string, [string, string][]> = {}
    for (const [k, v] of Object.entries(m?.builtin ?? {})) (g[v.group] ??= []).push([k, v.label])
    if (m && Object.keys(m.saved).length) g['融合指标'] = Object.entries(m.saved).map(([k, v]) => [k, v.label])
    return g
  }, [m])
  // 颜色跟随指标本身（按全部指标的固定顺序分配），不随选择顺序变化
  const allKeys = Object.keys(m?.builtin ?? {}).concat(Object.keys(m?.saved ?? {}))
  const colorOf = (k: string) => c.series[Math.max(0, allKeys.indexOf(k)) % c.series.length]

  const toggle = (k: string) => setSel(s => (s.includes(k) ? s.filter(x => x !== k) : s.length >= MAX ? s : [...s, k]))
  const save = async () => {
    setErr(null)
    try {
      await api.post('/api/market/formulas', { name, label, expr })
      meta.reload(); setSel(s => (s.includes(name) ? s : [...s.slice(0, MAX - 1), name])); setEdit(false)
    } catch (e) { setErr((e as Error).message) }
  }
  const remove = async (k: string) => {
    await api.del(`/api/market/formulas/${k}`); setSel(s => s.filter(x => x !== k)); meta.reload()
  }

  let body = null
  if (data && data.dates.length) {
    const series: Record<string, (number | null)[]> = {}
    for (const k of sel) if (data.series[k]) series[k] = data.series[k]
    const dates = data.dates
    if (edit && prev?.ok && prev.values) series['__preview'] = prev.values
    const w = sliceWindow(dates, series, win)
    const rows = Object.keys(w.series).map(k => k === '__preview'
      ? { key: k, label: `预览：${label || '未命名'}`, unit: '', values: w.series[k], color: c.accent }
      : { key: k, label: m?.builtin[k]?.label ?? m?.saved[k]?.label ?? k, unit: m?.builtin[k]?.unit ?? '', values: w.series[k], color: colorOf(k) })
    body = rows.length ? <Multiples dates={w.dates} rows={rows} /> : null
  }

  return (
    <Card title="市场指标" extra={<div className="flex items-center gap-2">
      <TimeRange value={win} onChange={setWin} />
      <Button variant="ghost" className="h-7 px-2.5 text-[12px]" onClick={() => setEdit(e => !e)}>{edit ? '收起编辑器' : '+ 融合指标'}</Button>
    </div>}>
      <div className="mb-3 space-y-2">
        {Object.entries(groups).map(([g, items]) => (
          <div key={g} className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 shrink-0 text-[11px] text-faint">{g}</span>
            {items.map(([k, l]) => {
              const on = sel.includes(k)
              return (
                <span key={k} className="inline-flex items-center">
                  <button onClick={() => toggle(k)} title={m?.saved[k]?.expr}
                    className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] transition ${on ? 'border-line-strong bg-surface-2 text-text' : 'border-line text-muted hover:text-text'}`}>
                    <span className="h-2 w-2 rounded-full" style={{ background: on ? colorOf(k) : 'var(--line-strong)' }} />{l}
                  </button>
                  {g === '融合指标' && <button className="cursor-pointer px-1 text-[12px] text-faint hover:text-up" title="删除" onClick={() => remove(k)}>×</button>}
                </span>
              )
            })}
          </div>
        ))}
        <div className="text-[11px] text-faint">最多同时显示 {MAX} 个 · 已选 {sel.length}</div>
      </div>

      {edit && (
        <div className="mb-4 rounded-xl border border-line bg-surface-2/50 p-4">
          <div className="grid gap-3 md:grid-cols-[160px_180px_1fr]">
            <Field label="标识名"><input className="field font-mono" value={name} onChange={e => setName(e.target.value.toLowerCase())} /></Field>
            <Field label="显示名称"><input className="field" value={label} onChange={e => setLabel(e.target.value)} /></Field>
            <Field label="公式（引用指标标识名，见上方按钮的悬停提示或下方列表）"><FormulaInput value={expr} onChange={setExpr} /></Field>
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[12px]">{prev == null ? null : prev.ok
              ? <span className="text-down">✓ 有效 · 最新值 {fmt(prev.last, 2)}（预览显示在图表最下方）</span>
              : <span className="text-up">✗ {prev.error}</span>}</div>
            <Button onClick={save} disabled={!prev?.ok || !name}>保存融合指标</Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {Object.entries(m?.builtin ?? {}).map(([k, v]) => (
              <button key={k} onClick={() => setExpr(e => `${e} ${k}`.trim())} title={v.label}
                className="cursor-pointer rounded bg-surface px-1.5 py-0.5 font-mono text-[11px] text-muted hover:text-accent-text">{k}</button>
            ))}
          </div>
          <div className="mt-2 font-mono text-[11px] text-faint">{TS_FUNCS}</div>
        </div>
      )}
      {err && <ErrorBox error={err} />}
      {!data ? <Loading /> : body ?? <div className="py-10 text-center text-faint">选择要显示的指标</div>}
      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-faint">
        <Badge>说明</Badge>近一周成交额前5%个股占比：每只股票近 5 个交易日成交额合计，全市场排名前 5% 的股票占总成交额比例，越高代表资金越集中（抱团/拥挤）。
        选股与回测公式中可用 <code className="font-mono">mkt_amt_top5</code> 做择时。
      </div>
    </Card>
  )
}
