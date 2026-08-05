import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

const frontendRoot = resolve(import.meta.dirname, '../..')
const repoRoot = resolve(frontendRoot, '../../..')

function sourceFiles(root: string): string[] {
  return readdirSync(root, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.(ts|vue|css)$/.test(entry.name))
    .map((entry) => resolve(entry.parentPath, entry.name))
}

test('Writer imports Core UI through its public package boundary', () => {
  const writerSource = [
    ...sourceFiles(resolve(frontendRoot, 'src')),
    resolve(frontendRoot, 'vite.config.ts'),
    resolve(frontendRoot, 'tsconfig.app.json'),
  ]
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n')
  const packageJson = JSON.parse(readFileSync(resolve(frontendRoot, 'package.json'), 'utf8'))
  const packageLock = JSON.parse(readFileSync(resolve(frontendRoot, 'package-lock.json'), 'utf8'))

  assert.doesNotMatch(writerSource, /core[\\/]ui[\\/]src/)
  assert.equal(packageJson.dependencies?.['@lamtools/ui'], 'file:../../../core/ui')
  assert.equal(packageLock.packages?.['']?.dependencies?.['@lamtools/ui'], 'file:../../../core/ui')
})

test('Writer loads the Core UI stylesheet from its public export', () => {
  const entry = readFileSync(resolve(frontendRoot, 'src/main.ts'), 'utf8')

  assert.match(entry, /import ['"]@lamtools\/ui\/styles\.css['"]/)
})

test('Core UI stays product-neutral and Writer avoids the legacy REST workbench name', () => {
  const coreSource = sourceFiles(resolve(repoRoot, 'core/ui/src'))
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n')
  const writerSource = sourceFiles(resolve(frontendRoot, 'src'))
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n')

  assert.doesNotMatch(coreSource, /writer-shell|writer-main/)
  assert.doesNotMatch(coreSource, /\b(?:writer|artist)\b/i)
  assert.doesNotMatch(coreSource, /(?:use|CoreRest)Workbench/)
  assert.doesNotMatch(writerSource, /(?:use|CoreRest)Workbench/)
})
