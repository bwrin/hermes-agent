import { act, cleanup } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { setApiRequestConnection, setApiRequestLocalMode, setApiRequestProfile } from '@/api/client'
import { getLatestSessionMessages } from '@/api/sessions'
import { createClientSessionState } from '@/lib/chat-runtime'
import { $activeGatewayProfile } from '@/store/profile'
import { setSessionOwnerHint } from '@/store/session'
import { requestForSessionProfile } from '@/store/session-request-router'
import { clearAllSessionStates } from '@/store/session-states'
import { loadTranscriptTail, saveTranscriptTail } from '@/store/transcript-tail-cache'

import { createPersistedDisplayTranscriptProvenance } from '../use-session-actions/transcript-provenance'

import { renderMessageStream } from './test-harness'

const owner = { connectionId: 'local', profile: 'default' }
const oldMessage = { id: 'old', role: 'assistant' as const, parts: [{ type: 'text' as const, text: 'old answer' }] }

function state(storedId: string, profile = 'default', connectionId = 'local') {
  return {
    ...createClientSessionState(storedId, [oldMessage]),
    model: 'chosen-model',
    transcriptProvenance: createPersistedDisplayTranscriptProvenance({
      lineageRootId: null,
      scope: { connectionId, profile },
      storedSessionId: storedId
    })
  }
}

afterEach(() => {
  cleanup()
  clearAllSessionStates()
  setApiRequestProfile(null)
  setApiRequestConnection(null)
  setApiRequestLocalMode(false)
  Reflect.deleteProperty(window, 'hermesDesktop')
  localStorage.clear()
})

it.each([
  { connectionId: 'local', profile: 'default', targetProfile: 'default' },
  { connectionId: 'remote', profile: 'alias', targetProfile: 'backend-worker' }
])('clears every viewer and background lineage cache for $profile, fencing old history and events', async owner => {
  setApiRequestLocalMode(true)
  setApiRequestConnection(owner.connectionId)
  setApiRequestProfile(owner.profile)
  $activeGatewayProfile.set('other-active-profile')
  const storedId = `clear-broadcast-tip-${owner.profile}`
  const rootId = `clear-broadcast-root-${owner.profile}`
  setSessionOwnerHint(storedId, owner)
  setSessionOwnerHint(rootId, owner)

  const states = () =>
    new Map([
      ['runtime-clear', state(storedId, owner.profile, owner.connectionId)],
      ['runtime-background', state(rootId, owner.profile, owner.connectionId)],
      ['runtime-other-profile', state(storedId, 'other', owner.connectionId)],
      ['runtime-side', state('side-chat')]
    ])

  const first = renderMessageStream('runtime-clear', { states: states() })
  const second = renderMessageStream('runtime-side', { states: states() })
  saveTranscriptTail(storedId, [oldMessage], owner)
  saveTranscriptTail(storedId, [oldMessage], { ...owner, profile: 'other' })

  let resolveHistory!: (value: unknown) => void
  Object.defineProperty(window, 'hermesDesktop', {
    configurable: true,
    value: {
      api: vi.fn(
        () =>
          new Promise(resolve => {
            resolveHistory = resolve
          })
      )
    }
  })
  const history = getLatestSessionMessages(storedId, owner)
  const staleHistory = expect(history).rejects.toThrow(/conversation was cleared/)

  act(() => {
    first.handleEvent({
      type: 'session.conversation_cleared',
      connectionId: owner.connectionId,
      profile: 'other-active-profile',
      payload: {
        profile: owner.targetProfile,
        stored_session_id: storedId,
        session_ids: [rootId, storedId],
        conversation_generation: 1
      }
    })
    first.handleEvent({
      type: 'message.complete',
      session_id: 'runtime-clear',
      connectionId: owner.connectionId,
      profile: owner.profile,
      conversation_generation: 0,
      payload: { text: 'late old reply' }
    })
  })
  resolveHistory({
    session_id: storedId,
    conversation_generation: 0,
    messages: [{ role: 'assistant', content: 'old answer' }]
  })
  await staleHistory

  for (const viewer of [first, second]) {
    expect(viewer.state('runtime-clear').messages).toEqual([])
    expect(viewer.state('runtime-background').messages).toEqual([])
    expect(viewer.state('runtime-clear').model).toBe('chosen-model')
    expect(viewer.state('runtime-clear').transcriptAuthorityEpoch).toBeGreaterThan(0)
    expect(viewer.state('runtime-other-profile').messages).toEqual([oldMessage])
    expect(viewer.state('runtime-side').messages).toEqual([oldMessage])
  }

  expect(loadTranscriptTail(storedId, owner)).toBeNull()
  expect(loadTranscriptTail(storedId, { ...owner, profile: 'other' })).toEqual([oldMessage])

  act(() =>
    first.handleEvent({
      type: 'message.complete',
      session_id: 'runtime-clear',
      connectionId: owner.connectionId,
      profile: owner.profile,
      conversation_generation: 1,
      payload: { text: 'new reply' }
    })
  )
  expect(first.text()).toBe('new reply')
})

it('a fresh resume after an offline clear invalidates cached history before its result is used', async () => {
  setApiRequestProfile('default')
  const storedId = 'clear-offline-stored'

  const viewer = renderMessageStream('runtime-offline', {
    states: new Map([['runtime-offline', state(storedId)]])
  })

  saveTranscriptTail(storedId, [oldMessage], owner)

  const request = vi.fn().mockResolvedValue({
    session_id: 'runtime-offline',
    resumed: storedId,
    conversation_generation: 2,
    messages: []
  })

  await act(async () => {
    await requestForSessionProfile(undefined, request, 'session.resume', { session_id: storedId })
  })
  expect(viewer.state().messages).toEqual([])
  expect(loadTranscriptTail(storedId, owner)).toBeNull()

  request.mockResolvedValue({
    session_id: 'runtime-offline',
    resumed: storedId,
    conversation_generation: 1,
    messages: [oldMessage]
  })
  await expect(
    requestForSessionProfile(undefined, request, 'session.resume', { session_id: storedId })
  ).rejects.toThrow(/conversation was cleared/)
})
