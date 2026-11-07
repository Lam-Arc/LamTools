# Sunday Windows sandbox runtime

user:“给我把 2 阶段做完，前端除外”+(使用真实文件写隔离后端，单独管理依赖和打包资源)。

This backend runtime is separate from the frontend. Install with `npm ci --ignore-scripts --prefix core/runtime/windows-sandbox` before running or building the Python host. Node 22 or later must be discoverable as `node.exe`. The Python package includes this directory as `lamtools_core/resources/windows-sandbox`; building without installing its dependencies leaves confinement unavailable and must not be treated as a working sandbox deployment.

The maintained MIT-licensed backend is `@deepseek-ai/dsh-sandbox-windows-acl@0.2.2-alpha.2`. Its npm integrity is `sha512-+TT6RdkXnyLrY3Faj4hwc710dTBQ7hGNP2BBmhF7snTYzJEX/PGFINfzi2jv2tsPqHSjGzjSsncGlhbi8BYpnQ==`; the lockfile pins the dependency graph. Package sources and licenses remain in their installed packages. This version implements the inspected contract in `deepseek-ai/deepseek-harness@f3803c96974ad4a94195fb97e5c637e9c2a3afe3`; this statement does not claim that the npm build is byte-identical to that source checkout.

The backend uses restricted tokens, low integrity, and capability ACLs. Enforcement is **partial**: it restricts file writes, with upstream ambient Everyone/logon SID and hard-link boundaries; it does not restrict reads, network or process visibility. Workspace grants are standing ACL and low-integrity-label changes retained by upstream for reuse. Private temp grants and directories belong to each run and are reclaimed. Tests apply grants only to disposable test workspaces.

Python's original Windows Job owns the runner and descendants. Missing runtime, incompatible native code, or runner failure never triggers an unconfined retry. Only an explicitly selected `danger-full-access` policy uses the ordinary process path. See `agent_docs/plugin_phase2_public_ports.md` for the SDK policy, cancellation and migration limits. This backend is not connected automatically to ordinary filesystem, shell, terminal or main-agent tools.
