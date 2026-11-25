import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, ErrorBox, Loading, PageHeader, Stat } from '../components/ui'
import { DataTable, type Col } from '../components/DataTable'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { money, pct, shortCode, trendClass, fmt } from '../lib/format'

export default function Financials() {
  const nav = useNavigate()
  const periods = useFetch<{ report_date: string; n: number }[]>('/api/financials/periods')
  const [period, setPeriod] = useState('')
  const [q, setQ] = useState('')
  const [universe, setUniverse] = useState(true)
  const [dl, setDl] = useState('')
  const [dlMsg, setDlMsg] = useState<string | null>(null)

  useEffect(() => { if (!period && periods.data?.length) setPeriod(periods.data[0].report_date) }, [periods.data, period])
  const list = useFetch<{ rows: Row[] }>(period ? `/api/financials?report_date=${period}&universe_only=${universe}&limit=6000` : null)

  const rows = useMemo(() => (list.data?.rows ?? []).filter(r => !q || r.code.includes(q) || r.name?.includes(q) || r.industry?.includes(q)), [list.data, q])
  const agg = useMemo(() => ({
    rev: rows.reduce((s, r) => s + (r.revenue ?? 0), 0),
    np: rows.reduce((s, r) => s + (r.net_profit ?? 0), 0),
    loss: rows.filter(r => (r.net_profit ?? 0) < 0).length,
    grow: rows.filter(r => (r.net_profit_yoy ?? 0) > 0).length,
  }), [rows])

  const download = async () => {
    setDlMsg(null)
    try {
      await api.post('/api/etl/financials', { report_date: dl })
      setDlMsg(`已开始下载 ${dl}，约 1 分钟…`)
      const task = `financials:${dl}`
      const poll = setInterval(async () => {
        const st = await api.get<Row[]>('/api/etl/status')
        const t = st.find(x => x.task === task)
        if (t && t.status !== 'running') {
          clearInterval(poll)
          setDlMsg(t.status === 'ok' ? `下载完成：${t.message}` : `下载失败：${t.message}`)
          periods.reload(); setPeriod(dl)
        }
      }, 3000)
    } catch (e) { setDlMsg((e as Error).message) }
  }

  const cols: Col[] = [
    { key: 'name', label: '公司', render: r => <div><div className="font-medium">{r.name}</div><div className="text-[11px] text-faint">{shortCode(r.code)}</div></div> },
    { key: 'industry', label: '行业', render: r => <span className="text-muted">{r.industry ?? '—'}</span> },
    { key: 'revenue', label: '营业总收入', align: 'right', render: r => money(r.revenue) },
    { key: 'revenue_yoy', label: '营收同比', align: 'right', render: r => <span className={trendClass(r.revenue_yoy)}>{pct(r.revenue_yoy, 1, true)}</span> },
    { key: 'net_profit', label: '净利润', align: 'right', render: r => <span className={r.net_profit < 0 ? 'text-down' : ''}>{money(r.net_profit)}</span> },
    { key: 'net_profit_yoy', label: '净利同比', align: 'right', render: r => <span className={trendClass(r.net_profit_yoy)}>{pct(r.net_profit_yoy, 1, true)}</span> },
    { key: 'op_profit', label: '营业利润', align: 'right', render: r => money(r.op_profit) },
    { key: 'total_expense', label: '营业总支出', align: 'right', render: r => money(r.total_expense) },
    { key: 'sell_exp', label: '销售费用', align: 'right', render: r => money(r.sell_exp) },
    { key: 'admin_exp', label: '管理费用', align: 'right', render: r => money(r.admin_exp) },
    { key: 'fin_exp', label: '财务费用', align: 'right', render: r => money(r.fin_exp) },
    { key: 'roe', label: 'ROE', align: 'right', render: r => pct(r.roe, 2) },
    { key: 'gross_margin', label: '毛利率', align: 'right', render: r => pct(r.gross_margin, 1) },
    { key: 'eps', label: 'EPS', align: 'right', render: r => fmt(r.eps, 3) },
    { key: 'effective_date', label: '回测可用日', render: r => <span className="text-faint">{r.effective_date}</span> },
  ]

  return (
    <>
      <PageHeader eyebrow="Financial Reports" title="财报数据" desc="按报告期下载全市场财报（东方财富 业绩报表 + 利润表），提取营收、利润、费用等关键字段"
        right={
          <div className="flex items-center gap-2">
            <input className="field num" type="date" value={dl} onChange={e => setDl(e.target.value)} title="报告期，如 2024-12-31" />
            <Button onClick={download} disabled={!dl}>下载报告期</Button>
          </div>
        } />
      {dlMsg && <div className="mb-4 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] text-muted">{dlMsg}</div>}
      {periods.error && <ErrorBox error={periods.error} />}

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="公司数" value={rows.length.toLocaleString()} sub={period ? `报告期 ${period}` : ''} />
        <Stat label="营收合计" value={money(agg.rev)} />
        <Stat label="净利润合计" value={money(agg.np)} />
        <Stat label="亏损 / 净利增长" value={<><span className="text-down">{agg.loss}</span><span className="text-faint"> / </span><span className="text-up">{agg.grow}</span></>} sub="家" />
      </div>

      <Card title="财报明细" extra={
        <div className="flex flex-wrap items-center gap-2">
          <select className="field num" value={period} onChange={e => setPeriod(e.target.value)}>
            {periods.data?.map(p => <option key={p.report_date} value={p.report_date}>{p.report_date}（{p.n}）</option>)}
          </select>
          <input className="field w-48" placeholder="搜索公司/行业" value={q} onChange={e => setQ(e.target.value)} />
          <label className="flex items-center gap-1.5 text-[13px] text-muted">
            <input type="checkbox" checked={universe} onChange={e => setUniverse(e.target.checked)} />仅股票池
          </label>
        </div>
      }>
        {list.error && <ErrorBox error={list.error} />}
        {!list.data ? <Loading /> : <DataTable cols={cols} rows={rows} initialSort={{ key: 'revenue', desc: true }} onRowClick={r => nav(`/stock/${r.code}`)} />}
      </Card>
    </>
  )
}
