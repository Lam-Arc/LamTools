// user:“多标签是浏览器骨架”+(标签元数据、活动标签与关闭栈收敛成纯逻辑，Rust 不持有标签顺序；顺序由前端布局模型决定)。
use std::collections::{BTreeMap, VecDeque};

use serde::Serialize;

use crate::browser::bridge::Ownership;
use crate::browser::session::BrowserProfile;
use crate::browser::BrowserError;

/// 同时存在的标签上限；超出直接报错而不是静默回收（休眠与回收在 M4 再做）。
pub const MAX_TABS: usize = 20;
/// 关闭栈上限，Ctrl+Shift+T 只在这里弹栈。
pub const CLOSED_LIMIT: usize = 20;

/// user:“label 由 Rust 分配，前端不能自定义”+(只允许 a-z0-9 且不超过 24 位，消除 label 注入面)。
pub fn valid_tab_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 24 && id.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

/// 子 webview 的 label 只能由这里拼出来。
pub fn label_for(tab: &str) -> Option<String> {
    valid_tab_id(tab).then(|| format!("browser-{tab}"))
}

/// 反向解析：旧的 `split-browser-` 前缀不再被接受。
pub fn parse_label(label: &str) -> Option<&str> {
    let id = label.strip_prefix("browser-")?;
    valid_tab_id(id).then_some(id)
}

#[derive(Clone, Debug, PartialEq)]
pub struct TabState {
    pub url: String,
    pub title: String,
    pub favicon: Option<String>,
    pub loading: bool,
    pub can_back: bool,
    pub can_forward: bool,
    pub zoom: f64,
    pub crashed: bool,
    /// user:“进入 human-owned 后 Rust 拒绝一切 Agent 写操作”+(两态状态机：agent-owned / human-owned，
    /// 由 isTrusted 真实输入触发接管，静默超阈值或用户显式交回时恢复)。
    pub ownership: Ownership,
    pub opener: Option<String>,
    /// user:“临时会话/自定义目录先留接缝”+(M1 一律 Normal；M2 才会真正切到 incognito 或独立目录)。
    pub profile: BrowserProfile,
    /// user:“cast 失败必须回落脚本”+(原生页内查找是否可用：attach 时判定一次，命令侧只读这个标志)。
    pub native_find: bool,
}

impl TabState {
    fn new(url: String, opener: Option<String>, profile: BrowserProfile) -> Self {
        Self {
            url,
            title: String::new(),
            favicon: None,
            loading: true,
            can_back: false,
            can_forward: false,
            zoom: 1.0,
            crashed: false,
            // 新标签默认由 Agent 使用；用户一碰页面（isTrusted 真实输入）就切到 human-owned。
            ownership: Ownership::default(),
            opener,
            profile,
            native_find: false,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct ClosedTab {
    pub url: String,
    pub title: String,
}

/// 标签注册表。顺序单独保存在 `order` 里，活跃标签由 `active` 指向。
pub struct TabRegistry {
    seed: String,
    next: u64,
    order: Vec<String>,
    tabs: BTreeMap<String, TabState>,
    active: Option<String>,
    closed: VecDeque<ClosedTab>,
}

fn base36(mut value: u64) -> String {
    const DIGITS: &[u8] = b"0123456789abcdefghijklmnopqrstuvwxyz";
    if value == 0 {
        return "0".to_string();
    }
    let mut out = Vec::new();
    while value > 0 {
        out.push(DIGITS[(value % 36) as usize]);
        value /= 36;
    }
    out.reverse();
    String::from_utf8(out).unwrap_or_else(|_| "0".to_string())
}

impl TabRegistry {
    /// `seed` 用来生成跨重启不会撞车的 id 前缀（生产用启动时间，测试用固定值）。
    pub fn new(seed: u64) -> Self {
        let mut prefix = base36(seed % 1_679_616);
        while prefix.len() < 4 {
            prefix.insert(0, '0');
        }
        Self {
            seed: prefix,
            next: 0,
            order: Vec::new(),
            tabs: BTreeMap::new(),
            active: None,
            closed: VecDeque::new(),
        }
    }

    fn next_id(&mut self) -> String {
        self.next += 1;
        let id = format!("t{}{}", self.seed, base36(self.next));
        debug_assert!(valid_tab_id(&id), "生成的标签 id 必须满足 label 规则: {id}");
        id
    }

    /// 新建标签并把它设为活动标签。超出上限返回 `tab_limit`。
    pub fn open(&mut self, url: String, opener: Option<String>) -> Result<String, BrowserError> {
        self.open_with_profile(url, opener, BrowserProfile::Normal)
    }

    /// 带会话形态的新建入口：创建 webview 之前调用方必须用同一个 profile 建环境。
    pub fn open_with_profile(
        &mut self,
        url: String,
        opener: Option<String>,
        profile: BrowserProfile,
    ) -> Result<String, BrowserError> {
        if self.tabs.len() >= MAX_TABS {
            return Err(BrowserError::new(
                "tab_limit",
                format!("最多同时打开 {MAX_TABS} 个浏览器标签"),
                false,
            ));
        }
        let id = self.next_id();
        self.tabs.insert(id.clone(), TabState::new(url, opener, profile));
        self.order.push(id.clone());
        self.active = Some(id.clone());
        Ok(id)
    }

    pub fn close(&mut self, tab: &str) -> Result<Option<ClosedTab>, BrowserError> {
        let state = self.tabs.remove(tab).ok_or_else(BrowserError::tab_not_found)?;
        let index = self.order.iter().position(|id| id == tab);
        if let Some(index) = index {
            self.order.remove(index);
        }
        if self.active.as_deref() == Some(tab) {
            // 关掉活动标签后交给左邻居，和浏览器的习惯一致。
            let fallback = index
                .and_then(|index| index.checked_sub(1).and_then(|prev| self.order.get(prev).cloned()))
                .or_else(|| self.order.first().cloned());
            self.active = fallback;
        }
        if state.url.is_empty() {
            return Ok(None);
        }
        // 同一个地址连续关闭只记一次，避免 Ctrl+Shift+T 反复回同一个页面。
        if self.closed.back().map(|last| last.url == state.url).unwrap_or(false) {
            return Ok(None);
        }
        let closed = ClosedTab { url: state.url, title: state.title };
        self.closed.push_back(closed.clone());
        while self.closed.len() > CLOSED_LIMIT {
            self.closed.pop_front();
        }
        Ok(Some(closed))
    }

    pub fn reopen(&mut self) -> Option<ClosedTab> {
        self.closed.pop_back()
    }

    pub fn activate(&mut self, tab: &str) -> Result<(), BrowserError> {
        if !self.tabs.contains_key(tab) {
            return Err(BrowserError::tab_not_found());
        }
        self.active = Some(tab.to_string());
        Ok(())
    }

    pub fn active(&self) -> Option<&str> {
        self.active.as_deref()
    }

    pub fn is_active(&self, tab: &str) -> bool {
        self.active.as_deref() == Some(tab)
    }

    pub fn contains(&self, tab: &str) -> bool {
        self.tabs.contains_key(tab)
    }

    pub fn get(&self, tab: &str) -> Result<&TabState, BrowserError> {
        self.tabs.get(tab).ok_or_else(BrowserError::tab_not_found)
    }

    pub fn get_mut(&mut self, tab: &str) -> Result<&mut TabState, BrowserError> {
        self.tabs.get_mut(tab).ok_or_else(BrowserError::tab_not_found)
    }

    pub fn ids(&self) -> Vec<String> {
        self.order.clone()
    }

    pub fn len(&self) -> usize {
        self.tabs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.tabs.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn registry() -> TabRegistry {
        TabRegistry::new(7)
    }

    #[test]
    fn label_rules_reject_frontend_supplied_names() {
        for bad in ["", "Bad", "a-b", "a_b", "split-browser-1"] {
            assert!(!valid_tab_id(bad), "{bad} 不该被接受");
            assert!(label_for(bad).is_none());
        }
        let long = "a".repeat(25);
        assert!(!valid_tab_id(&long));
        assert_eq!(label_for("tab01").unwrap(), "browser-tab01");
        assert_eq!(parse_label("browser-tab01"), Some("tab01"));
        // user:“不做两套浏览器”+(旧前缀不能再被识别成浏览器标签)。
        assert_eq!(parse_label("split-browser-tab01"), None);
        assert_eq!(parse_label("main"), None);
    }

    #[test]
    fn open_assigns_rust_owned_ids_and_tracks_active() {
        let mut tabs = registry();
        let first = tabs.open("https://example.com/".into(), None).unwrap();
        let second = tabs.open("https://example.org/".into(), Some(first.clone())).unwrap();
        assert_ne!(first, second);
        assert!(valid_tab_id(&first) && valid_tab_id(&second));
        assert_eq!(tabs.active(), Some(second.as_str()));
        assert_eq!(tabs.ids(), vec![first.clone(), second.clone()]);
        assert_eq!(tabs.get(&second).unwrap().opener.as_deref(), Some(first.as_str()));
    }

    #[test]
    fn history_flags_are_per_tab() {
        let mut tabs = registry();
        let a = tabs.open("https://a.example/".into(), None).unwrap();
        let b = tabs.open("https://b.example/".into(), None).unwrap();
        tabs.get_mut(&a).unwrap().can_back = true;
        assert!(tabs.get(&a).unwrap().can_back);
        assert!(!tabs.get(&b).unwrap().can_back, "独立历史不能互相影响");
        tabs.get_mut(&b).unwrap().can_forward = true;
        assert!(!tabs.get(&a).unwrap().can_forward);
    }

    #[test]
    fn close_pushes_reopen_stack_and_moves_active_neighbour() {
        let mut tabs = registry();
        let a = tabs.open("https://a.example/".into(), None).unwrap();
        let b = tabs.open("https://b.example/".into(), None).unwrap();
        tabs.get_mut(&b).unwrap().title = "B".into();
        tabs.activate(&b).unwrap();
        let closed = tabs.close(&b).unwrap().unwrap();
        assert_eq!(closed.url, "https://b.example/");
        assert_eq!(closed.title, "B");
        assert_eq!(tabs.active(), Some(a.as_str()), "关掉活动标签后落到左邻居");
        assert_eq!(tabs.ids(), vec![a]);
        let reopened = tabs.reopen().unwrap();
        assert_eq!(reopened.url, "https://b.example/");
        assert!(tabs.reopen().is_none(), "关闭栈只能弹一次");
    }

    #[test]
    fn close_stack_is_capped_and_deduplicated() {
        let mut tabs = registry();
        for index in 0..(CLOSED_LIMIT + 5) {
            let id = tabs.open(format!("https://example.com/{index}"), None).unwrap();
            tabs.close(&id).unwrap();
        }
        let mut seen = 0;
        while tabs.reopen().is_some() {
            seen += 1;
        }
        assert_eq!(seen, CLOSED_LIMIT);

        let mut tabs = registry();
        for _ in 0..3 {
            let id = tabs.open("https://same.example/".into(), None).unwrap();
            tabs.close(&id).unwrap();
        }
        assert!(tabs.reopen().is_some());
        assert!(tabs.reopen().is_none(), "连续关闭同一地址只记一次");
    }

    #[test]
    fn closing_empty_tab_does_not_enter_history() {
        let mut tabs = registry();
        let id = tabs.open(String::new(), None).unwrap();
        assert!(tabs.close(&id).unwrap().is_none());
        assert!(tabs.reopen().is_none());
    }

    #[test]
    fn tab_limit_is_reported_not_silently_evicted() {
        let mut tabs = registry();
        for index in 0..MAX_TABS {
            tabs.open(format!("https://example.com/{index}"), None).unwrap();
        }
        let error = tabs.open("https://overflow.example/".into(), None).unwrap_err();
        assert_eq!(error.code, "tab_limit");
        assert_eq!(tabs.len(), MAX_TABS);
    }

    #[test]
    fn tabs_carry_the_profile_they_were_opened_with() {
        let mut tabs = registry();
        let normal = tabs.open("https://a.example/".into(), None).unwrap();
        let secret = tabs
            .open_with_profile("https://b.example/".into(), None, BrowserProfile::Incognito)
            .unwrap();
        assert_eq!(tabs.get(&normal).unwrap().profile, BrowserProfile::Normal);
        assert_eq!(tabs.get(&secret).unwrap().profile, BrowserProfile::Incognito);
        // user:“命令与状态里能读能写”+(profile 挂在标签上，状态输出可直接读)。
        assert_eq!(tabs.get(&secret).unwrap().profile.label(), "incognito");
    }

    #[test]
    fn unknown_tab_is_tab_not_found() {
        let mut tabs = registry();
        assert_eq!(tabs.get("nope").unwrap_err().code, "tab_not_found");
        assert_eq!(tabs.close("nope").unwrap_err().code, "tab_not_found");
        assert_eq!(tabs.activate("nope").unwrap_err().code, "tab_not_found");
    }
}
