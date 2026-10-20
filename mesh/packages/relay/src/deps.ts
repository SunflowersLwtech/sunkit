import type { Db } from './db/db.ts'
import type { MessageStore } from './messages/store.ts'
import type { Fanout } from './fanout.ts'
import type { PresenceRegistry } from './presence/registry.ts'
import type { SessionRegistry } from './sessions/registry.ts'
import type { TaskStore } from './ledger/tasks.ts'
import type { LeaseStore } from './ledger/leases.ts'
import type { CommandQueue, MachineRegistry } from './machines/registry.ts'

export interface Deps {
  db: Db
  store: MessageStore
  fanout: Fanout
  presence: PresenceRegistry
  sessions?: SessionRegistry
  tasks?: TaskStore
  leases?: LeaseStore
  machines?: MachineRegistry
  commands?: CommandQueue
  now: () => Date
}
