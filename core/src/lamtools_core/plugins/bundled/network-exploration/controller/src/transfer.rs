// user:“修”+(下载的默认值、文件名与线路选择只有 Rust 后台一份实现)。
use serde_json::{json, Value};
pub fn normalize(mut p: Value) -> Result<Value, String> {
    let url = p["url"].as_str().ok_or("缺少下载地址")?.trim().to_string();
    let parsed = crate::observe::http_url(&url)?;
    p["url"] = json!(url);
    let filename = match p.get("filename") {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(value)) => value.trim().to_string(),
        _ => return Err("文件名必须是字符串".into()),
    };
    let filename = if filename.is_empty() {
        derive_filename(&parsed)
    } else {
        filename
    };
    p["filename"] = json!(filename);
    let connections = match p.get("connections") {
        None => 8,
        Some(value) => value
            .as_u64()
            .filter(|v| (1..=16).contains(v))
            .ok_or("下载连接数应为 1–16 的整数")?,
    };
    p["connections"] = json!(connections);
    if let Some(directory) = p.get("directory") {
        let directory = directory.as_str().ok_or("下载目录必须是字符串")?.trim();
        if directory.is_empty() {
            p.as_object_mut().unwrap().remove("directory");
        } else {
            p["directory"] = json!(directory);
        }
    }
    if let Some(value) = p.get("bytes_per_second") {
        if value.as_u64().is_none() {
            return Err("限速应为非负整数".into());
        }
    }
    if p.get("sha256").is_some_and(|v| !v.is_string()) {
        return Err("SHA-256 必须是字符串".into());
    }
    // user:“接管时把 Cookie 和 User-Agent 传给 aria2”+(只接受三个请求头，禁止换行注入，总量有上限)。
    p["headers"] = normalize_headers(p.get("headers"))?;
    let source = match p.get("source") {
        None | Some(Value::Null) => "page".to_string(),
        Some(Value::String(value)) => value.trim().to_lowercase(),
        _ => return Err("来源必须是字符串".into()),
    };
    if !matches!(source.as_str(), "page" | "tool" | "browser") {
        return Err("来源只能是 page、tool 或 browser".into());
    }
    p["source"] = json!(source);
    Ok(p)
}
/// 允许的请求头：只做转发登录态所需的最小集合。
const ALLOWED_HEADERS: [&str; 3] = ["Cookie", "User-Agent", "Referer"];
fn normalize_headers(value: Option<&Value>) -> Result<Value, String> {
    let Some(value) = value else {
        return Ok(json!({}));
    };
    if value.is_null() {
        return Ok(json!({}));
    }
    let map = value.as_object().ok_or("headers 必须是对象")?;
    if map.is_empty() {
        return Ok(json!({}));
    }
    let mut total = 0usize;
    let mut out = serde_json::Map::new();
    for (key, raw) in map {
        let canonical = ALLOWED_HEADERS
            .iter()
            .find(|allowed| allowed.eq_ignore_ascii_case(key))
            .ok_or_else(|| format!("不支持的请求头 {key}"))?;
        let text = raw.as_str().ok_or("请求头的值必须是字符串")?.trim();
        if text.is_empty() {
            continue;
        }
        if text.contains(['\r', '\n', '\0']) {
            return Err("请求头里不能有换行或空字符".into());
        }
        total += canonical.len() + text.len();
        if total > 8192 {
            return Err("请求头总长度超过 8 KB".into());
        }
        out.insert((*canonical).to_string(), json!(text));
    }
    Ok(Value::Object(out))
}
/// aria2 的 `header` 选项是字符串数组，这里把白名单对象摊开。
pub fn header_lines(value: &Value) -> Vec<String> {
    value
        .as_object()
        .map(|map| {
            map.iter()
                .map(|(key, raw)| format!("{key}: {}", raw.as_str().unwrap_or("")))
                .collect()
        })
        .unwrap_or_default()
}
fn derive_filename(url: &reqwest::Url) -> String {
    let source = url.path().rsplit('/').next().unwrap_or("").as_bytes();
    let mut decoded = Vec::new();
    let mut index = 0;
    while index < source.len() {
        if source[index] == b'%' && index + 2 < source.len() {
            if let (Some(a), Some(b)) = (
                (source[index + 1] as char).to_digit(16),
                (source[index + 2] as char).to_digit(16),
            ) {
                decoded.push((a * 16 + b) as u8);
                index += 3;
                continue;
            }
        }
        decoded.push(source[index]);
        index += 1;
    }
    let mut name: String = String::from_utf8_lossy(&decoded)
        .chars()
        .map(|ch| {
            if ch.is_control() || "\\/:*?\"<>|".contains(ch) {
                '_'
            } else {
                ch
            }
        })
        .collect();
    // Windows 文件名和接口均按 UTF-8 字节限制，不能切断一个字符。
    while name.len() > 200 {
        name.pop();
    }
    name = name.trim_end_matches(['.', ' ']).to_string();
    let stem = name.split('.').next().unwrap_or("").to_ascii_uppercase();
    if matches!(
        stem.as_str(),
        "CON"
            | "PRN"
            | "AUX"
            | "NUL"
            | "COM1"
            | "COM2"
            | "COM3"
            | "COM4"
            | "COM5"
            | "COM6"
            | "COM7"
            | "COM8"
            | "COM9"
            | "LPT1"
            | "LPT2"
            | "LPT3"
            | "LPT4"
            | "LPT5"
            | "LPT6"
            | "LPT7"
            | "LPT8"
            | "LPT9"
    ) {
        name.insert(0, '_');
    }
    if name.is_empty() {
        "download.bin".into()
    } else {
        name
    }
}
pub fn route(
    p: &Value,
    accelerator_port: Option<u16>,
    proxy_running: bool,
) -> Result<(&'static str, String), String> {
    let mode = if let Some(value) = p.get("route") {
        value.as_str().ok_or("下载线路无效")?
    } else if let Some(value) = p.get("proxy") {
        if value.as_bool().ok_or("proxy 必须是布尔值")? {
            "proxy"
        } else {
            "direct"
        }
    } else {
        "auto"
    };
    match mode {
        "auto" => Ok((
            "auto",
            accelerator_port
                .filter(|p| *p > 0)
                .map(|p| format!("http://127.0.0.1:{p}"))
                .unwrap_or_default(),
        )),
        "direct" => Ok(("direct", String::new())),
        "proxy" if proxy_running => Ok(("proxy", "http://127.0.0.1:17890".into())),
        "proxy" => Err("请先启动代理".into()),
        _ => Err("下载线路应为 auto、direct 或 proxy".into()),
    }
}
// user:“修”+(三个下载入口共用后台参数处理和线路决策)。
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn unified_download_defaults_and_filename() {
        let p = normalize(json!({"url":" https://example.com/My%20File%ZZ.zip "})).unwrap();
        assert_eq!(p["filename"], "My File%ZZ.zip");
        assert_eq!(p["connections"], 8);
        assert_eq!(p["url"], "https://example.com/My%20File%ZZ.zip");
        assert_eq!(
            normalize(json!({"url":"https://example.com/"})).unwrap()["filename"],
            "download.bin"
        );
        let p =
            normalize(json!({"url":format!("https://example.com/{}", "测".repeat(180))})).unwrap();
        assert!(p["filename"].as_str().unwrap().len() <= 200);
        assert!(normalize(json!({"url":"file:///tmp/a"})).is_err());
        for invalid in [json!(0), json!(17), json!(1.5), json!("8")] {
            assert!(
                normalize(json!({"url":"https://example.com/a", "connections":invalid})).is_err()
            );
        }
    }
    #[test]
    fn download_headers_are_whitelisted_and_bounded() {
        // user:“Cookie 只用于本次请求”+(只认三个头，禁换行注入，超长整批拒绝)。
        let ok = normalize(json!({
            "url":"https://example.com/a.zip",
            "headers":{"cookie":"session=ok","user-agent":"Sunday/1.0","Referer":"https://example.com/"}
        }))
        .unwrap();
        assert_eq!(ok["headers"]["Cookie"], "session=ok");
        assert_eq!(ok["headers"]["User-Agent"], "Sunday/1.0");
        assert_eq!(ok["headers"]["Referer"], "https://example.com/");
        assert_eq!(ok["source"], "page");
        assert!(normalize(json!({"url":"https://example.com/a.zip","headers":{"X-Token":"t"}})).is_err());
        assert!(normalize(json!({"url":"https://example.com/a.zip","headers":{"Cookie":"a\r\nB: c"}})).is_err());
        assert!(normalize(json!({"url":"https://example.com/a.zip","headers":{"Cookie":"x".repeat(9000)}})).is_err());
        assert!(normalize(json!({"url":"https://example.com/a.zip","source":"elsewhere"})).is_err());
        let lines = header_lines(&json!({"Cookie":"session=ok"}));
        assert_eq!(lines, vec!["Cookie: session=ok".to_string()]);
    }
    #[test]
    fn unified_download_route_obeys_explicit_choices_and_follows_acceleration() {
        assert_eq!(
            route(&json!({}), Some(49152), false).unwrap(),
            ("auto", "http://127.0.0.1:49152".to_string())
        );
        assert_eq!(route(&json!({}), None, true).unwrap().1, "");
        assert_eq!(
            route(&json!({"route":"direct"}), Some(49152), true)
                .unwrap()
                .1,
            ""
        );
        assert_eq!(
            route(&json!({"proxy":false}), Some(49152), true).unwrap().1,
            ""
        );
        assert_eq!(
            route(&json!({"proxy":true}), Some(49152), true).unwrap().1,
            "http://127.0.0.1:17890"
        );
        assert!(route(&json!({"route":"proxy"}), Some(49152), false).is_err());
        assert!(route(&json!({"route":"invalid"}), None, false).is_err());
    }
    #[tokio::test]
    async fn unified_download_status_and_list_share_metadata_and_recovery_state() {
        // user:“修”+(同一任务快照在工具列表和页面状态中一致，且不暴露下载凭据)。
        let dir = std::env::temp_dir().join(format!("unified-download-{}", uuid::Uuid::new_v4()));
        let mut controller = crate::state::Controller::new(dir.clone()).unwrap();
        controller.saved.downloads.push(json!({"gid":"test", "filename":"file.zip", "status":"waiting", "protected_request":"secret"}));
        let status = controller.call("status", json!({})).await.unwrap();
        let list = controller.call("transfer.list", json!({})).await.unwrap();
        assert_eq!(status["downloads"], list["tasks"]);
        assert_eq!(list["tasks"][0]["filename"], "file.zip");
        assert_eq!(list["tasks"][0]["status"], "recoverable");
        assert!(list["tasks"][0].get("protected_request").is_none());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[cfg(target_os = "windows")]
    #[tokio::test]
    async fn failed_aria_start_leaves_no_saved_download() {
        let dir = std::env::temp_dir().join(format!("failed-download-{}", uuid::Uuid::new_v4()));
        let mut controller = crate::state::Controller::new(dir.clone()).unwrap();
        let result = controller
            .add_download(serde_json::json!({"url":"https://example.com/report.zip"}))
            .await;
        let saved = crate::state::Controller::new(dir.clone()).unwrap();
        std::fs::remove_dir_all(dir).unwrap();
        assert!(result.unwrap_err().contains("aria2c"));
        assert!(controller.saved.downloads.is_empty());
        assert!(saved.saved.downloads.is_empty());
    }
}
