import { describe, expect, it } from 'vitest'

import { buildGuideChapters, flattenGuideSteps } from '../src/guide/guideScript.ts'
import type { GuideChapter } from '../src/guide/types.ts'

/**
 * user:“诉求是让哪怕没接触过电脑的小白也能用明白sunday”+
 * (内容可以改，但结构不能坏：章节要有步骤、每个指向真实界面的步骤必须有
 *  可定位的选择器，否则那一步会变成对着空气说话的空白卡片。)
 */

const fullOptions = { mode: 'full' as const, beginner: true, hasProvider: true }
const quickOptions = { mode: 'quick' as const, beginner: false, hasProvider: true }

function allSteps(chapters: GuideChapter[]) {
  return chapters.flatMap(chapter => chapter.steps)
}

describe('guide script', () => {
  it('keeps the beginner path first and includes every room in the full tour', () => {
    const chapters = buildGuideChapters(fullOptions)
    expect(chapters.map(chapter => chapter.id)).toEqual([
      'basics', 'welcome', 'interface', 'demo', 'knobs', 'rooms', 'desktop', 'provider', 'finish',
    ])
  })

  it('drops optional chapters in the quick tour and skips basics for experienced users', () => {
    const chapters = buildGuideChapters(quickOptions)
    expect(chapters.map(chapter => chapter.id)).toEqual(['welcome', 'interface', 'demo', 'finish'])
    expect(chapters.map(chapter => chapter.id)).not.toContain('basics')
  })

  it('teaches every rail area the user asked about', () => {
    const chapters = buildGuideChapters(fullOptions)
    const rooms = chapters.find(chapter => chapter.id === 'rooms')
    const targets = rooms?.steps.map(step => (
      step.kind === 'spotlight' ? step.target : ''
    )) ?? []
    expect(targets).toEqual([
      '[data-rail-entry="direct"]',
      '[data-rail-entry="superagent"]',
      '[data-rail-entry="arrange"]',
      '[data-rail-entry="library"]',
      '[data-rail-entry="plugins"]',
      '[data-rail-entry="settings"]',
    ])
    const desktop = chapters.find(chapter => chapter.id === 'desktop')
    expect(desktop?.steps.map(step => step.id)).toEqual(['desktop-ping', 'desktop-pet'])
  })

  it('points provider guidance at the right branch', () => {
    const missing = buildGuideChapters(fullOptions).find(chapter => chapter.id === 'provider')
    expect(missing?.steps[0]?.id).toBe('provider-configured')
    const unconfigured = buildGuideChapters({ ...fullOptions, hasProvider: false }).find(chapter => chapter.id === 'provider')
    expect(unconfigured?.steps[0]?.id).toBe('provider-missing')
  })

  it('keeps ids unique and visible copy filled in', () => {
    const steps = allSteps(buildGuideChapters(fullOptions))
    const ids = steps.map(step => step.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const step of steps) {
      expect(step.title.trim().length).toBeGreaterThan(0)
      expect(step.body.trim().length).toBeGreaterThan(0)
      if (step.kind === 'spotlight') {
        expect(step.target.trim().length).toBeGreaterThan(0)
      }
    }
  })

  it('flattens into one linear path with stable ordinals', () => {
    const chapters = buildGuideChapters(fullOptions)
    const steps = flattenGuideSteps(chapters)
    const expected = chapters.reduce((sum, chapter) => sum + chapter.steps.length, 0)
    expect(steps).toHaveLength(expected)
    expect(steps.map(item => item.ordinal)).toEqual(steps.map((_, index) => index + 1))
    expect(steps.every(item => item.total === expected)).toBe(true)
    expect(steps[0].chapterTitle).toBe('先会三件小事')
  })
})
