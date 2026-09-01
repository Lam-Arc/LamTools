import type { Component } from 'vue'
import {
  Archive,
  Box,
  Brain,
  GitFork,
  PawPrint,
  Puzzle,
  Sparkles,
  SquareTerminal,
  Target,
} from 'lucide-vue-next'
import { resolveComposerCommandKind } from './syntax.ts'
import type { CoreCommandCatalogItem } from '../types.ts'

const icons: Record<string, Component> = {
  archive: Archive,
  brain: Brain,
  box: Box,
  cube: Box,
  cuboid: Box,
  'git-branch': GitFork,
  'git-fork': GitFork,
  'paw-print': PawPrint,
  puzzle: Puzzle,
  sparkles: Sparkles,
  target: Target,
}

export function coreCommandIcon(command: CoreCommandCatalogItem): Component {
  return icons[command.icon] || (resolveComposerCommandKind(command) === 'skill' ? Sparkles : SquareTerminal)
}
