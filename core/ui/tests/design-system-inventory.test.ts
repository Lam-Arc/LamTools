import { describe, expect, it } from 'vitest'
import { analyzeSource, renderInventory } from '../../../scripts/ui-inventory.mjs'

describe('UI inventory', () => {
  it('identifies visible controls, layout and motion while preserving source paths', () => {
    const file = analyzeSource('core/ui/src/components/Example.vue', '<template><button @click="save">Save</button><input type="range"></template><style>.grid { display: grid; animation: spin 1s }</style>')
    expect(file.signals).toEqual(expect.arrayContaining(['button', 'range', 'grid', 'animation', 'event']))
    const report = renderInventory([file])
    expect(report).toContain('core/ui/src/components/Example.vue')
    expect(report).toContain('range')
  })
  it('does not infer controls from plain filenames or ordinary text', () => {
    const file = analyzeSource('core/ui/src/Switch.vue', '<template><p>switch</p></template>')
    expect(file.signals).not.toContain('switch')
    expect(file.signals).not.toContain('button')
  })
  it('identifies candidate native controls without flagging the shared checkbox or switch', () => {
    const source = `<template><select aria-label="测试"></select><input type="checkbox"><input class="sunday-checkbox" type="checkbox"><input class="sunday-switch__input" type="checkbox"><input type="range"></template>`
    const file = analyzeSource('core/ui/src/components/Example.vue', source)
    expect(file.nativeCandidates).toEqual({ select: 1, checkbox: 1, range: 1 })
    expect(renderInventory([file])).toContain('原生控件候选')
    expect(renderInventory([file])).toContain('select: 1、checkbox: 1、range: 1')
  })

})
