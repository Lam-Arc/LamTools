<!-- 历史参考，不代表当前架构 -->
# LamWriter TUI Implementation Plan

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python `textual`-based Terminal User Interface for LamWriter that provides a Claude Code / DeepSeek-level terminal interaction experience, integrating with the existing FastAPI backend via SSE.

**Architecture:** The TUI runs as an independent Python process (`python -m writer_tui`). It connects to a running LamWriter backend (FastAPI on port 6173) via HTTP REST + SSE streaming. The TUI maintains its own reactive `StateStore` that mirrors backend state through incoming SSE events. A custom `SSEClient` (async generator over `aiohttp`) transforms SSE wires into typed TUI events, which flow through Textual's message system to update widgets reactively.

**Tech Stack:** Python 3.14+, textual>=2.1.0, aiohttp>=3.11.0, httpx (sync fallback for config check), pydantic>=2.10.0, rich>=13.0 (bundled with textual)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                     Terminal                         │
│  ┌──────────────────────────────────────────────┐   │
│  │              LamWriter TUI (Textual App)      │   │
│  │                                                │   │
│  │  ┌─ Screen: SessionList ───────────────────┐  │   │
│  │  │  ListView of past sessions               │  │   │
│  │  └──────────────────────────────────────────┘  │   │
│  │                                                │   │
│  │  ┌─ Screen: Chat ──────────────────────────┐  │   │
│  │  │  ┌ Header ───────────────────────────┐  │  │   │
│  │  │  │ ModeBadge | SessionTitle | Status  │  │  │   │
│  │  │  └────────────────────────────────────┘  │  │   │
│  │  │  ┌ Transcript (VirtualMessageList) ──┐  │  │   │
│  │  │  │ MessageWidget                      │  │  │   │
│  │  │  │   ├─ ThinkingBlock (collapsible)   │  │  │   │
│  │  │  │   ├─ ToolCallBlock (expandable)    │  │  │   │
│  │  │  │   └─ TextBlock                     │  │  │   │
│  │  │  └────────────────────────────────────┘  │  │   │
│  │  │  ┌ Composer ─────────────────────────┐  │  │   │
│  │  │  │ Input(Multiline) | Send button     │  │  │   │
│  │  │  └────────────────────────────────────┘  │  │   │
│  │  │  ┌ Footer ───────────────────────────┐  │  │   │
│  │  │  │ PhaseChip | Tokens | Cost | Help   │  │  │   │
│  │  │  └────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────┘  │   │
│  │                                                │   │
│  │  ┌─ Screen: CommandPalette (overlay) ───────┐  │   │
│  │  │  FuzzyInput + OptionList                  │  │   │
│  │  └──────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌─ writer_tui/backend/ ─────────────────────────┐  │
│  │  BackendClient (HTTP REST + SSE via aiohttp)  │  │
│  │  ┌─ POST /api/sessions            (create)    │  │
│  │  │─ GET  /api/sessions            (list)      │  │
│  │  │─ POST /api/sessions/{id}/chat  (SSE stream)│  │
│  │  │─ POST /api/sessions/{id}/cancel            │  │
│  │  └─ POST /api/sessions/{id}/resume            │  │
│  └───────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + SSE
                       ▼
         ┌─────────────────────────┐
         │  LamWriter Backend      │
         │  (FastAPI :6173)         │
         │  WriterRuntime → TM → SSE│
         └─────────────────────────┘
```

### 1.1 Data Flow

```
User Input → Composer → ChatScreen.dispatch_message()
  → BackendClient.post_chat(session_id, text, mode)
    → HTTP POST /api/sessions/{id}/chat
      → Backend: WriterRuntime.run()
        → TaskManager.publish(event) ──┐
          → SSE stream to TUI ◄────────┘
            → SSEClient._parse_line()
              → yield TUIEvent(typed dict)
                → StateStore.apply(event)
                  → screen.query(widget).mutate()
                    → widget.render()
```

### 1.2 State Sync Model

TUI maintains a **single reactive `StateStore`** backed by a `reactive` dict per Textual pattern. SSE events are **reduced** into this store. Widgets use Textual `reactive` attributes to auto-rerender on state changes.

```
StateStore (dict)
  ├─ session_id: str
  ├─ mode: WriterInteractionMode
  ├─ phase: WriterRuntimePhase
  ├─ workflow_phase: WriterWorkflowPhase
  ├─ status: str (running | paused | done | error)
  ├─ messages: list[Message]
  │   ├─ id: str
  │   ├─ role: "user" | "assistant"
  │   ├─ blocks: list[Block]
  │   │   ├─ ThinkingBlock(text, expanded=False)
  │   │   ├─ TextBlock(text)
  │   │   └─ ToolCallBlock(name, args, result, status)
  │   └─ turn_number: int
  ├─ current_streaming: Message | None  (being built from SSE)
  ├─ tokens: int
  ├─ cost_estimate: float
  ├─ turn_count: int
  └─ pending_approval: WriterAction | None
```

---

## 2. File Structure

```
LamWriter/
├── writer_tui/                      # Top-level TUI package
│   ├── __init__.py
│   ├── __main__.py                  # Entry: python -m writer_tui [--server HOST:PORT]
│   ├── app.py                       # WriterTUIApp(Textual.App) — compose, keybinds, mount
│   │
│   ├── backend/                     # HTTP + SSE client layer
│   │   ├── __init__.py
│   │   ├── client.py                # BackendClient — REST calls (create/list/get session, cancel)
│   │   ├── sse.py                   # SSEClient — async generator over aiohttp SSE
│   │   └── types.py                 # Request/response Pydantic models (SessionData, MessageData)
│   │
│   ├── state/                       # Reactive state management
│   │   ├── __init__.py
│   │   ├── store.py                 # StateStore — reduces SSE events → reactive attributes
│   │   └── reducer.py               # event → state mutation functions
│   │
│   ├── events.py                    # TUIEvent types — typed wrappers around SSE events
│   │
│   ├── screens/                     # Textual Screen classes
│   │   ├── __init__.py
│   │   ├── session_list.py          # SessionListScreen — pick or create session
│   │   ├── chat.py                  # ChatScreen — main chat interface
│   │   └── command_palette.py       # CommandPaletteScreen — Ctrl+K fuzzy search
│   │
│   ├── widgets/                     # Reusable Textual Widget classes
│   │   ├── __init__.py
│   │   ├── header.py                # HeaderWidget — mode badge, title, phase indicator
│   │   ├── transcript.py            # TranscriptWidget — VirtualMessageList container
│   │   ├── message.py               # MessageWidget — one message (user or assistant)
│   │   ├── thinking_block.py        # ThinkingBlock — collapsible reasoning display
│   │   ├── tool_call_block.py       # ToolCallBlock — expandable tool invocation
│   │   ├── text_block.py            # TextBlock — rich text with markdown rendering
│   │   ├── composer.py              # ComposerWidget — multiline input + send button
│   │   ├── footer.py                # FooterWidget — status chips (tokens, cost, phase)
│   │   ├── mode_cycler.py           # ModeCycler — Tab-key mode badge
│   │   ├── permission_dialog.py     # PermissionDialog — y/n/ESC overlay for tool approval
│   │   └── status_badge.py          # StatusBadge — colored phase/mode chip
│   │
│   ├── themes/                      # Textual CSS theme files
│   │   ├── __init__.py
│   │   ├── dark.tcss                # Dark theme (primary)
│   │   ├── light.tcss               # Light theme (toggle with Ctrl+T)
│   │   └── base.tcss                # Shared layout + structure
│   │
│   └── utils/                       # Shared utilities
│       ├── __init__.py
│       ├── markdown.py              # Markdown → Rich renderable converter
│       ├── tokens.py                # Token counting (approximate, tiktoken optional)
│       └── keys.py                  # Keybinding constants
│
├── backend/
│   └── requirements.txt             # Add: textual>=2.1.0, aiohttp (already present)
│
└── writer_tui_requirements.txt      # TUI-only deps (or inline in backend/requirements.txt)
```

---

## 3. Component Hierarchy (Textual CSS + Python Classes)

### 3.1 App Level: `WriterTUIApp`

```python
# writer_tui/app.py
class WriterTUIApp(App):
    CSS_PATH = "themes/dark.tcss"
    BINDINGS = [
        ("ctrl+k", "command_palette", "Commands"),
        ("ctrl+t", "toggle_theme", "Toggle Theme"),
        ("f1", "show_help", "Help"),
        ("escape", "dismiss_overlay", "Dismiss"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def compose(self):
        # Screen stack managed by Textual via push_screen/pop_screen
        # Initial screen: SessionListScreen or ChatScreen (if --session-id passed)

    def on_mount(self):
        self.theme = "dark"
        self.state = StateStore()
        self.backend = BackendClient(server_url=self.server_url)
```

### 3.2 Screen: `ChatScreen`

```python
# writer_tui/screens/chat.py
class ChatScreen(Screen):
    """Main chat screen with header, transcript, composer, footer."""

    CSS = """
    ChatScreen {
        layout: vertical;
    }
    ChatScreen > HeaderWidget {
        dock: top;
        height: 3;
    }
    ChatScreen > TranscriptWidget {
        /* fills remaining space */
    }
    ChatScreen > ComposerWidget {
        dock: bottom;
        height: auto;
        max-height: 10;
    }
    ChatScreen > FooterWidget {
        dock: bottom;
        height: 1;
    }
    """

    BINDINGS = [
        ("tab", "cycle_mode_next", "Next Mode"),
        ("shift+tab", "cycle_mode_prev", "Prev Mode"),
        ("ctrl+enter", "submit", "Send"),
        ("j", "scroll_down", "Scroll Down"),
        ("k", "scroll_up", "Scroll Up"),
        ("g", "scroll_top", "Top"),
        ("shift+g", "scroll_bottom", "Bottom"),
        ("ctrl+d", "page_down", "Page Down"),
        ("ctrl+u", "page_up", "Page Up"),
    ]

    def compose(self):
        yield HeaderWidget()
        yield TranscriptWidget()
        yield ComposerWidget()
        yield FooterWidget()
```

### 3.3 Widget: `HeaderWidget`

```python
# writer_tui/widgets/header.py
class HeaderWidget(Widget):
    """Top bar: [ModeBadge] Session Title | Phase: executing | Status: running"""

    mode: reactive[str] = reactive("EXECUTE")
    phase: reactive[str] = reactive("idle")
    status: reactive[str] = reactive("idle")
    title: reactive[str] = reactive("New Session")
    turn_count: reactive[int] = reactive(0)

    CSS = """
    HeaderWidget {
        height: 3;
        background: $panel;
        border-bottom: solid $border-dim;
        padding: 0 1;
    }
    HeaderWidget .mode-badge {
        background: $accent;
        color: $text;
        padding: 0 1;
        text-style: bold;
    }
    """
```

### 3.4 Widget: `TranscriptWidget`

```python
# writer_tui/widgets/transcript.py
class TranscriptWidget(Widget):
    """VirtualMessageList — renders only visible items + 5 overscan."""

    messages: list[Message] = []
    scroll_offset: int = 0
    streaming_message: Message | None = None  # Current in-progress message

    CSS = """
    TranscriptWidget {
        overflow-y: scroll;
        scrollbar-size: 0 0;  /* hide scrollbar, use keyboard */
    }
    """

    def on_mount(self):
        self._message_widgets: dict[str, MessageWidget] = {}

    def render(self) -> RenderableType:
        """Calculate visible window, compose only visible widgets."""
        visible_start, visible_end = self._visible_range()
        ...
```

### 3.5 Widget: `MessageWidget`

```python
# writer_tui/widgets/message.py
class MessageWidget(Widget):
    """A single message — contains blocks (thinking, text, tool_calls)."""

    role: str  # "user" | "assistant"
    blocks: list[Block]  # ThinkingBlock | TextBlock | ToolCallBlock
    turn_number: int = 0

    CSS = """
    MessageWidget {
        padding: 0 1;
        margin: 1 0;
    }
    MessageWidget.user {
        border-left: solid $accent;
        padding-left: 1;
    }
    MessageWidget.assistant {
        border-left: solid $surface;
        padding-left: 1;
    }
    """
```

### 3.6 Widget: `ThinkingBlock`

```python
# writer_tui/widgets/thinking_block.py
class ThinkingBlock(Widget):
    """Collapsible reasoning block — like DeepSeek's thinking display."""

    text: str = ""
    expanded: bool = False

    CSS = """
    ThinkingBlock {
        background: $surface-dim;
        border: solid $border;
        margin: 1 0;
        padding: 0 1;
        color: $text-muted;
        text-style: italic;
    }
    ThinkingBlock .header {
        color: $accent-dim;
        text-style: bold;
    }
    ThinkingBlock.collapsed {
        height: 1;
        overflow: hidden;
    }
    """
```

### 3.7 Widget: `ToolCallBlock`

```python
# writer_tui/widgets/tool_call_block.py
class ToolCallBlock(Widget):
    """Tool invocation display with expand/collapse + status spinner."""

    tool_name: str = ""
    tool_args: dict = {}
    output: str = ""
    status: str = "pending"  # pending → running → completed | error

    CSS = """
    ToolCallBlock {
        background: $surface-dim;
        border: solid $accent-dim;
        margin: 0 0 0 2;
        padding: 0 1;
    }
    ToolCallBlock.running {
        border-style: dashed;
    }
    ToolCallBlock.completed {
        border: solid $success;
    }
    ToolCallBlock.error {
        border: solid $error;
    }
    """
```

### 3.8 Widget: `ComposerWidget`

```python
# writer_tui/widgets/composer.py
class ComposerWidget(Widget):
    """Bottom input area — multiline text input with send button."""

    input: TextArea
    mode_cycler: ModeCycler

    CSS = """
    ComposerWidget {
        height: auto;
        min-height: 3;
        max-height: 10;
        background: $panel;
        border-top: solid $border;
        padding: 1;
    }
    ComposerWidget TextArea {
        height: auto;
    }
    """
```

### 3.9 Widget: `FooterWidget`

```python
# writer_tui/widgets/footer.py
class FooterWidget(Widget):
    """Single-line status bar — tokens, cost, phase, keyboard hints."""

    tokens: reactive[int] = reactive(0)
    cost: reactive[str] = reactive("$0.0000")
    phase: reactive[str] = reactive("idle")
    mode: reactive[str] = reactive("EXECUTE")
    hint: reactive[str] = reactive("Ctrl+K Cmds | F1 Help | q Quit")

    CSS = """
    FooterWidget {
        height: 1;
        background: $panel;
        border-top: solid $border-dim;
        padding: 0 1;
    }
    """
```

### 3.10 Widget: `ModeCycler`

```python
# writer_tui/widgets/mode_cycler.py
class ModeCycler(Widget):
    """Tab-key cycling mode display sitting inside HeaderWidget."""

    current: reactive[str] = reactive("EXECUTE")
    MODES = ["EXECUTE", "TEACH", "DISCUSS", "PROTOTYPE", "REVIEW",
             "BRAINSTORM", "PAIR", "DECISION", "COMFORT"]

    CSS = """
    ModeCycler {
        width: 14;
        height: 1;
        content-align: center middle;
        background: $accent;
        color: $text;
        text-style: bold;
    }
    """
```

### 3.11 Screen: `CommandPaletteScreen`

```python
# writer_tui/screens/command_palette.py
class CommandPaletteScreen(ModalScreen):
    """Overlay for Ctrl+K — fuzzy search of commands."""

    COMMANDS = [
        ("New Session", "Create a new writer session."),
        ("List Sessions", "Browse past sessions."),
        ("Set Mode: EXECUTE", "Switch to autonomous execution."),
        ("Set Mode: TEACH", "Switch to teaching mode."),
        ("Cancel Current", "Stop the running runtime."),
        ("Toggle Theme", "Switch between dark and light."),
        ("Quit", "Exit LamWriter TUI."),
    ]

    CSS = """
    CommandPaletteScreen {
        align: center middle;
    }
    """
```

### 3.12 Widget: `PermissionDialog`

```python
# writer_tui/widgets/permission_dialog.py
class PermissionDialog(ModalScreen):
    """Overlay modal for tool approvals — y/n/ESC."""
    
    action: WriterAction
    
    CSS = """
    PermissionDialog {
        align: center middle;
        width: 60;
        height: auto;
        background: $panel;
        border: solid $warning;
        padding: 1 2;
    }
    """
```

### 3.13 Screen: `SessionListScreen`

```python
# writer_tui/screens/session_list.py
class SessionListScreen(Screen):
    """Session picker — browse/create sessions before entering Chat."""

    BINDINGS = [
        ("n", "new_session", "New Session"),
        ("enter", "select_session", "Open"),
        ("j", "cursor_down", ""),
        ("k", "cursor_up", ""),
    ]
```

---

## 4. State Management

### 4.1 StateStore

```python
# writer_tui/state/store.py
from textual.reactive import reactive

class StateStore:
    """Centralized reactive state. All SSE events reduce into this."""

    session_id: str = ""
    mode: str = "EXECUTE"
    phase: str = "idle"
    workflow_phase: str = "none"
    status: str = "idle"  # idle | running | paused | done | error
    messages: list[dict] = []  # Full message list
    current_streaming: dict | None = None  # Being built in real-time
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0
    turn_count: int = 0
    pending_approval: dict | None = None
    error: str = ""

    def apply(self, event: dict) -> str:
        """Reduce an SSE event into state mutation. Returns the changed key for widget reactivity."""
        handler = REDUCERS.get(event.get("event"))
        if handler:
            return handler(self, event.get("data", {}))
        return ""

    def clear_streaming(self):
        """Commit current_streaming message to messages list."""
        if self.current_streaming:
            self.messages.append(self.current_streaming)
            self.current_streaming = None
```

### 4.2 Reducers

```python
# writer_tui/state/reducer.py

def reduce_response(state, data):
    """writer_response → add/update assistant message text."""
    text = data.get("text", "")
    if not state.current_streaming:
        state.current_streaming = {"role": "assistant", "blocks": [], "text": ""}
    state.current_streaming["blocks"].append({"type": "text", "content": text})
    state.current_streaming["text"] += text
    return "current_streaming"

def reduce_thought(state, data):
    """writer_thought → add thinking block (collapsed by default)."""
    text = data.get("text", "")[:500]
    if not state.current_streaming:
        state.current_streaming = {"role": "assistant", "blocks": [], "text": ""}
    state.current_streaming["blocks"].append({"type": "thinking", "content": text, "expanded": False})
    return "current_streaming"

def reduce_action_started(state, data):
    """writer_action_started → add tool_call block with status=running."""
    action_type = data.get("action_type", "unknown")
    params = data.get("params", {})
    if not state.current_streaming:
        state.current_streaming = {"role": "assistant", "blocks": [], "text": ""}
    block = {"type": "tool_call", "tool_name": action_type, "tool_args": params, "status": "running", "output": ""}
    state.current_streaming["blocks"].append(block)
    return "current_streaming"

def reduce_part_updated(state, data):
    """writer_part_updated → update tool_call block with result."""
    tool_name = data.get("tool_name", "")
    status = data.get("status", "")
    content = data.get("content", "")
    if state.current_streaming:
        for block in state.current_streaming.get("blocks", []):
            if block["type"] == "tool_call" and block["tool_name"] == tool_name:
                block["status"] = status
                block["output"] = content[:500]  # Truncate long outputs
                break
    return "current_streaming"

def reduce_phase_changed(state, data):
    """writer_phase_changed → update phase."""
    state.phase = data.get("phase", state.phase)
    return "phase"

def reduce_mode_changed(state, data):
    """writer_mode_changed → update mode."""
    state.mode = data.get("mode", state.mode)
    return "mode"

def reduce_workflow(state, data):
    """writer_workflow → update workflow phase."""
    state.workflow_phase = data.get("workflow_phase", "none")
    return "workflow_phase"

def reduce_waiting_for_user(state, data):
    """writer_waiting_for_user → pause indicator."""
    state.status = "paused"
    return "status"

def reduce_resumed(state, data):
    """writer_resumed → unpause."""
    state.status = "running"
    return "status"

def reduce_done(state, data):
    """writer_done → finish current message, mark done."""
    state.clear_streaming()
    state.status = "done"
    return "status"

def reduce_error(state, data):
    """writer_error → set error state."""
    state.error = data.get("error", "Unknown error")
    state.status = "error"
    return "error"

REDUCERS = {
    "writer_response": reduce_response,
    "writer_thought": reduce_thought,
    "writer_action_started": reduce_action_started,
    "writer_part_updated": reduce_part_updated,
    "writer_phase_changed": reduce_phase_changed,
    "writer_mode_changed": reduce_mode_changed,
    "writer_workflow": reduce_workflow,
    "writer_waiting_for_user": reduce_waiting_for_user,
    "writer_resumed": reduce_resumed,
    "writer_done": reduce_done,
    "writer_error": reduce_error,
}
```

### 4.3 Widget → State Bindings

Widgets use `watch_*` methods triggered by reactive changes:

```python
class HeaderWidget(Widget):
    mode = reactive("EXECUTE")  # Auto-bound to state.mode

    def watch_mode(self, new_mode):
        self.query_one(".mode-badge").update(new_mode)

class TranscriptWidget(Widget):
    current_streaming = reactive(None)

    def watch_current_streaming(self, msg):
        """Called on every SSE event — efficient append, not full rerender."""
        if msg:
            self._append_or_update_block(msg)
```

The `ChatScreen.on_state_store_changed` message handler pulls state from store and fans out to child widgets:

```python
class ChatScreen(Screen):
    def on_state_store_changed(self, event: StateStoreChanged):
        """Fan out state changes to watchers."""
        for key, value in event.changes.items():
            self._dispatch_to_widgets(key, value)
```

---

## 5. Event Flow (SSE → TUI Updates)

### 5.1 SSE Client

```python
# writer_tui/backend/sse.py
import asyncio
import json
from typing import AsyncGenerator

import aiohttp


class SSEClient:
    """Async generator over an SSE endpoint. Yields parsed dict events."""

    def __init__(self, url: str, session: aiohttp.ClientSession):
        self._url = url
        self._session = session
        self._cancel = asyncio.Event()

    async def events(self) -> AsyncGenerator[dict, None]:
        """Connect and yield TypedEvent dicts until stream ends or cancelled."""
        async with self._session.get(self._url) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.content.iter_any():
                if self._cancel.is_set():
                    break
                text = chunk.decode("utf-8", errors="replace")
                buffer += text
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    parsed = self._parse_event(event_str)
                    if parsed:
                        yield parsed

    def _parse_event(self, raw: str) -> dict | None:
        """Parse an SSE event block into a dict."""
        event_type = "message"
        data = ""
        for line in raw.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if not data:
            return None
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return None
        parsed["_event_type"] = event_type
        return parsed

    def cancel(self):
        self._cancel.set()
```

### 5.2 BackendClient

```python
# writer_tui/backend/client.py
import aiohttp
from typing import AsyncGenerator

class BackendClient:
    """HTTP REST + SSE client for LamWriter backend."""

    def __init__(self, server_url: str = "http://localhost:6173"):
        self._base = server_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    # ── REST Operations ──

    async def check_health(self) -> bool:
        """Check if backend is alive."""
        try:
            async with self._session.get(f"{self._base}/api/health") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def create_session(self, title: str, mode: str = "EXECUTE", work_root: str = "") -> dict:
        """POST /api/sessions → new session dict."""
        async with self._session.post(
            f"{self._base}/api/sessions",
            json={"title": title, "mode": mode, "work_root": work_root},
        ) as resp:
            return await resp.json()

    async def list_sessions(self) -> list[dict]:
        """GET /api/sessions → list of sessions."""
        async with self._session.get(f"{self._base}/api/sessions") as resp:
            return await resp.json()

    async def get_session(self, session_id: str) -> dict:
        """GET /api/sessions/{id} → session detail."""
        async with self._session.get(f"{self._base}/api/sessions/{session_id}") as resp:
            return await resp.json()

    # ── SSE Streaming ──

    async def chat_stream(self, session_id: str, message: str, mode: str = "EXECUTE") -> AsyncGenerator[dict, None]:
        """POST /api/sessions/{id}/chat → SSE event stream."""
        sse_client = SSEClient(
            url=f"{self._base}/api/sessions/{session_id}/chat",
            session=self._session,
        )
        # Fire the POST request in the background — SSE stream is the response
        async with self._session.post(
            f"{self._base}/api/sessions/{session_id}/chat",
            json={"message": message, "mode": mode},
        ) as resp:
            resp.raise_for_status()
            async for event in sse_client.events():
                yield event

    async def resume(self, session_id: str, message: str) -> AsyncGenerator[dict, None]:
        """POST /api/sessions/{id}/resume → SSE event stream (same endpoint)."""
        async with self._session.post(
            f"{self._base}/api/sessions/{session_id}/resume",
            json={"message": message},
        ) as resp:
            resp.raise_for_status()
            # Resume reuses the existing SSE subscription
            sse_client = SSEClient(
                url=f"{self._base}/api/sessions/events?session_id={session_id}",
                session=self._session,
            )
            async for event in sse_client.events():
                yield event

    async def cancel_session(self, session_id: str) -> None:
        """POST /api/sessions/{id}/cancel."""
        async with self._session.post(f"{self._base}/api/sessions/{session_id}/cancel") as resp:
            pass
```

### 5.3 SSE → TUI Flow (Detailed)

```
1. User types text, presses Ctrl+Enter
2. ChatScreen.action_submit():
     a. Creates user MessageWidget in transcript
     b. Sets state.status = "running"
     c. await self.backend.chat_stream(session_id, text, mode)
3. For each yielded SSE event dict:
     a. state.apply(event) → mutates state (current_streaming, phase, etc.)
     b. ChatScreen.on_state_change() → fans to widgets
     c. TranscriptWidget watches current_streaming:
        - On new block: append block to current MessageWidget
        - On update: find existing ToolCallBlock, update status/result
     d. HeaderWidget watches mode, phase: updates badge text
     e. FooterWidget watches tokens: updates display
4. On "writer_done" event:
     a. state.clear_streaming() → commits message to history
     b. ComposerWidget re-enables input
5. On "writer_waiting_for_user":
     a. ComposerWidget shows "Respond to Writer..." prompt
     b. User types, presses Ctrl+Enter → resume flow
```

### 5.4 Permission Flow

When a `writer_action_started` or `writer_part_updated` event contains an action that requires approval (not auto-approved by the backend's MVP auto-approve mode), the TUI:

```
1. PermissionDialog pushes as modal overlay
2. Shows: tool name, args, suggested action (y/n/ESC)
3. y → approve (resume backend with approval)
4. n → reject (send rejection to backend)
5. ESC → dismiss (defer, action stays pending)

Note: In current backend, MVP auto-approves all "ask_user" tier actions.
The PermissionDialog exists as infrastructure for when auto-approve is disabled.
```

---

## 6. Keyboard Shortcuts

### 6.1 Global (Always Active)

| Key | Action | Context |
|-----|--------|---------|
| `Ctrl+K` | Open Command Palette | Anywhere |
| `Ctrl+T` | Toggle theme (dark/light) | Anywhere |
| `F1` | Show help overlay | Anywhere |
| `Ctrl+C` | Quit application | Anywhere |
| `ESC` | Dismiss overlay/modal | In overlay |
| `q` | Quit (when not in input) | Chat screen |

### 6.2 Chat Screen

| Key | Action |
|-----|--------|
| `Tab` | Cycle mode forward (EXECUTE → TEACH → ... → COMFORT → EXECUTE) |
| `Shift+Tab` | Cycle mode backward |
| `Ctrl+Enter` | Send message / Respond to Writer |
| `j` | Scroll transcript down (1 line) |
| `k` | Scroll transcript up (1 line) |
| `g` | Scroll to top of transcript |
| `Shift+G` | Scroll to bottom of transcript |
| `Ctrl+D` | Page down (half screen) |
| `Ctrl+U` | Page up (half screen) |
| `Ctrl+L` | Clear session (start new chat) |

### 6.3 Thinking/ToolCall Blocks

| Key | Action |
|-----|--------|
| `Enter` (on block) | Toggle expand/collapse |
| `Space` (on block) | Toggle expand/collapse |
| `j/k` | Move focus between blocks |
| `y` (on expanded tool call) | Copy output to clipboard |

### 6.4 Permission Dialog

| Key | Action |
|-----|--------|
| `y` | Approve action |
| `n` | Reject action |
| `ESC` | Dismiss (defer) |

### 6.5 Command Palette

| Key | Action |
|-----|--------|
| Type query | Fuzzy filter commands |
| `Ctrl+j/k` | Navigate results |
| `Enter` | Execute selected command |
| `ESC` | Close palette |

### 6.6 Session List

| Key | Action |
|-----|--------|
| `j/k` | Navigate sessions |
| `Enter` | Open selected session |
| `n` | New session |
| `d` | Delete session (with confirmation) |
| `ESC` | Quit |

---

## 7. Integration Points with Backend

### 7.1 API Endpoints Used

| Endpoint | Method | Used For |
|----------|--------|----------|
| `/api/health` | GET | Startup health check |
| `/api/sessions` | POST | Create new chat session |
| `/api/sessions` | GET | List past sessions |
| `/api/sessions/{id}` | GET | Load session detail |
| `/api/sessions/{id}/chat` | POST | Send message + stream SSE |
| `/api/sessions/{id}/cancel` | POST | Cancel running runtime |
| `/api/sessions/{id}/resume` | POST | Resume paused runtime |
| `/api/sessions/events?session_id={id}` | GET | Subscribe to existing event stream |

### 7.2 SSE Event Types Handled

| Backend Event | TUI Reducer | Widget Update |
|---------------|-------------|---------------|
| `writer_response` | Text appended to current streaming message | TranscriptWidget |
| `writer_thought` | ThinkingBlock added (collapsed) | TranscriptWidget |
| `writer_action_started` | ToolCallBlock added (status=running) | TranscriptWidget |
| `writer_part_updated` | ToolCallBlock status/output updated | TranscriptWidget |
| `writer_phase_changed` | state.phase = new | HeaderWidget, FooterWidget |
| `writer_mode_changed` | state.mode = new | ModeCycler, HeaderWidget |
| `writer_workflow` | state.workflow_phase = new | FooterWidget |
| `writer_waiting_for_user` | state.status = "paused" | ComposerWidget (enable input) |
| `writer_resumed` | state.status = "running" | ComposerWidget (disable input) |
| `writer_done` | Commit streaming message, status = "done" | Full screen |
| `writer_error` | state.error = msg, status = "error" | FooterWidget (error chip) |

### 7.3 Data Contract

TUI expects backend to provide event dicts in this shape (already in place, no backend changes needed):

```json
{
  "event": "writer_response",
  "data": {
    "session_id": "...",
    "text": "...",
    "output_type": "code",
    "output_meta": {}
  }
}
```

### 7.4 Backend Modifications Required

**None.** The TUI is a pure consumer of the existing HTTP + SSE API surface. No backend changes are needed. The backend already:

- Exposes all CRUD endpoints for sessions
- Provides SSE streaming via `/api/sessions/{id}/chat` and `/api/sessions/events`
- Emits all event types the TUI needs
- Handles cancellation, resume, and error states

The TUI only needs the backend to be running (`py -3.14 -m uvicorn app.main:app --reload --port 6173`).

---

## 8. Theme Design

### 8.1 Dark Theme (Default)

```textual
/* writer_tui/themes/dark.tcss */

$accent: #3B82F6;           /* DeepSeek blue */
$accent-dim: #1E40AF;
$accent-bright: #60A5FA;

$bg: #0F172A;               /* Slate 900 */
$surface: #1E293B;          /* Slate 800 */
$surface-dim: #334155;      /* Slate 700 */
$panel: #0F172A;

$text: #F1F5F9;             /* Slate 100 */
$text-muted: #94A3B8;       /* Slate 400 */
$text-dim: #64748B;         /* Slate 500 */

$border: #334155;
$border-dim: #1E293B;

$success: #22C55E;
$warning: #F59E0B;
$error: #EF4444;

$scrollbar: $surface-dim;
$scrollbar-hover: $accent-dim;
```

### 8.2 Light Theme (Ctrl+T toggle)

```textual
/* writer_tui/themes/light.tcss */

$accent: #2563EB;
$accent-dim: #1D4ED8;

$bg: #FFFFFF;
$surface: #F8FAFC;
$surface-dim: #E2E8F0;
$panel: #F1F5F9;

$text: #0F172A;
$text-muted: #475569;

$border: #CBD5E1;
$border-dim: #E2E8F0;
```

### 8.3 Theme Switching

```python
# writer_tui/app.py
def action_toggle_theme(self):
    if self.theme == "dark":
        self.theme = "light"
        self.stylesheet = Path("themes/light.tcss")
    else:
        self.theme = "dark"
        self.stylesheet = Path("themes/dark.tcss")
```

---

## 9. Implementation Tasks

### Task 1: Scaffold Package Structure

**Files:** `writer_tui/__init__.py`, `writer_tui/__main__.py`, `writer_tui/app.py`, `writer_tui_requirements.txt`

**Steps:**
- [ ] Create `writer_tui/` directory with package structure (all `__init__.py` files)
- [ ] Create `writer_tui/__main__.py` with argparse (host, port, session-id) and `App().run()`
- [ ] Create `writer_tui/app.py` with `WriterTUIApp(App)`, minimal compose (placeholder text)
- [ ] Create `writer_tui_requirements.txt` with `textual>=2.1.0`, `aiohttp>=3.11.0`
- [ ] Verify: `python -m writer_tui` starts and shows placeholder screen

**Verification:**
- [ ] `python -m writer_tui` launches Textual app with no errors
- [ ] `python -m writer_tui --help` shows usage

**Commit:** `feat: scaffold writer_tui package structure`

### Task 2: Backend Client Layer

**Files:** `writer_tui/backend/client.py`, `writer_tui/backend/sse.py`, `writer_tui/backend/types.py`

**Steps:**
- [ ] Create `writer_tui/backend/types.py` — Pydantic models for `SessionData`, `MessageData`, `ChatRequest`
- [ ] Create `writer_tui/backend/client.py` — `BackendClient` with REST methods (create_session, list_sessions, get_session, cancel_session) using aiohttp
- [ ] Create `writer_tui/backend/sse.py` — `SSEClient` async generator with `_parse_event` for SSE wire format
- [ ] Add `BackendClient.chat_stream()` — POST to /chat, parse SSE response body
- [ ] Unit test: mock aiohttp to verify parsing of 5 event types

**Verification:**
- [ ] `pytest writer_tui/backend/` passes with mock SSE event parsing
- [ ] SSEClient correctly splits `event:` and `data:` lines

**Commit:** `feat: backend client layer with SSE streaming`

### Task 3: State Store + Reducers

**Files:** `writer_tui/state/store.py`, `writer_tui/state/reducer.py`, `writer_tui/events.py`

**Steps:**
- [ ] Create `writer_tui/events.py` — define `StateStoreChanged` message (Textual Message subclass)
- [ ] Create `writer_tui/state/reducer.py` — all reducer functions (reduce_response, reduce_thought, etc.)
- [ ] Create `writer_tui/state/store.py` — `StateStore` class with `apply(event)` and `clear_streaming()`
- [ ] Unit test: feed all 11 SSE event types through state.apply, verify state mutations

**Verification:**
- [ ] `pytest writer_tui/state/` — all 11 reducer tests pass
- [ ] Reducers handle edge cases: missing data, None current_streaming, duplicate tool names

**Commit:** `feat: reactive state store with SSE event reducers`

### Task 4: Base Theme + Layout

**Files:** `writer_tui/themes/base.tcss`, `writer_tui/themes/dark.tcss`, `writer_tui/themes/light.tcss`, `writer_tui/app.py` (update)

**Steps:**
- [ ] Create `writer_tui/themes/base.tcss` with layout structure (Screen, vertical layout, dock positions)
- [ ] Create `writer_tui/themes/dark.tcss` with DeepSeek-blue color palette
- [ ] Create `writer_tui/themes/light.tcss` with light palette
- [ ] Update `WriterTUIApp` to load CSS, add `action_toggle_theme`
- [ ] Verify: app renders dark theme by default, Ctrl+T toggles

**Verification:**
- [ ] `Ctrl+T` toggles between dark and light theme seamlessly
- [ ] Colors render correctly in Windows Terminal and iTerm2

**Commit:** `feat: dark/light themes with DeepSeek-blue accent`

### Task 5: Header + Footer + ModeCycler Widgets

**Files:** `writer_tui/widgets/header.py`, `writer_tui/widgets/footer.py`, `writer_tui/widgets/mode_cycler.py`, `writer_tui/widgets/status_badge.py`

**Steps:**
- [ ] Create `writer_tui/widgets/status_badge.py` — colored chip for mode/phase
- [ ] Create `writer_tui/widgets/mode_cycler.py` — Tab/Shift+Tab cycling through 9 modes
- [ ] Create `writer_tui/widgets/header.py` — ModeBadge | Title | PhaseChip | TurnCount
- [ ] Create `writer_tui/widgets/footer.py` — Token count, cost, shortcut hints
- [ ] Create `ChatScreen` (in `screens/chat.py`) composing Header + Footer with BINDINGS

**Verification:**
- [ ] `Tab` cycles mode badge EXECUTE → TEACH → ... → COMFORT → EXECUTE
- [ ] `Shift+Tab` cycles backward
- [ ] Header shows mode, phase, turn count; Footer shows token hints

**Commit:** `feat: header, footer, and mode cycler widgets`

### Task 6: Composer Widget

**Files:** `writer_tui/widgets/composer.py`, `writer_tui/screens/chat.py` (update)

**Steps:**
- [ ] Create `writer_tui/widgets/composer.py` — multiline TextArea + mode badge inline
- [ ] Implement Ctrl+Enter → submit (placeholder: just print text to log)
- [ ] Implement input state: "Message Writer..." / "Respond to Writer..." based on status
- [ ] Add send button (or icon) on right side

**Verification:**
- [ ] Type multiline text, Ctrl+Enter captures full content
- [ ] Composer height grows up to max-height: 10
- [ ] Text clears after submit (or stays if paused)

**Commit:** `feat: multiline composer widget with submit`

### Task 7: TranscriptWidget + VirtualMessageList

**Files:** `writer_tui/widgets/transcript.py`, `writer_tui/widgets/message.py`, `writer_tui/widgets/text_block.py`

**Steps:**
- [ ] Create `writer_tui/widgets/text_block.py` — renders markdown/plain text with Rich renderable
- [ ] Create `writer_tui/widgets/message.py` — container for blocks, role-differentiated styling
- [ ] Create `writer_tui/widgets/transcript.py` — virtual scrolling list
- [ ] Implement `_visible_range()` — calculate which MessageWidgets are visible + 5 overscan
- [ ] Implement scroll: j/k, g/G, Ctrl+D/U

**Verification:**
- [ ] Pre-populate test messages; scroll works with j/k
- [ ] Virtual rendering: only visible messages mounted, offscreen unmounted
- [ ] User messages left-bordered blue, assistant messages left-bordered neutral

**Commit:** `feat: virtual-scrolling transcript with message widgets`

### Task 8: ThinkingBlock + ToolCallBlock

**Files:** `writer_tui/widgets/thinking_block.py`, `writer_tui/widgets/tool_call_block.py`

**Steps:**
- [ ] Create `writer_tui/widgets/thinking_block.py` — collapsible with `[+]`/`[-]` toggle, italic muted text
- [ ] Create `writer_tui/widgets/tool_call_block.py` — expandable with tool name, args, status spinner, truncated output
- [ ] Enter/Space toggle expand/collapse
- [ ] Status-dependent styling: running (dashed border + spinner), completed (green), error (red)

**Verification:**
- [ ] Toggle thinking block: shows/hides reasoning text
- [ ] ToolCallBlock shows tool_name, args preview, expandable output
- [ ] Status transitions visually correct (pending → running → completed/error)

**Commit:** `feat: thinking block and tool call widgets`

### Task 9: Wire SSE → Real-Time Display

**Files:** `writer_tui/screens/chat.py` (major update), `writer_tui/app.py` (update)

**Steps:**
- [ ] In `ChatScreen`, on Ctrl+Enter: call `backend.chat_stream()`, run SSE consumer in async worker
- [ ] SSE worker: for each event → `state.apply(event)` → Textual `post_message(StateStoreChanged(...))`
- [ ] `ChatScreen.on_state_store_changed`: fan out to widgets
- [ ] `TranscriptWidget`: append to `current_streaming` on text/thought/tool_call events
- [ ] `ComposerWidget`: disable during streaming, re-enable on done/paused
- [ ] `FooterWidget`: update token counts from events (if available) or local estimates
- [ ] Handle `writer_waiting_for_user`: show paused state, allow user to type response
- [ ] Handle `writer_done`: commit message, clear streaming state

**Verification:**
- [ ] Start backend, start TUI, send "say hello in one sentence" → text appears in transcript
- [ ] Send "create a file called hello.txt with content 'world'" → ToolCallBlock appears + updates
- [ ] Send "what do you think about this?" → ThinkingBlock appears (collapsed)
- [ ] Pause flow: if Writer asks a question, TUI shows "Respond to Writer..." prompt

**Commit:** `feat: real-time SSE streaming to transcript`

### Task 10: Session Management

**Files:** `writer_tui/screens/session_list.py`, `writer_tui/screens/chat.py` (update), `writer_tui/app.py` (update)

**Steps:**
- [ ] Create `writer_tui/screens/session_list.py` — ListView of sessions from `GET /api/sessions`
- [ ] Entry point: on mount, `push_screen(SessionListScreen())` (or skip if `--session-id` provided)
- [ ] Create new session: `n` → prompt for title → POST /api/sessions → push ChatScreen
- [ ] Open existing: `Enter` → GET /api/sessions/{id}/messages → load history → push ChatScreen
- [ ] ChatScreen composable: receives session_id, preloads historical messages

**Verification:**
- [ ] TUI starts → shows session list (from live backend)
- [ ] `n` → create session → ChatScreen appears
- [ ] Select existing session → ChatScreen with history loaded
- [ ] `--session-id abc123` skips list screen

**Commit:** `feat: session list and management screens`

### Task 11: Command Palette

**Files:** `writer_tui/screens/command_palette.py`

**Steps:**
- [ ] Create `writer_tui/screens/command_palette.py` — ModalScreen with Input + OptionList
- [ ] Fuzzy search: filter COMMANDS list by query substring
- [ ] Command actions: new session, list sessions, set mode, cancel, toggle theme, quit
- [ ] Wire Ctrl+K binding to `push_screen(CommandPaletteScreen())`
- [ ] `Ctrl+j/k` navigate results, `Enter` execute, `ESC` dismiss

**Verification:**
- [ ] `Ctrl+K` opens palette overlay
- [ ] Typing "mode" shows only mode-related commands
- [ ] Selecting "Set Mode: TEACH" switches current mode
- [ ] `ESC` closes palette

**Commit:** `feat: command palette with fuzzy search`

### Task 12: Permission Dialog

**Files:** `writer_tui/widgets/permission_dialog.py`

**Steps:**
- [ ] Create `writer_tui/widgets/permission_dialog.py` — ModalScreen overlay
- [ ] Display: tool name, params snippet, description
- [ ] Bindings: `y` → approve, `n` → reject, `ESC` → dismiss
- [ ] Wire into ChatScreen: on pending_approval set, push this dialog; on answer, resume backend
- [ ] Note: backend MVP auto-approves; dialog is infrastructure for future when auto-approve disabled

**Verification:**
- [ ] Dialog renders with tool info
- [ ] `y`/`n`/`ESC` produce correct callbacks
- [ ] Dialog dismisses after action

**Commit:** `feat: permission dialog for tool approval`

### Task 13: Markdown Rendering + Utilities

**Files:** `writer_tui/utils/markdown.py`, `writer_tui/utils/tokens.py`, `writer_tui/utils/keys.py`

**Steps:**
- [ ] Create `writer_tui/utils/markdown.py` — `render_markdown(text: str) → Rich Renderable`
- [ ] Support: headers, bold, italic, inline code, fenced code blocks, lists, links
- [ ] Create `writer_tui/utils/tokens.py` — approximate token counting for footer display
- [ ] Create `writer_tui/utils/keys.py` — keybinding constants dict (for help screen)

**Verification:**
- [ ] Markdown: `## Header` renders as bold; `**bold**` renders bold; ```python ...``` renders as code block
- [ ] Token counter returns reasonable estimates

**Commit:** `feat: markdown rendering and token utilities`

### Task 14: Help Screen + Polish

**Files:** `writer_tui/screens/help.py` (new), `writer_tui/app.py` (update)

**Steps:**
- [ ] Create `writer_tui/screens/help.py` — scrollable keybinding reference (from `utils/keys.py`)
- [ ] Wire `F1` binding to push HelpScreen
- [ ] Add loading spinner during initial backend connection
- [ ] Add error banner at top when backend unreachable
- [ ] Polish: smooth scrolling animation, proper truncation for long tool outputs

**Verification:**
- [ ] `F1` shows full keybinding reference
- [ ] Help screen scrollable with j/k
- [ ] Loading spinner while connecting to backend
- [ ] Error banner appears when backend is unreachable

**Commit:** `feat: help screen and UI polish`

### Task 15: E2E Integration Test

**Files:** `writer_tui/tests/test_e2e.py` (new)

**Steps:**
- [ ] Ensure backend is running on port 6173
- [ ] Use `textual` test harness (or subprocess) to run TUI with a real backend
- [ ] Send "开发一个食谱管理应用" (the task from AGENTS.md known issue)
- [ ] Assert: events received, messages rendered, tool calls displayed
- [ ] Assert: TUI doesn't crash, SSE stream completes, Writer reaches done state
- [ ] Screenshot/verify: transcript shows full conversation

**Verification:**
- [ ] Test passes: TUI starts, connects, streams, displays, and exits cleanly
- [ ] All message blocks (text, thinking, tool_call) appear in output
- [ ] Writer completes the recipe app task

**Commit:** `test: E2E test for recipe app creation via TUI`

---

## 10. Dependency Summary

### New Dependencies (TUI only)

```
textual>=2.1.0       # Core TUI framework (React-like, CSS-based, reactive)
aiohttp>=3.11.0      # Async HTTP client + SSE streaming (already in backend deps)
httpx>=0.27.0        # Sync HTTP fallback for startup health check
rich>=13.0           # Bundled with textual; explicit for markdown rendering
```

### Existing (No Changes)

```
fastapi, uvicorn, pydantic, sqlalchemy, aiosqlite — backend deps, untouched
```

### Installation

```bash
pip install -r backend/requirements.txt   # Existing deps
pip install -r writer_tui_requirements.txt # TUI deps
# Or combined:
pip install -r backend/requirements.txt textual>=2.1.0
```

---

## 11. Known Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `textual` CSS may not render identically across terminals | Use `base.tcss` with minimal structural rules; test in Windows Terminal, iTerm2, Alacritty |
| SSE streaming over aiohttp may block Textual event loop | Use aiohttp within the existing asyncio event loop (Textual is built on asyncio); use `asyncio.create_task` for SSE consumer |
| Virtual scrolling complexity in `textual` (no built-in virtual list) | Implement manual `_visible_range` with overscan; unmount offscreen widgets; this is the Claude Code approach |
| Large tool outputs (10K+ chars) may cause rendering lag | Truncate to 500 chars in reducer by default; expand on click |
| Backend timeouts on slow connections | Textual's async nature handles this; show status spinner while waiting |

---

## Appendix A: Interaction Mode Display

| Mode | Badge Color | Icon (Text) |
|------|-------------|-------------|
| EXECUTE | Green | `▶` |
| TEACH | Blue | `📖` |
| DISCUSS | Purple | `💬` |
| PROTOTYPE | Yellow | `⚡` |
| REVIEW | Orange | `🔍` |
| BRAINSTORM | Cyan | `💡` |
| PAIR | Teal | `🤝` |
| DECISION | Red | `⚖` |
| COMFORT | Pink | `❤` |

## Appendix B: SSE Event Wire Format (Backend → TUI)

```
event: writer_response
data: {"event":"writer_response","data":{"session_id":"abc","text":"Hello world","output_type":"text","output_meta":{}}}

event: writer_thought
data: {"event":"writer_thought","data":{"session_id":"abc","text":"Let me think about this..."}}

event: writer_action_started
data: {"event":"writer_action_started","data":{"action_type":"write_file","params":{"path":"test.txt","content":"hello"},"session_id":"abc"}}

event: writer_part_updated
data: {"event":"writer_part_updated","data":{"part_type":"tool_call","status":"completed","tool_name":"write_file","content":"File written","session_id":"abc"}}

event: writer_phase_changed
data: {"event":"writer_phase_changed","data":{"session_id":"abc","phase":"executing"}}

event: writer_mode_changed
data: {"event":"writer_mode_changed","data":{"session_id":"abc","mode":"PROTOTYPE"}}

event: writer_workflow
data: {"event":"writer_workflow","data":{"session_id":"abc","workflow_phase":"drafting","workflow_data":{}}}

event: writer_waiting_for_user
data: {"event":"writer_waiting_for_user","data":{"session_id":"abc","question":"Should I proceed?"}}

event: writer_resumed
data: {"event":"writer_resumed","data":{"session_id":"abc"}}

event: writer_done
data: {"event":"writer_done","data":{"session_id":"abc"}}

event: writer_error
data: {"event":"writer_error","data":{"session_id":"abc","error":"Something went wrong"}}
```

## Appendix C: Textual Worker Pattern for SSE

```python
# writer_tui/screens/chat.py — SSE consumer pattern

@work(exclusive=True, thread=False)
async def _consume_sse(self, session_id: str, message: str) -> None:
    """SSE consumer: yield events → update state → post messages."""
    async for event in self.app.backend.chat_stream(session_id, message, self.mode):
        changed_key = self.app.state.apply(event)
        if changed_key == "current_streaming":
            self.post_message(self.StreamingUpdate(self.app.state.current_streaming))
        elif changed_key:
            self.post_message(self.StateChanged(changed_key, getattr(self.app.state, changed_key)))

class StreamingUpdate(Message):
    def __init__(self, msg: dict | None) -> None:
        self.msg = msg
        super().__init__()

class StateChanged(Message):
    def __init__(self, key: str, value: object) -> None:
        self.key = key
        self.value = value
        super().__init__()
```
