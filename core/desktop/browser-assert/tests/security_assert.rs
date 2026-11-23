// user:“安全断言进构建”+(三条独立断言，失败信息必须给 path:line，不能只说“失败了”)。
//
// user:“安全断言不能只靠字符串检查”+(静态断言降级为「必要条件」，但要把口径写准)：
//
// 已核实的绑定语义（tauri 2.11.5 `src/ipc/authority.rs:439-471` `resolve_access`）：
// ```text
// origin.matches(cmd.context) && (cmd.webviews.iter().any(|w| w.matches(webview))
//                                 || cmd.windows.iter().any(|w| w.matches(window)))
// ```
// 由此得到两个必须写进断言的事实：
// 1. **空列表不匹配任何东西**（fail-closed）。`windows: []` + `webviews: []` 不会把浏览器标签纳入，
//    所以「没有写 windows」不是漏洞；危险的是**能 glob 命中 `browser-*` 的模式**或 `"*"` 这类全通配。
// 2. 子 webview 的 `window` 是它的父窗口 label（浏览器标签挂在 `main` 下），
//    因此 `windows: ["main"]` 会通过 window 分支命中 `browser-*` webview。
//    这条通道能不能被外部站点利用，取决于该 capability 是否开放 remote 上下文
//    （`remote: { urls }`；缺省时只匹配本地 origin）。所以第 1 条断言同时约束：
//    **任何声明了 remote 上下文的 capability，都不许匹配浏览器标签，也不许匹配承载它的窗口 label。**
//
// 运行时一侧的证明是 `browser_diagnostics` 命令（在网页里探 `__TAURI_INTERNALS__` / `ipc` / `__TAURI__`
// 并尝试越权调用），配置匹配 + 运行时验证共同证明「第三方网页无法越权调用 Tauri 命令」。
use std::path::{Path, PathBuf};

/// 浏览器子 webview 的 label 形状（`browser-<tabId>`，tabId 为 `^[a-z0-9]{1,24}$`）。
const BROWSER_LABELS: [&str; 3] = ["browser-t0abc1", "browser-abc", "browser-t1z9"];

/// 承载浏览器标签的窗口 label：子 webview 的 window 分支匹配的就是它。
const HOST_WINDOW: &str = "main";

/// 注入脚本里禁止出现的字样：任何一条出现都意味着网页侧可能拿到宿主通道。
const FORBIDDEN_TOKENS: [&str; 3] = ["invoke(", "__TAURI_INTERNALS__", "@tauri-apps/api"];

/// user:“browser_security_assert 的 CI 可跑性…拆成不依赖 bin 的独立测试 crate”+
/// (本 crate 与桌面包平级放在 `core/desktop/browser-assert`，只读源码与配置文本：
///  没有 tauri 依赖就不会构建 `Sunday.exe`，本机开着 dev/安装版时也不会再撞 os error 5)。
fn desktop_dir() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dir = manifest
        .parent()
        .expect("本 crate 必须放在 core/desktop 下")
        .join("src-tauri");
    assert!(
        dir.join("tauri.conf.json").exists(),
        "找不到桌面应用包：{}（断言必须指向真实的 src-tauri）",
        dir.display()
    );
    dir
}

/// 前端 UI 包（`core/ui`），Agent 桥的白名单就在这里。
fn ui_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|desktop| desktop.parent())
        .expect("本 crate 必须放在 core/desktop 下")
        .join("ui")
}

/// 字节偏移 → 行号，用于把失败定位到 `path:line`。
fn line_of(text: &str, index: usize) -> usize {
    text[..index.min(text.len())].matches('\n').count() + 1
}

/// Tauri capability 的 label 匹配用的是 glob：这里支持 `*` 与 `?`，与 `Pattern` 的行为对齐。
fn glob_match(pattern: &str, text: &str) -> bool {
    fn walk(pattern: &[u8], text: &[u8]) -> bool {
        match pattern.first() {
            None => text.is_empty(),
            Some(b'*') => {
                // `*` 吞任意长度（含 0），逐个后缀尝试就够：pattern 很短。
                let mut index = 0;
                loop {
                    if walk(&pattern[1..], &text[index..]) {
                        return true;
                    }
                    if index >= text.len() {
                        return false;
                    }
                    index += 1;
                }
            }
            Some(b'?') => !text.is_empty() && walk(&pattern[1..], &text[1..]),
            Some(byte) => text.first() == Some(byte) && walk(&pattern[1..], &text[1..]),
        }
    }
    walk(pattern.as_bytes(), text.as_bytes())
}

/// 在原文里找到某个模式字面量的行号（`"pattern"` 带引号），找不到返回 1。
fn pattern_line(text: &str, pattern: &str) -> usize {
    let quoted = format!("\"{pattern}\"");
    match text.find(&quoted) {
        Some(index) => line_of(text, index),
        None => 1,
    }
}

/// 一条 capability 的 windows/webviews 模式是否会把浏览器标签纳入。
fn capability_failures(
    file: &Path,
    text: &str,
    capability: &serde_json::Value,
    failures: &mut Vec<String>,
) {
    let identifier = capability
        .get("identifier")
        .and_then(|value| value.as_str())
        .unwrap_or("<未命名>");
    let patterns = |key: &str| -> Vec<String> {
        capability
            .get(key)
            .and_then(|value| value.as_array())
            .map(|items| items.iter().filter_map(|item| item.as_str().map(str::to_string)).collect())
            .unwrap_or_default()
    };
    let windows = patterns("windows");
    let webviews = patterns("webviews");
    // `remote` 存在 = 这个 capability 允许作用于非本地 origin，此时窗口/标签分支才真正可被站点利用。
    let remote = capability.get("remote").is_some();

    for pattern in windows.iter().chain(webviews.iter()) {
        let line = pattern_line(text, pattern);
        // 全通配：一定把浏览器标签纳入。
        if pattern.trim_matches('*').is_empty() || pattern == "**" {
            failures.push(format!(
                "{}:{}: capability `{}` 的模式 \"{}\" 是全局通配，会把浏览器标签一起纳入",
                file.display(),
                line,
                identifier,
                pattern
            ));
            continue;
        }
        for label in BROWSER_LABELS {
            if glob_match(pattern, label) {
                failures.push(format!(
                    "{}:{}: capability `{}` 的模式 \"{}\" 命中浏览器标签 {}",
                    file.display(),
                    line,
                    identifier,
                    pattern,
                    label
                ));
            }
        }
    }

    // user:“子 webview 的 window 是父窗口 label”+(remote capability 命中 `main` 等于把网页放进来)。
    if remote {
        for pattern in windows.iter() {
            if glob_match(pattern, HOST_WINDOW) {
                failures.push(format!(
                    "{}:{}: capability `{}` 声明了 remote 上下文，且窗口模式 \"{}\" 命中承载浏览器标签的窗口 {}（子 webview 的 window 就是它）",
                    file.display(),
                    pattern_line(text, pattern),
                    identifier,
                    pattern,
                    HOST_WINDOW
                ));
            }
        }
        if windows.is_empty() && webviews.is_empty() {
            failures.push(format!(
                "{}:1: capability `{}` 声明了 remote 上下文但没有限定 windows/webviews",
                file.display(),
                identifier
            ));
        }
    }
}

#[test]
fn capabilities_never_bind_browser_webviews() {
    // 先自证 matcher 本身没坏：否则「没命中」可能只是匹配器写错了。
    assert!(glob_match("ping-card-*", "ping-card-1"));
    assert!(!glob_match("ping-card-*", "browser-abc"));
    assert!(glob_match("browser-*", "browser-abc"));
    assert!(!glob_match("main", "browser-abc"));

    let mut failures = Vec::new();

    // 1) 内联在 tauri.conf.json 里的 capabilities
    let conf_path = desktop_dir().join("tauri.conf.json");
    let conf_text = std::fs::read_to_string(&conf_path)
        .unwrap_or_else(|error| panic!("读不到 {}：{error}", conf_path.display()));
    let conf: serde_json::Value = serde_json::from_str(&conf_text)
        .unwrap_or_else(|error| panic!("{} 不是合法 JSON：{error}", conf_path.display()));
    if let Some(capabilities) = conf
        .pointer("/app/security/capabilities")
        .and_then(|value| value.as_array())
    {
        for capability in capabilities {
            capability_failures(&conf_path, &conf_text, capability, &mut failures);
        }
    }

    // 2) 独立的 capabilities/*.json（当前工作树没有，存在则一并检查）
    let capability_dir = desktop_dir().join("capabilities");
    if let Ok(entries) = std::fs::read_dir(&capability_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            let text = std::fs::read_to_string(&path)
                .unwrap_or_else(|error| panic!("读不到 {}：{error}", path.display()));
            let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) else {
                panic!("{} 不是合法 JSON", path.display());
            };
            match value {
                serde_json::Value::Array(items) => {
                    for item in items {
                        capability_failures(&path, &text, &item, &mut failures);
                    }
                }
                other => capability_failures(&path, &text, &other, &mut failures),
            }
        }
    }

    assert!(
        failures.is_empty(),
        "capability 会把浏览器标签纳入 IPC 权限（浏览器标签必须没有任何 core/插件权限）：\n{}",
        failures.join("\n")
    );
}

#[test]
fn global_tauri_is_disabled() {
    let conf_path = desktop_dir().join("tauri.conf.json");
    let conf_text = std::fs::read_to_string(&conf_path)
        .unwrap_or_else(|error| panic!("读不到 {}：{error}", conf_path.display()));
    let conf: serde_json::Value = serde_json::from_str(&conf_text)
        .unwrap_or_else(|error| panic!("{} 不是合法 JSON：{error}", conf_path.display()));

    // user:“不启用 withGlobalTauri”+(缺省即 false；显式 true 等于给网页一个 window.__TAURI__)。
    match conf.pointer("/app/withGlobalTauri") {
        None => {}
        Some(serde_json::Value::Bool(false)) => {}
        Some(other) => {
            let line = conf_text
                .find("\"withGlobalTauri\"")
                .map(|index| line_of(&conf_text, index))
                .unwrap_or(1);
            panic!(
                "{}:{}: app.withGlobalTauri 必须是缺省或 false（外部页面不能有 window.__TAURI__），当前是 {}",
                conf_path.display(),
                line,
                other
            );
        }
    }
}

/// 扫出 `name(` 之后到配对右括号之间的参数文本（跳过字符串字面量里的括号）。
fn call_argument(text: &str, start: usize) -> Option<(usize, usize)> {
    let bytes = text.as_bytes();
    let mut index = text[start..].find('(')? + start + 1;
    let mut depth = 1usize;
    let mut in_string = false;
    let mut escaped = false;
    while index < bytes.len() {
        let byte = bytes[index];
        if in_string {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                in_string = false;
            }
        } else if byte == b'"' {
            in_string = true;
        } else if byte == b'(' {
            depth += 1;
        } else if byte == b')' {
            depth -= 1;
            if depth == 0 {
                return Some((start, index));
            }
        }
        index += 1;
    }
    None
}

/// 取出 Rust 源码里的字符串字面量（普通字符串与 `r#"..."#` 原始字符串），返回 (起始偏移, 内容)。
fn string_literals(text: &str) -> Vec<(usize, String)> {
    let bytes = text.as_bytes();
    let mut literals = Vec::new();
    let mut index = 0usize;
    while index < bytes.len() {
        // 跳过注释，避免把注释里的字样算成脚本内容。
        if bytes[index] == b'/' && bytes.get(index + 1) == Some(&b'/') {
            while index < bytes.len() && bytes[index] != b'\n' {
                index += 1;
            }
            continue;
        }
        if bytes[index] == b'/' && bytes.get(index + 1) == Some(&b'*') {
            index += 2;
            while index + 1 < bytes.len() && !(bytes[index] == b'*' && bytes[index + 1] == b'/') {
                index += 1;
            }
            index += 2;
            continue;
        }
        // 原始字符串 r"..." / r#"..."#
        if bytes[index] == b'r' && matches!(bytes.get(index + 1), Some(b'"') | Some(b'#')) {
            let mut hashes = 0usize;
            let mut cursor = index + 1;
            while bytes.get(cursor) == Some(&b'#') {
                hashes += 1;
                cursor += 1;
            }
            if bytes.get(cursor) == Some(&b'"') {
                let content_start = cursor + 1;
                let terminator = format!("\"{}", "#".repeat(hashes));
                if let Some(offset) = text[content_start..].find(&terminator) {
                    literals.push((index, text[content_start..content_start + offset].to_string()));
                    index = content_start + offset + terminator.len();
                    continue;
                }
            }
        }
        // 普通字符串
        if bytes[index] == b'"' {
            let content_start = index + 1;
            let mut cursor = content_start;
            let mut escaped = false;
            while cursor < bytes.len() {
                if escaped {
                    escaped = false;
                } else if bytes[cursor] == b'\\' {
                    escaped = true;
                } else if bytes[cursor] == b'"' {
                    break;
                }
                cursor += 1;
            }
            literals.push((index, text[content_start..cursor.min(text.len())].to_string()));
            index = cursor + 1;
            continue;
        }
        index += 1;
    }
    literals
}

fn rust_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            rust_files(&path, out);
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("rs") {
            out.push(path);
        }
    }
}

/// 把注释内容替换成空格（保持长度与换行），用于「只在代码里找调用点」。
/// 字符串不遮罩：`initialization_script("")` 的参数本身就是字符串字面量。
fn mask_comments(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = bytes.to_vec();
    let mut index = 0usize;
    while index < bytes.len() {
        if bytes[index] == b'/' && bytes.get(index + 1) == Some(&b'/') {
            while index < bytes.len() && bytes[index] != b'\n' {
                out[index] = b' ';
                index += 1;
            }
            continue;
        }
        if bytes[index] == b'/' && bytes.get(index + 1) == Some(&b'*') {
            out[index] = b' ';
            out[index + 1] = b' ';
            index += 2;
            while index < bytes.len() {
                let closing = bytes[index] == b'*' && bytes.get(index + 1) == Some(&b'/');
                if bytes[index] != b'\n' {
                    out[index] = b' ';
                }
                index += 1;
                if closing {
                    if index < bytes.len() && bytes[index] != b'\n' {
                        out[index] = b' ';
                    }
                    index += 1;
                    break;
                }
            }
            continue;
        }
        index += 1;
    }
    String::from_utf8(out).unwrap_or_default()
}

fn check_tokens(path: &Path, text: &str, span_start: usize, span: &str, failures: &mut Vec<String>) {
    for token in FORBIDDEN_TOKENS {
        let mut from = 0usize;
        while let Some(offset) = span[from..].find(token) {
            let absolute = span_start + from + offset;
            failures.push(format!(
                "{}:{}: 注入脚本里出现 `{}`（网页不能拿到宿主通道）",
                path.display(),
                line_of(text, absolute),
                token
            ));
            from += offset + token.len();
        }
    }
}

#[test]
fn injected_scripts_never_expose_tauri_ipc() {
    let mut failures = Vec::new();
    let mut files = Vec::new();
    rust_files(&desktop_dir().join("src"), &mut files);
    assert!(!files.is_empty(), "没扫到任何 Rust 源文件，断言等于没跑");

    for path in &files {
        let text = std::fs::read_to_string(path)
            .unwrap_or_else(|error| panic!("读不到 {}：{error}", path.display()));
        // 1) initialization_script 调用点：参数必须是受审计的桥常量，且不含越权字样。
        //    只认代码里的调用点：注释里提到这个 API 名字不算（bridge.rs 的说明就提到过）。
        let masked = mask_comments(&text);
        let mut from = 0usize;
        while let Some(offset) = masked[from..].find("initialization_script") {
            let call_start = from + offset;
            from = call_start + "initialization_script".len();
            let Some((span_start, span_end)) = call_argument(&masked, call_start) else {
                continue;
            };
            // 参数内容用原文（masked 只把注释放成空格，位置与原文一一对应）。
            let argument = &text[span_start..span_end];
            let allowed = ["bridge::BRIDGE_SCRIPT", "BRIDGE_SCRIPT", "\"\""]
                .iter()
                .any(|allowed| argument.trim_end_matches(')').ends_with(allowed));
            if !allowed {
                failures.push(format!(
                    "{}:{}: initialization_script 的参数必须来自受审计的 bridge::BRIDGE_SCRIPT，当前是 `{}`",
                    path.display(),
                    line_of(&text, span_start),
                    argument.trim()
                ));
            }
            check_tokens(path, &text, span_start, argument, &mut failures);
        }

        // 2) bridge.rs 的脚本常量：注入到页面的字符串一个越权字样都不能有。
        if path.file_name().and_then(|name| name.to_str()) == Some("bridge.rs") {
            for (start, literal) in string_literals(&text) {
                check_tokens(path, &text, start, &literal, &mut failures);
            }
        }
    }

    // 3) user:“页面里的脚本永远不出现 invoke / __TAURI_INTERNALS__ / @tauri-apps/api（扩展覆盖新脚本）”+
    // 注入脚本本体单独成文件（由 `include_str!` 打进二进制），所以静态断言必须直接扫这份源码。
    let script_path = desktop_dir().join("src/browser/bridge_script.js");
    let script = std::fs::read_to_string(&script_path)
        .unwrap_or_else(|error| panic!("读不到 {}：{error}", script_path.display()));
    check_tokens(&script_path, &script, 0, &script, &mut failures);
    // 桥只做「读结构 / 派发合成事件 / 滚动 / 上报真实输入」：出现这些就等于扩了能力集合。
    for token in ["WebAssembly", "document.write", "fetch(", "XMLHttpRequest", "eval("] {
        if let Some(index) = script.find(token) {
            failures.push(format!(
                "{}:{}: 注入脚本里不该出现 `{}`（桥不允许发网络请求或执行任意脚本）",
                script_path.display(),
                line_of(&script, index),
                token
            ));
        }
    }
    // 用户接管信号必须来自 isTrusted，且必须真的上报。
    assert!(
        script.contains("isTrusted"),
        "{}: 注入脚本必须用 isTrusted 判断真实用户输入",
        script_path.display()
    );

    assert!(
        failures.is_empty(),
        "注入脚本会把网页接到 Tauri IPC 上（网页是不可信输入）：\n{}",
        failures.join("\n")
    );
}


// ---------------------------------------------------------------------------
// user:“保证「新增 browser 标签页能力」不会被静默漏测”+
// (命令表与 agent 桥白名单会各自长大：这里让它们互相对账，
//  新增一条 browser 命令却忘记注册、或桥里写了一条不存在的命令，都会在这里当场失败)。
// ---------------------------------------------------------------------------

fn read_text(path: &Path) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|error| panic!("读不到 {}：{error}", path.display()))
}

/// `src/browser/mod.rs` 里的全部 `fn browser_*`（都是对外命令）。
///
/// 只看 `#[cfg(test)]` 之前的部分：测试模块里的 `fn browser_open_must_stay_async()` 之类
/// 是断言本身的名字，不是命令——扫进去会变成「定义了却没注册」的假红。
fn browser_commands(text: &str) -> std::collections::BTreeSet<String> {
    let mut found = std::collections::BTreeSet::new();
    let commands_only = match text.find("#[cfg(test)]") {
        Some(index) => &text[..index],
        None => text,
    };
    for line in commands_only.lines() {
        let trimmed = line.trim();
        let Some(index) = trimmed.find("fn browser_") else { continue };
        let rest = &trimmed[index + "fn ".len()..];
        let name = rest.split('(').next().unwrap_or("").trim();
        if name.starts_with("browser_") {
            found.insert(name.to_string());
        }
    }
    found
}

/// `main.rs` 的 `generate_handler![...]` 里注册的 `browser::browser_*`。
fn registered_commands(text: &str) -> std::collections::BTreeSet<String> {
    let mut found = std::collections::BTreeSet::new();
    for line in text.lines() {
        let trimmed = line.trim();
        let Some(rest) = trimmed.strip_prefix("browser::") else { continue };
        let name = rest.trim().trim_end_matches(',').trim();
        if name.starts_with("browser_") {
            found.insert(name.to_string());
        }
    }
    found
}

/// `core/ui/src/browser/agentBridge.ts` 里 ALLOWED_COMMANDS 的白名单。
fn bridge_allowlist(text: &str) -> std::collections::BTreeSet<String> {
    let mut found = std::collections::BTreeSet::new();
    let mut inside = false;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("const ALLOWED_COMMANDS") {
            inside = true;
            continue;
        }
        if !inside {
            continue;
        }
        if trimmed.starts_with("])") {
            break;
        }
        let item = trimmed.trim_end_matches(',').trim();
        if item.starts_with('\'') && item.ends_with('\'') && item.contains("browser_") {
            found.insert(item.trim_matches('\'').to_string());
        }
    }
    found
}

#[test]
fn every_browser_command_is_registered_and_reachable_through_the_bridge() {
    let defined = browser_commands(&read_text(&desktop_dir().join("src/browser/mod.rs")));
    assert!(!defined.is_empty(), "没扫到任何 browser 命令，断言等于没跑");
    let registered = registered_commands(&read_text(&desktop_dir().join("src/main.rs")));

    for name in &defined {
        assert!(
            registered.contains(name),
            "src/browser/mod.rs 定义了 {name}，但 main.rs 的 generate_handler 里没有注册（前端永远调不到）"
        );
    }
    for name in &registered {
        assert!(defined.contains(name), "main.rs 注册了 {name}，但 src/browser/mod.rs 里没有这条命令");
    }

    let allowed = bridge_allowlist(&read_text(&ui_dir().join("src/browser/agentBridge.ts")));
    assert!(!allowed.is_empty(), "agent 桥白名单为空，等于所有 Agent 浏览器操作都被静默拒绝");
    for name in &allowed {
        assert!(
            registered.contains(name),
            "agent 桥白名单里的 {name} 没有注册，Agent 调用会永远失败"
        );
    }
}
