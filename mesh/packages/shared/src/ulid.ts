import { monotonicFactory } from 'ulid'

const MESSAGE_ID_REGEX = /^msg_[0-9A-HJKMNP-TV-Z]{26}$/

const monotonicUlid = monotonicFactory()

export type MessageId = `msg_${string}`

export function newMessageId(): MessageId {
  return `msg_${monotonicUlid()}` as MessageId
}

export function isValidMessageId(id: string): id is MessageId {
  return MESSAGE_ID_REGEX.test(id)
}

export function compareMessageIds(a: MessageId, b: MessageId): number {
  return a < b ? -1 : a > b ? 1 : 0
}
