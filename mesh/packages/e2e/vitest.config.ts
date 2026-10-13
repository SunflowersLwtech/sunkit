import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    testTimeout: 60_000,
    hookTimeout: 30_000,
    maxConcurrency: 1,
    pool: 'forks',
    poolOptions: { forks: { singleFork: true } },
  },
})
