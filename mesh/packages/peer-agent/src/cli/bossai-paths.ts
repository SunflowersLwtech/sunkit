import { homedir } from 'node:os'
import { join } from 'node:path'

/** Electron userData of the desktop app, per platform (app name "@bossai/desktop"). Kept apart so meshd can import it alone. */
export function bossaiPortFile(platform: NodeJS.Platform, env: NodeJS.ProcessEnv = process.env, home: string = homedir()): string {
  const base = platform === 'darwin'
    ? join(home, 'Library', 'Application Support')
    : platform === 'win32'
      ? (env.APPDATA ?? join(home, 'AppData', 'Roaming'))
      : (env.XDG_CONFIG_HOME ?? join(home, '.config'))
  return join(base, '@bossai', 'desktop', 'desktop-server-port.json')
}
