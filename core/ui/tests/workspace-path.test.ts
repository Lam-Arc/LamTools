/**
 * `workspaceRelativePath` — the guard that keeps a message part's `uri` inside
 * the work root before it is handed to the desktop shell's asset protocol.
 */

import { describe, expect, it } from 'vitest'

import { workspaceRelativePath } from '../src/helpers/workspacePath'

describe('workspaceRelativePath', () => {
  it('passes through ordinary workspace paths', () => {
    expect(workspaceRelativePath('.lam/artifacts/run-1/image.png')).toBe('.lam/artifacts/run-1/image.png')
    expect(workspaceRelativePath('lam_projects/demo/out/图 1.png')).toBe('lam_projects/demo/out/图 1.png')
  })

  it('normalizes separators, dot segments and duplicates', () => {
    expect(workspaceRelativePath('lam_projects\\demo\\.\\out\\\\a.png')).toBe('lam_projects/demo/out/a.png')
    expect(workspaceRelativePath('/lam_projects/demo/a.png')).toBe('lam_projects/demo/a.png')
  })

  it('refuses anything that could leave the work root', () => {
    expect(workspaceRelativePath('../../Users/x/secret.png')).toBe('')
    expect(workspaceRelativePath('lam_projects/../../secret.png')).toBe('')
    expect(workspaceRelativePath('..\\..\\Windows\\System32\\config')).toBe('')
    expect(workspaceRelativePath('C:/Users/x/secret.png')).toBe('')
    expect(workspaceRelativePath('c:\\Users\\x\\secret.png')).toBe('')
  })

  it('ignores empty and non-string input', () => {
    expect(workspaceRelativePath('')).toBe('')
    expect(workspaceRelativePath('   ')).toBe('')
    expect(workspaceRelativePath(undefined)).toBe('')
    expect(workspaceRelativePath(null)).toBe('')
    expect(workspaceRelativePath(42)).toBe('')
  })
})
