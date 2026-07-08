export type DirectoryPickSource = 'desktop' | 'app-server' | 'cancelled' | 'unsupported'

export interface DesktopDirectorySelector {
  selectDirectory?: () => Promise<string>
}

export interface ProjectDirectoryPickOptions {
  desktop?: DesktopDirectorySelector
  appServerPickDirectory?: () => Promise<string>
}

export interface ProjectDirectoryPickResult {
  path: string
  source: DirectoryPickSource
  message?: string
}

type ProjectDirectoryPickInput = DesktopDirectorySelector | ProjectDirectoryPickOptions | undefined

function isPickerOptions(input: ProjectDirectoryPickInput): input is ProjectDirectoryPickOptions {
  return Boolean(input && ('desktop' in input || 'appServerPickDirectory' in input))
}

function desktopSelector(input: ProjectDirectoryPickInput): DesktopDirectorySelector | undefined {
  if (!input) return undefined
  return isPickerOptions(input) ? input.desktop : input
}

function appServerSelector(input: ProjectDirectoryPickInput): (() => Promise<string>) | undefined {
  return isPickerOptions(input) ? input.appServerPickDirectory : undefined
}

export async function pickProjectDirectory(input?: ProjectDirectoryPickInput): Promise<ProjectDirectoryPickResult> {
  const desktop = desktopSelector(input)
  if (desktop?.selectDirectory) {
    const path = await desktop.selectDirectory()
    return path ? { path, source: 'desktop' } : { path: '', source: 'cancelled' }
  }

  const pickFromAppServer = appServerSelector(input)
  if (pickFromAppServer) {
    const path = await pickFromAppServer()
    return path ? { path, source: 'app-server' } : { path: '', source: 'cancelled' }
  }

  return {
    path: '',
    source: 'unsupported',
    message: '当前浏览器不能提供本机绝对路径，请在桌面版使用浏览，或手动输入绝对路径。',
  }
}

export function projectNameFromPath(path: string): string {
  return path.split(/[/\\]/).filter(Boolean).pop() || ''
}
