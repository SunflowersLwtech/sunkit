// Bundles the peer-agent and the `mesh` CLI into dependency-free files inside
// the Claude Code plugin, so a device needs only Node to run them.
import { build } from 'esbuild'

const common = {
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  legalComments: 'none',
  // Some deps still use require(); give ESM output a require() to call.
  banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
}
await build({ ...common, entryPoints: ['packages/peer-agent/src/index.ts'], outfile: 'plugins/mesh/server/mesh-peer.mjs' })
await build({ ...common, entryPoints: ['packages/peer-agent/src/cli.ts'], outfile: 'plugins/mesh/server/mesh-cli.mjs' })
console.log('bundled plugins/mesh/server/{mesh-peer,mesh-cli}.mjs')
