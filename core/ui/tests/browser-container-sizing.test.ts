// @vitest-environment node
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'
import { webviewBoundsArgs } from '@/split/native'

it('rounds the viewport edges together when the container has fractional CSS coordinates', () => {
  const args = webviewBoundsArgs({
    surfaceId: 'float',
    visible: true,
    contentRect: { x: 10, y: 20.4, width: 459.6, height: 542 },
  }, 1.25)
  expect(args.x + args.width).toBe(Math.round(469.6 * 1.25))
  expect(args.y + args.height).toBe(Math.round(562.4 * 1.25))
})

it('does not pull the session header above the scrollable split pane', () => {
  const css = readFileSync('src/styles/split-workspace.css', 'utf8')
  expect(css).toMatch(/\.workspace-shell--split \.workspace-main > \[data-session-header\]\s*\{[^}]*margin-top:\s*0/)
})
