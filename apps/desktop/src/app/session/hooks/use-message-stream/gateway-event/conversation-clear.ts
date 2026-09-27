import type { GatewayEvent } from '@hermes/shared'
import { useEffect } from 'react'

import {
  type ConversationClear,
  conversationGeneration,
  type ConversationScope,
  conversationScopeKey,
  observeConversationGeneration,
  onConversationCleared
} from '@/lib/conversation-generation'
import { clearInFlightTurnJournal } from '@/lib/inflight-turn-journal'
import { clearClarifyRequest } from '@/store/clarify'
import { $activeGatewayProfile } from '@/store/profile'
import { clearAllPrompts } from '@/store/prompts'
import { clearSessionProviderWait } from '@/store/provider-wait'
import { getSessionOwnerHint } from '@/store/session'
import { clearSessionControl } from '@/store/session-control'
import { knownOwnerForSession } from '@/store/session-states'
import { clearSessionTodos } from '@/store/todos'
import { setSessionDraftingTool } from '@/store/tool-drafting'
import { clearTranscriptTail } from '@/store/transcript-tail'
import { dropTranscriptTail } from '@/store/transcript-tail-cache'

import { invalidatePersistedDisplayTranscriptAuthority } from '../../use-session-actions/transcript-provenance'

import type { GatewayEventDeps } from './types'

function runtimeScope(runtimeId: string, deps: GatewayEventDeps): ConversationScope | null {
  const provenance = deps.sessionStateByRuntimeIdRef.current.get(runtimeId)?.transcriptProvenance

  if (provenance) {
    return provenance
  }

  const owner = knownOwnerForSession(runtimeId)

  if (owner) {
    return typeof owner === 'string' ? { profile: owner } : owner
  }

  return null
}

/** A clear reaches every cached tile; only updateSessionState decides which view paints. */
function clearCachedConversation(clear: ConversationClear, deps: GatewayEventDeps): void {
  for (const storedId of clear.sessionIds) {
    dropTranscriptTail(storedId, clear.scope)

    // The existing disk cache retains the request spelling: both an explicit
    // local route and the untagged primary address this same backend.
    if (!clear.scope.connectionId || clear.scope.connectionId === 'local') {
      dropTranscriptTail(storedId, { ...clear.scope, connectionId: clear.scope.connectionId ? null : 'local' })
    }

    clearTranscriptTail(storedId, clear.scope)
  }

  for (const [runtimeId, state] of deps.sessionStateByRuntimeIdRef.current) {
    if (runtimeId !== clear.runtimeSessionId && !clear.sessionIds.includes(state.storedSessionId ?? '')) {
      continue
    }

    const owner = runtimeScope(runtimeId, deps)

    if (
      owner ? conversationScopeKey(owner) !== conversationScopeKey(clear.scope) : runtimeId !== clear.runtimeSessionId
    ) {
      continue
    }

    deps.dropQueuedDeltas(runtimeId)
    deps.compactedTurnRef.current.delete(runtimeId)
    clearAllPrompts(runtimeId)
    clearClarifyRequest(undefined, runtimeId)
    clearSessionControl(runtimeId)
    clearSessionProviderWait(runtimeId)
    clearSessionTodos(runtimeId)
    setSessionDraftingTool(runtimeId, '')
    clearInFlightTurnJournal(state.storedSessionId)
    deps.updateSessionState(runtimeId, previous =>
      invalidatePersistedDisplayTranscriptAuthority({
        ...previous,
        messages: [],
        busy: false,
        awaitingResponse: false,
        streamId: null,
        sawAssistantPayload: false,
        adoptedRunningTurn: false,
        pendingBranchGroup: null,
        interrupted: false,
        interimBoundaryPending: false,
        heartbeatSettledStreamId: null,
        needsInput: false,
        turnStartedAt: null,
        turnLive: false,
        usage: null
      })
    )
  }

  deps.scheduleSessionsRefresh()
}

export function useConversationClear(deps: GatewayEventDeps): void {
  const {
    activeSessionIdRef,
    compactedTurnRef,
    dropQueuedDeltas,
    scheduleSessionsRefresh,
    sessionStateByRuntimeIdRef,
    updateSessionState
  } = deps

  useEffect(
    () => onConversationCleared(clear => clearCachedConversation(clear, deps)),
    // The handler's other dependencies do not participate in clearing state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      activeSessionIdRef,
      compactedTurnRef,
      dropQueuedDeltas,
      scheduleSessionsRefresh,
      sessionStateByRuntimeIdRef,
      updateSessionState
    ]
  )
}

/** Generation checks precede routing, so old background/replayed events cannot recreate a row. */
export function admitConversationEvent(event: GatewayEvent, deps: GatewayEventDeps): boolean {
  const payload = event.payload as
    | {
        conversation_generation?: number
        profile?: string | null
        session_ids?: string[]
        stored_session_id?: string
      }
    | undefined

  const generation = event.conversation_generation ?? payload?.conversation_generation

  if (typeof generation !== 'number') {
    return true
  }

  const storedId =
    payload?.stored_session_id ||
    (event.session_id ? deps.sessionStateByRuntimeIdRef.current.get(event.session_id)?.storedSessionId : null)

  const sessionIds = payload?.session_ids ?? (storedId ? [storedId] : [])

  const scope = (event.type !== 'session.conversation_cleared' && event.session_id
    ? runtimeScope(event.session_id, deps)
    : null) || {
    connectionId: event.connectionId,
    profile: payload?.profile || event.profile || $activeGatewayProfile.get()
  }

  const scopes: ConversationScope[] = [scope]

  // Global clears name the backend profile, while remote Desktop aliases have
  // their own cache keys. Translate only through an established owner route;
  // the active socket's presentation profile is not authority for a broadcast.
  for (const id of [event.session_id, ...sessionIds]) {
    if (!id) {
      continue
    }

    const owner = knownOwnerForSession(id) || getSessionOwnerHint(id)

    if (
      owner &&
      typeof owner === 'object' &&
      (owner.connectionId || 'local') === (scope.connectionId || 'local') &&
      (owner.targetProfile || owner.profile) === scope.profile
    ) {
      scopes.push(owner)
    }
  }

  if (scopes.some(owner => sessionIds.some(id => generation < conversationGeneration(id, owner)))) {
    return false
  }

  for (const owner of scopes) {
    observeConversationGeneration({ generation, scope: owner, sessionIds, runtimeSessionId: event.session_id })
  }

  return event.type !== 'session.conversation_cleared'
}
