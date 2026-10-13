import Database from 'better-sqlite3'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

export type Db = Database.Database

const __dirname = dirname(fileURLToPath(import.meta.url))
const SCHEMA_PATH = join(__dirname, 'schema.sql')

export function openDatabase(path: string): Db {
  const db = new Database(path)
  const schema = readFileSync(SCHEMA_PATH, 'utf8')
  db.exec(schema)
  migrateV1ToV2(db)
  return db
}

/**
 * Adds `last_active_at` to `human` for existing v1 databases. Fresh databases
 * get the column from schema.sql directly and this is a no-op.
 */
function migrateV1ToV2(db: Db): void {
  const cols = db.pragma('table_info(human)') as Array<{ name: string }>
  if (!cols.some(c => c.name === 'last_active_at')) {
    db.exec('ALTER TABLE human ADD COLUMN last_active_at TEXT')
    db.exec('UPDATE human SET last_active_at = created_at WHERE last_active_at IS NULL')
  }
  db.exec('INSERT OR IGNORE INTO schema_version(version) VALUES (2)')
  migrateV2ToV3(db)
}

/** v3: session-level addressing columns on `message`. */
function migrateV2ToV3(db: Db): void {
  const cols = db.pragma('table_info(message)') as Array<{ name: string }>
  for (const col of ['from_session', 'from_name', 'to_session']) {
    if (!cols.some(c => c.name === col)) db.exec(`ALTER TABLE message ADD COLUMN ${col} TEXT`)
  }
  db.exec('CREATE INDEX IF NOT EXISTS idx_message_to_session ON message(team_id, to_session, id)')
  db.exec('INSERT OR IGNORE INTO schema_version(version) VALUES (3)')
}

export function getSchemaVersion(db: Db): number {
  const row = db.prepare('SELECT MAX(version) AS v FROM schema_version').get() as { v: number | null }
  return row.v ?? 0
}

export function closeDatabase(db: Db): void {
  db.close()
}
