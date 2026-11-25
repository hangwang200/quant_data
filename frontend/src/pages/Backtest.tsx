import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, Segmented, cx } from '../components/ui'
import { Chart, axisStyle } from '../components/Chart'
import { DataTable } from '../components/DataTable'
import { FactorSelect, FormulaInput, NeutralToggle, UniverseSelect } from '../components/FactorSelect'
import { TimeRange, drawdown, sliceWindow, windowBounds, type Win } from '../components/TimeRange'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { factorLabel, useMeta } from '../lib/meta'
import { useColors } from '../lib/theme'
import { fmt, ratio, shortCode, trendClass } from '../lib/format'
import type { Pool } from './Screener'

interface FactorIn { name: string; weight: number; direction: 'high' | 'low' }
interface Result {
  run_id: string; name: string; params: Row
  metrics: Record<string, any>
  series: { dates: string[]; nav: number[]; bench: number[]; drawdown: number[] }
  monthly: { year: number; month: number; ret: number | null }[]
  yearly: { year: number; ret: number | null; bench: number | null }[]
  holdings: { date: string | null; stocks: Row[] }
  n_rebalance: number
}

const TEMPLATES: { name: string; factors: FactorIn[] }[] = [
  { name: '价值+质量', factors: [{ name: 'ep', weight: 1, direction: 'high' }, { name: 'roe_ann', weight: 1, direction: 'high' }] },
  { name: '低波动', factors: [{ name: 'vol_60', weight: 1, direction: 'low' }] },
  { name: '质量成长', factors: [{ name: 'roe_ann', weight: 1, direction: 'high' }, { name: 'revenue_yoy', weight: 1, direction: 'high' }, { name: 'vol_60', weight: 0.5, direction: 'low' }] },
  { name: '小市值', factors: [{ name: 'float_mv', weight: 1, direction: 'low' }] },
  { name: '红利', factors: [{ name: 'dividend_yield', weight: 1, direction: 'high' }, { name: 'payout_ratio', weight: 0.5, direction: 'high' }, { name: 'vol_60', weight: 0.5, direction: 'low' }] },
  { name: '反转+低换手', factors: [{ name: 'mom_5', weight: 1, direction: 'low' }, { name: 'turnover_20', weight: 1, direction: 'low' }] },
]

const UNIV_SHORT: Record<string, string> = { all: '全A', hs800: '300+500', hs300: '300', zz500: '500', core: '当前800' }

interface CompareItem { run_id: string; name: string; params: Row; metrics: Record<string, any>; series: Result['series']; yearly: Result['yearly'] }

function CompareView({ items, onClose }: { items: CompareItem[]; onClose: () => void }) {
  const c = useColors()
  const { meta } = useMeta()
  const [win, setWin] = useState<Win>({ preset: 'ALL' })
  const last = items.map(i => i.series.dates[i.series.dates.length - 1]).sort().pop() ?? ''
  const [wa, wb] = windowBounds(win, last)
  const cut = (it: CompareItem, key: 'nav' | 'bench') => {
    const pts = it.series.dates.map((d, i) => [d, it.series[key][i]] as [string, number]).filter(([d]) => d >= wa && d <= wb)
    const base = pts[0]?.[1] || 1
    return pts.map(([d, v]) => [d, +(v / base).toFixed(4)])
  }
  const rows = items.map(it => ({ ...it.metrics, run_id: it.run_id, name: it.name, params: it.params }))
  const years = Array.from(new Set(items.flatMap(it => it.yearly.map(y => y.year)))).sort()
    .filter(y => `${y}-12-31` >= wa && `${y}-01-01` <= wb)
  return (
    <div className="space-y-4">
      <Card title={`策略对比 · ${items.length} 个`} extra={<div className="flex items-center gap-2">
        <TimeRange value={win} onChange={setWin} presets={['1Y', '3Y', '5Y', 'ALL']} />
        <Button variant="ghost" onClick={onClose}>返回</Button></div>}>
        <Chart height={400} option={{
          legend: { data: [...items.map(i => i.name), '沪深300'] },
          xAxis: { type: 'time', ...axisStyle(c), splitLine: { show: false } },
          yAxis: { type: 'value', scale: true, ...axisStyle(c) },
          dataZoom: [{ type: 'inside' }],
          tooltip: { trigger: 'axis', valueFormatter: (v: any) => (typeof v === 'number' ? v.toFixed(3) : '—') },
          series: [
            ...items.map((it, k) => ({
              name: it.name, type: 'line' as const, showSymbol: false, data: cut(it, 'nav'),
              lineStyle: { width: 2, color: c.series[k % c.series.length] }, itemStyle: { color: c.series[k % c.series.length] },
            })),
            { name: '沪深300', type: 'line', showSymbol: false, data: cut(items[0], 'bench'),
              lineStyle: { width: 1.2, color: c.faint, type: 'dashed' }, itemStyle: { color: c.faint } },
          ],
        }} />
      </Card>
      <Card title="指标对比">
        <DataTable rowKey="run_id" rows={rows} cols={[
          { key: 'name', label: '策略', render: r => <div><div className="font-medium">{r.name}</div>
            <div className="text-[11px] text-faint">{r.params.factors.map((f: FactorIn) => factorLabel(meta, f.name)).join(' + ')} · {UNIV_SHORT[r.params.universe ?? 'core'] ?? ''}</div></div> },
          { key: 'annual_return', label: '年化', align: 'right', render: r => <span className={trendClass(r.annual_return)}>{ratio(r.annual_return, 2, true)}</span> },
          { key: 'excess_annual', label: '年化超额', align: 'right', render: r => <span className={trendClass(r.excess_annual)}>{ratio(r.excess_annual, 2, true)}</span> },
          { key: 'sharpe', label: '夏普', align: 'right', render: r => fmt(r.sharpe) },
          { key: 'max_drawdown', label: '最大回撤', align: 'right', render: r => <span className="text-down">{ratio(r.max_drawdown, 1)}</span> },
          { key: 'calmar', label: '卡玛', align: 'right', render: r => fmt(r.calmar) },
          { key: 'info_ratio', label: '信息比率', align: 'right', render: r => fmt(r.info_ratio) },
          { key: 'monthly_win_rate', label: '月胜率', align: 'right', render: r => ratio(r.monthly_win_rate, 0) },
          { key: 'avg_turnover', label: '换手', align: 'right', render: r => ratio(r.avg_turnover, 0) },
          { key: 'start', label: '区间', align: 'right', render: r => <span className="text-[12px] text-faint">{r.start} ~ {r.end}</span> },
        ]} />
      </Card>
      <Card title="年度收益对比">
        <Chart height={300} option={{
          legend: { data: items.map(i => i.name) },
          xAxis: { type: 'category', data: years.map(String), ...axisStyle(c), splitLine: { show: false } },
          yAxis: { type: 'value', ...axisStyle(c), axisLabel: { formatter: '{value}%', color: c.faint, fontSize: 11 } },
          tooltip: { trigger: 'axis', valueFormatter: (v: any) => (typeof v === 'number' ? `${v.toFixed(2)}%` : '—') },
          series: items.map((it, k) => ({
            name: it.name, type: 'bar' as const, barMaxWidth: 12,
            itemStyle: { color: c.series[k % c.series.length], borderRadius: 3 },
            data: years.map(y => { const v = it.yearly.find(x => x.year === y)?.ret; return v == null ? null : +(v * 100).toFixed(2) }),
          })),
        }} />
      </Card>
    </div>
  )
}

function MetricCard({ label, value, cls, sub }: { label: string; value: string; cls?: string; sub?: string }) {
  return (
    <div className="card px-4 py-3.5">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`num mt-1 text-[22px] font-semibold ${cls ?? ''}`}>{value}</div>
      {sub && <div className="text-[11px] text-faint">{sub}</div>}
    </div>
  )
}

function Results({ r }: { r: Result }) {
  const c = useColors()
  const nav = useNavigate()
  const m = r.metrics
  const [win, setWin] = useState<Win>({ preset: 'ALL' })
  const w = sliceWindow(r.series.dates, { nav: r.series.nav, bench: r.series.bench }, win, ['nav', 'bench'])
  const dd = drawdown(w.series.nav)
  const last = r.series.dates[r.series.dates.length - 1] ?? ''
  const [wa, wb] = windowBounds(win, last)
  const inWin = (y: number, mth = 12) => `${y}-${String(mth).padStart(2, '0')}-31` >= wa && `${y}-${String(mth).padStart(2, '0')}-01` <= wb
  const navEnd = w.series.nav[w.series.nav.length - 1], benchEnd = w.series.bench[w.series.bench.length - 1]
  const yearly = r.yearly.filter(y => inWin(y.year))
  const monthly = r.monthly.filter(x => inWin(x.year, x.month))
  const years = Array.from(new Set(monthly.map(x => x.year)))
  const heat = monthly.map(x => [x.month - 1, years.indexOf(x.year), x.ret == null ? null : +(x.ret * 100).toFixed(2)])
  const maxAbs = Math.max(5, ...heat.map(h => Math.abs((h[2] as number) ?? 0)))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="年化收益" value={ratio(m.annual_return, 2, true)} cls={trendClass(m.annual_return)} sub={`基准 ${ratio(m.bench_annual_return, 2, true)}`} />
        <MetricCard label="年化超额" value={ratio(m.excess_annual, 2, true)} cls={trendClass(m.excess_annual)} sub={`信息比率 ${fmt(m.info_ratio)}`} />
        <MetricCard label="夏普比率" value={fmt(m.sharpe)} sub={`年化波动 ${ratio(m.annual_vol, 1)}`} />
        <MetricCard label="最大回撤" value={ratio(m.max_drawdown, 2)} cls="text-down" sub={`${m.max_dd_start} → ${m.max_dd_end}`} />
        <MetricCard label="累计收益" value={ratio(m.total_return, 1, true)} cls={trendClass(m.total_return)} sub={`${m.start} ~ ${m.end}`} />
        <MetricCard label="卡玛比率" value={fmt(m.calmar)} sub={`基准最大回撤 ${ratio(m.bench_max_drawdown, 1)}`} />
        <MetricCard label="月度胜率(vs 基准)" value={ratio(m.monthly_win_rate, 1)} />
        <MetricCard label="平均单边换手" value={ratio(m.avg_turnover, 1)} sub={`调仓 ${r.n_rebalance} 次`} />
      </div>

      <Card title="净值曲线" extra={<div className="flex items-center gap-3">
        {win.preset !== 'ALL' && navEnd != null && <span className="num text-[12px] text-faint">
          区间 策略 <span className={trendClass(navEnd - 1)}>{ratio(navEnd - 1, 1, true)}</span> · 基准 <span className={trendClass((benchEnd ?? 1) - 1)}>{ratio((benchEnd ?? 1) - 1, 1, true)}</span>
          · 回撤 <span className="text-down">{ratio(Math.min(...dd.map(x => x ?? 0)), 1)}</span></span>}
        <TimeRange value={win} onChange={setWin} presets={['6M', 'YTD', '1Y', '3Y', '5Y', 'ALL']} />
      </div>}>
        <Chart height={420} option={{
          axisPointer: { link: [{ xAxisIndex: 'all' }] },
          legend: { data: ['策略', '基准', '回撤'] },
          grid: [{ left: 8, right: 16, top: 32, height: '60%', containLabel: true }, { left: 8, right: 16, top: '76%', height: '18%', containLabel: true }],
          xAxis: [
            { type: 'category', data: w.dates, ...axisStyle(c), splitLine: { show: false }, axisLabel: { show: false } },
            { type: 'category', data: w.dates, gridIndex: 1, ...axisStyle(c), splitLine: { show: false } },
          ],
          yAxis: [{ type: 'value', scale: true, ...axisStyle(c) },
            { type: 'value', gridIndex: 1, ...axisStyle(c), splitNumber: 2, axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%`, color: c.faint, fontSize: 11 } }],
          dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
          series: [
            { name: '策略', type: 'line', data: w.series.nav, showSymbol: false, lineStyle: { width: 2, color: c.accent }, itemStyle: { color: c.accent } },
            { name: '基准', type: 'line', data: w.series.bench, showSymbol: false, lineStyle: { width: 1.4, color: c.faint }, itemStyle: { color: c.faint } },
            { name: '回撤', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: dd, showSymbol: false,
              lineStyle: { width: 1, color: c.down }, itemStyle: { color: c.down }, areaStyle: { color: c.down, opacity: 0.15 } },
          ],
        }} />
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="年度收益">
          <Chart height={300} option={{
            xAxis: { type: 'category', data: yearly.map(y => String(y.year)), ...axisStyle(c), splitLine: { show: false } },
            yAxis: { type: 'value', ...axisStyle(c), axisLabel: { formatter: '{value}%', color: c.faint, fontSize: 11 } },
            series: [
              { name: '策略', type: 'bar', barMaxWidth: 16, data: yearly.map(y => ({ value: y.ret == null ? null : +(y.ret * 100).toFixed(2), itemStyle: { color: c.accent, borderRadius: 3 } })) },
              { name: '基准', type: 'bar', barMaxWidth: 16, data: yearly.map(y => ({ value: y.bench == null ? null : +(y.bench * 100).toFixed(2), itemStyle: { color: c.faint, borderRadius: 3 } })) },
            ],
          }} />
        </Card>
        <Card title="月度收益热力图（%）">
          <Chart height={300} option={{
            tooltip: { trigger: 'item', formatter: (p: any) => `${years[p.value[1]]}年${p.value[0] + 1}月：${p.value[2]}%` },
            grid: { left: 8, right: 8, top: 8, bottom: 40, containLabel: true },
            xAxis: { type: 'category', data: Array.from({ length: 12 }, (_, i) => `${i + 1}月`), ...axisStyle(c), splitLine: { show: false } },
            yAxis: { type: 'category', data: years.map(String), ...axisStyle(c), splitLine: { show: false } },
            visualMap: { min: -maxAbs, max: maxAbs, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 120, itemWidth: 10,
              inRange: { color: [c.down, c.surface2, c.up] }, textStyle: { color: c.faint, fontSize: 11 } },
            series: [{ type: 'heatmap', data: heat, label: { show: true, fontSize: 9, color: c.text }, itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 3 } }],
          }} />
        </Card>
      </div>

      <Card title={`最新持仓 · ${r.holdings.stocks.length} 只`} extra={<span className="text-[12px] text-faint">调仓日 {r.holdings.date}</span>}>
        <div className="flex flex-wrap gap-2">
          {r.holdings.stocks.map(s => (
            <button key={s.code} onClick={() => nav(`/stock/${s.code}`)} className="cursor-pointer rounded-lg border border-line px-2.5 py-1.5 text-left text-[12px] hover:border-accent">
              <span className="font-medium">{s.name}</span> <span className="num text-faint">{shortCode(s.code)}</span>
              <div className="text-[11px] text-faint">{s.industry ?? '—'}</div>
            </button>
          ))}
        </div>
      </Card>
    </div>
  )
}

export default function Backtest() {
  const { meta } = useMeta()
  const [sp] = useSearchParams()
  const pools = useFetch<Pool[]>('/api/pools')
  const history = useFetch<Row[]>('/api/backtests')
  const [name, setName] = useState('价值+质量')
  const [factors, setFactors] = useState<FactorIn[]>(TEMPLATES[0].factors)
  const [poolId, setPoolId] = useState(sp.get('pool') ?? '')
  const [topN, setTopN] = useState(30)
  const [freq, setFreq] = useState<'M' | 'W' | 'Q'>('M')
  const [universe, setUniverse] = useState('all')
  const [neutral, setNeutral] = useState<string[]>([])
  const [expr, setExpr] = useState('')
  const [minAmount, setMinAmount] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [cmp, setCmp] = useState<CompareItem[] | null>(null)
  const [start, setStart] = useState('2015-01-01')
  const [bench, setBench] = useState('sh.000300')
  const [slip, setSlip] = useState(0.1)
  const [res, setRes] = useState<Result | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await api.post<Result>('/api/backtest', {
        name, factors, pool_id: poolId || null, top_n: topN, freq, start, benchmark: bench, slippage: slip / 100,
        universe, neutralize: neutral, expr: expr.trim() || null, min_amount: minAmount,
      })
      setRes(r); setCmp(null); history.reload()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const load = async (id: string) => {
    setBusy(true); setErr(null)
    try { setRes(await api.get<Result>(`/api/backtests/${id}`)); setCmp(null) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const compare = async () => {
    setBusy(true); setErr(null)
    try { setCmp(await api.get<CompareItem[]>(`/api/backtests/compare?ids=${selected.join(',')}`)) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const remove = async (id: string) => {
    await api.del(`/api/backtests/${id}`)
    setSelected(s => s.filter(x => x !== id)); history.reload()
  }
  const toggle = (id: string) => setSelected(s => (s.includes(id) ? s.filter(x => x !== id) : s.length >= 8 ? s : [...s, id]))

  return (
    <>
      <PageHeader eyebrow="Factor Backtest" title="因子回测"
        desc="信号日收盘打分选 Top N，次日开盘等权调仓；按当时的历史成分股与 ST 状态选股，含退市股；计入佣金、印花税、滑点，处理停牌与一字涨跌停" />
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <Card title="策略配置">
            <div className="space-y-4">
              <Field label="策略名称"><input className="field" value={name} onChange={e => setName(e.target.value)} /></Field>
              <div>
                <div className="mb-1.5 text-[12px] font-medium text-muted">模板</div>
                <div className="flex flex-wrap gap-1.5">
                  {TEMPLATES.map(t => (
                    <button key={t.name} onClick={() => { setFactors(t.factors); setName(t.name) }}
                      className="cursor-pointer rounded-md border border-line px-2.5 py-1 text-[12px] hover:border-accent hover:text-accent-text">{t.name}</button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-[12px] font-medium text-muted">因子（权重 · 方向）</span>
                  <button className="cursor-pointer text-[12px] text-accent-text" onClick={() => setFactors(f => [...f, { name: 'roe_ann', weight: 1, direction: 'high' }])}>+ 添加</button>
                </div>
                <div className="space-y-2">
                  {factors.map((f, i) => (
                    <div key={i} className="grid grid-cols-[1fr_56px_74px_18px] items-center gap-1.5">
                      <FactorSelect value={f.name}
                        onChange={v => setFactors(fs => fs.map((x, j) => (j === i ? { ...x, name: v, direction: meta!.factors[v].better } : x)))} />
                      <input className="field num min-w-0 px-2" type="number" step="0.5" value={f.weight}
                        onChange={e => setFactors(fs => fs.map((x, j) => (j === i ? { ...x, weight: +e.target.value } : x)))} />
                      <select className="field min-w-0 px-1.5" value={f.direction}
                        onChange={e => setFactors(fs => fs.map((x, j) => (j === i ? { ...x, direction: e.target.value as 'high' | 'low' } : x)))}>
                        <option value="high">大↑优</option><option value="low">小↓优</option>
                      </select>
                      <button className="cursor-pointer text-faint hover:text-up" onClick={() => setFactors(fs => fs.filter((_, j) => j !== i))}>×</button>
                    </div>
                  ))}
                </div>
              </div>
              <Field label="股票池（按信号日的历史成分）"><UniverseSelect value={universe} onChange={setUniverse} /></Field>
              <Field label="附加选股条件（已保存的股票池规则）">
                <select className="field" value={poolId} onChange={e => setPoolId(e.target.value)}>
                  <option value="">无</option>
                  {pools.data?.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
                </select>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="持仓数量 Top N"><input className="field num" type="number" min={1} max={200} value={topN} onChange={e => setTopN(+e.target.value)} /></Field>
                <Field label="开始日期"><input className="field num" type="date" value={start} onChange={e => setStart(e.target.value)} /></Field>
                <Field label="业绩基准">
                  <select className="field" value={bench} onChange={e => setBench(e.target.value)}>
                    {meta && Object.entries(meta.benchmarks).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </Field>
                <Field label="单边滑点 %"><input className="field num" type="number" step="0.05" value={slip} onChange={e => setSlip(+e.target.value)} /></Field>
                <Field label="最低日均成交额(亿)" className="col-span-2"><input className="field num" type="number" step="0.1" min={0} value={minAmount} onChange={e => setMinAmount(+e.target.value)} /></Field>
              </div>
              <Field label="过滤公式（可选，结果为真的股票入池）">
                <FormulaInput value={expr} onChange={setExpr} placeholder="例如：(roe_ann > 8) and (dividend_yield > 2)" />
              </Field>
              <div className="flex items-center justify-between gap-2">
                <span className="text-[12px] font-medium text-muted">因子中性化</span>
                <NeutralToggle value={neutral} onChange={setNeutral} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-muted">调仓频率</span>
                <Segmented value={freq} onChange={setFreq} options={[{ value: 'W', label: '周度' }, { value: 'M', label: '月度' }, { value: 'Q', label: '季度' }]} />
              </div>
              <Button className="w-full" onClick={run} disabled={busy || !factors.length}>{busy ? '回测中…' : '运行回测'}</Button>
            </div>
          </Card>
          <Card title="历史回测" extra={<Button variant="ghost" className="h-7 px-2.5 text-[12px]" disabled={selected.length < 2 || busy} onClick={compare}>
              对比{selected.length ? ` ${selected.length} 个` : ''}</Button>}>
            {history.data?.length ? (
              <ul className="max-h-[520px] divide-y divide-line overflow-auto">
                {history.data.map(h => (
                  <li key={h.run_id} className="group flex items-center gap-2 py-2">
                    <input type="checkbox" className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--accent)]" checked={selected.includes(h.run_id)} onChange={() => toggle(h.run_id)} title="勾选以对比" />
                    <button onClick={() => load(h.run_id)} className={cx('flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 text-left', res?.run_id === h.run_id && 'text-accent-text')}>
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium">{h.name}</div>
                        <div className="truncate text-[11px] text-faint">
                          {h.params.factors.map((f: FactorIn) => factorLabel(meta, f.name)).join(' + ')} · Top{h.params.top_n} · {({ W: '周', M: '月', Q: '季' } as Record<string, string>)[h.params.freq] ?? '月'} · {UNIV_SHORT[h.params.universe ?? 'core']}
                          {h.params.neutralize?.length ? ' · 中性' : ''}
                        </div>
                      </div>
                      <Badge tone={h.metrics.excess_annual > 0 ? 'up' : 'down'}><span className="num">{ratio(h.metrics.annual_return, 1, true)}</span></Badge>
                    </button>
                    <button className="cursor-pointer px-1 text-faint opacity-0 transition group-hover:opacity-100 hover:text-up" title="删除" onClick={() => remove(h.run_id)}>×</button>
                  </li>
                ))}
              </ul>
            ) : <div className="text-[13px] text-faint">暂无</div>}
          </Card>
        </div>
        <div className="min-w-0">
          {err && <div className="mb-4"><ErrorBox error={err} /></div>}
          {cmp ? <CompareView items={cmp} onClose={() => setCmp(null)} />
            : busy && !res ? <Card><Loading text="回测运行中（首次需加载全市场价格面板，约 20–40 秒）…" /></Card>
            : res ? <Results r={res} />
            : <Card><Empty text="配置策略后点击「运行回测」" /></Card>}
        </div>
      </div>
    </>
  )
}
