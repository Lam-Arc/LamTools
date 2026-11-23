// user:“M3 下载接管，唯一通道是 tauri 的 on_download”+(wry 默认已经注册过 DownloadStarting，
// 再 `add_DownloadStarting` 会出现双回调/后设覆盖先设，表现为下载静默失败或出现两份)。
//
// 已核实的接口（tauri 2.11.5 `src/webview/mod.rs:643`）：
// - `WebviewBuilder::on_download(Fn(Webview, DownloadEvent) -> bool)`
// - `DownloadEvent::Requested { url, destination: &mut PathBuf }`：必须在这里把落盘路径定下来
// - `DownloadEvent::Finished { url, path, success }`
//
// user:“只做开始/完成/失败三态”+(wry 默认 handler 不转发字节进度，自维护列表也不做进度/暂停/继续)。
//
// 这个文件里的路径策略与状态机是纯逻辑，全部可单测；文件系统只通过传入的闭包访问。
use std::path::{Path, PathBuf};

use serde::Serialize;

/// 下载目录名：落在系统下载目录下的 `Sunday` 子目录，不和用户自己的文件混在一起。
pub const DOWNLOAD_FOLDER: &str = "Sunday";

/// user:“危险后缀要审批才能打开”+(落盘可以，但不自动打开、不自动进 Library)。
pub const DANGEROUS_EXTENSIONS: &[&str] = &["exe", "msi", "bat", "cmd", "ps1", "scr", "lnk", "hta", "vbs", "jar"];

/// Windows 保留设备名：作为文件名会被系统当成设备，必须改名。
const RESERVED_NAMES: &[&str] = &[
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2",
    "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
];

/// 文件名长度上限（Windows 是 255，这里留出改名后缀的余量）。
const MAX_NAME_LEN: usize = 180;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum DownloadState {
    Started,
    Finished,
    Failed,
}

impl DownloadState {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Finished => "finished",
            Self::Failed => "failed",
        }
    }
}

/// 下载列表里的一条记录（对外事件与 `browser_downloads` 命令共用这个形状）。
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadRecord {
    pub id: String,
    pub tab: String,
    pub url: String,
    pub filename: String,
    pub path: Option<String>,
    pub state: DownloadState,
    /// 危险后缀：可以落盘，但「打开」需要显式确认。
    pub needs_approval: bool,
    pub started_at: String,
    pub finished_at: Option<String>,
}

/// 把任意建议名收敛成安全的文件名：去路径、去非法字符、避开保留名与空名。
pub fn safe_filename(raw: &str) -> String {
    // 只保留最后一段，`..`、绝对路径、`C:\x` 这类都在这里被切掉。
    let base = raw
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(raw)
        .trim()
        .trim_matches('.');
    let cleaned: String = base
        .chars()
        .map(|ch| {
            if ch.is_control() || matches!(ch, '<' | '>' | ':' | '"' | '|' | '?' | '*' | '\\' | '/') {
                '_'
            } else {
                ch
            }
        })
        .collect();
    let cleaned = cleaned.trim().trim_matches('.').to_string();
    let candidate = if cleaned.is_empty() { "download".to_string() } else { cleaned };
    // 拆分主名与扩展名，分别处理保留名与超长
    let (stem, extension) = match candidate.rsplit_once('.') {
        Some((stem, extension)) if !stem.is_empty() && !extension.is_empty() => (stem.to_string(), format!(".{extension}")),
        _ => (candidate.clone(), String::new()),
    };
    let stem = if RESERVED_NAMES.contains(&stem.to_ascii_lowercase().as_str()) {
        format!("{stem}_file")
    } else {
        stem
    };
    let stem = if stem.len() + extension.len() > MAX_NAME_LEN {
        stem.chars().take(MAX_NAME_LEN.saturating_sub(extension.len())).collect()
    } else {
        stem
    };
    format!("{stem}{extension}")
}

/// 危险后缀判断（只看最终扩展名，大小写不敏感）。
pub fn needs_approval(filename: &str) -> bool {
    match filename.rsplit_once('.') {
        Some((_, extension)) => DANGEROUS_EXTENSIONS.contains(&extension.to_ascii_lowercase().as_str()),
        None => false,
    }
}

/// user:“重名不覆盖”+(已有文件就自动改成 `name (2).ext`，绝不静默覆盖用户文件)。
pub fn unique_path(dir: &Path, filename: &str, exists: impl Fn(&Path) -> bool) -> PathBuf {
    let (stem, extension) = match filename.rsplit_once('.') {
        Some((stem, extension)) if !stem.is_empty() => (stem.to_string(), format!(".{extension}")),
        _ => (filename.to_string(), String::new()),
    };
    let first = dir.join(filename);
    if !exists(&first) {
        return first;
    }
    for index in 2..=999 {
        let candidate = dir.join(format!("{stem} ({index}){extension}"));
        if !exists(&candidate) {
            return candidate;
        }
    }
    // 极端兜底：用时间戳，不再尝试用户可猜的名字。
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis())
        .unwrap_or(0);
    dir.join(format!("{stem}-{stamp}{extension}"))
}

/// 落盘路径策略：目录固定 + 安全名 + 不覆盖。返回前再做一次「必须在目录内」的断言。
pub fn download_target(dir: &Path, suggested: &str, exists: impl Fn(&Path) -> bool) -> PathBuf {
    let filename = safe_filename(suggested);
    let candidate = unique_path(dir, &filename, exists);
    // 双保险：任何跑出目录的结果都不接受（纯逻辑，便于单测断言）。
    if !within(dir, &candidate) {
        return dir.join(safe_filename("download"));
    }
    candidate
}

/// `path` 是否在 `dir` 之下（不依赖文件系统，按组件比较）。
pub fn within(dir: &Path, path: &Path) -> bool {
    let mut parts = path.components();
    for component in dir.components() {
        if parts.next() != Some(component) {
            return false;
        }
    }
    parts.next().is_some()
}

/// 从 URL 推断建议文件名（取最后一段路径；失败就用主机名）。
pub fn suggested_filename(url: &str) -> String {
    if let Ok(parsed) = url::Url::parse(url) {
        let last = parsed.path_segments().and_then(|segments| segments.last()).unwrap_or("");
        let decoded = urlencoding::decode(last).map(|value| value.to_string()).unwrap_or_else(|_| last.to_string());
        if !decoded.trim().is_empty() {
            return safe_filename(&decoded);
        }
        if let Some(host) = parsed.host_str() {
            return safe_filename(host);
        }
    }
    "download".to_string()
}

/// 三态下载表：只追加/更新，不做字节进度。
#[derive(Debug, Default)]
pub struct DownloadRegistry {
    records: Vec<DownloadRecord>,
    next: u64,
}

/// 列表上限：超出后丢弃最老的已完成记录，正在下载的不丢。
pub const DOWNLOAD_LIMIT: usize = 100;

impl DownloadRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// 新下载开始：返回记录 id，路径此时已经确定。
    pub fn begin(&mut self, tab: &str, url: &str, path: &Path, now: &str) -> String {
        self.next += 1;
        let id = format!("d{}", self.next);
        let filename = path.file_name().map(|name| name.to_string_lossy().to_string()).unwrap_or_default();
        self.records.push(DownloadRecord {
            id: id.clone(),
            tab: tab.to_string(),
            url: url.to_string(),
            filename: filename.clone(),
            path: Some(path.to_string_lossy().to_string()),
            state: DownloadState::Started,
            needs_approval: needs_approval(&filename),
            started_at: now.to_string(),
            finished_at: None,
        });
        self.trim();
        id
    }

    /// user:“完成或失败”+(success=false 就是失败，不给「部分成功」这种模糊态)。
    pub fn finish(&mut self, id: &str, path: Option<&Path>, success: bool, now: &str) -> Option<DownloadRecord> {
        let record = self.records.iter_mut().find(|record| record.id == id)?;
        record.state = if success { DownloadState::Finished } else { DownloadState::Failed };
        record.finished_at = Some(now.to_string());
        if let Some(path) = path {
            record.path = Some(path.to_string_lossy().to_string());
            if let Some(name) = path.file_name() {
                record.filename = name.to_string_lossy().to_string();
                record.needs_approval = needs_approval(&record.filename);
            }
        }
        Some(record.clone())
    }

    /// 请求被拒绝（例如路径策略失败）时记一条失败，让用户看得见。
    pub fn fail(&mut self, id: &str, now: &str) -> Option<DownloadRecord> {
        self.finish(id, None, false, now)
    }

    /// 回调是 `Fn`（不能捕获可变状态）：按 tab+url 找最近一条还在下载的记录来做关联。
    pub fn pending_id(&self, tab: &str, url: &str) -> Option<String> {
        self.records
            .iter()
            .rev()
            .find(|record| record.state == DownloadState::Started && record.tab == tab && record.url == url)
            .map(|record| record.id.clone())
    }

    pub fn get(&self, id: &str) -> Option<&DownloadRecord> {
        self.records.iter().find(|record| record.id == id)
    }

    /// 列表按时间倒序（最近的在前），可按标签过滤。
    pub fn list(&self, tab: Option<&str>) -> Vec<DownloadRecord> {
        let mut records = self
            .records
            .iter()
            .filter(|record| tab.map(|tab| record.tab == tab).unwrap_or(true))
            .cloned()
            .collect::<Vec<_>>();
        records.reverse();
        records
    }

    pub fn len(&self) -> usize {
        self.records.len()
    }

    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    fn trim(&mut self) {
        while self.records.len() > DOWNLOAD_LIMIT {
            // 优先丢最老的已完成/失败记录；全在下载中就不动。
            let index = self
                .records
                .iter()
                .position(|record| record.state != DownloadState::Started);
            match index {
                Some(index) => {
                    self.records.remove(index);
                }
                None => break,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dir() -> PathBuf {
        PathBuf::from(r"C:\Users\Example\Downloads\Sunday")
    }

    fn never(_: &Path) -> bool {
        false
    }

    #[test]
    fn filename_drops_paths_and_illegal_characters() {
        // user:“逃逸路径一律拒绝”+(绝对路径、`..`、盘符都在这里被拍平成普通文件名)。
        assert_eq!(safe_filename(r"C:\Windows\System32\evil.exe"), "evil.exe");
        assert_eq!(safe_filename("../../etc/passwd"), "passwd");
        assert_eq!(safe_filename("/tmp/a?b*c.txt"), "a_b_c.txt");
        assert_eq!(safe_filename("   "), "download");
        assert_eq!(safe_filename("..."), "download");
        assert_eq!(safe_filename("name:"), "name_");
    }

    #[test]
    fn reserved_device_names_get_renamed() {
        // CON/NUL 这类名字在 Windows 上会指向设备，不能直接落盘。
        assert_eq!(safe_filename("con.txt"), "con_file.txt");
        assert_eq!(safe_filename("NUL"), "NUL_file");
        assert_eq!(safe_filename("com1.log"), "com1_file.log");
    }

    #[test]
    fn long_names_are_truncated_but_keep_extension() {
        let long = format!("{}.zip", "a".repeat(400));
        let safe = safe_filename(&long);
        assert!(safe.len() <= MAX_NAME_LEN);
        assert!(safe.ends_with(".zip"), "{safe}");
    }

    #[test]
    fn collisions_never_overwrite() {
        let existing = |path: &Path| path.file_name().map(|name| name == "report.pdf").unwrap_or(false);
        assert_eq!(download_target(&dir(), "report.pdf", existing), dir().join("report (2).pdf"));
        let both = |path: &Path| {
            path.file_name()
                .map(|name| name == "report.pdf" || name == "report (2).pdf")
                .unwrap_or(false)
        };
        assert_eq!(download_target(&dir(), "report.pdf", both), dir().join("report (3).pdf"));
        assert_eq!(download_target(&dir(), "report.pdf", never), dir().join("report.pdf"));
    }

    #[test]
    fn every_target_stays_inside_the_download_folder() {
        for suggested in [r"..\..\evil.exe", "/etc/passwd", r"C:\Windows\win.ini", "../../"] {
            let target = download_target(&dir(), suggested, never);
            assert!(within(&dir(), &target), "{suggested} -> {target:?}");
            assert_eq!(target.parent(), Some(dir().as_path()));
        }
    }

    #[test]
    fn dangerous_suffixes_need_approval() {
        for name in ["setup.exe", "patch.MSI", "run.bat", "x.ps1", "shortcut.lnk", "a.scr", "b.hta"] {
            assert!(needs_approval(name), "{name}");
        }
        for name in ["report.pdf", "video.mp4", "archive.zip", "noext"] {
            assert!(!needs_approval(name), "{name}");
        }
    }

    #[test]
    fn three_states_are_recorded_and_capped() {
        let mut registry = DownloadRegistry::new();
        let id = registry.begin("tab1", "https://example.com/a.zip", &dir().join("a.zip"), "2026-11-16T00:00:00Z");
        assert_eq!(registry.get(&id).unwrap().state, DownloadState::Started);
        assert_eq!(registry.get(&id).unwrap().filename, "a.zip");
        assert!(!registry.get(&id).unwrap().needs_approval);

        let done = registry.finish(&id, Some(&dir().join("a (2).zip")), true, "2026-11-16T00:00:05Z").unwrap();
        assert_eq!(done.state, DownloadState::Finished);
        assert_eq!(done.finished_at.as_deref(), Some("2026-11-16T00:00:05Z"));
        assert_eq!(done.filename, "a (2).zip");

        let failed_id = registry.begin("tab1", "https://example.com/b.exe", &dir().join("b.exe"), "2026-11-16T00:00:06Z");
        let failed = registry.fail(&failed_id, "2026-11-16T00:00:07Z").unwrap();
        assert_eq!(failed.state, DownloadState::Failed);
        assert!(failed.needs_approval, "exe 需要审批");
        assert_eq!(registry.list(Some("tab1")).len(), 2);
        assert_eq!(registry.list(Some("tab2")).len(), 0);
        // 最近的在最前
        assert_eq!(registry.list(None)[0].id, failed_id);
        assert!(registry.get("missing").is_none());
    }

    #[test]
    fn suggested_filename_falls_back_safely() {
        assert_eq!(suggested_filename("https://example.com/files/report%20final.pdf"), "report final.pdf");
        assert_eq!(suggested_filename("https://example.com/"), "example.com");
        assert_eq!(suggested_filename("not a url"), "download");
    }

    #[test]
    fn completed_records_are_trimmed_first() {
        let mut registry = DownloadRegistry::new();
        for index in 0..(DOWNLOAD_LIMIT + 5) {
            let id = registry.begin("tab", "https://example.com/x", &dir().join(format!("f{index}.bin")), "t");
            registry.finish(&id, None, true, "t");
        }
        assert_eq!(registry.len(), DOWNLOAD_LIMIT);
    }
}
