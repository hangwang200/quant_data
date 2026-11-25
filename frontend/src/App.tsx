import { Component, type ReactNode } from 'react'
import { HashRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { ThemeProvider, useTheme } from './lib/theme'
import { MetaProvider, useMeta } from './lib/meta'
import { cx, ErrorBox } from './components/ui'
import Overview from './pages/Overview'
import Stock from './pages/Stock'
import Compare from './pages/Compare'
import Screener from './pages/Screener'
import Backtest from './pages/Backtest'
import Financials from './pages/Financials'
import Analysis from './pages/Analysis'
import Formulas from './pages/Formulas'
import DataAdmin from './pages/DataAdmin'

const NAV = [
  { to: '/', label: '市场总览', icon: 'M3 13h4v8H3zM10 8h4v13h-4zM17 3h4v18h-4z' },
  { to: '/stock', label: '个股看板', icon: 'M3 17l5-6 4 4 9-11M14 4h7v7' },
  { to: '/compare', label: '公司对比', icon: 'M4 6h7v12H4zM13 10h7v8h-7z' },
  { to: '/screener', label: '选股器', icon: 'M3 5h18l-7 8v6l-4 2v-8z' },
  { to: '/analysis', label: '因子分析', icon: 'M4 20h16M6 16v-4M10 16V8M14 16v-6M18 16V4' },
  { to: '/formulas', label: '公式因子', icon: 'M5 4h6M8 4v16M5 20h6M14 8l6 8M20 8l-6 8' },
  { to: '/backtest', label: '因子回测', icon: 'M4 19V5M4 19h16M8 15l4-4 3 3 5-6' },
  { to: '/financials', label: '财报数据', icon: 'M6 3h9l4 4v14H6zM9 12h7M9 16h7M9 8h3' },
  { to: '/data', label: '数据管理', icon: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3' },
]

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

function Sidebar() {
  const { meta } = useMeta()
  const { mode, toggle } = useTheme()
  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r border-line bg-surface px-4 py-5 lg:flex">
      <div className="mb-8 flex items-center gap-2.5 px-2">
        <img src="/favicon.svg" className="h-8 w-8" alt="" />
        <div>
          <div className="text-[15px] font-bold tracking-tight">Factor Lab</div>
          <div className="text-[11px] text-faint">A 股因子实验室</div>
        </div>
      </div>
      <div className="eyebrow mb-2 px-2">工作台</div>
      <nav className="flex flex-col gap-0.5">
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'}
            className={({ isActive }) => cx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-[14px] transition',
              isActive ? 'bg-accent-soft font-semibold text-accent-text' : 'text-muted hover:bg-surface-2 hover:text-text')}>
            <Icon d={n.icon} />{n.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto space-y-3">
        <button onClick={toggle} className="flex w-full cursor-pointer items-center justify-between rounded-lg border border-line px-3 py-2 text-[13px] text-muted hover:bg-surface-2">
          <span>{mode === 'light' ? '浅色模式' : '深色模式'}</span><span>{mode === 'light' ? '☀' : '☾'}</span>
        </button>
        <div className="rounded-lg bg-surface-2 px-3 py-2.5 text-[12px] leading-relaxed text-muted">
          <div className="flex items-center gap-1.5">
            <span className={cx('h-1.5 w-1.5 rounded-full', meta?.ready ? 'bg-down' : 'bg-warn')} />
            {meta?.ready ? '本地数据已就绪' : '等待数据'}
          </div>
          {meta?.ready && <div className="num text-faint">{meta.n_stocks} 只 · 截至 {meta.end}</div>}
        </div>
      </div>
    </aside>
  )
}

function MobileNav() {
  return (
    <nav className="sticky top-0 z-40 flex gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 lg:hidden">
      {NAV.map(n => (
        <NavLink key={n.to} to={n.to} end={n.to === '/'}
          className={({ isActive }) => cx('shrink-0 rounded-md px-3 py-1.5 text-[13px]', isActive ? 'bg-accent-soft text-accent-text' : 'text-muted')}>
          {n.label}
        </NavLink>
      ))}
    </nav>
  )
}

/** 单个页面渲染出错时只影响该页面，并显示错误信息，而不是整个应用白屏 */
class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    return this.state.error ? <ErrorBox error={`页面渲染出错：${this.state.error.message}`} /> : this.props.children
  }
}

function Shell() {
  const loc = useLocation()
  const { meta, error } = useMeta()
  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <MobileNav />
        <div className="mx-auto max-w-[1360px] px-4 py-7 sm:px-8">
          {error && <div className="mb-4"><ErrorBox error={`无法连接后端：${error}`} /></div>}
          {meta && !meta.ready && <div className="mb-4"><ErrorBox error="数据尚未就绪，请先运行：python -m backend.cli etl" /></div>}
          <PageBoundary key={loc.pathname}>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/stock" element={<Stock />} />
            <Route path="/stock/:code" element={<Stock />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/screener" element={<Screener />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/financials" element={<Financials />} />
            <Route path="/analysis" element={<Analysis />} />
            <Route path="/formulas" element={<Formulas />} />
            <Route path="/data" element={<DataAdmin />} />
          </Routes>
          </PageBoundary>
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <MetaProvider>
        <HashRouter>
          <Shell />
        </HashRouter>
      </MetaProvider>
    </ThemeProvider>
  )
}
