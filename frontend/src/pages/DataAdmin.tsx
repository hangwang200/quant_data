import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Card, ErrorBox, Loading, PageHeader, Stat } from '../components/ui'
import { DataTable } from '../components/DataTable'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useMeta } from '../lib/meta'
import { fmt } from '../lib/format'

interface Status {
  tables: { table: string; label: string; unit: string; rows: number; count: number | null; extra: number | null; start: string | null; end: string | null }[]
  etl: Row[]
  db_size_mb: number
  coverage: { listed: number; delisted: number } | null
  tasks: { key: string; label: string; running: boolean; started: string | null }[]
}

const STATUS_TONE: Record<string, 'down' | 'warn' | 'up' | 'neutral'> = { ok: 'down', partial: 'warn', running: 'neutral', error: 'up' }
const STATUS_TEXT: Record<string, string> = { ok: '成功', partial: '部分失败', running: '运行中', error: '失败' }

export default function DataAdmin() {
  const { reload: reloadMeta } = useMeta()
  const st = useFetch<Status>('/api/data/status')
  const [err, setErr] = useState<string | null>(null)
  const [logTask, setLogTask] = useState<string | null>(null)
  const [log, setLog] = useState<string[]>([])
  const running = st.data?.tasks.find(t => t.running)

  // 有任务运行时每 3 秒刷新状态与日志
  useEffect(() => {
    const active = running?.key ?? logTask
    if (!active) return
    const tick = () => {
      api.get<{ lines: string[] }>(`/api/data/log/${active}`).then(r => setLog(r.lines)).catch(() => {})
    }
    tick()
    if (!running) return
    const id = window.setInterval(() => { tick(); st.reload() }, 3000)
    return () => window.clearInterval(id)
  }, [running?.key, logTask]) // eslint-disable-line react-hooks/exhaustive-deps

  // 任务结束后刷新全局元数据（股票数、日期范围、因子列表）
  const wasRunning = useRef<string | null>(null)
  useEffect(() => {
    if (wasRunning.current && !running) reloadMeta()
    wasRunning.current = running?.key ?? null
  }, [running?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (task: string) => {
    setErr(null)
    try { await api.post('/api/data/run', { task }); setLogTask(task); st.reload() } catch (e) { setErr((e as Error).message) }
  }

  if (!st.data) return <><PageHeader eyebrow="Data" title="数据管理" />{st.error ? <ErrorBox error={st.error} /> : <Loading />}</>
  const d = st.data
  const t = Object.fromEntries(d.tables.map(x => [x.table, x]))
  return (
    <>
      <PageHeader eyebrow="Data Management" title="数据管理" desc="各数据表的覆盖范围与更新状态；可在此触发 ETL 任务（以后台进程运行，日志写入 logs/ 目录）"
        right={<Button variant="ghost" onClick={st.reload}>刷新</Button>} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="有行情的股票" value={fmt((d.coverage?.listed ?? 0) + (d.coverage?.delisted ?? 0), 0)} sub={`上市 ${d.coverage?.listed ?? 0} · 退市 ${d.coverage?.delisted ?? 0}`} />
        <Stat label="行情区间" value={<span className="text-[18px]">{t.daily_bar?.end ?? '—'}</span>} sub={`自 ${t.daily_bar?.start ?? '—'}`} />
        <Stat label="财报报告期" value={fmt(t.financial_report?.count, 0)} sub={`${t.financial_report?.start ?? '—'} ~ ${t.financial_report?.end ?? '—'}`} />
        <Stat label="因子宽表" value={`${fmt((t.factor_daily?.rows ?? 0) / 1e6, 1)}M`} sub={`${t.factor_daily?.count ?? 0} 只股票`} />
        <Stat label="数据库文件" value={`${fmt(d.db_size_mb / 1024, 2)} GB`} sub="data/quant.duckdb" />
      </div>
      {err && <div className="mb-4"><ErrorBox error={err} /></div>}
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <div className="space-y-4">
          <Card title="数据表">
            <DataTable rowKey="table" maxHeight={520} rows={d.tables as Row[]} cols={[
              { key: 'label', label: '数据', render: r => <div><div className="font-medium">{r.label}</div><div className="font-mono text-[11px] text-faint">{r.table}</div></div> },
              { key: 'rows', label: '行数', align: 'right', render: r => fmt(r.rows, 0) },
              { key: 'count', label: '覆盖', align: 'right', render: r => r.table === 'stock_basic'
                  ? <span className="text-muted">{fmt(r.count, 0)} 上市 / {fmt(r.extra, 0)} 退市</span>
                  : r.count != null ? <span className="text-muted">{fmt(r.count, 0)} {r.unit}</span> : '—' },
              { key: 'start', label: '起始', align: 'right', render: r => r.start ?? '—' },
              { key: 'end', label: '截至', align: 'right', render: r => r.end ?? '—' },
            ]} />
          </Card>
          <Card title="更新记录">
            <DataTable rowKey="task" maxHeight={420} rows={d.etl} cols={[
              { key: 'task', label: '任务', render: r => <span className="font-mono text-[12px]">{r.task}</span> },
              { key: 'status', label: '状态', render: r => <Badge tone={STATUS_TONE[r.status] ?? 'neutral'}>{STATUS_TEXT[r.status] ?? r.status}</Badge> },
              { key: 'message', label: '说明', render: r => <span className="block max-w-[420px] truncate text-muted" title={r.message}>{r.message || '—'}</span> },
              { key: 'updated_at', label: '时间', align: 'right', render: r => String(r.updated_at ?? '').slice(0, 19).replace('T', ' ') },
            ]} />
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="运行任务">
            <ul className="space-y-2">
              {d.tasks.map(task => (
                <li key={task.key} className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2.5">
                  <div className="min-w-0">
                    <div className="font-mono text-[12px] font-medium">{task.key}</div>
                    <div className="text-[12px] text-muted">{task.label}</div>
                  </div>
                  {task.running
                    ? <Badge tone="accent"><span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />运行中</Badge>
                    : <div className="flex shrink-0 gap-1">
                        <Button variant="ghost" className="h-7 px-2 text-[12px]" onClick={() => setLogTask(task.key)}>日志</Button>
                        <Button className="h-7 px-2.5 text-[12px]" disabled={!!running} onClick={() => run(task.key)}>运行</Button>
                      </div>}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[11px] leading-relaxed text-faint">
              日常收盘后运行 daily 即可。首次扩展到全 A 股时依次运行：prices → st → shares → members → dividends → factors。任务运行期间页面查询可能稍慢。
            </p>
          </Card>
          <Card title={`日志${running ? ` · ${running.key}` : logTask ? ` · ${logTask}` : ''}`}>
            {log.length ? (
              <pre className="max-h-[420px] overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted">
                {log.map(l => l.replace(/^\d{4}-\d\d-\d\d /, '')).join('\n')}
              </pre>
            ) : <div className="text-[13px] text-faint">选择任务查看日志</div>}
          </Card>
        </div>
      </div>
    </>
  )
}
