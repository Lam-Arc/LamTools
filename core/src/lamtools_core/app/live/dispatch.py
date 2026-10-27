"""Built-in live-operation registration; contains no operation implementation."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from .approvals import handle_approval_respond_operation
from .attachments import (
    handle_attachment_get_operation,
    handle_attachment_list_operation,
    handle_attachment_open_operation,
    handle_attachment_preview_operation,
)
from .commands import handle_command_catalog_operation, handle_command_execute_operation
from .composer import handle_session_composer_set_operation
from .interactions import handle_interaction_list_operation, handle_interaction_respond_operation
from .permissions import handle_session_permissions_set_operation
from .processes import (
    handle_process_forget_operation,
    handle_process_kill_operation,
    handle_process_list_operation,
    handle_process_log_operation,
)
from .queue import (
    handle_queue_create_operation,
    handle_queue_delete_operation,
    handle_queue_guidance_operation,
    handle_queue_update_operation,
)
from .steering import handle_turn_steer_operation
from .threads import (
    handle_sync_start_operation,
    handle_thread_history_operation,
    handle_thread_outline_operation,
    handle_thread_read_operation,
    handle_thread_resume_operation,
    handle_thread_start_operation,
)
from .turn_cancel import (
    handle_turn_cancel_operation,
    handle_turn_force_reset_operation,
    handle_turn_terminate_operation,
)
from .turn_pause import handle_turn_pause_operation
from .turn_start import handle_turn_resume_operation, handle_turn_start_operation


_CORE_LIVE_OPERATION_EXECUTORS = {
    "sync.start": handle_sync_start_operation,
    "thread.start": handle_thread_start_operation,
    "thread.read": handle_thread_read_operation,
    "thread.resume": handle_thread_resume_operation,
    "thread.history": handle_thread_history_operation,
    "thread.outline": handle_thread_outline_operation,
    "turn.start": handle_turn_start_operation,
    "turn.resume": handle_turn_resume_operation,
    "turn.pause": handle_turn_pause_operation,
    # ``turn.cancel`` keeps its terminal meaning for clients that still send it
    # (mobile); the desktop sends ``turn.terminate`` for the explicit stop.
    "turn.cancel": handle_turn_cancel_operation,
    "turn.terminate": handle_turn_terminate_operation,
    "turn.force_reset": handle_turn_force_reset_operation,
    "turn.steer": handle_turn_steer_operation,
    "approval.respond": handle_approval_respond_operation,
    "interaction.list": handle_interaction_list_operation,
    "interaction.respond": handle_interaction_respond_operation,
    "session.permissions.set": handle_session_permissions_set_operation,
    "session.composer.set": handle_session_composer_set_operation,
    "command.catalog": handle_command_catalog_operation,
    "command.execute": handle_command_execute_operation,
    "attachment.list": handle_attachment_list_operation,
    "attachment.get": handle_attachment_get_operation,
    "attachment.preview": handle_attachment_preview_operation,
    "attachment.open": handle_attachment_open_operation,
    "queue.create": handle_queue_create_operation,
    "queue.update": handle_queue_update_operation,
    "queue.delete": handle_queue_delete_operation,
    "queue.guide": handle_queue_guidance_operation,
    "process.list": handle_process_list_operation,
    "process.kill": handle_process_kill_operation,
    "process.forget": handle_process_forget_operation,
    "process.log": handle_process_log_operation,
}
