/** Shared, low-saturation theme presets. */
import {
  SUNDAY_DARK_THEME,
  SUNDAY_LIGHT_THEME,
  type ThemeData,
  type ThemePreset,
} from '../helpers/theme'

const theme = (overrides: Partial<ThemeData>): Partial<ThemeData> => overrides
const solid = (color: string) => [{ color, position: 0 }]
const neutralDark = theme({
  backdropStops: solid('#242424'), backdropAngle: 180, backdropText: '#f2efeb',
  mainStops: solid('#151515'), mainAngle: 180, mainText: '#f2efeb', mainOpacity: 1,
  composerStops: solid('#303030'), composerAngle: 180, composerText: '#f2efeb', composerOpacity: 1,
  controlStops: solid('#3d3d3d'), controlAngle: 180, controlText: '#f3eee8', controlOpacity: 1,
  processIconColor: '#a493ff',
})

const neutralLight = theme({
  backdropStops: solid('#dfdfdf'), backdropAngle: 180, backdropText: '#1f1f1f',
  mainStops: solid('#f8f8ef'), mainAngle: 180, mainText: '#1f1f1f', mainOpacity: 1,
  composerStops: solid('#efefef'), composerAngle: 180, composerText: '#1f1f1f', composerOpacity: 1,
  controlStops: solid('#d8d8d8'), controlAngle: 180, controlText: '#1f1f1f', controlOpacity: 1,
  processIconColor: '#6554d9',
})
const berryTealBackdrop = {
  backdropStops: [
    { color: '#281a1f', position: 0 },
    { color: '#272734', position: 50 },
    { color: '#1e2429', position: 100 },
  ],
  backdropAngle: 180,
}
const berryTealLightBackdrop = {
  ...berryTealBackdrop,
  backdropStops: [
    { color: '#e3d9dc', position: 0 },
    { color: '#d8d8e4', position: 50 },
    { color: '#d3e1e3', position: 100 },
  ],
}
const morningMistLightBackdrop = {
  backdropStops: [
    { color: '#c1d8e2', position: 0 },
    { color: '#fff2db', position: 100 },
  ],
  backdropAngle: 185,
}
const morningMistDarkBackdrop = {
  backdropStops: [
    { color: '#110e11', position: 0 },
    { color: '#1a140f', position: 100 },
  ],
  backdropAngle: 185,
  backdropText: '#f2efeb',
}
const morningMistDarkTheme = {
  ...neutralDark,
  ...morningMistDarkBackdrop,
  mainStops: [{ color: '#151514', position: 0 }],
  mainAngle: 180,
  mainText: '#f2efeb',
  mainOpacity: 1,
  composerStops: [
    { color: '#242525', position: 0 },
    { color: '#282929', position: 100 },
  ],
  composerAngle: 180,
  composerText: '#f2efeb',
  composerOpacity: 1,
  controlStops: [{ color: '#1a2824', position: 0 }],
  controlAngle: 180,
  controlText: '#f3eee8',
  controlOpacity: 1,
}
const morningMistLightTheme = {
  ...neutralLight,
  ...morningMistLightBackdrop,
  mainStops: [{ color: '#eeeeea', position: 0 }],
  mainAngle: 180,
  mainText: '#242625',
  mainOpacity: 1,
  composerStops: [
    { color: '#e6e8e4', position: 0 },
    { color: '#e2e4e0', position: 100 },
  ],
  composerAngle: 180,
  composerText: '#1f1f1f',
  composerOpacity: 1,
  controlStops: [{ color: '#d3d6d2', position: 0 }],
  controlAngle: 180,
  controlText: '#1f1f1f',
  controlOpacity: 1,
}

export const THEME_PRESETS: ThemePreset[] = [
  {
    id: 'sunday', group: 'theme', name: 'Sunday', note: '象牙白与石墨灰的纯色主题。',
    method: '浅色使用象牙白承载石墨标记，暗色反转为石墨底与象牙标记。', rationale: '纯色层级更安静，并以清晰实线边界维持长期工作的可读性。',
    theme: SUNDAY_DARK_THEME, lightTheme: SUNDAY_LIGHT_THEME, darkTheme: SUNDAY_DARK_THEME,
  },
  {
    id: 'default', group: 'theme', name: '默认', note: '克制的中性灰阶。',
    method: '工作区域保持纯色，颜色只用于控件层级。', rationale: '适合长时间处理任务与配置。',
    theme: neutralDark, lightTheme: neutralLight, darkTheme: neutralDark,
  },
  {
    id: 'berry-teal', group: 'theme', name: '浮梦', note: '莓紫、灰蓝与青绿的横向渐变。',
    method: '只改变背景板，聊天区、输入栏和控件保持中性。', rationale: '先提供背景方向，其他区域可继续单独调整。',
    theme: { ...neutralDark, ...berryTealBackdrop },
    lightTheme: { ...neutralLight, ...berryTealLightBackdrop },
    darkTheme: { ...neutralDark, ...berryTealBackdrop },
  },
  {
    id: 'morning-mist', group: 'theme', name: '晨宵', note: '雾蓝到奶油白的浅色渐变。',
    method: '浅色使用雾蓝到奶油白，暗色使用墨绿到蓝黑背景，其他界面层保持中性。', rationale: '同一主题在两种模式下保持不同的明暗气质。',
    theme: neutralDark,
    lightTheme: morningMistLightTheme,
    darkTheme: morningMistDarkTheme,
  },
]

export const THEME_PRESET_GROUPS: Array<{ id: ThemePreset['group']; label: string }> = [
  { id: 'theme', label: '主题预设' },
]
