import { useMemo, useState } from 'react'
import { BalanceSheet } from '../components/BalanceSheet'
import { useNavigate, useParams } from 'react-router-dom'
import { Badge, Card, ErrorBox, Loading, PageHeader, Segmented } from '../components/ui'
import { TimeRange, windowBounds, type Win } from '../components/TimeRange'
import { Chart, axisStyle } from '../components/Chart'
import { StockSearch } from '../components/StockSearch'
import { useFetch } from '../lib/hooks'
import { useColors } from '../lib/theme'
import { fmt, money, pct, shortCode, trendClass } from '../lib/format'
import type { Row } from '../lib/api'

interface Band { dates: string[]; values: number[]; mean: number; std: number; current: number; percentile: number }
interface Detail { basic: Row; snapshot: Row | null; kline: Row[]; valuation: Partial<Record<'pe_ttm' | 'pb', Band>> }

/** 按时间窗口筛选行（key 为日期字段，last 为数据最后一天） */
function inWin<T extends Row>(rows: T[], key: string, win: Win, last: string): T[] {
  const [a, b] = windowBounds(win, last)
  return rows.filter(r => { const d = String(r[key] ?? '').slice(0, 10); return d >= a && d <= b })
}

const WIN_KEY = 'stock_win'
function loadWin(): Win {
  try { const v = JSON.parse(localStorage.getItem(WIN_KEY) ?? ''); if (v && v.preset) return v } catch { /* ignore */ }
  return { preset: '3Y' }
}

/** 区间统计：涨跌幅、最高/最低、最大回撤、年化波动 */
function RangeStats({ rows }: { rows: Row[] }) {
  const st = useMemo(() => {
    const cl = rows.map(r => r.close as number).filter(v => v != null && v > 0)
    if (cl.length < 2) return null
    let peak = cl[0], mdd = 0
    const rets: number[] = []
    for (let i = 0; i < cl.length; i++) {
      peak = Math.max(peak, cl[i]); mdd = Math.min(mdd, cl[i] / peak - 1)
      if (i) rets.push(Math.log(cl[i] / cl[i - 1]))
    }
    const m = rets.reduce((a, b) => a + b, 0) / rets.length
    const sd = Math.sqrt(rets.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(rets.length - 1, 1))
    const days = rows.length
    const ret = cl[cl.length - 1] / cl[0] - 1
    return {
      ret: ret * 100, ann: (Math.pow(1 + ret, 252 / days) - 1) * 100, hi: Math.max(...rows.map(r => r.high ?? -Infinity)),
      lo: Math.min(...rows.map(r => r.low ?? Infinity)), mdd: mdd * 100, vol: sd * Math.sqrt(252) * 100, days,
    }
  }, [rows])
  if (!st) return null
  const items: [string, string, string?][] = [
    ['区间涨跌', pct(st.ret, 2, true), trendClass(st.ret)],
    ['年化收益', pct(st.ann, 1, true), trendClass(st.ann)],
    ['最大回撤', pct(st.mdd, 1), 'text-down'],
    ['年化波动', pct(st.vol, 1)],
    ['区间最高', fmt(st.hi)],
    ['区间最低', fmt(st.lo)],
    ['交易日', String(st.days)],
  ]
  return (
    <dl className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
      {items.map(([k, v, cls]) => (
        <div key={k} className="flex items-baseline gap-1.5"><dt className="text-muted">{k}</dt><dd className={`num font-semibold ${cls ?? ''}`}>{v}</dd></div>
      ))}
    </dl>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/60 px-4 py-3">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="num mt-1 text-[18px] font-semibold">{value}</div>
      {hint && <div className="text-[11px] text-faint">{hint}</div>}
    </div>
  )
}

function Dividends({ code, win, last }: { code: string; win: Win; last: string }) {
  const c = useColors()
  const all = useFetch<Row[]>(`/api/stocks/${code}/dividends`).data
  if (!all) return <Loading />
  // 按报告期筛选；窗口太短（如 3 个月）时至少保留最近一年度
  const [a] = windowBounds(win, last)
  const data = all.filter(d => String(d.report_date) >= a.slice(0, 4) + '-01-01' || d === all[0])
  if (!data.length) return <div className="py-8 text-center text-faint">无现金分红记录</div>
  const years = data.filter(d => d.year_dps != null).slice().reverse()
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
      <Chart height={260} option={{
        legend: { data: ['每股分红(元)', '分红率(%)'] },
        grid: [{ left: 8, right: 16, top: 32, height: '36%', containLabel: true }, { left: 8, right: 16, top: '62%', height: '30%', containLabel: true }],
        xAxis: [
          { type: 'category', data: years.map(d => String(d.year)), ...axisStyle(c), splitLine: { show: false }, axisLabel: { show: false } },
          { type: 'category', data: years.map(d => String(d.year)), gridIndex: 1, ...axisStyle(c), splitLine: { show: false } },
        ],
        yAxis: [{ type: 'value', ...axisStyle(c) }, { type: 'value', gridIndex: 1, ...axisStyle(c) }],
        tooltip: { trigger: 'axis' },
        series: [
          { name: '每股分红(元)', type: 'bar', barMaxWidth: 18, data: years.map(d => d.year_dps), itemStyle: { color: c.accent, borderRadius: [4, 4, 0, 0] } },
          { name: '分红率(%)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: years.map(d => d.year_payout == null ? null : +d.year_payout.toFixed(1)),
            symbolSize: 8, lineStyle: { width: 2, color: c.series[1] }, itemStyle: { color: c.series[1], borderColor: c.surface, borderWidth: 2 } },
        ],
      }} />
      <div className="max-h-[260px] overflow-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-surface text-[12px] text-muted">
            <tr>{['报告期', '每10股派(元)', '送转', '预案公告', '除权除息', '进度'].map(h => <th key={h} className="border-b border-line px-2 py-2 text-left font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {data.map(d => (
              <tr key={d.report_date} className="border-b border-line/70">
                <td className="num px-2 py-2">{d.report_date}</td>
                <td className="num px-2 py-2">{fmt(d.dps * 10, 2)}</td>
                <td className="num px-2 py-2 text-muted">{d.bonus_per10 ? fmt(d.bonus_per10, 1) : '—'}</td>
                <td className="num px-2 py-2 text-muted">{d.plan_date ?? '—'}</td>
                <td className="num px-2 py-2 text-muted">{d.ex_date ?? '—'}</td>
                <td className="px-2 py-2 text-muted">{d.progress ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function KChart({ rows }: { rows: Row[] }) {
  const c = useColors()
  const dates = rows.map(r => r.date)
  return (
    <Chart height={420} option={{
      legend: { data: ['日K', 'MA20', 'MA60'], top: 0, right: 0 },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [{ left: 8, right: 16, top: 32, height: '62%', containLabel: true }, { left: 8, right: 16, top: '78%', height: '16%', containLabel: true }],
      xAxis: [
        { type: 'category', data: dates, ...axisStyle(c), splitLine: { show: false }, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, ...axisStyle(c), splitLine: { show: false } },
      ],
      yAxis: [{ scale: true, ...axisStyle(c) }, { gridIndex: 1, ...axisStyle(c), axisLabel: { show: false }, splitLine: { show: false } }],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
      series: [
        { name: '日K', type: 'candlestick', data: rows.map(r => [r.open, r.close, r.low, r.high]),
          itemStyle: { color: c.up, color0: c.down, borderColor: c.up, borderColor0: c.down } },
        { name: 'MA20', type: 'line', data: rows.map(r => r.ma20), showSymbol: false, lineStyle: { width: 1.2, color: c.series[1] } },
        { name: 'MA60', type: 'line', data: rows.map(r => r.ma60), showSymbol: false, lineStyle: { width: 1.2, color: c.series[3] } },
        { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: rows.map(r => ({ value: r.volume, itemStyle: { color: (r.pct_chg ?? 0) >= 0 ? c.up : c.down, opacity: 0.55 } })) },
      ],
    }} />
  )
}

/** 估值带按窗口重算：均值、标准差、当前值所处分位都只用窗口内数据 */
function windowBand(band: Band | undefined, win: Win): Band | undefined {
  if (!band || !band.dates.length) return band
  const [a, b] = windowBounds(win, band.dates[band.dates.length - 1])
  const idx = band.dates.map((d, i) => [d.slice(0, 10), i] as const).filter(([d]) => d >= a && d <= b).map(([, i]) => i)
  if (idx.length < 2) return undefined
  const values = idx.map(i => band.values[i])
  const mean = values.reduce((x, y) => x + y, 0) / values.length
  const std = Math.sqrt(values.reduce((x, y) => x + (y - mean) ** 2, 0) / (values.length - 1))
  const current = values[values.length - 1]
  return { dates: idx.map(i => band.dates[i]), values, mean, std, current, percentile: (values.filter(v => v < current).length / values.length) * 100 }
}

/** 估值带：历史值 + 均值 + ±1σ（对应参考图的"高估/均值/低估"） */
function BandChart({ band, label }: { band: Band; label: string }) {
  const c = useColors()
  const hi = band.mean + band.std, lo = Math.max(band.mean - band.std, 0)
  const line = (v: number, color: string, name: string) => ({
    name, type: 'line' as const, data: band.dates.map(() => +v.toFixed(2)), showSymbol: false, lineStyle: { type: 'dashed' as const, width: 1.4, color }, itemStyle: { color },
  })
  return (
    <Chart height={300} option={{
      xAxis: { type: 'category', data: band.dates, ...axisStyle(c), splitLine: { show: false } },
      yAxis: { type: 'value', scale: true, ...axisStyle(c) },
      dataZoom: [{ type: 'inside' }],
      series: [
        { name: label, type: 'line', data: band.values, showSymbol: false, lineStyle: { width: 1.6, color: c.accent }, itemStyle: { color: c.accent } },
        line(hi, c.up, '+1σ 偏高'),
        line(band.mean, c.warn, '均值'),
        line(lo, c.down, '-1σ 偏低'),
      ],
    }} />
  )
}

function FinCharts({ code, win, last }: { code: string; win: Win; last: string }) {
  const c = useColors()
  const res = useFetch<Row[]>(`/api/stocks/${code}/financials?limit=60`)
  if (res.error) return <ErrorBox error={res.error} />
  if (!res.data) return <Loading />
  // 窗口按报告期筛选；短窗口时至少保留最近 4 期，避免图表为空
  const sel = inWin(res.data, 'report_date', win, last)
  const data = sel.length >= 4 ? sel : res.data.slice(-4)
  if (!data.length) return <div className="py-10 text-center text-faint">暂无财报数据</div>
  const x = data.map(r => r.report_date)
  const yi = (v: number | null) => (v == null ? null : +(v / 1e8).toFixed(2))
  const latest = data[data.length - 1]
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <div className="mb-1 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold">营收与利润（亿元，报告期累计）</h3>
          <span className="text-[12px] text-faint">最新 {latest.report_date}：营收 {money(latest.revenue)} · 净利 {money(latest.net_profit)}</span>
        </div>
        <Chart height={280} option={{
          xAxis: { type: 'category', data: x, ...axisStyle(c), splitLine: { show: false } },
          yAxis: [{ type: 'value', ...axisStyle(c) }, { type: 'value', ...axisStyle(c), splitLine: { show: false }, axisLabel: { formatter: '{value}%', color: c.faint, fontSize: 11 } }],
          series: [
            { name: '营业总收入', type: 'bar', data: data.map(r => yi(r.revenue)), barMaxWidth: 14, itemStyle: { borderRadius: [3, 3, 0, 0] } },
            { name: '净利润', type: 'bar', data: data.map(r => yi(r.net_profit)), barMaxWidth: 14, itemStyle: { borderRadius: [3, 3, 0, 0] } },
            { name: '营收同比', type: 'line', yAxisIndex: 1, data: data.map(r => r.revenue_yoy), symbolSize: 4, lineStyle: { width: 1.4 } },
          ],
        }} />
      </div>
      <div>
        <h3 className="mb-1 text-[13px] font-semibold">费用结构（亿元）</h3>
        <Chart height={280} option={{
          xAxis: { type: 'category', data: x, ...axisStyle(c), splitLine: { show: false } },
          yAxis: { type: 'value', ...axisStyle(c) },
          series: [
            { name: '营业支出', type: 'bar', stack: 'e', data: data.map(r => yi(r.op_cost)), barMaxWidth: 18 },
            { name: '销售费用', type: 'bar', stack: 'e', data: data.map(r => yi(r.sell_exp)) },
            { name: '管理费用', type: 'bar', stack: 'e', data: data.map(r => yi(r.admin_exp)) },
            { name: '财务费用', type: 'bar', stack: 'e', data: data.map(r => yi(r.fin_exp)) },
          ],
        }} />
      </div>
    </div>
  )
}

export default function Stock() {
  const { code = 'sh.600519' } = useParams()
  const nav = useNavigate()
  const [win, setWinRaw] = useState<Win>(loadWin)
  const setWin = (w: Win) => { setWinRaw(w); try { localStorage.setItem(WIN_KEY, JSON.stringify(w)) } catch { /* ignore */ } }
  const [val, setVal] = useState<'pe_ttm' | 'pb'>('pe_ttm')
  // 一次取全部历史，时间窗口在前端截取（切换窗口无需重新请求）
  const { data, error } = useFetch<Detail>(`/api/stocks/${code}?years=0`)
  const last = data?.kline.length ? String(data.kline[data.kline.length - 1].date) : ''
  const kline = useMemo(() => (data ? inWin(data.kline, 'date', win, last) : []), [data, win, last])

  const search = <StockSearch onSelect={r => nav(`/stock/${r.code}`)} />
  if (error) return <><PageHeader eyebrow="Stock" title="个股看板" right={search} /><ErrorBox error={error} /></>
  if (!data) return <Loading />
  const b = data.basic, s = data.snapshot ?? {}
  const band = windowBand(data.valuation[val], win)
  const [wa, wb] = windowBounds(win, last)
  const winText = win.preset === 'ALL' ? '全部历史' : `${kline[0]?.date ?? wa} ~ ${kline[kline.length - 1]?.date ?? wb}`

  return (
    <>
      <PageHeader eyebrow="Stock Dashboard" title="个股看板" right={search} />

      <div className="card mb-4 flex flex-wrap items-center justify-between gap-6 px-6 py-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-[24px] font-bold">{b.name}</h2>
            <span className="num text-muted">{shortCode(b.code)}</span>
            {b.industry && <Badge tone="accent">{b.industry}</Badge>}
            {b.universe_src && <Badge>{b.universe_src === 'hs300' ? '沪深300' : '中证500'}</Badge>}
            {b.status === 0 && <Badge tone="warn">已退市 {b.out_date}</Badge>}
            {s.is_st === 1 && <Badge tone="up">ST</Badge>}
          </div>
          <div className="mt-1 text-[12px] text-faint">上市日期 {b.ipo_date} · 数据日期 {s.date ?? '—'}</div>
        </div>
        <div className="text-right">
          <div className={`num text-[30px] font-bold ${trendClass(s.pct_chg)}`}>{fmt(s.close)}</div>
          <div className={`num text-[14px] font-medium ${trendClass(s.pct_chg)}`}>{pct(s.pct_chg, 2, true)}</div>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Metric label="PE(TTM)" value={fmt(s.pe_ttm, 1)} hint={data.valuation.pe_ttm ? `历史分位 ${data.valuation.pe_ttm.percentile.toFixed(0)}%` : undefined} />
        <Metric label="PB" value={fmt(s.pb, 2)} hint={data.valuation.pb ? `历史分位 ${data.valuation.pb.percentile.toFixed(0)}%` : undefined} />
        <Metric label="ROE(年化)" value={pct(s.roe_ann, 1)} hint={s.fin_report_date ? `报告期 ${s.fin_report_date}` : undefined} />
        <Metric label="毛利率" value={pct(s.gross_margin, 1)} />
        <Metric label="营收同比" value={pct(s.revenue_yoy, 1, true)} />
        <Metric label="60日波动率" value={pct(s.vol_60, 1)} />
        <Metric label="股息率(TTM)" value={pct(s.dividend_yield, 2)} hint={s.payout_ratio != null ? `分红率 ${fmt(s.payout_ratio, 0)}%` : undefined} />
        <Metric label="流通市值" value={`${fmt(s.float_mv, 0)}亿`} />
      </div>

      <div className="sticky top-0 z-10 -mx-1 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface/95 px-4 py-2.5 backdrop-blur">
        <div className="text-[13px]"><span className="font-semibold">时间窗口</span><span className="num ml-2 text-faint">{winText}</span></div>
        <TimeRange value={win} onChange={setWin} presets={['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'ALL']} />
      </div>

      <Card title="价格走势（前复权）">
        <RangeStats rows={kline} />
        {kline.length ? <KChart rows={kline} /> : <div className="py-16 text-center text-faint">所选窗口内没有行情数据</div>}
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="估值通道" extra={<Segmented value={val} onChange={setVal} options={[{ value: 'pe_ttm', label: 'PE(TTM)' }, { value: 'pb', label: 'PB' }]} />}>
          {band ? <BandChart band={band} label={val === 'pb' ? 'PB' : 'PE(TTM)'} /> : <div className="py-16 text-center text-faint">窗口内无有效估值数据（亏损、缺少财报或窗口过短）</div>}
        </Card>
        <Card title="估值解读">
          {band ? (
            <div className="space-y-4">
              <div>
                <div className="text-[12px] text-muted">当前 {val === 'pb' ? 'PB' : 'PE'} 处于所选窗口内</div>
                <div className="num text-[34px] font-bold">{band.percentile.toFixed(0)}<span className="text-[16px] text-muted"> 分位</span></div>
                <div className="mt-2 h-2 rounded-full bg-gradient-to-r from-down via-warn to-up opacity-80">
                  <div className="relative h-2" style={{ width: `${band.percentile}%` }}>
                    <span className="absolute -right-1.5 -top-1 h-4 w-3 rounded-sm border-2 border-surface bg-text" />
                  </div>
                </div>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-[13px]">
                <div><dt className="text-muted">当前值</dt><dd className="num font-semibold">{fmt(band.current)}</dd></div>
                <div><dt className="text-muted">窗口均值</dt><dd className="num font-semibold">{fmt(band.mean)}</dd></div>
                <div><dt className="text-muted">+1σ（偏高）</dt><dd className="num font-semibold text-up">{fmt(band.mean + band.std)}</dd></div>
                <div><dt className="text-muted">-1σ（偏低）</dt><dd className="num font-semibold text-down">{fmt(Math.max(0, band.mean - band.std))}</dd></div>
              </dl>
              <p className="rounded-lg bg-surface-2 px-3 py-2.5 text-[12px] leading-relaxed text-muted">
                {band.current > band.mean + band.std ? '当前估值高于窗口均值 1 个标准差，处于偏高区间。'
                  : band.current < band.mean - band.std ? '当前估值低于窗口均值 1 个标准差，处于偏低区间。'
                  : '当前估值位于均值 ±1σ 区间内。'}
                统计区间 {band.dates[0]} ~ {band.dates[band.dates.length - 1]}，估值由 PIT 财报计算，仅供参考。
              </p>
            </div>
          ) : <div className="text-faint">—</div>}
        </Card>
      </div>

      <Card className="mt-4" title="财务数据"><FinCharts code={code} win={win} last={last} /></Card>
      <Card className="mt-4" title="资产负债结构"><BalanceSheet code={code} /></Card>
      <Card className="mt-4" title="分红记录"><Dividends code={code} win={win} last={last} /></Card>
    </>
  )
}
