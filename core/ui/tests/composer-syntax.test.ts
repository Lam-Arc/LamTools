import { describe, expect, it } from 'vitest';
import type { CoreCommandCatalogItem } from '../src/types';
import { findActiveSlashCandidate, parseComposerInput, parseComposerSyntax } from '../src/composer/syntax';

const commands: CoreCommandCatalogItem[] = [
  {
    name: 'compact',
    title: 'Compact',
    description: '',
    icon: '/',
    source: 'core',
    action: 'run_action',
    kind: 'action',
  },
  {
    name: 'goal',
    title: 'Goal',
    description: '',
    icon: '/',
    source: 'core',
    action: 'run_action',
    kind: 'action',
    accepts_args: true,
  },
  {
    name: 'reviewer',
    title: 'Reviewer',
    description: '',
    icon: '/',
    source: 'core',
    action: 'insert_token',
    kind: 'skill',
    accepts_args: true,
  },
];

describe('parseComposerSyntax', () => {
  it('parses slash commands only at input start or after whitespace', () => {
    expect(parseComposerSyntax('/compact')).toMatchObject([
      { kind: 'slash', start: 0, end: 8, value: 'compact' },
    ]);
    expect(parseComposerSyntax('请用 /brainstorming 梳理一下')).toMatchObject([
      { kind: 'slash', value: 'brainstorming' },
    ]);
    expect(parseComposerSyntax('abc/compact')).toEqual([]);
    expect(parseComposerSyntax('https://example.com/a/b')).toEqual([]);
    expect(parseComposerSyntax('C:/tmp/a.txt')).toEqual([]);
  });

  it('ignores slash commands inside quotes and markdown code', () => {
    expect(parseComposerSyntax('"/compact"')).toEqual([]);
    expect(parseComposerSyntax('\'/compact\'')).toEqual([]);
    expect(parseComposerSyntax('`/compact`')).toEqual([]);
    expect(parseComposerSyntax('```md\n/compact\n```')).toEqual([]);
  });

  it('keeps at-resource parsing aligned with slash parsing', () => {
    expect(parseComposerSyntax('@E:\\tmp\\a.txt')).toMatchObject([
      { kind: 'resource', value: 'E:\\tmp\\a.txt' },
    ]);
    expect(parseComposerSyntax('abc@E:\\tmp\\a.txt')).toEqual([]);
    expect(parseComposerSyntax('email@example.com')).toEqual([]);
    expect(parseComposerSyntax('`@E:\\tmp\\a.txt`')).toEqual([]);
  });

  it('finds the active slash candidate at the cursor', () => {
    const text = '请用 /comp';
    expect(findActiveSlashCandidate(text, text.length)).toMatchObject({
      kind: 'slash',
      value: 'comp',
    });
    expect(findActiveSlashCandidate('abc/comp', 8)).toBeNull();
  });

  it('parses only a known leading command and keeps its arguments intact', () => {
    expect(parseComposerInput('/compact', commands)).toEqual({
      kind: 'action',
      name: 'compact',
      arguments: '',
    });
    expect(parseComposerInput('/goal 创建发布计划', commands)).toEqual({
      kind: 'action',
      name: 'goal',
      arguments: '创建发布计划',
    });
    expect(parseComposerInput('/reviewer inspect these changes', commands)).toEqual({
      kind: 'skill',
      name: 'reviewer',
      arguments: 'inspect these changes',
    });
  });

  it('does not turn prose, unknown commands, quotes, or code into executable commands', () => {
    expect(parseComposerInput('帮我执行 /goal', commands)).toBeNull();
    expect(parseComposerInput('/unknown xxx', commands)).toBeNull();
    expect(parseComposerInput('"/goal 创建发布计划"', commands)).toBeNull();
    expect(parseComposerInput('```md\n/goal 创建发布计划\n```', commands)).toBeNull();
  });
});
