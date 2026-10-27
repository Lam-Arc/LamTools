"""Protocol constants copied from @tencent-connect/qqbot-nodejs 1.0.5.

Keeping the numeric values here (instead of importing the Node package) makes
the port self-contained and lets tests assert the wire format directly.
"""

from __future__ import annotations

# ── Gateway intents (QQ Open Platform) ─────────────────────────────────────
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MEMBERS = 1 << 1
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_INTERACTION = 1 << 26

# The upstream SDK subscribes to every intent it knows.  The plugin only needs
# group/C2C messages and button interactions, but keeping the full mask matches
# the original plugin's behaviour and avoids silently losing future events.
FULL_INTENTS = (
    INTENT_GUILDS
    | INTENT_GUILD_MEMBERS
    | INTENT_PUBLIC_GUILD_MESSAGES
    | INTENT_DIRECT_MESSAGE
    | INTENT_GROUP_AND_C2C
    | INTENT_INTERACTION
)

# ── Gateway opcodes ────────────────────────────────────────────────────────
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# ── Gateway close codes ────────────────────────────────────────────────────
CLOSE_AUTH_FAILED = 4004
CLOSE_INVALID_SESSION = 4006
CLOSE_SEQ_OUT_OF_RANGE = 4007
CLOSE_RATE_LIMITED = 4008
CLOSE_SESSION_TIMEOUT = 4009
CLOSE_INSUFFICIENT_INTENTS = 4914
CLOSE_DISALLOWED_INTENTS = 4915

# ── Dispatch event types ───────────────────────────────────────────────────
EVENT_READY = "READY"
EVENT_RESUMED = "RESUMED"
EVENT_C2C_MESSAGE_CREATE = "C2C_MESSAGE_CREATE"
EVENT_AT_MESSAGE_CREATE = "AT_MESSAGE_CREATE"
EVENT_DIRECT_MESSAGE_CREATE = "DIRECT_MESSAGE_CREATE"
EVENT_GROUP_AT_MESSAGE_CREATE = "GROUP_AT_MESSAGE_CREATE"
EVENT_GROUP_MESSAGE_CREATE = "GROUP_MESSAGE_CREATE"
EVENT_INTERACTION_CREATE = "INTERACTION_CREATE"

MESSAGE_EVENTS = {
    EVENT_C2C_MESSAGE_CREATE,
    EVENT_AT_MESSAGE_CREATE,
    EVENT_DIRECT_MESSAGE_CREATE,
    EVENT_GROUP_AT_MESSAGE_CREATE,
    EVENT_GROUP_MESSAGE_CREATE,
}

# ── Message types ──────────────────────────────────────────────────────────
MSG_TYPE_TEXT = 0
MSG_TYPE_MARKDOWN = 2
MSG_TYPE_ARK = 3
MSG_TYPE_EMBED = 4
MSG_TYPE_INPUT_NOTIFY = 6
MSG_TYPE_MEDIA = 7

# ── Media file types ───────────────────────────────────────────────────────
MEDIA_TYPE_IMAGE = 1
MEDIA_TYPE_VIDEO = 2
MEDIA_TYPE_VOICE = 3
MEDIA_TYPE_FILE = 4

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
VOICE_EXTS = {".mp3", ".wav", ".ogg", ".aac", ".silk", ".amr"}

# ── Limits ─────────────────────────────────────────────────────────────────
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
CHUNKED_UPLOAD_MAX_SIZE = 100 * 1024 * 1024
LARGE_FILE_THRESHOLD = 5 * 1024 * 1024

# ── Defaults (mirror the upstream ConfigSchema) ────────────────────────────
DEFAULT_TOKEN_BASE_URL = "https://bots.qq.com"
DEFAULT_API_BASE_URL = "https://api.sgroup.qq.com"
DEFAULT_GATEWAY_PATH = "/gateway"
DEFAULT_TOKEN_PATH = "/app/getAppAccessToken"
DEFAULT_QR_HOST = "q.qq.com"

DEFAULT_REPLY_LIMIT = 4
DEFAULT_REPLY_LIMIT_TTL_MS = 60 * 60 * 1000
DEFAULT_STREAM_THROTTLE_MS = 500
MIN_STREAM_THROTTLE_MS = 300
DEFAULT_TYPING_SECONDS = 60
DEFAULT_TYPING_KEEPALIVE_MS = 50 * 1000
DEFAULT_HISTORY_LIMIT = 10
DEFAULT_MSGID_CACHE_PER_TARGET = 10
DEFAULT_MSGID_CACHE_TARGETS = 200
GROUP_REPLY_TTL_MS = 5 * 60 * 1000
C2C_REPLY_TTL_MS = 30 * 60 * 1000
EVENT_ID_PREFIX = "INTERACTION_CREATE:"

# Reconnect schedule from the SDK.
RECONNECT_DELAYS = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
RATE_LIMIT_DELAY = 60.0
INVALID_SESSION_DELAY = 3.0

# ── Error codes ────────────────────────────────────────────────────────────
ERR_RATE_LIMITED = 50002
ERR_UPLOAD_DAILY_LIMIT = 40093001

__all__ = [name for name in dir() if name.isupper()]
