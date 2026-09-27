import { ConfirmDialog, host } from '@hermes/plugin-sdk'

import { clearBotCanonicalChat } from './bot-clear'
import { useBots } from './i18n'
import type { RosterRow } from './types'

export function ClearBotChatDialog({ bot, onClose }: { bot: RosterRow | null; onClose: () => void }) {
  const b = useBots()

  return (
    <ConfirmDialog
      busyLabel={b.bot.clearingChat}
      confirmLabel={b.bot.clearChatAction}
      description={b.bot.clearChatDescription}
      destructive
      doneLabel={b.bot.chatCleared}
      onClose={onClose}
      onConfirm={async () => {
        if (bot) {
          await clearBotCanonicalChat(bot)
          host.notify({ kind: 'success', message: b.bot.chatCleared })
        }
      }}
      open={Boolean(bot)}
      title={b.bot.clearChatTitle}
    />
  )
}
