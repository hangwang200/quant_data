import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { useColors } from '../lib/theme'

/** ECharts 封装：注入统一的字体、坐标轴、提示框样式（随主题切换） */
export function Chart({ option, height = 320 }: { option: EChartsOption; height?: number }) {
  const c = useColors()
  const base: EChartsOption = {
    backgroundColor: 'transparent',
    color: c.series,
    textStyle: { fontFamily: 'Inter, PingFang SC, Microsoft YaHei, sans-serif', color: c.muted },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis', backgroundColor: c.surface, borderColor: c.line, borderWidth: 1,
      textStyle: { color: c.text, fontSize: 12 }, extraCssText: 'border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,.08);',
    },
    legend: { top: 0, right: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 4, textStyle: { color: c.muted, fontSize: 12 } },
  }
  // legend / tooltip 与统一样式做浅层合并：页面只需写差异（如 data、valueFormatter），位置与配色保持一致
  const merged: EChartsOption = { ...base, ...option }
  for (const k of ['legend', 'tooltip'] as const) {
    const o = option[k]
    if (o && !Array.isArray(o) && typeof o === 'object') merged[k] = { ...(base[k] as object), ...(o as object) } as never
  }
  return <ReactECharts key={c.mode} option={merged} style={{ height }} notMerge lazyUpdate />
}

export function axisStyle(c: ReturnType<typeof useColors>) {
  return {
    axisLine: { lineStyle: { color: c.line } },
    axisTick: { show: false },
    axisLabel: { color: c.faint, fontSize: 11 },
    splitLine: { lineStyle: { color: c.line, type: 'dashed' as const } },
  }
}
