import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { focusManager, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  editChatMessage, getChatMessages, getChatSettings, getChatUnread,
  listChatAdmins, markChatRead, putChatColor, sendChatMessage,
} from '../api/chat'
import { listDocumentsSummary } from '../api/documents'
import { chatAdminKey, readStored, writeStored } from '../utils/layoutStorage'
import {
  buildSummaryText, clampText, editErrorText, incomingUnreadIds, mergeMessages, newestId, sendErrorText,
  threadFromPage, threadWasCleared,
} from '../utils/chatCore'
import { colorById } from '../utils/chatColors'
import { documentKeys } from './useDocumentsQueries'

const PAGE_SIZE = 100
const MAX_CATCH_UP_PAGES = 10 // a poll that keeps reporting hasMore must still end
const UNREAD_POLL_MS = 30_000
const THREAD_POLL_MS = 5_000

// Every key starts with the user id, so one user's chat can never be read as another's.
export const chatKeys = {
  unread: (uid) => ['chat', uid, 'unread'],
  admins: (uid) => ['chat', uid, 'admins'],
  thread: (uid) => ['chat', uid, 'thread'],
  settings: (uid) => ['chat', uid, 'settings'],
}

const pollOptions = (ms) => ({
  refetchInterval: ms,
  refetchIntervalInBackground: false, // a hidden tab makes no chat requests
  refetchOnWindowFocus: true, // and refreshes the moment it is visible again
  staleTime: 0,
  retry: false, // a failed background poll keeps the old data and tries again next interval
})

export function useChatUnread(userId, enabled) {
  const { data } = useQuery({
    queryKey: chatKeys.unread(userId),
    queryFn: getChatUnread,
    enabled,
    ...pollOptions(UNREAD_POLL_MS),
  })
  return data?.count ?? 0
}

function usePageVisible() {
  return useSyncExternalStore(focusManager.subscribe, () => focusManager.isFocused(), () => true)
}

async function loadFresh() {
  const page = await getChatMessages({ limit: PAGE_SIZE })
  return { fetched: page.messages, page, hadPrev: false }
}

async function loadChanges(prev) {
  let since = prev.nextSince
  let fetched = []
  let page
  for (let i = 0; i < MAX_CATCH_UP_PAGES; i += 1) {
    page = await getChatMessages({ since })
    fetched = fetched.concat(page.messages)
    if (!page.hasMore || page.nextSince === since) break
    since = page.nextSince
  }
  return { fetched, page, hadPrev: true }
}

function useThread(userId, enabled) {
  const qc = useQueryClient()
  const key = chatKeys.thread(userId)
  return useQuery({
    queryKey: key,
    queryFn: async () => {
      const prev = qc.getQueryData(key)
      let result = prev ? await loadChanges(prev) : await loadFresh()
      let latest = qc.getQueryData(key)
      if (prev && threadWasCleared(mergeMessages(latest?.messages, result.fetched), result.page.threadCount)) {
        result = await loadFresh() // an admin cleared the chat: start over instead of merging
        latest = undefined
      }
      return threadFromPage({ ...result, latest, now: Date.now() })
    },
    enabled,
    ...pollOptions(THREAD_POLL_MS),
  })
}

// Re-renders exactly when the next own message's edit window closes (no interval).
function useEditClock(messages, offset, enabled) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return undefined
    const serverNow = Date.now() + offset
    let next = Infinity
    for (const m of messages) {
      const t = m.mine && m.editableUntil ? Date.parse(m.editableUntil) : Infinity
      if (t > serverNow && t < next) next = t
    }
    if (next === Infinity) return undefined
    const id = setTimeout(() => setNow(Date.now()), next - serverNow + 50)
    return () => clearTimeout(id)
  }, [messages, offset, enabled, now])
  return now
}

function useAdminChoice(userId, admins) {
  const stored = useMemo(() => readStored(chatAdminKey(userId)), [userId])
  const [picked, setPicked] = useState(null)
  const choice = picked?.userId === userId ? picked.id : stored
  const selectedAdminId = admins.some((a) => a.id === choice) ? choice : (admins[0]?.id ?? null)
  const selectAdmin = useCallback(
    (id) => {
      writeStored(chatAdminKey(userId), id)
      setPicked({ userId, id })
    },
    [userId],
  )
  return { selectedAdminId, selectAdmin }
}

function useChatColor(userId, enabled) {
  const qc = useQueryClient()
  const key = chatKeys.settings(userId)
  const { data } = useQuery({ queryKey: key, queryFn: getChatSettings, enabled, staleTime: 60_000, retry: false })
  const mutation = useMutation({
    mutationFn: putChatColor,
    onMutate: async (color) => {
      await qc.cancelQueries({ queryKey: key })
      const before = qc.getQueryData(key)
      qc.setQueryData(key, { chatColor: color })
      return { before }
    },
    onError: (_err, _color, ctx) =>
      ctx.before ? qc.setQueryData(key, ctx.before) : qc.invalidateQueries({ queryKey: key }),
  })
  return { color: colorById(data?.chatColor), setColor: mutation.mutate, colorFailed: mutation.isError }
}

// Everything the chat UI needs. `open` gates the message/admin/settings requests; `canChat` gates
// all of them (signed in, not an admin, no forced password change).
export function useChat({ userId, canChat, open }) {
  const qc = useQueryClient()
  const active = canChat && open
  const visible = usePageVisible()

  const unread = useChatUnread(userId, canChat)
  const thread = useThread(userId, active)
  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data])
  const offset = thread.data?.offset ?? 0
  const now = useEditClock(messages, offset, active)

  const admins = useQuery({ queryKey: chatKeys.admins(userId), queryFn: listChatAdmins, enabled: active, staleTime: 0, refetchOnWindowFocus: false, retry: false })
  const adminList = useMemo(() => admins.data ?? [], [admins.data])
  const { selectedAdminId, selectAdmin } = useAdminChoice(userId, adminList)
  const { color, setColor, colorFailed } = useChatColor(userId, active)

  const [draft, setDraft] = useState('')
  const [sendError, setSendError] = useState(null)
  const [sending, setSending] = useState(false)
  const sendingRef = useRef(false)
  const [edit, setEdit] = useState({ id: null, error: null, saving: false })
  const [expiredEdits, setExpiredEdits] = useState(() => new Set())
  const [summaryError, setSummaryError] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [atBottom, setAtBottom] = useState(true)

  const putMessage = useCallback(
    (message) =>
      qc.setQueryData(chatKeys.thread(userId), (old) =>
        old && { ...old, messages: mergeMessages(old.messages, [message]) },
      ),
    [qc, userId],
  )

  const send = useCallback(
    async (text) => {
      if (sendingRef.current || !selectedAdminId) return false
      sendingRef.current = true
      setSending(true)
      setSendError(null)
      try {
        putMessage(await sendChatMessage(selectedAdminId, text))
        writeStored(chatAdminKey(userId), selectedAdminId)
        setDraft('')
        return true
      } catch (err) {
        setSendError(sendErrorText(err))
        return false
      } finally {
        sendingRef.current = false
        setSending(false)
      }
    },
    [selectedAdminId, userId, putMessage],
  )

  const startEdit = useCallback((id) => setEdit({ id, error: null, saving: false }), [])
  const cancelEdit = useCallback(() => setEdit({ id: null, error: null, saving: false }), [])
  const saveEdit = useCallback(
    async (text) => {
      const id = edit.id
      setEdit((e) => ({ ...e, error: null, saving: true }))
      try {
        putMessage(await editChatMessage(id, text))
        setEdit({ id: null, error: null, saving: false })
      } catch (err) {
        if (err.response?.status === 403) setExpiredEdits((s) => new Set(s).add(id))
        setEdit({ id, error: editErrorText(err), saving: false })
      }
    },
    [edit.id, putMessage],
  )

  const loadOlder = useCallback(async () => {
    const oldest = messages[0]
    if (!oldest || loadingOlder) return
    setLoadingOlder(true)
    try {
      const page = await getChatMessages({ before: oldest.id, limit: PAGE_SIZE })
      qc.setQueryData(chatKeys.thread(userId), (old) =>
        old && { ...old, messages: mergeMessages(old.messages, page.messages), hasOlder: page.hasMore },
      )
    } catch {
      // the button stays; the user can press it again
    } finally {
      setLoadingOlder(false)
    }
  }, [messages, loadingOlder, qc, userId])

  const insertSummary = useCallback(async () => {
    setSummaryError(false)
    try {
      const data = await qc.fetchQuery({ queryKey: documentKeys.summary, queryFn: listDocumentsSummary, staleTime: 0 })
      const text = buildSummaryText(data)
      setDraft((d) => clampText(d ? `${d}\n${text}` : text))
      return true
    } catch {
      setSummaryError(true)
      return false
    }
  }, [qc])

  // Mark read only what the screen showed: nothing while the tab is hidden or scrolled away from the
  // newest message, and never beyond the newest message in the list at the moment of the call.
  const lastMarked = useRef(null)
  const polledAt = thread.dataUpdatedAt
  useEffect(() => {
    if (!active || !visible || !atBottom || incomingUnreadIds(messages).length === 0) return
    const upToId = newestId(messages)
    if (upToId === lastMarked.current) return
    lastMarked.current = upToId
    markChatRead(upToId).then(
      () => qc.invalidateQueries({ queryKey: chatKeys.unread(userId) }),
      () => { lastMarked.current = null },
    )
  }, [active, visible, atBottom, messages, polledAt, qc, userId])

  return {
    unread,
    messages,
    offset,
    now,
    hasOlder: thread.data?.hasOlder ?? false,
    loading: thread.isPending && active,
    loadOlder,
    loadingOlder,
    setAtBottom,
    admins: adminList,
    adminsState: admins.isSuccess ? 'ready' : admins.isError ? 'error' : 'loading',
    selectedAdminId,
    selectAdmin,
    color,
    setColor,
    colorFailed,
    draft,
    setDraft,
    send,
    sending,
    sendError,
    edit,
    expiredEdits,
    startEdit,
    cancelEdit,
    saveEdit,
    insertSummary,
    summaryError,
  }
}
