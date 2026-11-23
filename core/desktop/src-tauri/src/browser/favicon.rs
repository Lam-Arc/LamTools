// user:“favicon 显示”+(官方来源是 `ICoreWebView2_15::add_FaviconChanged` + `GetFavicon(PNG)`；
// 按 tab + 绝对 URL 缓存，cast 失败时退回脚本读 `<link rel=icon>`，再退到首字母)。
//
// 这一层只管「字节 → 可直接放进 img src 的 data URL」与「缓存键 = tab + 绝对 URL」这一条纯逻辑。
use std::collections::HashMap;

use base64::Engine;

/// 单个图标最大字节数：`GetFavicon` 正常返回几十 KB，超过这个数说明拿到的不是图标。
pub const MAX_FAVICON_BYTES: usize = 512 * 1024;

/// PNG 文件头，用来把「拿到的其实是空流/错误页」挡掉。
const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];

/// 图标字节是否看起来真的是一张 PNG。
pub fn looks_like_png(bytes: &[u8]) -> bool {
    bytes.len() > PNG_SIGNATURE.len() && bytes.starts_with(&PNG_SIGNATURE)
}

/// 把 PNG 字节包成能直接塞进 `<img src>` 的 data URL；不像 PNG 就返回 None（由调用方走退化顺序）。
pub fn png_data_url(bytes: &[u8]) -> Option<String> {
    if bytes.is_empty() || bytes.len() > MAX_FAVICON_BYTES || !looks_like_png(bytes) {
        return None;
    }
    let encoded = base64::engine::general_purpose::STANDARD.encode(bytes);
    Some(format!("data:image/png;base64,{encoded}"))
}

/// user:“按 tab+绝对 URL 缓存”+(同一标签换页后旧图标必须失效，否则地址栏会显示上一个站点的图标)。
#[derive(Debug, Default)]
pub struct FaviconCache {
    entries: HashMap<String, (String, String)>,
}

impl FaviconCache {
    pub fn new() -> Self {
        Self::default()
    }

    /// 记下某个标签在某个绝对 URL 上的图标。
    pub fn insert(&mut self, tab: &str, page_url: &str, data_url: String) {
        self.entries.insert(tab.to_string(), (page_url.to_string(), data_url));
    }

    /// 只有 URL 完全对得上才算命中。
    pub fn get(&self, tab: &str, page_url: &str) -> Option<String> {
        self.entries
            .get(tab)
            .filter(|(url, _)| url == page_url)
            .map(|(_, data_url)| data_url.clone())
    }

    pub fn forget(&mut self, tab: &str) {
        self.entries.remove(tab);
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn png() -> Vec<u8> {
        let mut bytes = PNG_SIGNATURE.to_vec();
        bytes.extend_from_slice(&[0x00, 0x01, 0x02, 0x03]);
        bytes
    }

    #[test]
    fn png_bytes_become_a_data_url() {
        let url = png_data_url(&png()).unwrap();
        assert!(url.starts_with("data:image/png;base64,"), "{url}");
        assert!(!url.contains(' '));
    }

    #[test]
    fn non_png_payloads_are_rejected() {
        // 空流、HTML 错误页、超长字节都必须走退化顺序，而不是变成一个坏图标。
        assert_eq!(png_data_url(&[]), None);
        assert_eq!(png_data_url(b"<html>error</html>"), None);
        let huge = vec![0u8; MAX_FAVICON_BYTES + 1];
        assert_eq!(png_data_url(&huge), None);
        assert!(!looks_like_png(&PNG_SIGNATURE));
    }

    #[test]
    fn cache_key_is_tab_plus_absolute_url() {
        let mut cache = FaviconCache::new();
        cache.insert("tab1", "https://example.com/a", "data:image/png;base64,AAA".into());
        assert_eq!(
            cache.get("tab1", "https://example.com/a").as_deref(),
            Some("data:image/png;base64,AAA")
        );
        // 换页后旧图标不再命中
        assert_eq!(cache.get("tab1", "https://example.com/b"), None);
        // 别的标签互不影响
        cache.insert("tab2", "https://example.com/a", "data:image/png;base64,BBB".into());
        assert_eq!(
            cache.get("tab2", "https://example.com/a").as_deref(),
            Some("data:image/png;base64,BBB")
        );
        assert_eq!(cache.len(), 2);
        cache.forget("tab1");
        assert_eq!(cache.get("tab1", "https://example.com/a"), None);
        assert!(!cache.is_empty());
    }
}
