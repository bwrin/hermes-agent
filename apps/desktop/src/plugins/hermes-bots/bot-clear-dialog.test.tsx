import type * as HermesSdk from '@hermes/plugin-sdk'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { ClearBotChatDialog } from './bot-clear-dialog'
import { translateBotsIn } from './i18n-test-helper'
import type { RosterRow } from './types'

const { requestForBot } = vi.hoisted(() => ({ requestForBot: vi.fn() }))

vi.mock('@hermes/plugin-sdk', async importOriginal => ({
  ...(await importOriginal<typeof HermesSdk>()),
  usePluginI18n: () => translateBotsIn('en')
}))
vi.mock('./routing', () => ({
  backendTargetProfile: (_route: unknown, profile: string) => profile,
  botConnectionRoute: () => ({ connectionId: 'local', profile: 'worker' }),
  requestForBot
}))

afterEach(cleanup)

it('cancel preserves the conversation, and an unsupported backend leaves confirmation open with an explanation', async () => {
  const onClose = vi.fn()
  const bot = { name: 'worker' } as RosterRow
  const first = render(<ClearBotChatDialog bot={bot} onClose={onClose} />)

  fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
  expect(onClose).toHaveBeenCalledOnce()
  expect(requestForBot).not.toHaveBeenCalled()
  first.unmount()

  requestForBot.mockRejectedValueOnce(new Error('Method not found (-32601)'))
  render(<ClearBotChatDialog bot={bot} onClose={onClose} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Clear chat' }))

  expect(await screen.findByText(/Update the gateway, then try again/)).toBeTruthy()
  expect(requestForBot).toHaveBeenCalledExactlyOnceWith(bot, 'session.clear_bot_chat', { profile: 'worker' })
  expect(onClose).toHaveBeenCalledOnce()
})
