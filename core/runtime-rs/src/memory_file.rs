//! The structured ``MEMORY.md`` compatibility format.
//!
//! The Python host treats this file as a human readable export of the
//! structured memory store.  Keep the parser deliberately small and
//! dependency free here: the native host must be able to read and merge the
//! same document without a Python process.

use serde::{Deserialize, Serialize};
use std::fmt;

/// The five sections understood by the long term memory file.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemorySection {
    Preferences,
    #[default]
    Facts,
    Decisions,
    Todo,
    Deprecated,
}

impl MemorySection {
    pub const ORDER: [Self; 5] = [
        Self::Preferences,
        Self::Facts,
        Self::Decisions,
        Self::Todo,
        Self::Deprecated,
    ];

    pub const fn title(self) -> &'static str {
        match self {
            Self::Preferences => "Preferences",
            Self::Facts => "Facts",
            Self::Decisions => "Decisions",
            Self::Todo => "Todo",
            Self::Deprecated => "Deprecated",
        }
    }

    pub fn from_title(title: &str) -> Option<Self> {
        match title.trim().to_ascii_lowercase().as_str() {
            "preferences" | "preference" => Some(Self::Preferences),
            "facts" | "fact" => Some(Self::Facts),
            "decisions" | "decision" => Some(Self::Decisions),
            "todo" | "todos" => Some(Self::Todo),
            "deprecated" => Some(Self::Deprecated),
            _ => None,
        }
    }

    /// Map a structured memory kind to the compatibility section.
    pub fn from_kind(kind: &str) -> Self {
        match kind.trim().to_ascii_lowercase().as_str() {
            "preference" | "preferences" => Self::Preferences,
            "decision" | "decisions" => Self::Decisions,
            "todo" | "todos" => Self::Todo,
            "deprecated" => Self::Deprecated,
            // ``fact``, ``lesson`` and future kinds intentionally share the
            // facts section, matching the Python compatibility export.
            _ => Self::Facts,
        }
    }
}

impl fmt::Display for MemorySection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Preferences => "preferences",
            Self::Facts => "facts",
            Self::Decisions => "decisions",
            Self::Todo => "todo",
            Self::Deprecated => "deprecated",
        })
    }
}

/// A structured candidate supplied by Dreaming.
///
/// The native runtime only needs these four fields to produce the file
/// compatibility export.  `id` is used as the fallback source identifier,
/// just as the Python merge helper does.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryEntry {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub kind: String,
    pub content: String,
    #[serde(default)]
    pub source: String,
}

impl MemoryEntry {
    pub fn new(id: impl Into<String>, kind: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            kind: kind.into(),
            content: content.into(),
            source: String::new(),
        }
    }

    pub fn with_source(mut self, source: impl Into<String>) -> Self {
        self.source = source.into();
        self
    }
}

/// One parsed list item from `MEMORY.md`.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ParsedEntry {
    pub content: String,
    pub section: MemorySection,
    /// Empty source means that the line was authored by a person.
    pub source: String,
    pub date: String,
    pub is_todo_open: bool,
    pub is_todo_done: bool,
    pub is_deprecated: bool,
    pub note: String,
    /// Index in [`MemorySnapshot::raw_lines`].  `-1` marks a new entry.
    pub line_index: isize,
}

impl ParsedEntry {
    pub fn is_human(&self) -> bool {
        self.source.is_empty()
    }
}

/// Parsed representation of a memory document.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct MemorySnapshot {
    pub entries: Vec<ParsedEntry>,
    pub raw: String,
    /// Unknown lines, custom sections, comments and the original formatting.
    /// Parsed entry lines are replaced in place during rendering.
    pub raw_lines: Vec<String>,
}

impl MemorySnapshot {
    pub fn section(&self, section: MemorySection) -> Vec<&ParsedEntry> {
        self.entries
            .iter()
            .filter(|entry| entry.section == section)
            .collect()
    }
}

/// Character budget used by the Python project context loader as well as the
/// native compatibility writer.
pub const MAX_MEMORY_MD_CHARS: usize = 20_000;
pub const SECTION_ORDER: [MemorySection; 5] = MemorySection::ORDER;

const MEMORY_HEADER: &str = "# Memory\n\n> 由 LamTools dreaming 自动维护。跨会话的长期记忆，每次会话自动加载。\n> 可手动编辑；下次 dreaming 以手动内容为基线归并。";

/// Parse a memory document.  This is intentionally forgiving: malformed or
/// unknown lines remain in `raw_lines` and therefore survive a later merge.
pub fn parse_memory_md(text: &str) -> MemorySnapshot {
    let raw_lines = text.lines().map(str::to_owned).collect::<Vec<_>>();
    let mut snapshot = MemorySnapshot {
        entries: Vec::new(),
        raw: text.to_owned(),
        raw_lines,
    };
    let mut current = None;

    for (index, line) in snapshot.raw_lines.iter().enumerate() {
        let stripped = line.trim();
        if stripped.is_empty() {
            continue;
        }
        if let Some(title) = heading_title(stripped) {
            current = MemorySection::from_title(title);
            continue;
        }
        let Some(section) = current else {
            continue;
        };
        if !stripped.starts_with('-') {
            continue;
        }
        if let Some(mut entry) = parse_entry_line(stripped, section) {
            entry.line_index = index as isize;
            snapshot.entries.push(entry);
        }
    }
    snapshot
}

/// Render a snapshot, preserving unrecognised source lines and enforcing the
/// 20,000 character machine-memory budget.  The snapshot is updated when
/// machine entries have to be removed for the budget.
pub fn render_memory_md(snapshot: &mut MemorySnapshot) -> String {
    let mut text = render_lines(snapshot);
    if text.chars().count() > MAX_MEMORY_MD_CHARS {
        text = trim_to_budget(snapshot);
    }
    text
}

/// Merge structured entries into a memory document and return the rendered
/// document plus the counts used by the Dreaming status surface.
pub fn merge_into_memory_md(
    existing: &str,
    new_entries: &[MemoryEntry],
    today: Option<&str>,
) -> MemoryMergeResult {
    let mut snapshot = parse_memory_md(existing);
    let date = today
        .filter(|value| !value.trim().is_empty())
        .map(str::to_owned)
        .unwrap_or_else(today_utc);

    // Source alone is not unique: one source can contribute a fact and a
    // todo.  Pairing it with the section preserves both lines.
    let mut by_key = Vec::<((String, MemorySection), usize)>::new();
    for (index, entry) in snapshot.entries.iter().enumerate() {
        if !entry.source.is_empty() {
            by_key.push(((entry.source.clone(), entry.section), index));
        }
    }

    let mut added = 0;
    let mut updated = 0;
    for memory in new_entries {
        let section = MemorySection::from_kind(&memory.kind);
        let source = if memory.source.trim().is_empty() {
            memory.id.trim()
        } else {
            memory.source.trim()
        };
        let key = (source.to_owned(), section);
        if let Some((_, index)) = by_key.iter().find(|(candidate, _)| *candidate == key) {
            let entry = &mut snapshot.entries[*index];
            entry.content = memory.content.trim().to_owned();
            entry.date = date.clone();
            entry.source = source.to_owned();
            // Keep the original todo/deprecated marker when a machine entry
            // is updated, while applying the section's marker to new rows.
            updated += 1;
            continue;
        }

        let new_entry = ParsedEntry {
            content: memory.content.trim().to_owned(),
            section,
            source: source.to_owned(),
            date: date.clone(),
            is_todo_open: section == MemorySection::Todo,
            is_todo_done: false,
            is_deprecated: section == MemorySection::Deprecated,
            note: String::new(),
            line_index: -1,
        };
        snapshot.entries.push(new_entry);
        let index = snapshot.entries.len() - 1;
        by_key.push((key, index));
        added += 1;
    }

    let text = render_memory_md(&mut snapshot);
    MemoryMergeResult {
        text,
        added,
        updated,
        total: snapshot.entries.len(),
    }
}

/// Remove machine-authored compatibility entries by source or, when no source
/// is supplied, by exact case-insensitive content.  Human entries are never
/// selected.
pub fn suppress_memory_md_entries(
    existing: &str,
    source: &str,
    content: &str,
) -> MemorySuppressResult {
    let source = source.trim();
    let content_key = content.trim().to_ascii_lowercase();
    let mut snapshot = parse_memory_md(existing);
    let targets = snapshot
        .entries
        .iter()
        .filter(|entry| {
            !entry.is_human()
                && ((!source.is_empty() && entry.source == source)
                    || (source.is_empty()
                        && !content_key.is_empty()
                        && entry.content.to_ascii_lowercase() == content_key))
        })
        .map(|entry| entry.line_index)
        .collect::<Vec<_>>();
    if targets.is_empty() {
        return MemorySuppressResult {
            text: existing.to_owned(),
            removed: 0,
        };
    }

    for line_index in targets.iter().rev() {
        if *line_index >= 0 {
            let index = *line_index as usize;
            if index < snapshot.raw_lines.len() {
                snapshot.raw_lines.remove(index);
            }
        }
    }
    snapshot
        .entries
        .retain(|entry| !targets.contains(&entry.line_index));
    // The remaining parsed entries have moved with their source lines.
    for entry in &mut snapshot.entries {
        if entry.line_index >= 0 {
            let removed_before = targets
                .iter()
                .filter(|line_index| **line_index >= 0 && **line_index < entry.line_index)
                .count();
            entry.line_index -= removed_before as isize;
        }
    }
    let text = render_memory_md(&mut snapshot);
    MemorySuppressResult {
        text,
        removed: targets.len(),
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct MemoryMergeResult {
    pub text: String,
    pub added: usize,
    pub updated: usize,
    pub total: usize,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct MemorySuppressResult {
    pub text: String,
    pub removed: usize,
}

fn heading_title(line: &str) -> Option<&str> {
    let hashes = line.bytes().take_while(|byte| *byte == b'#').count();
    if !(1..=6).contains(&hashes) {
        return None;
    }
    let remainder = &line[hashes..];
    if !remainder.chars().next().is_some_and(char::is_whitespace) {
        return None;
    }
    Some(remainder.trim())
}

fn parse_entry_line(line: &str, section: MemorySection) -> Option<ParsedEntry> {
    let mut remainder = line.strip_prefix('-')?.trim_start();
    let mut is_todo_done = false;
    let mut is_todo_open = false;
    if let Some(rest) = remainder.strip_prefix("[x]") {
        is_todo_done = true;
        remainder = rest.trim_start();
    } else if let Some(rest) = remainder.strip_prefix("[ ]") {
        is_todo_open = true;
        remainder = rest.trim_start();
    }

    let mut date = String::new();
    if remainder.len() >= 12 && remainder.as_bytes()[0] == b'[' && remainder.as_bytes()[11] == b']'
    {
        let candidate = &remainder[1..11];
        if is_date(candidate) {
            date = candidate.to_owned();
            remainder = remainder[12..].trim_start();
        }
    }
    if remainder.is_empty() {
        return None;
    }

    let (content, source) = split_source_suffix(remainder);
    if content.is_empty() {
        return None;
    }
    let (content, note, is_deprecated) = parse_deprecated(content);
    Some(ParsedEntry {
        content,
        section,
        source,
        date,
        is_todo_open,
        is_todo_done,
        is_deprecated,
        note,
        line_index: -1,
    })
}

fn is_date(value: &str) -> bool {
    value.len() == 10
        && value.as_bytes()[4] == b'-'
        && value.as_bytes()[7] == b'-'
        && value
            .bytes()
            .enumerate()
            .all(|(index, byte)| index == 4 || index == 7 || byte.is_ascii_digit())
}

fn split_source_suffix(value: &str) -> (String, String) {
    let Some(index) = value.rfind('—') else {
        return (value.trim().to_owned(), String::new());
    };
    let candidate = value[index + '—'.len_utf8()..].trim();
    let Some(source) = candidate.strip_prefix("source:").map(str::trim) else {
        return (value.trim().to_owned(), String::new());
    };
    if source.is_empty() || source.chars().any(char::is_whitespace) {
        return (value.trim().to_owned(), String::new());
    }
    let content = value[..index].trim();
    if content.is_empty() {
        return (value.trim().to_owned(), String::new());
    }
    (content.to_owned(), source.to_owned())
}

fn parse_deprecated(value: String) -> (String, String, bool) {
    let Some(inner) = value.strip_prefix("~~") else {
        return (value, String::new(), false);
    };
    let Some(close) = inner.rfind("~~") else {
        return (value, String::new(), false);
    };
    let content = inner[..close].trim();
    if content.is_empty() {
        return (value, String::new(), false);
    }
    let tail = inner[close + 2..].trim();
    if tail.is_empty() {
        return (content.to_owned(), String::new(), true);
    }
    let note = tail
        .strip_prefix('（')
        .and_then(|value| value.strip_suffix('）'))
        .or_else(|| {
            tail.strip_prefix('(')
                .and_then(|value| value.strip_suffix(')'))
        });
    match note {
        Some(note) if !note.is_empty() => (content.to_owned(), note.to_owned(), true),
        _ => (value, String::new(), false),
    }
}

fn render_lines(snapshot: &MemorySnapshot) -> String {
    if snapshot.raw_lines.is_empty() {
        let mut lines = vec![MEMORY_HEADER.to_owned(), String::new()];
        for section in MemorySection::ORDER {
            let entries = snapshot.section(section);
            if entries.is_empty() {
                continue;
            }
            lines.push(format!("## {}", section.title()));
            lines.push(String::new());
            lines.extend(entries.into_iter().map(format_entry_line));
            lines.push(String::new());
        }
        return finish_lines(lines);
    }

    let by_index = snapshot
        .entries
        .iter()
        .filter(|entry| entry.line_index >= 0)
        .map(|entry| (entry.line_index as usize, entry))
        .collect::<std::collections::BTreeMap<_, _>>();
    let mut output = snapshot.raw_lines.clone();
    for (index, line) in output.iter_mut().enumerate() {
        if let Some(entry) = by_index.get(&index) {
            *line = format_entry_line(entry);
        }
    }
    append_new_entries(&mut output, snapshot);
    finish_lines(output)
}

fn append_new_entries(lines: &mut Vec<String>, snapshot: &MemorySnapshot) {
    let mut pending = Vec::<(MemorySection, Vec<&ParsedEntry>)>::new();
    for section in MemorySection::ORDER {
        let entries = snapshot
            .entries
            .iter()
            .filter(|entry| entry.line_index < 0 && entry.section == section)
            .collect::<Vec<_>>();
        if !entries.is_empty() {
            pending.push((section, entries));
        }
    }
    if pending.is_empty() {
        return;
    }

    for (section, entries) in pending {
        let header_index = lines.iter().position(|line| {
            heading_title(line.trim()).and_then(MemorySection::from_title) == Some(section)
        });
        if let Some(header_index) = header_index {
            let insert_at = section_tail(lines, header_index);
            let mut formatted = Vec::with_capacity(entries.len() + 1);
            formatted.push(String::new());
            formatted.extend(entries.into_iter().map(format_entry_line));
            lines.splice(insert_at..insert_at, formatted);
        } else {
            if lines.last().is_some_and(|line| !line.trim().is_empty()) {
                lines.push(String::new());
            }
            lines.push(format!("## {}", section.title()));
            lines.push(String::new());
            lines.extend(entries.into_iter().map(format_entry_line));
        }
    }
}

fn section_tail(lines: &[String], header_index: usize) -> usize {
    let mut end = lines.len();
    for (index, line) in lines.iter().enumerate().skip(header_index + 1) {
        if heading_title(line.trim()).is_some() {
            end = index;
            break;
        }
    }
    let mut last_content = header_index;
    for (index, line) in lines.iter().enumerate().take(end).skip(header_index + 1) {
        if !line.trim().is_empty() {
            last_content = index;
        }
    }
    last_content + 1
}

fn format_entry_line(entry: &ParsedEntry) -> String {
    let prefix = if entry.is_todo_done {
        "- [x]"
    } else if entry.is_todo_open {
        "- [ ]"
    } else {
        "-"
    };
    let mut content = entry.content.clone();
    if entry.is_deprecated {
        content = format!("~~{}~~", content);
        if !entry.note.is_empty() {
            content.push('（');
            content.push_str(&entry.note);
            content.push('）');
        }
    }
    let date = if entry.date.is_empty() {
        String::new()
    } else {
        format!("[{}] ", entry.date)
    };
    let source = if entry.source.is_empty() {
        String::new()
    } else {
        format!(" — source: {}", entry.source)
    };
    format!("{prefix} {date}{content}{source}")
}

fn finish_lines(mut lines: Vec<String>) -> String {
    while lines.last().is_some_and(|line| line.trim().is_empty()) {
        lines.pop();
    }
    let mut text = lines.join("\n").trim_end().to_owned();
    text.push('\n');
    text
}

fn trim_to_budget(snapshot: &mut MemorySnapshot) -> String {
    let mut drop_order = snapshot
        .entries
        .iter()
        .filter(|entry| !entry.is_human())
        .cloned()
        .collect::<Vec<_>>();
    // Match the Python export's ordering: source date first, then content
    // length, with the deprecated marker participating in the same stable
    // tuple.  Human entries never enter this list.
    drop_order.sort_by_key(|entry| {
        (
            entry.is_deprecated,
            entry.date.clone(),
            entry.content.chars().count(),
        )
    });

    let mut text = render_lines(snapshot);
    let mut candidate_index = 0;
    while candidate_index < drop_order.len() {
        let candidate = &drop_order[candidate_index];
        let current_index = if candidate.line_index >= 0 {
            snapshot
                .entries
                .iter()
                .position(|entry| entry.line_index == candidate.line_index && !entry.is_human())
        } else {
            snapshot.entries.iter().position(|entry| {
                entry.line_index < 0
                    && entry.content == candidate.content
                    && entry.source == candidate.source
                    && entry.section == candidate.section
                    && entry.date == candidate.date
                    && entry.is_deprecated == candidate.is_deprecated
            })
        };
        let Some(current_index) = current_index else {
            candidate_index += 1;
            continue;
        };
        let line_index = snapshot.entries[current_index].line_index;
        if line_index >= 0 {
            let index = line_index as usize;
            if index < snapshot.raw_lines.len() {
                snapshot.raw_lines.remove(index);
            }
            for other in &mut snapshot.entries {
                if other.line_index > line_index {
                    other.line_index -= 1;
                }
            }
        }
        snapshot.entries.remove(current_index);
        for candidate in drop_order.iter_mut().skip(candidate_index + 1) {
            if candidate.line_index > line_index {
                candidate.line_index -= 1;
            }
        }
        text = render_lines(snapshot);
        if text.chars().count() <= MAX_MEMORY_MD_CHARS {
            break;
        }
        candidate_index += 1;
    }
    text
}

fn today_utc() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    let days = (seconds / 86_400) as i64;
    let (year, month, day) = civil_from_days(days);
    format!("{year:04}-{month:02}-{day:02}")
}

// Howard Hinnant's public-domain civil_from_days algorithm.
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    let year = y + if month <= 2 { 1 } else { 0 };
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "# Memory\n\n> managed\n\n## Preferences\n- [2026-08-04] 用户偏好 UTF-8 — source: session#a\n- 手工偏好\n\n## Facts\n- [2026-08-04] 数据库在 data/core.db — source: session#b\n\n## Todo\n- [ ] 接 FTS5 — source: session#b\n\n## Deprecated\n- ~~向量检索~~（LIKE 足够） — source: session#a\n";

    #[test]
    fn parse_and_render_keep_sections_and_human_entries() {
        let snapshot = parse_memory_md(SAMPLE);
        assert_eq!(snapshot.entries.len(), 5);
        assert!(snapshot.entries.iter().any(|entry| entry.is_human()));
        assert!(snapshot
            .entries
            .iter()
            .any(|entry| entry.is_deprecated && entry.note == "LIKE 足够"));
        let mut snapshot = snapshot;
        let rendered = render_memory_md(&mut snapshot);
        assert!(rendered.contains("# Memory"));
        assert!(rendered.contains("- 手工偏好"));
        assert!(rendered.contains("## Deprecated"));
    }

    #[test]
    fn merge_updates_source_and_section_without_clobbering_other_section() {
        let entries = [MemoryEntry {
            id: "m1".into(),
            kind: "fact".into(),
            content: "数据库已迁移".into(),
            source: "session#b".into(),
        }];
        let result = merge_into_memory_md(SAMPLE, &entries, Some("2026-08-05"));
        assert_eq!(result.added, 0);
        assert_eq!(result.updated, 1);
        assert!(result.text.contains("数据库已迁移 — source: session#b"));
        assert!(result.text.contains("- [ ] 接 FTS5 — source: session#b"));
        assert!(result.text.contains("- 手工偏好"));
    }

    #[test]
    fn new_sections_are_appended_at_their_section_tail() {
        let entries = [
            MemoryEntry {
                id: "decision".into(),
                kind: "decision".into(),
                content: "决定 A".into(),
                source: "session#d".into(),
            },
            MemoryEntry {
                id: "todo".into(),
                kind: "todo".into(),
                content: "决定 B".into(),
                source: "session#e".into(),
            },
        ];
        let result = merge_into_memory_md(SAMPLE, &entries, Some("2026-08-05"));
        assert!(result
            .text
            .contains("## Decisions\n\n- [2026-08-05] 决定 A"));
        assert!(result.text.contains("## Todo"));
        assert!(result.text.contains("- [ ] [2026-08-05] 决定 B"));
    }

    #[test]
    fn suppress_removes_only_machine_rows() {
        let result = suppress_memory_md_entries(SAMPLE, "", "用户偏好 UTF-8");
        assert_eq!(result.removed, 1);
        assert!(!result.text.contains("用户偏好 UTF-8"));
        assert!(result.text.contains("手工偏好"));
    }

    #[test]
    fn budget_drops_machine_rows_before_human_rows() {
        let human = "人工内容".repeat(3_000);
        let machine = "机器内容".repeat(2_000);
        let source = format!(
            "# Memory\n\n## Facts\n- {human}\n- [2026-08-01] {machine} — source: session#trim\n"
        );
        let mut snapshot = parse_memory_md(&source);
        let rendered = render_memory_md(&mut snapshot);
        assert!(rendered.contains(&human));
        assert!(!rendered.contains(&machine));
        assert!(rendered.chars().count() <= MAX_MEMORY_MD_CHARS);
    }

    #[test]
    fn merge_preserves_custom_sections_and_unparsed_lines() {
        let existing =
            format!("{SAMPLE}\n## Links\n- https://example.com/memory\n\n<!-- 人工备注 -->\n");
        let entries = [MemoryEntry {
            id: "new".into(),
            kind: "fact".into(),
            content: "新增事实".into(),
            source: "session#new".into(),
        }];
        let result = merge_into_memory_md(&existing, &entries, Some("2026-08-05"));
        assert!(result.text.contains("## Links"));
        assert!(result.text.contains("- https://example.com/memory"));
        assert!(result.text.contains("<!-- 人工备注 -->"));
        assert!(result.text.contains("新增事实 — source: session#new"));
    }
}
