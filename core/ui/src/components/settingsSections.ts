/**
 * 设置 / 插件的分区清单与图标映射 — 唯一权威来源。
 *
 * SettingsShell 的内置导航和 LamToolsApp 的「会话栏当侧栏」竖排导航都从
 * 这里取同一份清单，保证两边永远一致。icon 字段填键名，渲染为 lucide 矢量。
 */
import {
  Activity,
  AppWindow,
  Bell,
  Bot,
  Braces,
  Brain,
  Brush,
  Circle,
  Database,
  Eye,
  FileCode2,
  Folder,
  Globe,
  Image as ImageIcon,
  Info,
  Layers,
  ListChecks,
  Lock,
  Palette,
  Plug,
  Puzzle,
  Scale,
  Search,
  Server,
  Smartphone,
  Settings2,
  Sparkles,
  UsersRound,
  Wand2,
  type LucideIcon,
} from 'lucide-vue-next'

export interface SettingsSection {
  id: string
  label: string
  icon?: string
  description?: string
}

/** 设置分区图标注册表：未注册的键回退到圆点。 */
const ICON_MAP: Record<string, LucideIcon> = {
  activity: Activity,
  'app-window': AppWindow,
  bell: Bell,
  bot: Bot,
  braces: Braces,
  brain: Brain,
  brush: Brush,
  database: Database,
  eye: Eye,
  'file-code': FileCode2,
  folder: Folder,
  globe: Globe,
  image: ImageIcon,
  info: Info,
  layers: Layers,
  'list-checks': ListChecks,
  lock: Lock,
  palette: Palette,
  puzzle: Puzzle,
  plug: Plug,
  scale: Scale,
  search: Search,
  server: Server,
  smartphone: Smartphone,
  settings: Settings2,
  sparkles: Sparkles,
  users: UsersRound,
  wand: Wand2,
}

export function settingsSectionIcon(icon: string | undefined): LucideIcon | null {
  if (!icon) return null
  return ICON_MAP[icon.toLowerCase()] || null
}

export const CORE_SETTINGS_SECTIONS: SettingsSection[] = [
  { id: 'models', label: '模型与供应商', icon: 'database' },
  { id: 'appearance', label: '界面', icon: 'palette' },
  { id: 'loadtools', label: '工具模式', icon: 'list-checks' },
  { id: 'permissions', label: '权限', icon: 'lock' },
  { id: 'mobile-control', label: '手机控制', icon: 'smartphone' },
  { id: 'agents', label: '上下文', icon: 'file-code' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
  { id: 'about', label: '关于与更新', icon: 'info' },
]

export const PLUGIN_SHELL_SECTIONS: SettingsSection[] = [
  { id: 'plugins', label: '插件', icon: 'puzzle' },
  { id: 'skills', label: '技能', icon: 'sparkles' },
  { id: 'hooks', label: '钩子', icon: 'plug' },
]

export const PROJECT_SETTINGS_SECTIONS: SettingsSection[] = [
  { id: 'project', label: '项目', icon: 'folder' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
]
