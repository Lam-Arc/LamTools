// Shim so `node tauri ...` works from this directory.
//
// The generated Gradle build task runs `node tauri android android-studio-script`
// with the working directory set to `src-tauri`. Node treats that argument as a
// file path rather than a package name, so it looks for `./tauri` and fails even
// when the CLI is installed in node_modules.
//
// This file forwards to the real CLI, which is installed once for the desktop
// app and reused here through a directory junction. Keeping one copy means the
// Android and desktop builds cannot drift onto different Tauri versions.

require('@tauri-apps/cli/tauri.js')
