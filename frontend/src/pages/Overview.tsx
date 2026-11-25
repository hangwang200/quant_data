import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Card, ErrorBox, Loading, PageHeader, Segmented, Stat } from '../components/ui'
import { Gauge, sentimentLabel, sentimentTone } from '../components/Gauge'
import { Chart, axisStyle } from '../components/Chart'
import { DataTable, type Col } from '../components/DataTable'
import { MarketIndicators } from '../components/MarketIndicators'
import { TimeRange, sliceWindow, type Win } from '../components/TimeRange'
import { useFetch } from '../lib/hooks'
import { useMeta } from '../lib/meta'
import { useColors } from '../lib/theme'
import { fmt, pct, shortCode, trendClass } from '../lib/format'
import type { Row } from '../lib/api'

interface Overview {
  date: string
  stats: { n: number; up: number; down: number; flat: number; amount: number }
  sentiment: {
    score: number
    components: Record<string, number | null>
    history: Record<'prev' | 'week' | 'month' | 'year', { date: string; score: number } | null>
    timeline: { dates: string[]; scores: number[] }
  }
  indices: { code: string; name: string; close: number; pct_chg: number | null; dates: string[]; values: number[] }[]
}

const COMP_LABEL: Record<string, string> = {
  breadth: '上涨家数占比', above_ma20: '站上20日均线', high_low: '新高/新低', volume: '成交活跃度', momentum: '指数动量',
}

function Spark({ values, up }: { values: number[]; up: boolean }) {
  const c = useColors()
  return (
    <Chart height={64} option={{
      grid: { left: 0, right: 0, top: 4, bottom: 0 },
      xAxis: { type: 'category', show: false, data: values.map((_, i) => i) },
      yAxis: { type: 'value', show: false, scale: true },
      tooltip: { show: false },
      series: [{
        type: 'line', data: values, showSymbol: false, lineStyle: { width: 1.6, color: up ? c.up : c.down },
        areaStyle: { color: up ? c.up : c.down, opacity: 0.08 },
      }],
    }} />
  )
}

export default function Overview() {
  const nav = useNavigate()
  const c = useColors()
  const { meta } = useMeta()
  const ov = useFetch<Overview>(meta?.ready ? '/api/market/overview' : null)
  const st = useFetch<{ rows: Row[] }>(meta?.ready ? '/api/market/stocks' : null)
  const [q, setQ] = useState('')
  const [ind, setInd] = useState('')
  const [view, setView] = useState<'overview' | 'timeline'>('overview')
  const [sWin, setSWin] = useState<Win>({ preset: '1Y' })
  const [iWin, setIWin] = useState<Win>({ preset: '1Y' })

  const rows = useMemo(() => (st.data?.rows ?? []).filter(r =>
    (!ind || r.industry === ind) && (!q || r.code.includes(q) || r.name?.includes(q) || r.industry?.includes(q))), [st.data, q, ind])

  if (!meta?.ready) return null
  if (ov.error) return <ErrorBox error={ov.error} />
  if (!ov.data) return <Loading />
  const d = ov.data, s = d.sentiment
  const tl = sliceWindow(s.timeline.dates, { scores: s.timeline.scores }, sWin)

  const cols: Col[] = [
    { key: 'name', label: '股票 / 代码', render: r => <div><div className="font-medium">{r.name}</div><div className="text-[11px] text-faint">{shortCode(r.code)}</div></div> },
    { key: 'industry', label: '行业', render: r => <span className="text-muted">{r.industry ?? '—'}</span> },
    { key: 'close', label: '收盘价', align: 'right', render: r => fmt(r.close) },
    { key: 'pct_chg', label: '涨跌幅', align: 'right', render: r => <span className={trendClass(r.pct_chg)}>{pct(r.pct_chg, 2, true)}</span> },
    { key: 'amount', label: '成交额(亿)', align: 'right', render: r => fmt(r.amount) },
    { key: 'turnover', label: '换手率', align: 'right', render: r => pct(r.turnover) },
    { key: 'float_mv', label: '流通市值(亿)', align: 'right', render: r => fmt(r.float_mv, 0) },
    { key: 'pe_ttm', label: 'PE(TTM)', align: 'right', render: r => fmt(r.pe_ttm, 1) },
    { key: 'pb', label: 'PB', align: 'right', render: r => fmt(r.pb) },
    { key: 'roe_ann', label: 'ROE', align: 'right', render: r => pct(r.roe_ann, 1) },
    { key: 'go', label: '', sortable: false, render: () => <span className="text-accent-text">查看 →</span> },
  ]

  return (
    <>
      <PageHeader eyebrow="Market Overview" title="市场总览"
        desc={`全 A 股 · 数据截至 ${d.date}`} />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="上涨" value={d.stats.up?.toLocaleString()} tone="up" sub={`占比 ${pct(d.stats.up / d.stats.n * 100, 1)}`} />
        <Stat label="下跌" value={d.stats.down?.toLocaleString()} tone="down" sub={`占比 ${pct(d.stats.down / d.stats.n * 100, 1)}`} />
        <Stat label="平盘" value={d.stats.flat?.toLocaleString()} tone="muted" sub={`有成交 ${d.stats.n} 只`} />
        <Stat label="成交额" value={`${fmt(d.stats.amount / 1e8, 0)}亿`} sub="全市场合计" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Card title="市场情绪指数" extra={<div className="flex items-center gap-2">
          {view === 'timeline' && <TimeRange value={sWin} onChange={setSWin} presets={['3M', '6M', '1Y', '3Y', 'ALL']} />}
          <Segmented value={view} onChange={setView} options={[{ value: 'overview', label: '概览' }, { value: 'timeline', label: '走势' }]} />
        </div>}>
          {view === 'overview' ? (
            <div className="grid items-center gap-6 md:grid-cols-[1.2fr_1fr]">
              <div className="flex flex-col items-center">
                <Gauge value={s.score} />
                <Badge tone={sentimentTone(s.score) === 'neutral' ? 'neutral' : sentimentTone(s.score)}>当前：{sentimentLabel(s.score)}</Badge>
              </div>
              <ul className="divide-y divide-line">
                {([['prev', '前一交易日'], ['week', '1 周前'], ['month', '1 个月前'], ['year', '1 年前']] as const).map(([k, label]) => {
                  const h = s.history[k]
                  return (
                    <li key={k} className="flex items-center justify-between py-2.5">
                      <div><div className="text-[12px] text-faint">{label}</div><div className="text-[13px] font-medium">{h ? sentimentLabel(h.score) : '—'}</div></div>
                      {h && <Badge tone={sentimentTone(h.score) === 'neutral' ? 'neutral' : sentimentTone(h.score)}><span className="num">{h.score.toFixed(0)}</span></Badge>}
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : (
            <Chart height={250} option={{
              xAxis: { type: 'category', data: tl.dates, ...axisStyle(c), splitLine: { show: false } },
              yAxis: { type: 'value', min: 0, max: 100, ...axisStyle(c) },
              dataZoom: [{ type: 'inside' }],
              series: [{
                type: 'line', name: '情绪指数', data: tl.series.scores, showSymbol: false, lineStyle: { width: 1.8, color: c.accent },
                markArea: { silent: true, data: [[{ yAxis: 0, itemStyle: { color: c.down, opacity: 0.06 } }, { yAxis: 25 }], [{ yAxis: 75, itemStyle: { color: c.up, opacity: 0.06 } }, { yAxis: 100 }]] },
              }],
            }} />
          )}
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2.5 border-t border-line pt-4 sm:grid-cols-3">
            {Object.entries(s.components).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-[12px]"><span className="text-muted">{COMP_LABEL[k]}</span><span className="num font-medium">{v == null ? '—' : v.toFixed(0)}</span></div>
                <div className="mt-1 h-1.5 rounded-full bg-surface-2"><div className="h-1.5 rounded-full bg-accent" style={{ width: `${v ?? 0}%` }} /></div>
              </div>
            ))}
          </div>
        </Card>

        <div className="grid gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold">主要指数</span>
            <TimeRange value={iWin} onChange={setIWin} presets={['1M', '3M', '6M', 'YTD', '1Y', '3Y', 'ALL']} />
          </div>
          {d.indices.map(ix => {
            const chg = ix.pct_chg ?? 0
            const w = sliceWindow(ix.dates, { v: ix.values }, iWin)
            const vals = w.series.v.filter((x): x is number => x != null)
            const yr = vals.length ? (vals[vals.length - 1] / vals[0] - 1) * 100 : 0
            return (
              <div key={ix.code} className="card px-5 py-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[13px] text-muted">{ix.name}</div>
                    <div className="num mt-0.5 text-[22px] font-semibold">{fmt(ix.close)}</div>
                  </div>
                  <div className="text-right">
                    <div className={`num text-[15px] font-semibold ${trendClass(chg)}`}>{pct(chg, 2, true)}</div>
                    <div className="text-[12px] text-faint">区间 <span className={trendClass(yr)}>{pct(yr, 1, true)}</span></div>
                  </div>
                </div>
                <Spark values={vals} up={yr >= 0} />
              </div>
            )
          })}
        </div>
      </div>

      <div className="mt-4"><MarketIndicators /></div>

      <Card className="mt-4" title={`行情列表 · ${rows.length} 只`} extra={
        <div className="flex gap-2">
          <input className="field w-56" placeholder="搜索代码、名称或行业" value={q} onChange={e => setQ(e.target.value)} />
          <select className="field" value={ind} onChange={e => setInd(e.target.value)}>
            <option value="">全部行业</option>
            {meta.industries?.map(i => <option key={i}>{i}</option>)}
          </select>
        </div>
      }>
        {st.data ? <DataTable cols={cols} rows={rows} initialSort={{ key: 'amount', desc: true }} onRowClick={r => nav(`/stock/${r.code}`)} /> : <Loading />}
      </Card>
    </>
  )
}
