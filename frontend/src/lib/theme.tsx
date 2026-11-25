import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type Mode = 'light' | 'dark'
const Ctx = createContext<{ mode: Mode; toggle: () => void }>({ mode: 'light', toggle: () => {} })

function initial(): Mode {
  try {
    const s = localStorage.getItem('theme')
    if (s === 'light' || s === 'dark') return s
  } catch { /* storage unavailable */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(initial)
  // 在渲染阶段同步设置，保证子组件 useColors 读取到的是新主题的变量
  document.documentElement.dataset.theme = mode
  useEffect(() => {
    try { localStorage.setItem('theme', mode) } catch { /* ignore */ }
  }, [mode])
  return <Ctx.Provider value={{ mode, toggle: () => setMode(m => (m === 'light' ? 'dark' : 'light')) }}>{children}</Ctx.Provider>
}

export const useTheme = () => useContext(Ctx)

/** 读取当前主题的 CSS 变量，供 ECharts 使用 */
export function useColors() {
  const { mode } = useTheme()
  return useMemo(() => {
    const cs = getComputedStyle(document.documentElement)
    const v = (n: string) => cs.getPropertyValue(n).trim()
    return {
      mode,
      text: v('--text'), muted: v('--muted'), faint: v('--faint'), line: v('--line'), surface: v('--surface'),
      surface2: v('--surface-2'), accent: v('--accent'), up: v('--up'), down: v('--down'), warn: v('--warn'),
      series: [v('--chart-1'), v('--chart-2'), v('--chart-3'), v('--chart-4'), v('--chart-5'), v('--chart-6')],
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])
}
