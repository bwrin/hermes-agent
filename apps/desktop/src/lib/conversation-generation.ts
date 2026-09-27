/** A clear revokes reads already in flight for exactly one conversation owner. */
export interface ConversationScope {
  connectionId?: string | null
  profile?: string | null
}

export interface ConversationClear {
  scope: ConversationScope
  sessionIds: string[]
  generation: number
  runtimeSessionId?: string
}

const generations = new Map<string, number>()
const listeners = new Set<(clear: ConversationClear) => void>()

export function conversationScopeKey(scope: ConversationScope): string {
  return JSON.stringify([scope.connectionId?.trim() || 'local', scope.profile?.trim() || 'default'])
}

function key(sessionId: string, scope: ConversationScope): string {
  return `${conversationScopeKey(scope)}:${sessionId}`
}

export function conversationGeneration(sessionId: string, scope: ConversationScope): number {
  return generations.get(key(sessionId, scope)) ?? 0
}

export function observeConversationGeneration(clear: ConversationClear): void {
  if (!Number.isSafeInteger(clear.generation) || clear.generation < 0) {
    return
  }

  const sessionIds = [...new Set(clear.sessionIds.filter(Boolean))]
  const changed = sessionIds.some(id => clear.generation > conversationGeneration(id, clear.scope))

  for (const id of sessionIds) {
    generations.set(key(id, clear.scope), Math.max(clear.generation, conversationGeneration(id, clear.scope)))
  }

  // An initial zero is an ordinary old/uncleared conversation. A first positive
  // generation also revokes disk caches when the clear happened while offline.
  if (changed) {
    for (const listener of listeners) {
      listener({ ...clear, sessionIds })
    }
  }
}

export function onConversationCleared(listener: (clear: ConversationClear) => void): () => void {
  listeners.add(listener)

  return () => void listeners.delete(listener)
}

export function captureConversationRead(sessionId: string, scope: ConversationScope) {
  const generation = conversationGeneration(sessionId, scope)

  return (responseGeneration?: number, resolvedSessionId = sessionId) => {
    const current = Math.max(conversationGeneration(sessionId, scope), conversationGeneration(resolvedSessionId, scope))

    if (responseGeneration === undefined ? current !== generation : responseGeneration < current) {
      throw new Error('This conversation was cleared while its history was loading. Please try again.')
    }

    if (responseGeneration !== undefined) {
      observeConversationGeneration({
        generation: responseGeneration,
        scope,
        sessionIds: [sessionId, resolvedSessionId]
      })
    }
  }
}
