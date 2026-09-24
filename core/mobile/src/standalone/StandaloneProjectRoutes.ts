import type {
  CoreProjectClient,
  TransportHttpRequest,
  TransportHttpResponse,
} from '@lamtools/ui'

/**
 * Project file and directory HTTP routes for the standalone transport.
 *
 * The desktop serves these from the Python server. The mobile host has no HTTP
 * server, so the same paths are answered here — and answered *through* the
 * project client the mobile UI already uses, so a panel that reaches a route
 * sees exactly what a panel that calls the client sees.
 */

const IGNORED_DIRECTORY_NAMES = new Set([
  '.git',
  '__pycache__',
  'node_modules',
  '.venv',
  'venv',
  'dist',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
])

type RouteHandler = (request: TransportHttpRequest) => Promise<TransportHttpResponse | null>

export function createStandaloneProjectRoutes(
  client: CoreProjectClient,
): RouteHandler {
  return async function handle(request: TransportHttpRequest): Promise<TransportHttpResponse | null> {
    const url = new URL(request.path, 'http://localhost')
    const segments = url.pathname.split('/').filter(Boolean)

    // The folder picker in project creation and in the plugins panel talks to
    // this route directly instead of going through the project client.
    if (url.pathname === '/browse-directory' && request.method === 'GET') {
      const path = url.searchParams.get('path') || ''
      try {
        const listing = await client.browseDirectory(path)
        return jsonResponse({
          entries: listing.entries.filter(entry => isBrowseEntry(entry)),
          path: listing.path,
        })
      } catch (error) {
        return projectErrorResponse(error, '目录不存在')
      }
    }

    if (segments[0] !== 'projects' || !segments[1]) return null
    const projectId = decodeURIComponent(segments[1])

    // GET|PUT /projects/{id}/agents-md
    if (segments.length === 3 && segments[2] === 'agents-md') {
      try {
        if (request.method === 'GET') return jsonResponse(await client.readAgents(projectId))
        if (request.method === 'PUT') {
          const body = decodeJson(request.body)
          if (typeof body.content !== 'string') return jsonResponse({ error: 'content 不能为空' }, 400)
          return jsonResponse(await client.writeAgents(projectId, body.content))
        }
      } catch (error) {
        return projectErrorResponse(error, '项目不存在')
      }
    }

    // GET /projects/{id}/files?path=
    if (segments.length === 3 && segments[2] === 'files' && request.method === 'GET') {
      const path = url.searchParams.get('path') || ''
      try {
        const listing = await client.listFiles(projectId, path)
        return jsonResponse({
          entries: listing.entries.filter(entry => isProjectFileEntry(entry)),
          path: listing.path,
        })
      } catch (error) {
        return projectErrorResponse(error, '路径不存在')
      }
    }

    if (segments.length === 4 && segments[2] === 'files' && segments[3] === 'raw' && request.method === 'GET') {
      const path = url.searchParams.get('path') || ''
      if (!path) return jsonResponse({ error: '缺少 path 参数' }, 400)
      try {
        const response = await client.readRawFile(projectId, path)
        return response.status === 404 ? jsonResponse({ error: '文件不存在' }, 404) : response
      } catch (error) {
        return projectErrorResponse(error, '文件不存在')
      }
    }

    if (segments.length === 4 && segments[2] === 'files' && segments[3] === 'content') {
      const path = url.searchParams.get('path') || ''
      if (!path) return jsonResponse({ error: '缺少 path 参数' }, 400)
      if (request.method === 'GET') {
        try {
          const file = await client.readFile(projectId, path)
          return jsonResponse({ content: file.content, path: file.path })
        } catch (error) {
          return projectErrorResponse(error, '文件不存在')
        }
      }
      if (request.method === 'PUT') {
        const body = decodeJson(request.body)
        if (typeof body.content !== 'string') return jsonResponse({ error: 'content 不能为空' }, 400)
        // Desktop refuses to write a path that does not already exist; probing
        // here keeps a typo from creating a file on mobile that the desktop
        // would have rejected.
        const exists = await pathExists(client, projectId, path)
        if (!exists) return jsonResponse({ error: '文件不存在' }, 404)
        try {
          const written = await client.writeFile(projectId, path, body.content)
          return jsonResponse({ content: written.content, path: written.path })
        } catch (error) {
          return projectErrorResponse(error, '文件写入失败')
        }
      }
    }

    return null
  }
}

async function pathExists(client: CoreProjectClient, projectId: string, path: string): Promise<boolean> {
  try {
    await client.readFile(projectId, path)
    return true
  } catch (error) {
    // A non-UTF-8 file cannot be decoded but still exists; only an explicit
    // miss may block the write.
    return !isMissingPathError(error)
  }
}

/** Desktop hides dotfiles and build directories in the folder picker. */
function isBrowseEntry(entry: { name: string; type: string }): boolean {
  if (entry.name.startsWith('.') && entry.name !== '.') return false
  return !(entry.type === 'directory' && IGNORED_DIRECTORY_NAMES.has(entry.name))
}

/** Desktop hides build directories in the project file tree, dotfiles stay. */
function isProjectFileEntry(entry: { name: string; type: string }): boolean {
  return !(entry.type === 'directory' && IGNORED_DIRECTORY_NAMES.has(entry.name))
}

function projectErrorResponse(error: unknown, fallback: string): TransportHttpResponse {
  const message = error instanceof Error ? error.message : String(error)
  const status = isMissingPathError(error) ? 404
    : /must stay inside the current project|symbolic link|path escapes|permission denied|拒绝访问/i.test(message) ? 403
    : /is not a file|is not a directory|not a directory|缺少 path|不能为空/i.test(message) ? 400
    : /valid utf-8|utf-8/i.test(message) ? 422
    : /超过 \d+ mib/i.test(message) ? 413
    : 500
  return jsonResponse({ error: message || fallback }, status)
}

function isMissingPathError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /not found|no such file|cannot find|does not exist|不存在|os error 2\b/i.test(message)
}

function decodeJson(body: Uint8Array | undefined): Record<string, unknown> {
  if (!body || body.length === 0) return {}
  try {
    const parsed = JSON.parse(new TextDecoder().decode(body)) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {}
  } catch {
    return {}
  }
}

function jsonResponse(value: unknown, status = 200): TransportHttpResponse {
  return {
    status,
    headers: { 'Content-Type': 'application/json' },
    body: status === 204 ? new Uint8Array() : new TextEncoder().encode(JSON.stringify(value)),
  }
}
