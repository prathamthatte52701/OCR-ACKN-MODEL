import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { editMessage, fetchChatFile, getMessages, listThreads, markRead, sendChatFile, sendMessage } from '../api/chat'
import { useChatFiles } from './useChatFiles'
import { createState, markFinished, markStarted, recordFailure, recordSuccess, shouldRun } from '../utils/autoRefreshCore'
import { createTokens, overlayUnread, pickSelected, unreadForAdmin } from '../utils/chatAdminCore'
import {
  clampText, editErrorText, fileSendErrorText, mergeMessages, newestId, nextEditExpiry, sendErrorText,
  threadFromPage, threadWasCleared, validateFile,
} from '../utils/chatCore'
import { ADMIN_TICK_EVENT, notifyCountsChanged } from '../utils/events'
import { chatUserKey, readStored, removeStored, writeStored } from '../utils/layoutStorage'

const PAGE_SIZE = 100
const MAX_CATCH_UP_PAGES = 10 // a poll that keeps reporting hasMore must still end
const THREAD_POLL_MS = 5000
const UNAVAILABLE = 'This user is no longer available.'
const EMPTY_THREAD = { userId: null, ready: false, messages: [], nextSince: null, hasOlder: false, offset: 0 }

const subscribeVisibility = (onChange) => {
  document.addEventListener('visibilitychange', onChange)
  return () => document.removeEventListener('visibilitychange', onChange)
}
const isVisible = () => document.visibilityState === 'visible'
const usePageVisible = () => useSyncExternalStore(subscribeVisibility, isVisible, () => true)

async function loadFresh(userId, signal) {
  const page = await getMessages({ userId, limit: PAGE_SIZE }, signal)
  return { fetched: page.messages, page, hadPrev: false }
}

async function loadChanges(userId, prev, signal) {
  let since = prev.nextSince
  let fetched = []
  let page
  for (let i = 0; i < MAX_CATCH_UP_PAGES; i += 1) {
    page = await getMessages({ userId, since }, signal)
    fetched = fetched.concat(page.messages)
    if (!page.hasMore || page.nextSince === since) break
    since = page.nextSince
  }
  return { fetched, page, hadPrev: true }
}

// Re-renders when the data changes and exactly when the next own message's edit window closes
// (a timeout, no interval). `now` is refreshed whenever new data lands, so an expired message
// can never keep a stale Edit button.
function useEditClock(thread, enabled) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return undefined
    const refresh = setTimeout(() => setNow(Date.now()), 0)
    const wait = nextEditExpiry(thread.messages, thread.offset, Date.now())
    const expiry = wait === null ? null : setTimeout(() => setNow(Date.now()), wait + 50)
    return () => {
      clearTimeout(refresh)
      clearTimeout(expiry)
    }
  }, [thread, enabled])
  return now
}

// Everything the admin chat panel needs. No query library: threads and the open thread are plain
// state, the open thread is polled by a timeout chain (one request in flight), and every answer is
// checked against the thread that was open when its request started.
export function useAdminChat({ adminId, open, byUser }) {
  const visible = usePageVisible()
  const [tokens] = useState(createTokens)
  const mounted = useRef(true) // a request that outlives the panel (or the login) must not write anything
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const epoch = useRef(0) // bumped whenever the open thread is replaced; older answers are dropped

  const [threads, setThreads] = useState([])
  const [threadsReady, setThreadsReady] = useState(false)
  const [selectedId, setSelectedId] = useState(() => readStored(chatUserKey(adminId)))
  const selectedRef = useRef(selectedId)
  const [notice, setNoticeState] = useState('')
  const noticeRef = useRef('')
  const [thread, setThreadState] = useState(EMPTY_THREAD)
  const threadRef = useRef(EMPTY_THREAD)
  const [reloadKey, setReloadKey] = useState(0)
  const [atBottom, setAtBottom] = useState(true)

  const [drafts, setDrafts] = useState({})
  const [sendFailure, setSendFailure] = useState(null)
  const [sending, setSending] = useState(false)
  const [progress, setProgress] = useState(0)
  const [fileByUser, setFileByUser] = useState({}) // userId -> { file, error }: one chip per thread
  const sendingRef = useRef(false)
  const [edit, setEdit] = useState({ id: null, error: null, saving: false })
  const [expiredEdits, setExpiredEdits] = useState(() => new Set())
  const [loadingOlder, setLoadingOlder] = useState(false)

  const commitThread = useCallback((next) => {
    threadRef.current = next
    setThreadState(next)
  }, [])
  const setNotice = useCallback((text) => {
    noticeRef.current = text
    setNoticeState(text)
  }, [])

  // Opening a user starts their thread from scratch: nothing of the previous thread is kept.
  const select = useCallback(
    (id) => {
      selectedRef.current = id
      setSelectedId(id)
      commitThread({ ...EMPTY_THREAD, userId: id })
      setEdit({ id: null, error: null, saving: false })
      epoch.current += 1
      if (id) {
        writeStored(chatUserKey(adminId), id)
        setNotice('')
      } else {
        removeStored(chatUserKey(adminId)) // a user that is gone must not be re-opened on every reload
      }
    },
    [adminId, commitThread, setNotice],
  )

  const loadThreads = useCallback(async () => {
    const token = tokens.next()
    try {
      const list = await listThreads()
      if (!mounted.current || !tokens.isCurrent(token)) return
      setThreads(list)
      setThreadsReady(true)
      const current = selectedRef.current
      if (current && !list.some((t) => t.userId === current)) {
        setNotice(UNAVAILABLE)
        select(null)
      } else if (!current && !noticeRef.current) {
        select(pickSelected(list, readStored(chatUserKey(adminId))))
      }
    } catch {
      // keep the list we have; the next beat tries again
    }
  }, [tokens, adminId, select, setNotice])

  // Threads: when the panel opens, on every shell heartbeat while open, and after a send.
  useEffect(() => {
    if (!open) return undefined
    const first = setTimeout(loadThreads, 0)
    const onTick = () => { if (isVisible()) loadThreads() }
    window.addEventListener(ADMIN_TICK_EVENT, onTick)
    return () => {
      clearTimeout(first)
      window.removeEventListener(ADMIN_TICK_EVENT, onTick)
    }
  }, [open, loadThreads])

  // The open thread: poll only while the panel is open, the tab is visible and a user is selected.
  useEffect(() => {
    if (!open || !visible || !selectedId) return undefined
    let alive = true
    let timer
    const ctl = new AbortController()
    const gate = createState()

    async function pollOnce() {
      const prev = threadRef.current.userId === selectedId && threadRef.current.ready ? threadRef.current : null
      let result = prev ? await loadChanges(selectedId, prev, ctl.signal) : await loadFresh(selectedId, ctl.signal)
      if (!alive) return
      let latest = threadRef.current.userId === selectedId ? threadRef.current : undefined
      if (prev && threadWasCleared(mergeMessages(latest?.messages, result.fetched), result.page.threadCount)) {
        result = await loadFresh(selectedId, ctl.signal) // the thread was cleared: start over
        if (!alive) return
        latest = undefined
      }
      commitThread({ userId: selectedId, ready: true, ...threadFromPage({ ...result, latest, now: Date.now() }) })
    }

    async function beat() {
      if (shouldRun(gate, { visible: true, now: Date.now() })) {
        markStarted(gate, Date.now())
        try {
          await pollOnce()
          recordSuccess(gate)
        } catch (err) {
          if (!alive) return
          recordFailure(gate, err?.response?.status)
          if (err?.response?.status === 404) {
            setNotice(UNAVAILABLE)
            select(null)
            loadThreads()
            return
          }
        } finally {
          markFinished(gate)
        }
      }
      if (alive) timer = setTimeout(beat, THREAD_POLL_MS)
    }

    beat()
    return () => {
      alive = false
      clearTimeout(timer)
      ctl.abort()
    }
  }, [open, visible, selectedId, reloadKey, commitThread, select, setNotice, loadThreads])

  const active = open && Boolean(selectedId) && thread.userId === selectedId
  const view = active ? thread : EMPTY_THREAD
  // cache lives while this thread is open: closing the panel or switching thread revokes every URL
  const files = useChatFiles(active ? `${adminId}:${selectedId}` : null, fetchChatFile)
  const now = useEditClock(view, active)

  // Mark read only what the screen showed, for the thread that was open: nothing while the tab is
  // hidden or scrolled away from the newest message, and never beyond the newest message of THIS
  // thread at the moment of the call.
  const lastMarked = useRef(null)
  useEffect(() => {
    lastMarked.current = null
  }, [selectedId])
  useEffect(() => {
    if (!active || !visible || !atBottom) return
    if (unreadForAdmin(thread.messages, adminId).length === 0) return
    const forUser = selectedId
    const upToId = newestId(thread.messages)
    const mark = `${forUser}:${upToId}`
    if (lastMarked.current === mark) return
    lastMarked.current = mark
    markRead(forUser, upToId).then(
      () => {
        if (selectedRef.current === forUser) {
          setThreads((list) => list.map((t) => (t.userId === forUser ? { ...t, unreadCount: 0 } : t)))
        }
        notifyCountsChanged()
      },
      () => { if (lastMarked.current === mark) lastMarked.current = null },
    )
  }, [active, visible, atBottom, selectedId, thread, adminId])

  const putMessage = useCallback(
    (forUser, message) => {
      const cur = threadRef.current
      if (cur.userId === forUser && cur.ready) commitThread({ ...cur, messages: mergeMessages(cur.messages, [message]) })
    },
    [commitThread],
  )

  const send = useCallback(
    async (text) => {
      const forUser = selectedRef.current
      if (sendingRef.current || !forUser) return false
      sendingRef.current = true
      setSending(true)
      setSendFailure(null)
      setProgress(0)
      const file = fileByUser[forUser]?.file ?? null
      try {
        putMessage(forUser, file ? await sendChatFile(forUser, file, text, setProgress) : await sendMessage(forUser, text))
        if (file) setFileByUser((f) => ({ ...f, [forUser]: { file: null, error: null } }))
        setDrafts((d) => (d[forUser]?.trim() === text ? { ...d, [forUser]: '' } : d)) // keep what was typed while sending
        loadThreads()
        return true
      } catch (err) {
        setSendFailure({ userId: forUser, text: file ? fileSendErrorText(err) : sendErrorText(err) })
        return false
      } finally {
        sendingRef.current = false
        setSending(false)
      }
    },
    [putMessage, loadThreads, fileByUser],
  )

  const chooseFile = useCallback((f) => {
    const forUser = selectedRef.current
    const error = f ? validateFile(f) : null
    setSendFailure(null)
    setFileByUser((all) => ({ ...all, [forUser]: { file: f && !error ? f : null, error } }))
  }, [])

  const startEdit = useCallback((id) => setEdit({ id, error: null, saving: false }), [])
  const cancelEdit = useCallback(() => setEdit({ id: null, error: null, saving: false }), [])
  const saveEdit = useCallback(
    async (text) => {
      const { id } = edit
      const forUser = selectedRef.current
      setEdit((e) => ({ ...e, error: null, saving: true }))
      try {
        putMessage(forUser, await editMessage(id, text))
        setEdit({ id: null, error: null, saving: false })
      } catch (err) {
        if (err.response?.status === 403) setExpiredEdits((s) => new Set(s).add(id))
        setEdit({ id, error: editErrorText(err), saving: false })
      }
    },
    [edit, putMessage],
  )

  const loadOlder = useCallback(async () => {
    const forUser = selectedRef.current
    const cur = threadRef.current
    if (!forUser || cur.userId !== forUser || !cur.messages.length || loadingOlder) return
    const startedAt = epoch.current
    setLoadingOlder(true)
    try {
      const page = await getMessages({ userId: forUser, before: cur.messages[0].id, limit: PAGE_SIZE })
      const latest = threadRef.current
      if (latest.userId === forUser && epoch.current === startedAt) {
        commitThread({ ...latest, messages: mergeMessages(latest.messages, page.messages), hasOlder: page.hasMore })
      }
    } catch {
      // the button stays; the admin can press it again
    } finally {
      setLoadingOlder(false)
    }
  }, [loadingOlder, commitThread])

  // After a clear: drop what is on screen and load the thread again from scratch. Restarting the
  // poll effect aborts any request that started before the clear and drops its answer.
  const reloadThread = useCallback(() => {
    epoch.current += 1
    commitThread({ ...EMPTY_THREAD, userId: selectedRef.current })
    setReloadKey((k) => k + 1)
    loadThreads()
  }, [commitThread, loadThreads])

  const threadList = useMemo(() => overlayUnread(threads, byUser), [threads, byUser])
  const selectedThread = threadList.find((t) => t.userId === selectedId) ?? null

  return {
    threads: threadList,
    threadsReady,
    selectedId,
    selectedThread,
    select,
    notice,
    messages: view.messages,
    offset: view.offset,
    hasOlder: view.hasOlder,
    loading: Boolean(selectedId) && !view.ready,
    now,
    loadOlder,
    loadingOlder,
    setAtBottom,
    reloadThread,
    draft: drafts[selectedId] ?? '',
    setDraft: (text) => setDrafts((d) => ({ ...d, [selectedRef.current]: clampText(text) })),
    send,
    sending,
    progress,
    files,
    file: fileByUser[selectedId]?.file ?? null,
    fileError: fileByUser[selectedId]?.error ?? null,
    chooseFile,
    sendError: sendFailure?.userId === selectedId ? sendFailure.text : null,
    edit,
    expiredEdits,
    startEdit,
    cancelEdit,
    saveEdit,
  }
}
