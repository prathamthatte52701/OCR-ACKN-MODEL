import { useCallback, useEffect, useState } from 'react'
import api from '../../utils/api'

// GET once on mount, again only when reload() is called (user action). Each widget group owns its
// own instance, so one failing endpoint never takes the rest of the page down.
export default function useApi(url, fallbackMessage) {
  const [state, setState] = useState({ data: null, loading: true, error: '' })

  const run = useCallback(
    () =>
      api
        .get(url)
        .then((res) => setState({ data: res.data, loading: false, error: '' }))
        .catch((err) => setState((s) => ({ ...s, loading: false, error: err.userMessage || fallbackMessage }))),
    [url, fallbackMessage],
  )

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: '' }))
    return run()
  }, [run])

  useEffect(() => {
    run()
  }, [run])

  return { ...state, reload }
}
