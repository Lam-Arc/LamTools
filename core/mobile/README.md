# LamTools Mobile

Vue + Capacitor mobile shell for controlling a desktop LamTools Core instance.

The shared Workbench is used by both the desktop and mobile shells. A mobile
build selects a trusted LAN Noise tunnel first and then the configured relay;
there is no direct Core fallback. Native builds use a six-digit pairing code
resolved through the configured Relay to provision the desktop identity and
access token; the token is kept in secure storage. Pairing is intentionally
manual and has no camera or deep-link dependency.

```powershell
npm install
npm run dev
npm run build
npm run cap:sync
```

The mobile shell reuses `core/ui` components and Workbench state. Tunnel,
pairing, secure storage, lifecycle, LAN discovery and push adapters live under
`src/`; Capacitor plugins provide native secure storage, network monitoring and
push-registration boundaries.

## Sidebar data and transport contract

Mobile and desktop use the same `SessionSidebar` data shape:

```ts
interface CoreProject {
  id: string
  name: string
  workRoot: string
  createdAt?: string
  updatedAt?: string
}

interface ProjectGroup {
  id: string
  name: string
  workRoot?: string
  canManage?: boolean
  sessions: SessionItem[]
}

interface SessionItem {
  id: string
  title: string
  createdAt?: string
  updatedAt?: string
  status?: string
  meta?: string
  metadata?: Record<string, unknown>
}
```

`ProjectGroup` is the canonical `@lamtools/ui/types` shape; the mobile shell
does not maintain a second project/session model. `SessionItem` is the
presentation projection of Core's session record (`created_at`/`updated_at`
are mapped to `createdAt`/`updatedAt`).

Sidebar mutations reuse the Core HTTP API mounted at `/api/core` (no mobile-
only RPC methods):

| Action | Method and path | JSON body |
| --- | --- | --- |
| Rename session | `PATCH /sessions/{session_id}` | `{ "title": string }` |
| Delete session | `DELETE /sessions/{session_id}` | none |
| Create project session | `POST /projects/{project_id}/sessions` | `{ "title": string }` |
| Rename project | `PATCH /projects/{project_id}` | `{ "name": string }` |
| Delete project | `DELETE /projects/{project_id}` | none |
| Export session | `POST /sessions/{session_id}/export` | `{ "mode": "transcript"\|"handoff"\|"full", "format": "markdown"\|"txt"\|"jsonl"\|"json"\|"zip" }` |

The JSON responses follow the same resource shapes: list sessions returns
`SessionItem[]`; project listing returns `{ "projects": CoreProject[] }`; create
or rename returns the created/updated resource; delete returns `204` with an
empty body. Export returns bytes, with `Content-Type` set to Markdown, plain
text, NDJSON, JSON, or ZIP according to the requested format.

The response is either a JSON resource or the binary export body. In a browser
the request is sent directly; in a paired native build it is wrapped by the
versioned tunnel frame:

```ts
interface TunnelFrame {
  version: 1
  type: 'http.request' | 'http.response' | 'rpc.data' | string
  stream_id: string
  request_id?: string
  payload?: string // frame-specific JSON text; HTTP bodies inside it are base64
  sequence: number
}
```

Frame payloads are:

```ts
// type = "http.request"
{ method: string; path: string; headers: Record<string, string>; body: string }

// type = "http.response"
{ status: number; headers: Record<string, string>; body: string }

// type = "rpc.data"
// payload is the UTF-8 JSON-RPC message text; stream_id is "rpc".
```

`body` is base64 of the raw HTTP bytes (empty string means no body). Frames
are newline-delimited JSON, `version` is `1`, and `sequence` increases for
each direction; the decoder rejects replayed or out-of-order sequence values.

Pins, collapse state and manual ordering remain presentation preferences in
local storage (`lamtools-core.sidebar.pinned-projects` on desktop and
`lamtools-mobile.sessions` on mobile); they are intentionally not sent to
Core or mixed into session metadata.
