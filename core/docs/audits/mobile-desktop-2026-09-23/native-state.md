# Mobile native/state audit — 2026-09-23

Read-only code audit of the current Android/Tauri mobile path against the desktop HTTP project/attachment path. No source edits, network calls, credentials, or device tests. The findings below are source conclusions; where noted, Android runtime behavior still needs device verification.

## Findings

### P1 — standalone attachment upload reports success but discards content

`core/mobile/src/standalone/StandaloneTransport.ts:435-445` handles `POST /sessions/{id}/attachments` by generating metadata and returning 201. It does not persist `request.body`. `inputContent()` at about line 1493 turns an attachment input item into only `[附件: filename]`, so the Rust model receives neither bytes nor extracted content. There is no standalone `/attachments/{id}/download`, `/preview`, or `/open` handler. The shared UI uses the upload response as a successful attachment. Desktop `core/src/lamtools_core/app/http_agent_app.py:751-778` stores the bytes through `attachment_store().create` and serves downloads. User impact: false success and silent loss of the attachment's intended input. Reject standalone uploads visibly until an actual store/model input path exists, or implement durable storage and retrieval.

### P1 — restored encrypted preferences can prevent app initialization

The actual signed `release/mobile/Sunday-mobile_0.1.7.apk` merged manifest was inspected with Android SDK build-tools 36.1.0 `aapt dump xmltree AndroidManifest.xml`: targetSdkVersion is 36, and `<application>` has no `allowBackup`, `fullBackupContent`, or `dataExtractionRules` attribute. Android's default backup participation thus applies; SharedPreferences can be restored via cloud backup or device transfer if that mechanism is enabled. `core/mobile/src-tauri/gen/android/app/src/main/java/com/lamtools/mobile/LamToolsSecureStoragePlugin.kt` stores AES-GCM ciphertext in `WSSecureStorageSharedPreferences` and keys in AndroidKeyStore. This matches the previous Capacitor library's preference file, prefix and encryption format, but AndroidKeyStore keys are not portable to a restored device. On get, `secretKey()` generates a missing alias; `decrypt()` then fails authentication, the plugin rejects, and `core/mobile/src/native/secureStorage.ts` propagates. `core/mobile/src/pairing/DeviceIdentity.ts:36` does not recover from storage get failure. `core/mobile/src/App.vue:858-906` catches it only at the outer initialization boundary, stopping subsequent account/device setup. Exclude the encrypted preference file from all backup/transfer rules, or implement explicit invalidated-key recovery and re-pair flow. No backup/restore device test was run; the merged manifest and code establish exposure, not incidence.

### P2 — project file tree is flattened and directory browsing is empty

`core/mobile/src-tauri/src/lib.rs:1497-1540` recursively lists every file under the requested path, returning only `path,size`. `core/mobile/src/standalone/StandaloneProjectClient.ts:69-92` maps each to `type:'file'`, uses the full relative path as `name`, and exposes no directory entries; `browseDirectory()` at ~145 always returns `entries:[]`. The shared file tree (`core/ui/src/components/FileTreeNode.vue:139`) calls `listFiles` again when expanding directories. Desktop's `CoreProjectClient` calls `/projects/{id}/files` and `/browse-directory` (`core/ui/src/projects/client.ts:107-129`). Android users cannot navigate a native directory hierarchy or browse for a directory through this client despite native files existing. This is implementation behavior, not an Android permission requirement.

### P2 — native project writes and repository state publication are not failure-atomic

`project_file_write` in `core/mobile/src-tauri/src/lib.rs:1558-1573` uses `tokio::fs::write` directly on the destination. It can truncate an existing file before a write error or process death; this includes `AGENTS.md` via `StandaloneProjectClient.writeAgents`. By contrast, memory writes at `core/mobile/src-tauri/src/lib.rs:1011-1038` use a temporary file, sync and rename. In `core/mobile/src/storage/LocalRepository.ts:641-647`, `replaceState()` publishes `state.value` and updates `activeScope`/`localScopes` before awaiting `database.writeScope`; a failed durable write leaves UI/in-memory state ahead of SQLite and later operations can act on non-durable data. Rust `local_state_write` itself is transactional (`core/mobile/src-tauri/src/lib.rs:1677-1720`). Restore/rollback in-memory state on write failure and use atomic replacement for project text files.

### P2 — lexical project confinement does not guard existing symlinks

`safe_project_relative_path` (`core/mobile/src-tauri/src/lib.rs:1836-1858`) and Rust Agent `ProjectFileTools.resolve` (`core/runtime-rs/src/project_tools.rs:17-32`) block absolute paths and `..` but simply join components to the root. Read/list/write follow a symlink already present inside a project and can access paths outside the project, including another project or app-private state. The shipped UI and Agent text-file tools do not themselves create symlinks, and other Android apps cannot normally alter the app-private project root, so a reachable attack needs a preexisting link from another local/import/plugin route. Treat as a confinement hardening defect; validate/canonicalize components or use no-follow open semantics if any route can introduce links.

## Checked behavior and boundaries

- The Tauri state DB name is allowlisted to ASCII alphanumeric, `-`, `_` (`native_state_path`), and scoped writes use one SQLite transaction with WAL/FULL. `TauriLocalDatabase` surfaces native failure instead of silently falling back to memory. `LocalRepository` serializes its writes.
- Android secure storage intentionally reuses the old Capacitor key prefix, `WSSecureStorageSharedPreferences`, AES/GCM format, IV delimiter, and AndroidKeyStore alias. Source inspection of `node_modules/@aparajita/capacitor-secure-storage` supports upgrade compatibility for intact same-device data.
- Native turn cancellation has a per-turn latch and race against cancellation; `StandaloneTransport` generation-fences result publication. On WebView reload, `recoverOrphanedTurn` cancels a surviving native turn and marks the snapshot cancelled rather than replaying a potentially duplicated model/tool run. Approval continuation is persisted in the snapshot before the UI receives it.
- `SyncEngine` buffers live messages across snapshot/delta sync and serializes repository writes at close. This audit did not establish a replay or cursor corruption defect in that path.
- The production Network Security Config denies base cleartext and permits only `c.pki.goog` HTTP for certificate revocation retrieval. The manifest has only INTERNET permission. The FileProvider uses an external-path mapping, but is not exported and requires granted URI permission; no arbitrary URI grant route was identified in this audit.
- In Tauri, `Capacitor.isNativePlatform()` is false and `createMobileFilePicker` uses the DOM input path. The shared DOM picker sets `capture=environment` for camera and `accept=image/*` for photos; whether the Android WebView offers the intended camera/photo chooser requires device observation. This is not counted as a confirmed failure.

## Known unknowns

- No Android backup/restore, process-kill-during-write, symlink-insertion, or camera chooser device test was performed. The APK manifest check used the signed 0.1.7 APK already present locally.
- Exact app-level effect of Android backup depends on the user's enabled backup/transfer mechanism. The absence of exclusion rules in the merged APK is confirmed.
- The audit did not re-review model/provider, memory, hooks, subagent semantics, business RPC coverage, or the just-completed Study skill assembly; those are owned by the other reviewers.

## Native affordances, diagnostics and CLI parity addendum

### P2 — Tauri LAN auto-discovery is an empty adapter

`core/mobile/src/connection/LanDiscovery.ts` routes discovery through `discoverNativeLanDevices`; `core/mobile/src/native/lanDiscovery.ts:15-19` returns `[]` whenever `Capacitor.isNativePlatform()` is false. The current Android product is Tauri, so this branch is taken. `PairingClient.candidates()` at `core/mobile/src/pairing/PairingClient.ts:181-193` then has no LAN candidates without a manually entered gateway; `ConnectionManager` similarly loses native discovery. Manual gateway and account/Relay paths still exist. This is an actual Tauri adapter gap, not an Android permission limitation.

### P2 — native notification capability is claimed but no delivery path exists

`core/mobile/src/native/notifications.ts:11-13` exports `notifyMobile` as an empty async function; `registerPushNotifications()` is Capacitor-only and has no call site in the mobile app. The Tauri Android merged manifest has no push notification service/receiver or POST_NOTIFICATIONS permission. `core/mobile/src/App.vue:241` correctly reports shared UI `notifications: false` under Tauri because `Capacitor.isNativePlatform()` is false. However, `core/mobile/src-tauri/src/lib.rs:1446-1453` sets `DeviceCapabilities.notifications=true`; `core/runtime-rs/src/lib.rs:846` adds that bit to the Agent capability map. Thus the native Agent is told notifications are available although no native notification tool/delivery implementation was identified. Set this capability false until implemented; do not infer that the shared UI itself advertises push support.

### P2 — Android native GUI/CLI parity is absent

`core/mobile/src-tauri/src/main.rs` only calls `sunday_mobile_lib::run()`, and `core/mobile/package.json` defines build/test/Tauri launch scripts rather than commands for on-device Agent, Study, workflow, configuration, projects or state. The native commands are Tauri `invoke_handler` operations in `core/mobile/src-tauri/src/lib.rs:1921-1958`, callable from the GUI WebView but without an on-device CLI entrypoint. `core/src/lamtools_core/cli.py:1514-1531` has a `mobile` tree for controlling the **desktop** gateway, and its `cmd_mobile_control` connects to a desktop loopback discovery file. Python Core CLI and the bundled workflow CLI operate the desktop/Python runtime or its remote RPC; they do not invoke the Android Tauri Rust host or its app-private SQLite/Keystore/Study state. Therefore the project's AGENTS rule that every GUI capability have corresponding CLI is unmet for the Android-native capabilities. A host-local CLI/command bridge would be needed; the existing desktop CLI is not equivalent.

### Diagnostics and lifecycle checked

- `onMobileResume` (`core/mobile/src/native/lifecycle.ts`) subscribes to browser focus/visibility events, deduplicates bursts, and attempts Capacitor `appStateChange`. In Tauri, that native listener may reject but the browser event fallback remains. No confirmed reconnect defect from code alone.
- No deep-link handling is implemented in the Tauri Android manifest (launcher MAIN/LAUNCHER only), native activity, or mobile TypeScript. No current GUI deep-link promise was found; this is a platform feature absence, not a broken route.
- Remote transport diagnostics are payload-free structured events sent to `console.info` by `defaultRemoteDiagnosticSink` (`core/mobile/src/connection/TunnelTransport.ts:36-62`). Native stage events and standalone trace state are emitted/recorded, but no dedicated mobile log export path or command was found. This limits user-supplied diagnostic capture without WebView/adb access; it does not prove logs are lost internally.
- The Tauri file picker uses the shared DOM input fallback; `core/ui/src/app/runtime.ts:100-127` sets `accept=image/*` and `capture=environment` for photo/camera requests. No code evidence that the Android chooser necessarily fails, so this remains a device-observation unknown rather than a finding.
