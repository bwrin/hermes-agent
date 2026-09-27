import type { GatewayEvent } from './gateway-events.js'

/** Runtime ids are backend-unique; a clear keeps that id but retires its old frames. */
export class ConversationEventFence {
  private generations = new Map<string, number>()

  admit(event: GatewayEvent): boolean {
    const generation =
      event.conversation_generation ??
      (event.type === 'session.conversation_cleared'
        ? (event as GatewayEvent<'session.conversation_cleared'>).payload?.conversation_generation
        : undefined)

    const id = event.session_id

    if (!id || generation === undefined) {
      return true
    }

    if (generation < (this.generations.get(id) ?? 0)) {
      return false
    }

    this.generations.set(id, generation)

    return true
  }

  checkSnapshot(method: string, params: Record<string, unknown>, result: unknown): void {
    if (
      !['session.resume', 'session.activate', 'session.history', 'session.events.since'].includes(method) ||
      !result ||
      typeof result !== 'object'
    ) {
      return
    }

    const snapshot = result as { session_id?: string; conversation_generation?: number }
    const id = snapshot.session_id || (typeof params.session_id === 'string' ? params.session_id : '')

    if (
      snapshot.conversation_generation !== undefined &&
      snapshot.conversation_generation < (this.generations.get(id) ?? 0)
    ) {
      throw new Error('This conversation was cleared while its history was loading. Please try again.')
    }

    if (id && snapshot.conversation_generation !== undefined) {
      this.generations.set(id, snapshot.conversation_generation)
    }
  }
}
