import type { Db } from './db/db.ts'
import type { MessageStore } from './messages/store.ts'
import type { Fanout } from './fanout.ts'
import type { PresenceRegistry } from './presence/registry.ts'
import type { SessionRegistry } from './sessions/registry.ts'

export interface Deps {
  db: Db
  store: MessageStore
  fanout: Fanout
  presence: PresenceRegistry
  sessions?: SessionRegistry
  now: () => Date
}
