import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export function useFetch<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [tick, setTick] = useState(0)
  const seq = useRef(0)
  useEffect(() => {
    if (!url) return
    const id = ++seq.current
    setLoading(true)
    setError(null)
    api.get<T>(url)
      .then(d => { if (id === seq.current) setData(d) })
      .catch(e => { if (id === seq.current) setError(String(e.message ?? e)) })
      .finally(() => { if (id === seq.current) setLoading(false) })
  }, [url, tick])
  const reload = useCallback(() => setTick(t => t + 1), [])
  return { data, error, loading, reload }
}
