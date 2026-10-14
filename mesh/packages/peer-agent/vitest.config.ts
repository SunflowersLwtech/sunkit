import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    testTimeout: 10_000,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: [
        'src/**/*.test.ts',
        // Entry points and CLI glue — covered by the L3 integration tests
        // in packages/e2e (gated behind CLAUDE_DRIVER=cli). Unit-testing
        // them here would just mock filesystem/stdin/fetch, which isn't
        // a useful signal.
        'src/index.ts',
        'src/cli.ts',
        'src/cli/send.ts',
        'src/cli/admin.ts',
        'src/cli/pair.ts',
        'src/cli/respond.ts',
        'src/mcp-registration.ts',
        // SSE client — reconnect loop with infinite fetch is better covered
        // by the e2e harness than a mock-heavy unit test.
        'src/stream.ts'
      ],
      // Thresholds reflect current measured coverage for business-logic
      // files (CLI glue + SSE client are excluded above). The validation-
      // branch coverage of tools.ts, config.ts, and roots.ts has room to
      // grow — see the follow-ups list in README §Caveats.
      thresholds: { lines: 80, functions: 80, branches: 70, statements: 80 }
    }
  }
})
