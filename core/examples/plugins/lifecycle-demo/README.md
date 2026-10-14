# Managed plugin lifecycle example

This is an integrated Sunday capability: one manifest supplies a backend,
native Agent tool, and direct RPC operation. It starts no separate application,
performs no network/file writes, and uses no extra dependencies.

From `E:\LamTools\core`, connect the existing Sunday CLI to the running backend
using its usual `--base-url` / `--token` options:

```powershell
py -3.14 -m lamtools_core.cli plugin install local E:\LamTools\core\examples\plugins\lifecycle-demo
```

Restart Sunday after first installation so the new RPC/tool declarations are
discovered. Then inspect and exercise the same installed capability:

```powershell
py -3.14 -m lamtools_core.cli plugin list --raw
py -3.14 -m lamtools_core.cli plugin disable lifecycle-demo
py -3.14 -m lamtools_core.cli plugin enable lifecycle-demo
```

The plugin row should report `backend.state: ready` and `available: true`.
Ask Sunday's Agent to call `lifecycle_echo` with a message. Integrations can call
`lifecycle_demo.status` through the same RPC connection to read the heartbeat.
Disabled or failed backends expose neither callable entry point.

`backend.py` keeps its factory synchronous, creates its critical heartbeat in
`start`, reports that task in `lifecycle_tasks`, implements `health_check`, and
cleans up idempotently in `stop`. A plugin-specific handler package avoids
global `tools.py` import collisions.

For failure testing in a disposable copy, raise an exception in `start` or end
the heartbeat task. Inspect `plugin.list` / the plugin panel: the enabled
preference remains true but availability is false and the diagnostic is shown.
After repairing the runtime, use Retry startup / `plugin enable` for startup
recovery. Source-code edits to an already imported module require a host restart;
disable/enable reuses the runtime and is not a code updater.

The repository regression test loads this exact example, verifies its RPC,
forces heartbeat termination, and verifies recovery. See the full
[lifecycle contract](../../../docs/plugin-lifecycle.md), including deadlines,
factory-only embeddings and Task 3 update boundaries.
