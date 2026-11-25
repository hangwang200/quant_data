import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, Segmented } from '../components/ui'
import { Chart, axisStyle } from '../components/Chart'
import { DataTable, type Col } from '../components/DataTable'
import { FactorSelect, NeutralToggle, UniverseSelect } from '../components/FactorSelect'
import { Spark } from '../components/Spark'
import { TimeRange, sliceWindow, type Win } from '../components/TimeRange'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { factorLabel, useMeta } from '../lib/meta'
import { useColors } from '../lib/theme'
import { fmt, isNum, ratio, trendClass } from '../lib/format'
import type { Pool } from './Screener'

type Tab = 'board' | 'single' | 'corr'
interface Common { universe: string; start: string; freq: 'W' | 'M' | 'Q'; neutralize: string[] }
interface Single {
  factor: string; label: string; groups: number
  stats: Record<string, any>
  ic: { dates: string[]; values: (number | null)[]; cum: (number | null)[]; ma12: (number | null)[] }
  quantiles: { dates: string[]; nav: Record<string, (number | null)[]>; long_short: (number | null)[]; universe: (number | null)[]; annual: (number | null)[] }
  decay: { lag: number; ic: number | null }[]
  yearly: { year: number; ic: number | null; ls_return: number | null; top_return: number | null }[]
}
interface Corr { factors: string[]; labels: string[]; matrix: (number | null)[][]; samples: number }

const FREQ = [{ value: 'W' as const, label: '周' }, { value: 'M' as const, label: '月' }, { value: 'Q' as const, label: '季' }]
const DEFAULT_CORR = ['ep', 'bp', 'dividend_yield', 'roe_ann', 'gross_margin', 'revenue_yoy', 'mom_20', 'mom_12_1', 'vol_60', 'turnover_20', 'float_mv', 'beta_60']

/** 从浅到深的单色相序列（G1 最浅 = 最差，GN 最深 = 最好） */
function ramp(n: number, dark: boolean) {
  const out: string[] = []
  for (let i = 0; i < n; i++) {
    const t = n === 1 ? 1 : i / (n - 1)
    const l = dark ? 38 + t * 40 : 82 - t * 50
    out.push(`hsl(229 ${dark ? 85 : 66}% ${l}%)`)
  }
  return out
}

function StatTile({ label, value, cls, sub }: { label: string; value: string; cls?: string; sub?: string }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`num mt-0.5 text-[20px] font-semibold ${cls ?? ''}`}>{value}</div>
      {sub && <div className="text-[11px] text-faint">{sub}</div>}
    </div>
  )
}

function irTone(v: number | null | undefined): 'up' | 'down' | 'neutral' {
  if (!isNum(v)) return 'neutral'
  return Math.abs(v) >= 0.5 ? (v > 0 ? 'up' : 'down') : 'neutral'
}

// ---------------- 因子看板 ----------------
function Board({ common, onPick }: { common: Common; onPick: (f: string) => void }) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const key = JSON.stringify(common)
  useEffect(() => {
    let alive = true
    setBusy(true); setErr(null)
    api.post<Row[]>('/api/analysis/scoreboard', common)
      .then(r => alive && setRows(r)).catch(e => alive && setErr(e.message)).finally(() => alive && setBusy(false))
    return () => { alive = false }
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const cols: Col[] = [
    { key: 'label', label: '因子', render: r => <div><div className="font-medium">{r.label}</div><div className="text-[11px] text-faint">{r.factor} · {r.better === 'high' ? '越大越好' : '越小越好'}</div></div> },
    { key: 'group', label: '类别', render: r => <Badge>{r.group}</Badge> },
    { key: 'ic_mean', label: 'IC 均值', align: 'right', render: r => <span className={trendClass(r.ic_mean)}>{fmt(r.ic_mean, 3)}</span> },
    { key: 'ir_annual', label: '年化 ICIR', align: 'right', render: r => <Badge tone={irTone(r.ir_annual)}><span className="num">{fmt(r.ir_annual, 2)}</span></Badge> },
    { key: 'ic_positive', label: 'IC>0 占比', align: 'right', render: r => ratio(r.ic_positive, 0) },
    { key: 't_stat', label: 't 值', align: 'right', render: r => <span className={isNum(r.t_stat) && Math.abs(r.t_stat) >= 2 ? 'font-semibold' : 'text-muted'}>{fmt(r.t_stat, 2)}</span> },
    { key: 'ls_annual', label: '多空年化', align: 'right', render: r => <span className={trendClass(r.ls_annual)}>{ratio(r.ls_annual, 1, true)}</span> },
    { key: 'spark', label: '累计 IC', sortable: false, render: r => <Spark values={r.spark} /> },
  ]
  return (
    <Card title="全因子看板" extra={<span className="text-[12px] text-faint">方向已按"越大越好"调整：IC 为正说明默认方向有效 · 点击行查看详情</span>}>
      {err && <ErrorBox error={err} />}
      {busy ? <Loading text="计算全部因子的 IC（首次约 10–40 秒，之后有缓存）…" />
        : rows && <DataTable cols={cols} rows={rows} rowKey="factor" maxHeight={720} onRowClick={r => onPick(r.factor)} />}
    </Card>
  )
}

// ---------------- 单因子 ----------------
function SingleView({ r }: { r: Single }) {
  const c = useColors()
  const s = r.stats
  const G = r.groups
  const colors = ramp(G, c.mode === 'dark')
  const qNames = Object.keys(r.quantiles.nav)
  const [win, setWin] = useState<Win>({ preset: 'ALL' })
  const icw = sliceWindow(r.ic.dates, { values: r.ic.values, ma12: r.ic.ma12 }, win)
  let acc = 0
  const icCum = icw.series.values.map(v => +(acc += v ?? 0).toFixed(4))
  const qSeries: Record<string, (number | null)[]> = { ...r.quantiles.nav, __ls: r.quantiles.long_short, __u: r.quantiles.universe }
  const qw = sliceWindow(r.quantiles.dates, qSeries, win,
    [...qNames, '__ls', '__u'])
  const range = <TimeRange value={win} onChange={setWin} presets={['1Y', '3Y', '5Y', 'ALL']} />
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Rank IC 均值" value={fmt(s.ic_mean, 4)} cls={trendClass(s.ic_mean)} sub={`标准差 ${fmt(s.ic_std, 3)}`} />
        <StatTile label="年化 ICIR" value={fmt(s.ir_annual, 2)} sub={`单期 IR ${fmt(s.ir, 3)}`} />
        <StatTile label="IC>0 占比" value={ratio(s.ic_positive, 1)} sub={`t 值 ${fmt(s.t_stat, 2)}`} />
        <StatTile label="多空年化" value={ratio(s.ls_annual, 2, true)} cls={trendClass(s.ls_annual)} sub={`夏普 ${fmt(s.ls_sharpe, 2)} · 回撤 ${ratio(s.ls_max_drawdown, 1)}`} />
        <StatTile label={`G${G} 超额(vs 池内等权)`} value={ratio(s.top_excess, 2, true)} cls={trendClass(s.top_excess)} sub={`G${G} 年化 ${ratio(s.top_annual, 1)}`} />
        <StatTile label="单调性" value={fmt(s.monotonicity, 2)} sub={`G${G} 换手 ${ratio(s.top_turnover, 0)} · 覆盖 ${fmt(s.avg_coverage, 0)} 只`} />
      </div>

      <Card title="IC 序列" extra={<div className="flex items-center gap-3"><span className="text-[12px] text-faint">{s.start} ~ {s.end} · {s.periods} 期</span>{range}</div>}>
        <Chart height={380} option={{
          axisPointer: { link: [{ xAxisIndex: 'all' }] },
          legend: { data: ['单期 IC', '12 期均值', '累计 IC'] },
          grid: [{ left: 8, right: 16, top: 32, height: '46%', containLabel: true }, { left: 8, right: 16, top: '66%', height: '26%', containLabel: true }],
          xAxis: [
            { type: 'category', data: icw.dates, ...axisStyle(c), splitLine: { show: false }, axisLabel: { show: false } },
            { type: 'category', data: icw.dates, gridIndex: 1, ...axisStyle(c), splitLine: { show: false } },
          ],
          yAxis: [{ type: 'value', ...axisStyle(c), name: 'IC', nameTextStyle: { color: c.faint, fontSize: 11 } },
            { type: 'value', gridIndex: 1, ...axisStyle(c), name: '累计', nameTextStyle: { color: c.faint, fontSize: 11 } }],
          dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
          tooltip: { trigger: 'axis', valueFormatter: (v: any) => (isNum(v) ? v.toFixed(3) : '—') },
          series: [
            { name: '单期 IC', type: 'bar', barMaxWidth: 6, data: icw.series.values.map(v => ({ value: v, itemStyle: { color: (v ?? 0) >= 0 ? c.up : c.down, borderRadius: 2 } })) },
            { name: '12 期均值', type: 'line', data: icw.series.ma12, showSymbol: false, lineStyle: { width: 2, color: c.text }, itemStyle: { color: c.text } },
            { name: '累计 IC', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: icCum, showSymbol: false,
              lineStyle: { width: 2, color: c.accent }, itemStyle: { color: c.accent }, areaStyle: { color: c.accent, opacity: 0.08 } },
          ],
        }} />
      </Card>

      <Card title={`分层回测 · ${G} 组`} extra={<div className="flex items-center gap-3"><span className="text-[12px] text-faint">G1 最差 → G{G} 最好 · 等权 · 不计成本</span>{range}</div>}>
        <Chart height={380} option={{
          legend: { data: [...qNames, '多空', '池内等权'] },
          xAxis: { type: 'category', data: qw.dates, ...axisStyle(c), splitLine: { show: false } },
          yAxis: { type: 'value', scale: true, ...axisStyle(c) },
          dataZoom: [{ type: 'inside' }],
          tooltip: { trigger: 'axis', valueFormatter: (v: any) => (isNum(v) ? v.toFixed(3) : '—') },
          series: [
            ...qNames.map((g, i) => ({
              name: g, type: 'line' as const, data: qw.series[g], showSymbol: false,
              lineStyle: { width: i === G - 1 || i === 0 ? 2 : 1.4, color: colors[i] }, itemStyle: { color: colors[i] },
              endLabel: i === G - 1 || i === 0 ? { show: true, formatter: g, color: c.muted, fontSize: 11 } : undefined,
            })),
            { name: '多空', type: 'line', data: qw.series.__ls, showSymbol: false, lineStyle: { width: 2, color: c.series[1], type: 'dashed' }, itemStyle: { color: c.series[1] } },
            { name: '池内等权', type: 'line', data: qw.series.__u, showSymbol: false, lineStyle: { width: 1.2, color: c.faint }, itemStyle: { color: c.faint } },
          ],
          grid: { left: 8, right: 40, top: 36, bottom: 8, containLabel: true },
        }} />
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="各组年化收益" extra={<span className="text-[12px] text-faint">全区间</span>}>
          <Chart height={260} option={{
            xAxis: { type: 'category', data: qNames, ...axisStyle(c), splitLine: { show: false } },
            yAxis: { type: 'value', ...axisStyle(c), axisLabel: { formatter: '{value}%', color: c.faint, fontSize: 11 } },
            tooltip: { trigger: 'item', valueFormatter: (v: any) => (isNum(v) ? `${v.toFixed(2)}%` : '—') },
            series: [{ type: 'bar', name: '年化', barMaxWidth: 36,
              data: r.quantiles.annual.map((v, i) => ({ value: v == null ? null : +(v * 100).toFixed(2), itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] } })),
              label: { show: true, position: 'top', color: c.muted, fontSize: 11, formatter: (p: any) => `${p.value}%` } }],
          }} />
        </Card>
        <Card title="IC 衰减" extra={<span className="text-[12px] text-faint">因子对第 k 期之后收益的 IC</span>}>
          <Chart height={260} option={{
            xAxis: { type: 'category', data: r.decay.map(d => `+${d.lag}`), ...axisStyle(c), splitLine: { show: false } },
            yAxis: { type: 'value', ...axisStyle(c) },
            tooltip: { trigger: 'item', valueFormatter: (v: any) => (isNum(v) ? v.toFixed(4) : '—') },
            series: [{ type: 'bar', name: 'IC', barMaxWidth: 32,
              data: r.decay.map(d => ({ value: d.ic, itemStyle: { color: (d.ic ?? 0) >= 0 ? c.up : c.down, borderRadius: 4 } })),
              label: { show: true, position: 'top', color: c.muted, fontSize: 11, formatter: (p: any) => (isNum(p.value) ? p.value.toFixed(3) : '') } }],
          }} />
        </Card>
      </div>

      <Card title="分年度表现">
        <DataTable rowKey="year" maxHeight={420} rows={r.yearly as Row[]} cols={[
          { key: 'year', label: '年份' },
          { key: 'ic', label: 'IC 均值', align: 'right', render: x => <span className={trendClass(x.ic)}>{fmt(x.ic, 4)}</span> },
          { key: 'top_return', label: `G${G} 收益`, align: 'right', render: x => <span className={trendClass(x.top_return)}>{ratio(x.top_return, 1, true)}</span> },
          { key: 'ls_return', label: '多空收益', align: 'right', render: x => <span className={trendClass(x.ls_return)}>{ratio(x.ls_return, 1, true)}</span> },
        ]} />
      </Card>
    </div>
  )
}

function SingleTab({ common, factor, setFactor }: { common: Common; factor: string; setFactor: (f: string) => void }) {
  const { meta } = useMeta()
  const pools = useFetch<Pool[]>('/api/pools')
  const [groups, setGroups] = useState(5)
  const [direction, setDirection] = useState<string>('')
  const [poolId, setPoolId] = useState('')
  const [minAmount, setMinAmount] = useState(0)
  const [res, setRes] = useState<Single | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true); setErr(null)
    try {
      setRes(await api.post<Single>('/api/analysis/factor', {
        ...common, factor, groups, direction: direction || null, pool_id: poolId || null, min_amount: minAmount,
      }))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  useEffect(() => { if (meta?.ready) run() }, [factor, JSON.stringify(common)]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="因子" className="w-[220px]"><FactorSelect value={factor} onChange={setFactor} /></Field>
          <Field label="方向" className="w-[160px]">
            <select className="field" value={direction} onChange={e => setDirection(e.target.value)}>
              <option value="">默认（{meta?.factors[factor]?.better === 'low' ? '越小越好' : '越大越好'}）</option>
              <option value="high">越大越好</option><option value="low">越小越好</option>
            </select>
          </Field>
          <Field label="分组数" className="w-[90px]"><input className="field num" type="number" min={2} max={10} value={groups} onChange={e => setGroups(+e.target.value)} /></Field>
          <Field label="附加股票池条件" className="w-[180px]">
            <select className="field" value={poolId} onChange={e => setPoolId(e.target.value)}>
              <option value="">无</option>
              {pools.data?.map(p => <option key={p.pool_id} value={p.pool_id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="最低日均成交额(亿)" className="w-[140px]"><input className="field num" type="number" step="0.1" min={0} value={minAmount} onChange={e => setMinAmount(+e.target.value)} /></Field>
          <Button onClick={run} disabled={busy}>{busy ? '计算中…' : '分析'}</Button>
        </div>
        {meta?.factors[factor]?.expr && <div className="mt-3 text-[12px] text-faint">公式：<code className="font-mono text-muted">{meta.factors[factor].expr}</code></div>}
      </Card>
      {err && <ErrorBox error={err} />}
      {busy && !res ? <Card><Loading text="计算 IC 与分层收益…" /></Card> : res ? <SingleView r={res} /> : <Card><Empty text="选择因子后点击「分析」" /></Card>}
    </div>
  )
}

// ---------------- 相关性 ----------------
function CorrTab({ common }: { common: Common }) {
  const c = useColors()
  const { meta } = useMeta()
  const [names, setNames] = useState<string[]>(DEFAULT_CORR)
  const [res, setRes] = useState<Corr | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true); setErr(null)
    try { setRes(await api.post<Corr>('/api/analysis/correlation', { factors: names, universe: common.universe, start: common.start })) }
    catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  useEffect(() => { if (meta?.ready) run() }, [common.universe, common.start]) // eslint-disable-line react-hooks/exhaustive-deps
  const data = useMemo(() => res ? res.matrix.flatMap((row, i) => row.map((v, j) => [j, i, v == null ? null : +v.toFixed(2)])) : [], [res])
  const n = res?.labels.length ?? 0
  return (
    <div className="space-y-4">
      <Card title="选择因子" extra={<Button onClick={run} disabled={busy || names.length < 2}>{busy ? '计算中…' : '计算相关性'}</Button>}>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(meta?.factors ?? {}).map(([k, f]) => {
            const on = names.includes(k)
            return (
              <button key={k} onClick={() => setNames(x => (on ? x.filter(y => y !== k) : [...x, k]))}
                className={`cursor-pointer rounded-md border px-2 py-1 text-[12px] transition ${on ? 'border-accent bg-accent-soft text-accent-text' : 'border-line text-muted hover:text-text'}`}>
                {f.label}
              </button>
            )
          })}
        </div>
      </Card>
      {err && <ErrorBox error={err} />}
      <Card title="截面 Spearman 相关系数（时间均值）" extra={res && <span className="text-[12px] text-faint">抽样 {res.samples} 个截面 · 未做方向调整</span>}>
        {busy && !res ? <Loading /> : !res ? <Empty text="选择至少 2 个因子" /> : (
          <Chart height={Math.max(360, n * 34 + 120)} option={{
            tooltip: { trigger: 'item', formatter: (p: any) => `${res.labels[p.value[1]]} × ${res.labels[p.value[0]]}<br/><b>${p.value[2]}</b>` },
            grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
            xAxis: { type: 'category', data: res.labels, ...axisStyle(c), splitLine: { show: false }, axisLabel: { color: c.muted, fontSize: 11, rotate: 40, interval: 0 } },
            yAxis: { type: 'category', data: res.labels, inverse: true, ...axisStyle(c), splitLine: { show: false }, axisLabel: { color: c.muted, fontSize: 11 } },
            visualMap: { min: -1, max: 1, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemHeight: 160, itemWidth: 10,
              inRange: { color: [c.down, c.surface2, c.up] }, textStyle: { color: c.faint, fontSize: 11 } },
            series: [{ type: 'heatmap', data, label: { show: n <= 16, fontSize: 10, color: c.text },
              itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 3 } }],
          }} />
        )}
      </Card>
    </div>
  )
}

export default function Analysis() {
  const { meta } = useMeta()
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('tab') as Tab) || 'board'
  const factor = sp.get('factor') || 'ep'
  const [common, setCommon] = useState<Common>({ universe: 'all', start: '2015-01-01', freq: 'M', neutralize: [] })
  const set = (k: Record<string, string>) => setSp(p => { const n = new URLSearchParams(p); Object.entries(k).forEach(([a, b]) => n.set(a, b)); return n })
  return (
    <>
      <PageHeader eyebrow="Factor Analysis" title="因子分析"
        desc="Rank IC / ICIR、分层回测、IC 衰减与因子相关性；信号日收盘计算因子，前瞻收益为到下一信号日的后复权收益"
        right={<Segmented value={tab} onChange={v => set({ tab: v })} options={[
          { value: 'board', label: '因子看板' }, { value: 'single', label: '单因子' }, { value: 'corr', label: '相关性' }]} />} />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="股票池" className="w-[220px]"><UniverseSelect value={common.universe} onChange={v => setCommon(c => ({ ...c, universe: v }))} /></Field>
          <Field label="开始日期" className="w-[150px]"><input className="field num" type="date" value={common.start} onChange={e => setCommon(c => ({ ...c, start: e.target.value }))} /></Field>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted">调仓频率</span>
            <Segmented value={common.freq} onChange={v => setCommon(c => ({ ...c, freq: v }))} options={FREQ} />
          </div>
          {tab !== 'corr' && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[12px] font-medium text-muted">中性化</span>
              <NeutralToggle value={common.neutralize} onChange={v => setCommon(c => ({ ...c, neutralize: v }))} />
            </div>
          )}
          {tab === 'single' && <div className="ml-auto text-[12px] text-faint">当前：{factorLabel(meta, factor)}</div>}
        </div>
      </Card>
      {tab === 'board' && <Board common={common} onPick={f => set({ tab: 'single', factor: f })} />}
      {tab === 'single' && <SingleTab common={common} factor={factor} setFactor={f => set({ factor: f })} />}
      {tab === 'corr' && <CorrTab common={common} />}
    </>
  )
}
