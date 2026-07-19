# LamWriter TUI Implementation Plan

> **For agentic workers:** Use `executing-plans` or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a terminal-native TUI for LamWriter that connects to the FastAPI backend via SSE, supporting real-time event streaming, all 9 interaction modes, 15 action types, tool approval, thinking blocks, and session management.

**Architecture:** Separate TUI client app (Python/Textual) communicates with FastAPI backend via HTTP REST + SSE streaming. The TUI runs in an alternate terminal screen (alt-buffer) with a Header-Transcript-Composer-Footer layout inspired by DeepSeek TUI and Claude Code, using Textual's reactive widget system for async event handling.

**Tech Stack:** Python 3.14, Textual (TUI framework), httpx (HTTP client + SSE), Pydantic (data models), Rich (rendering within Textual)

---

## Architecture Diagram

```
+------------------------+        HTTP REST        +---------------------------+
|  LamWriter TUI Client  |  <------------------->  |   LamWriter FastAPI       |
|  (Python/Textual)      |        SSE Stream       |   Backend                   |
|                        |  <--------------------  |                             |
|  +------------------+  |                         |  /api/sessions              |
|  | HeaderWidget     |  |                         |  /api/sessions/{id}/chat  |
|  | (mode, session)  |  |                         |  /api/sessions/{id}/msgs  |
|  +------------------+  |                         |  /api/sessions/events       |
|  | TranscriptWidget |  |                         |                             |
|  | (virtual scroll) |  |                         |  SSE Events:                |
|  +------------------+  |                         |  writer_turn_started        |
|  | ComposerWidget   |  |                         |  writer_response            |
|  | (input + send)   |  |                         |  writer_action_started      |
|  +------------------+  |                         |  writer_action_completed    |
|  | FooterWidget     |  |                         |  writer_thinking          |
|  | (shortcuts, info)|  |                         |  writer_done                |
|  +------------------+  |                         |  writer_waiting_for_approval|
|                        |                         |  writer_error               |
|  Components:           |                         |  writer_mode_changed        |
|  - SSEClient (async)  |                         |  writer_phase_changed       |
|  - SessionStore        |                         |  writer_part_updated        |
|  - EventBus            |                         |                             |
|  - CommandPalette      |                         |                             |
+------------------------+                         +-----------------------------+
```

---

## File Structure

```
tui/
├── pyproject.toml              # Project config, dependencies
├── requirements.txt            # runtime deps: textual, httpx, pydantic
├── README.md                   # Quick start guide
├── src/
│   └── lamwriter_tui/
│       ├── __init__.py
│       ├── __main__.py         # Entry point: python -m lamwriter_tui
│       ├── app.py              # Main TUI App (Textual App subclass)
│       ├── config.py           # TUI config (API base URL, theme)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── client.py       # HTTP REST client (httpx)
│       │   ├── sse.py          # SSE streaming client
│       │   └── models.py       # Pydantic models for API responses
│       ├── screens/
│       │   ├── __init__.py
│       │   ├── main_screen.py  # Primary screen with Header/Transcript/Composer/Footer
│       │   ├── session_screen.py  # Session list/create/switch
│       │   └── command_palette.py # Ctrl+K command palette overlay
│       ├── widgets/
│       │   ├── __init__.py
│       │   ├── header.py       # Top bar: mode badge, session name, status
│       │   ├── transcript.py   # Scrollable message list (virtualized)
│       │   ├── composer.py     # Bottom input area
│       │   ├── footer.py       # Shortcut hints, status chips
│       │   ├── message_row.py  # Individual message rendering
│       │   ├── thinking_block.py # Collapsible thinking/reasoning
│       │   ├── tool_call.py    # Tool call display with approval
│       │   ├── mode_badge.py   # Interaction mode indicator
│       │   └── session_list.py # Session list widget
│       ├── stores/
│       │   ├── __init__.py
│       │   ├── session_store.py # In-memory session state management
│       │   └── event_bus.py    # Internal pub/sub for UI updates
│       └── utils/
│           ├── __init__.py
│           ├── themes.py       # Color schemes, styling
│           └── helpers.py      # Misc utilities
```

---

## Component Breakdown

### 1. API Layer

#### api/client.py - HTTP REST Client

```python
class LamWriterClient:
    """Async HTTP client for LamWriter backend."""
    
    def __init__(self, base_url: str = "http://localhost:6173/api"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[Session]:
        """GET /sessions"""
    
    async def create_session(self, title: str, work_root: str = "", mode: str = "EXECUTE") -> Session:
        """POST /sessions"""
    
    async def get_session(self, session_id: str) -> Session | None:
        """GET /sessions/{session_id}"""
    
    async def delete_session(self, session_id: str) -> None:
        """DELETE /sessions/{session_id}"""
    
    async def send_message(self, session_id: str, message: str, work_root: str = "", mode: str = "EXECUTE") -> None:
        """POST /sessions/{session_id}/chat (starts SSE stream)"""
    
    async def cancel_session(self, session_id: str) -> None:
        """POST /sessions/{session_id}/cancel"""
    
    async def resume_session(self, session_id: str, message: str) -> None:
        """POST /sessions/{session_id}/resume"""
```

#### api/sse.py - SSE Streaming Client

```python
class SSEClient:
    """Async SSE client that streams events from the backend."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[dict], Awaitable[None]]] = []
    
    async def connect(self, session_id: str | None = None) -> None:
        """Connect to SSE endpoint and start streaming."""
        # GET /sessions/events?session_id={id}
        # Parse SSE events, dispatch to callbacks
    
    def on_event(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """Register an event handler."""
    
    async def disconnect(self) -> None:
        """Close SSE connection."""
    
    def is_connected(self) -> bool:
        """Check if connected."""
```

#### api/models.py - Pydantic Models

```python
class Session(BaseModel):
    id: str
    title: str
    work_root: str
    branch: str | None
    phase: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime

class Message(BaseModel):
    id: str
    session_id: str
    role: str
    content: str | None
    parts: dict | None
    created_at: datetime

class WriterEvent(BaseModel):
    event: str
    data: dict[str, Any]
```

---

### 2. Store Layer

#### stores/session_store.py - Session State Management

```python
class SessionStore:
    """In-memory store for session state and messages."""
    
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.messages: dict[str, list[Message]] = {}
        self.current_session_id: str | None = None
        self.current_mode: str = "EXECUTE"
        self.current_phase: str = "idle"
        self.pending_approvals: dict[str, WriterAction] = {}
    
    def add_session(self, session: Session) -> None:
        """Add or update a session."""
    
    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID."""
    
    def set_current_session(self, session_id: str) -> None:
        """Set the active session."""
    
    def add_message(self, session_id: str, message: Message) -> None:
        """Add a message to a session's transcript."""
    
    def get_messages(self, session_id: str) -> list[Message]:
        """Get all messages for a session."""
    
    def add_pending_approval(self, action: WriterAction) -> None:
        """Queue an action waiting for user approval."""
    
    def approve_action(self, action_id: str) -> WriterAction | None:
        """Mark an action as approved."""
    
    def reject_action(self, action_id: str) -> WriterAction | None:
        """Mark an action as rejected."""
```

#### stores/event_bus.py - Internal Pub/Sub

```python
class EventBus:
    """Simple pub/sub for decoupled UI updates."""
    
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
    
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to an event type."""
    
    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from an event type."""
    
    def publish(self, event_type: str, data: Any) -> None:
        """Publish an event to all subscribers."""
```

---

### 3. Widget Layer

#### widgets/header.py - Top Bar

```python
class HeaderWidget(Widget):
    """Top bar showing mode badge, session name, and connection status."""
    
    mode: Reactive[str] = Reactive("EXECUTE")
    session_name: Reactive[str] = Reactive("Untitled")
    phase: Reactive[str] = Reactive("idle")
    connected: Reactive[bool] = Reactive(False)
    
    def compose(self) -> ComposeResult:
        yield ModeBadge(self.mode)
        yield Static(self.session_name, id="session-name")
        yield Static(self.phase, id="phase-indicator")
        yield ConnectionStatus(self.connected)
    
    def watch_mode(self, mode: str) -> None:
        """Update mode badge when mode changes."""
    
    def watch_phase(self, phase: str) -> None:
        """Update phase indicator."""
```

#### widgets/transcript.py - Message List

```python
class TranscriptWidget(Widget):
    """Scrollable transcript of messages with virtual scrolling."""
    
    messages: Reactive[list[Message]] = Reactive([])
    
    def compose(self) -> ComposeResult:
        yield ScrollableContainer(id="transcript-container")
    
    def add_message(self, message: Message) -> None:
        """Add a message to the transcript."""
    
    def scroll_to_bottom(self) -> None:
        """Auto-scroll to the latest message."""
    
    def show_new_messages_pill(self, count: int) -> None:
        """Show 'N new messages' pill (Claude Code pattern)."""
```

#### widgets/composer.py - Input Area

```python
class ComposerWidget(Widget):
    """Bottom input area with multiline text input and send button."""
    
    def compose(self) -> ComposeResult:
        yield Input(id="composer-input", multiline=True)
        yield Button("Send", id="send-btn")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send button click."""
    
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
    
    def clear_input(self) -> None:
        """Clear the input field after sending."""
    
    def focus_input(self) -> None:
        """Focus the input field."""
```

#### widgets/footer.py - Bottom Bar

```python
class FooterWidget(Widget):
    """Footer with keyboard shortcuts and status chips."""
    
    def compose(self) -> ComposeResult:
        yield Static("Tab: cycle mode | Ctrl+K: commands | Ctrl+C: cancel", id="shortcuts")
        yield StatusChips(id="status-chips")
    
    def update_status(self, status: str) -> None:
        """Update status chips."""
```

#### widgets/thinking_block.py - Collapsible Thinking

```python
class ThinkingBlock(Widget):
    """Collapsible thinking/reasoning block (DeepSeek pattern)."""
    
    thinking: Reactive[str] = Reactive("")
    collapsed: Reactive[bool] = Reactive(True)
    
    def compose(self) -> ComposeResult:
        yield Button("Thinking...", id="thinking-toggle")
        yield Static(self.thinking, id="thinking-content")
    
    def toggle(self) -> None:
        """Toggle collapse/expand."""
    
    def append_thinking(self, text: str) -> None:
        """Append streaming thinking text."""
```

#### widgets/tool_call.py - Tool Call with Approval

```python
class ToolCallWidget(Widget):
    """Display a tool call with approval buttons (y/n/ESC)."""
    
    action: Reactive[WriterAction] = Reactive(None)
    
    def compose(self) -> ComposeResult:
        yield Static("Tool: {name}", id="tool-name")
        yield Static("{description}", id="tool-description")
        yield Button("Approve (y)", id="approve-btn")
        yield Button("Reject (n)", id="reject-btn")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle approval/rejection."""
    
    def on_key(self, event: events.Key) -> None:
        """Handle y/n/ESC keys."""
```

#### widgets/mode_badge.py - Mode Indicator

```python
class ModeBadge(Widget):
    """Colored badge showing current interaction mode."""
    
    mode: Reactive[str] = Reactive("EXECUTE")
    
    MODES = {
        "EXECUTE": ("blue", "Execute"),
        "TEACH": ("green", "Teach"),
        "DISCUSS": ("yellow", "Discuss"),
        "PROTOTYPE": ("magenta", "Prototype"),
        "REVIEW": ("cyan", "Review"),
        "BRAINSTORM": ("orange", "Brainstorm"),
        "PAIR": ("purple", "Pair"),
        "DECISION": ("red", "Decision"),
        "COMFORT": ("pink", "Comfort"),
    }
    
    def render(self) -> str:
        """Render colored mode badge."""
```

---

### 4. Screen Layer

#### screens/main_screen.py - Primary Screen

```python
class MainScreen(Screen):
    """Main TUI screen with Header/Transcript/Composer/Footer layout."""
    
    def compose(self) -> ComposeResult:
        yield HeaderWidget(id="header")
        yield TranscriptWidget(id="transcript")
        yield ComposerWidget(id="composer")
        yield FooterWidget(id="footer")
    
    def on_mount(self) -> None:
        """Connect to SSE when screen mounts."""
    
    async def handle_sse_event(self, event: dict) -> None:
        """Route SSE events to appropriate widgets."""
    
    def action_cycle_mode(self) -> None:
        """Tab: Cycle through interaction modes."""
    
    def action_command_palette(self) -> None:
        """Ctrl+K: Open command palette."""
    
    def action_cancel(self) -> None:
        """Ctrl+C: Cancel current operation."""
```

#### screens/session_screen.py - Session Management

```python
class SessionScreen(Screen):
    """Screen for listing, creating, and switching sessions."""
    
    def compose(self) -> ComposeResult:
        yield DataTable(id="session-list")
        yield Button("New Session", id="new-session-btn")
        yield Button("Switch", id="switch-btn")
        yield Button("Delete", id="delete-btn")
    
    async def load_sessions(self) -> None:
        """Load sessions from API."""
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle session actions."""
```

#### screens/command_palette.py - Command Palette

```python
class CommandPalette(Screen):
    """Ctrl+K command palette overlay (DeepSeek pattern)."""
    
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type a command...", id="palette-input")
        yield ListView(id="palette-results")
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter commands as user types."""
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Execute selected command."""
    
    COMMANDS = [
        ("New Session", "create_session"),
        ("Switch Session", "switch_session"),
        ("Delete Session", "delete_session"),
        ("Set Mode: Execute", "set_mode_execute"),
        ("Set Mode: Teach", "set_mode_teach"),
        ("Set Mode: Discuss", "set_mode_discuss"),
        ("Cancel Operation", "cancel"),
        ("Quit", "quit"),
    ]
```

---

## SSE Event Mapping

| SSE Event | UI Update | Widget |
|-----------|-----------|--------|
| `writer_turn_started` | Show turn indicator in transcript | TranscriptWidget |
| `writer_response` | Append text to current message | TranscriptWidget |
| `writer_action_started` | Show tool call card with spinner | ToolCallWidget |
| `writer_action_completed` | Update tool call with result | ToolCallWidget |
| `writer_thinking` | Append to thinking block | ThinkingBlock |
| `writer_done` | Show completion indicator, enable input | ComposerWidget |
| `writer_waiting_for_approval` | Show approval dialog (y/n/ESC) | ToolCallWidget |
| `writer_error` | Show error toast/inline | TranscriptWidget |
| `writer_mode_changed` | Update mode badge | ModeBadge |
| `writer_phase_changed` | Update phase indicator | HeaderWidget |
| `writer_part_updated` | Update part status (pending/running/completed/error) | TranscriptWidget |
| `writer_waiting_for_user` | Show pause indicator, enable input | ComposerWidget |
| `writer_resumed` | Hide pause indicator | ComposerWidget |
| `writer_session_created` | Add to session list | SessionScreen |
| `writer_session_ended` | Show session ended indicator | HeaderWidget |

---

## Implementation Phases

### Phase 1: Foundation (2-3 days)
- [ ] Set up TUI project structure (pyproject.toml, src layout)
- [ ] Create API client layer (HTTP REST + SSE)
- [ ] Implement Pydantic models for all API responses
- [ ] Build basic Textual app with alt-screen support
- [ ] Create MainScreen with Header/Transcript/Composer/Footer layout
- [ ] Implement ComposerWidget with multiline input

### Phase 2: Core Features (3-4 days)
- [ ] Implement SSE streaming and event routing
- [ ] Build TranscriptWidget with message rendering
- [ ] Add MessageRow widget for different message types
- [ ] Implement ModeBadge with color coding
- [ ] Add FooterWidget with shortcuts and status
- [ ] Create SessionScreen for session management
- [ ] Implement session list/create/switch/delete

### Phase 3: Advanced Features (2-3 days)
- [ ] Add ThinkingBlock with collapsible UI
- [ ] Implement ToolCallWidget with approval (y/n/ESC)
- [ ] Build CommandPalette (Ctrl+K)
- [ ] Add mode cycling (Tab key)
- [ ] Implement virtual scrolling for long transcripts
- [ ] Add "N new messages" pill (Claude Code pattern)

### Phase 4: Polish & E2E (2-3 days)
- [ ] Add error handling and reconnection logic
- [ ] Implement graceful disconnect/reconnect
- [ ] Add keyboard shortcuts (F1 help, Ctrl+R resume, etc.)
- [ ] Style with custom CSS (Textual CSS)
- [ ] Add E2E test: "Develop a recipe management app"
- [ ] Verify files created, score against baseline
- [ ] Performance optimization (reduce flicker, smooth scrolling)

---

## E2E Test Plan

### Test: Recipe Management App

**Steps:**
1. Start TUI: `python -m lamwriter_tui`
2. Create new session (or use existing)
3. Send message: "Develop a recipe management app"
4. Observe real-time SSE events in TUI
5. Approve/deny tool calls as needed
6. Wait for completion (writer_done event)

**Verification:**
- [ ] Files are created in the work_root directory
- [ ] TUI shows all events (thinking, actions, responses)
- [ ] Tool approvals work (y/n/ESC)
- [ ] Mode switching works (Tab)
- [ ] Command palette works (Ctrl+K)
- [ ] Session can be listed/switched

**Scoring:**
- Files created: 1 point per expected file
- Correct file structure: 1 point
- Functional app: 1 point
- TUI stability (no crashes): 1 point
- Total: 4 points

**Baseline:** Compare against manual run without TUI

---

## Key Decisions

### Framework Choice: Textual
- **Why:** React-like component model, built-in async support, CSS styling, active community
- **Alternatives considered:** Rich (lower-level, no widgets), urwid (older, less active), blessed (too low-level)
- **Trade-off:** Textual is heavier but provides everything we need out of the box

### SSE vs Polling
- **Why SSE:** Real-time streaming of thinking blocks and tool results
- **Reconnection:** Exponential backoff with max retries
- **Fallback:** If SSE fails, show error and allow manual retry

### Alt-Screen Mode
- **Why:** Prevents scrollback pollution, enables mouse support, consistent with Claude Code
- **Trade-off:** Loses terminal scrollback (mitigated by Ctrl+O transcript export)

### Session State
- **In-memory store:** Fast, reactive updates
- **No local persistence:** Sessions are server-side; TUI is stateless
- **Reconnect:** On startup, fetch session list from server

---

## Appendix: API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/sessions | List sessions |
| POST | /api/sessions | Create session |
| GET | /api/sessions/{id} | Get session |
| PATCH | /api/sessions/{id} | Update session |
| DELETE | /api/sessions/{id} | Delete session |
| GET | /api/sessions/{id}/messages | Get messages |
| POST | /api/sessions/{id}/messages | Send message |
| POST | /api/sessions/{id}/chat | Start chat with SSE |
| POST | /api/sessions/{id}/cancel | Cancel session |
| POST | /api/sessions/{id}/resume | Resume session |
| GET | /api/sessions/events | SSE event stream |
