---
name: network-exploration
description: Use when inspecting Sunday Network Exploration state, diagnosing DNS/TCP/TLS connectivity, managing integrated Mihomo proxy or aria2 downloads, or helping the user recover plugin-owned network settings. Includes the network_download tool for foreground or background file downloads.
---

<!-- user:“实现这个插件，也正好实验我们的新插件架构”+(使用真实数据与现有 command，不重复提供 Agent 工具)。 -->

Use Sunday's existing `run_command`. Never start a second network controller, agent loop or unmanaged network kernel.

Read state from the running host:

```text
core network-exploration call status
core network-exploration call interfaces
core network-exploration call connections --arguments-file E:\temp\network-query.json
core network-exploration call diagnose --arguments-file E:\temp\network-query.json
core network-exploration call proxy.optimize --arguments-file E:\temp\network-query.json
core network-exploration call accelerator.start
core network-exploration call accelerator.stop
core network-exploration call transfer.list
```

The argument file is a JSON object. For diagnosis use `{"target":"github.com","port":443,"kind":"basic"}`. For connections use `{"filter":"443"}`. For automatic line selection use `{"group":"Auto"}`; `proxy.optimize` measures real members of one Selector group, skips `DIRECT`/`REJECT`, and switches to the lowest measured delay. `"fastest"` is latency-based only, not a bandwidth benchmark, and a null `selected` means every measured node failed and the current choice was kept. `accelerator.start` starts the local CONNECT accelerator on a loopback port and returns it; it resolves common GitHub/Steam/etc. domains with DoH and tunnels TLS directly without installing certificates or changing hosts. Non-matching domains use the running Mihomo core when available. A target blocked at the IP/SNI layer can still fail. `--base-url` and `--ws-path` can select the existing desktop backend; otherwise the command uses Sunday environment variables.

Use the native `network_download` tool for queued HTTP/HTTPS downloads. Pass `url`; optional `directory` (absolute), `filename`, `connections` (1–16), and `proxy`. Background is the default: it returns a `gid` immediately. Set `foreground: true` to wait until completion, failure, or `wait_seconds` (default 300, max 900); a timeout returns `status: "downloading"` and the download keeps running. The default directory is the plugin's private download folder. Never invent a success result: report the returned status and path.

Use `ping`, `tracert`, `Resolve-DnsName`, `curl`, `git`, package managers and existing CLI tools directly for capabilities they already provide. `network_download` is the only plugin-native tool and only wraps the existing download queue; prefer native package-manager caches when they already satisfy the request.

Separate measured DNS, TCP, TLS/HTTP and ICMP evidence. A timeout does not prove poisoning, censorship or a firewall failure. System-interface traffic includes traffic outside Mihomo; Mihomo counters only describe its own traffic. Per-process bandwidth and connection bytes are not measured by the current connection-table implementation.

All system DNS/proxy/firewall/QoS changes must pass the host's operation approval. If the CLI reports `approval_required`, ask the user to perform the concrete change in the Network Exploration panel; do not call the approval response endpoint, invent `confirmed` flags, adjust trust levels or bypass a hard block. An existing explicit host authorization remains valid.

The GUI provides current-user system proxy, per-interface DNS, application outbound firewall rules, application upload QoS, and transaction restoration. Never permanently elevate the plugin. Before recommending restoration, inspect its saved transaction and current ownership; an external change must be preserved. Do not install root certificates, enable TUN, change routes or claim those unsupported operations succeeded.

Downloads use the integrated aria2 engine. Interrupted tasks recover paused; resuming reuses `.aria2` metadata. Sensitive URLs and subscription configurations are encrypted using the current Windows account. Never copy decrypted configurations, URLs with credentials, cookies, tokens or encrypted credential blobs into chat or diagnostic logs.
