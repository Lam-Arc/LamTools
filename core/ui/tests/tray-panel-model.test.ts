/**
 * 托盘面板条目验收。
 *
 * user:“上面不需要标题和状态，多此一举了”“这个东西不需要小字”+
 * (只保留四行可点项，两个开关反映真实可见性。)
 */
import { describe, expect, it } from 'vitest'
import { trayRows } from '@/tray/model.ts'

describe('托盘面板条目', () => {
  it('顺序固定为界面、桌宠、标注层、退出', () => {
    const rows = trayRows({ petOpen: false, overlayOpen: false })
    expect(rows.map(row => row.id)).toEqual(['main', 'pet', 'overlay', 'quit'])
  })

  it('两个开关反映真实可见性', () => {
    const closed = trayRows({ petOpen: false, overlayOpen: false })
    expect(closed.find(row => row.id === 'pet')?.value).toBe(false)
    expect(closed.find(row => row.id === 'overlay')?.value).toBe(false)

    const open = trayRows({ petOpen: true, overlayOpen: true })
    expect(open.find(row => row.id === 'pet')?.value).toBe(true)
    expect(open.find(row => row.id === 'overlay')?.value).toBe(true)
  })

  it('桌宠和标注层带开关，界面和退出不带', () => {
    const rows = trayRows({ petOpen: true, overlayOpen: false })
    expect(rows.filter(row => row.kind === 'toggle').map(row => row.id)).toEqual(['pet', 'overlay'])
    expect(rows.find(row => row.id === 'main')?.kind).toBe('action')
    expect(rows.find(row => row.id === 'quit')?.kind).toBe('danger')
  })

  it('每行只有一句标签，不带解释小字', () => {
    const rows = trayRows({ petOpen: true, overlayOpen: true })
    expect(rows.every(row => Object.keys(row).sort().join(',') === 'id,kind,title,value'
      || Object.keys(row).sort().join(',') === 'id,kind,title')).toBe(true)
    expect(rows.map(row => row.title)).toEqual(['打开界面', '桌宠', '交互层', '退出'])
  })
})
