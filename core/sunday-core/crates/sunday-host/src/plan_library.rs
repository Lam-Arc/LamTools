//! The plan library: markdown files in a project's `方案/` folder.
//!
//! user:“优先复用 Windows Sunday 已经验证的功能、Library、预览器、文件操作与 UI”
//! +(资料库不是新存储，桌面侧本来就是「一个文件即一份方案」；这里用同一份目录布局与同一套
//! frontmatter 语义，手机和桌面看到的是同一批文件)。
//!
//! Ported from `core/src/lamtools_core/app/plan_library.py`: the folder name, the frontmatter
//! fields, the four states and the entry shape all match, because the interface reads one
//! shape and a second dialect would show up as an empty library on one platform.
//!
//! Every path is contained to `方案/` here, checked segment by segment: a name with a
//! separator or `..` is refused rather than normalised, so no operation can be talked into
//! touching another folder.

use std::path::{Path, PathBuf};

/// The designated folder inside every project workspace.
pub const DIRNAME: &str = "方案";

/// A plan as the library lists it.
#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Serialize)]
pub struct PlanEntry {
    pub name: String,
    /// Library-relative spelling, always starting with `方案/`.
    pub path: String,
    /// Directory inside the library, `""` for the top level.
    pub folder: String,
    pub title: String,
    pub status: String,
    pub summary: String,
    pub favorite: bool,
    pub size: u64,
    pub updated_at: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, serde::Serialize)]
pub struct PlanFolder {
    pub name: String,
    pub path: String,
    pub dir: String,
    pub parent: String,
    pub count: usize,
}

/// Every plan in the library, newest first.
///
/// A file that cannot be read is skipped rather than failing the list: a library that
/// refuses to open because one draft is unreadable is worse than one missing a row.
pub fn scan(work_root: &Path) -> Vec<PlanEntry> {
    let root = work_root.join(DIRNAME);
    let mut entries = Vec::new();
    collect(&root, &root, &mut entries);
    entries.sort_by(|left, right| {
        right
            .updated_at
            .cmp(&left.updated_at)
            .then_with(|| right.name.cmp(&left.name))
    });
    entries
}

fn collect(dir: &Path, root: &Path, out: &mut Vec<PlanEntry>) {
    let Ok(listing) = std::fs::read_dir(dir) else {
        return;
    };
    for item in listing.flatten() {
        let path = item.path();
        let Ok(kind) = item.file_type() else {
            continue;
        };
        if kind.is_dir() {
            collect(&path, root, out);
            continue;
        }
        if !kind.is_file() || path.extension().and_then(|value| value.to_str()) != Some("md") {
            continue;
        }
        if let Some(entry) = entry_for(&path, root) {
            out.push(entry);
        }
    }
}

/// One folder as the library reports it, with its depth in `方案/`.
pub fn folders(work_root: &Path) -> Vec<PlanFolder> {
    let root = work_root.join(DIRNAME);
    let entries = scan(work_root);
    let mut found = Vec::new();
    walk_folders(&root, &root, &entries, &mut found);
    found.sort_by(|left, right| left.dir.cmp(&right.dir));
    found
}

fn walk_folders(dir: &Path, root: &Path, entries: &[PlanEntry], out: &mut Vec<PlanFolder>) {
    let Ok(listing) = std::fs::read_dir(dir) else {
        return;
    };
    for item in listing.flatten() {
        let Ok(kind) = item.file_type() else {
            continue;
        };
        if !kind.is_dir() {
            continue;
        }
        let name = item.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }
        let path = item.path();
        let dir_name = path
            .strip_prefix(root)
            .map(|value| value.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| name.clone());
        let count = entries
            .iter()
            .filter(|entry| entry.folder == dir_name)
            .count();
        out.push(PlanFolder {
            name: name.clone(),
            path: format!("{DIRNAME}/{dir_name}"),
            parent: dir_name
                .rsplit_once('/')
                .map(|(head, _)| head.to_owned())
                .unwrap_or_default(),
            dir: dir_name,
            count,
        });
        walk_folders(&path, root, entries, out);
    }
}

/// Creates a plan document. An existing name is refused rather than overwritten.
pub fn create_file(work_root: &Path, name: &str, folder: &str) -> Result<PlanEntry, String> {
    let cleaned = clean_segment(name, "名称")?;
    let stem = cleaned.strip_suffix(".md").unwrap_or(&cleaned).to_owned();
    let file_name = format!("{stem}.md");
    let inside = clean_relative_dir(folder)?;
    let dir = library_dir(work_root)?;
    let target_dir = if inside.is_empty() {
        dir.clone()
    } else {
        dir.join(&inside)
    };
    std::fs::create_dir_all(&target_dir).map_err(|error| format!("无法创建目录: {error}"))?;
    let target = target_dir.join(&file_name);
    if target.exists() {
        return Err(format!("{stem} 已经存在"));
    }
    let text = format!(
        "---\n状态: 草稿\n摘要:\n---\n\n# {stem}\n\n（在这里写下方案内容。就绪后对助手说「可以开工了」。）\n"
    );
    std::fs::write(&target, text).map_err(|error| format!("无法写入: {error}"))?;
    entry_for(&target, &dir).ok_or_else(|| "新文件写入后读不回来".to_owned())
}

/// Creates a folder at any depth. An existing folder is the same folder, not an error.
pub fn create_folder(work_root: &Path, relative: &str) -> Result<PlanFolder, String> {
    let inside = clean_relative_dir(relative)?;
    if inside.is_empty() {
        return Err("文件夹名称不能为空".into());
    }
    let dir = library_dir(work_root)?;
    let target = dir.join(&inside);
    std::fs::create_dir_all(&target).map_err(|error| format!("无法创建文件夹: {error}"))?;
    folder_for(&target, &dir, &scan(work_root)).ok_or_else(|| "文件夹创建后读不回来".to_owned())
}

pub fn rename(work_root: &Path, path: &str, name: &str) -> Result<PlanEntry, String> {
    let source = resolve_file(work_root, path)?;
    let cleaned = clean_segment(name, "名称")?;
    let stem = cleaned.strip_suffix(".md").unwrap_or(&cleaned).to_owned();
    let target = source.with_file_name(format!("{stem}.md"));
    if target != source && target.exists() {
        return Err(format!("{stem} 已经存在"));
    }
    std::fs::rename(&source, &target).map_err(|error| format!("无法重命名: {error}"))?;
    entry_for(&target, &library_dir(work_root)?).ok_or_else(|| "重命名后读不回来".to_owned())
}

pub fn move_to(work_root: &Path, path: &str, folder: &str) -> Result<PlanEntry, String> {
    let source = resolve_file(work_root, path)?;
    let inside = clean_relative_dir(folder)?;
    let dir = library_dir(work_root)?;
    let target_dir = if inside.is_empty() {
        dir.clone()
    } else {
        dir.join(&inside)
    };
    std::fs::create_dir_all(&target_dir).map_err(|error| format!("无法创建目录: {error}"))?;
    let target = target_dir.join(
        source
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| "文件名无法读取".to_owned())?,
    );
    if target != source && target.exists() {
        return Err("目标文件夹里已经有同名文件".into());
    }
    if target != source {
        std::fs::rename(&source, &target).map_err(|error| format!("无法移动: {error}"))?;
    }
    entry_for(&target, &dir).ok_or_else(|| "移动后读不回来".to_owned())
}

/// Marks a plan as starred, in the document's own frontmatter.
pub fn favorite(work_root: &Path, path: &str, starred: bool) -> Result<PlanEntry, String> {
    let target = resolve_file(work_root, path)?;
    let text = std::fs::read_to_string(&target).unwrap_or_default();
    let updated = set_field(&text, "收藏", if starred { Some("true") } else { None });
    std::fs::write(&target, updated).map_err(|error| format!("无法写入: {error}"))?;
    entry_for(&target, &library_dir(work_root)?).ok_or_else(|| "收藏后读不回来".to_owned())
}

pub fn delete_file(work_root: &Path, path: &str) -> Result<String, String> {
    let target = resolve_file(work_root, path)?;
    std::fs::remove_file(&target).map_err(|error| format!("无法删除: {error}"))?;
    Ok(target.to_string_lossy().replace('\\', "/"))
}

pub fn delete_folder(work_root: &Path, relative: &str) -> Result<String, String> {
    let inside = clean_relative_dir(relative)?;
    if inside.is_empty() {
        return Err("路径不能是方案文件夹本身".into());
    }
    let target = library_dir(work_root)?.join(&inside);
    if !target.is_dir() {
        return Err("文件夹不存在".into());
    }
    // Only the folder itself, and only inside the library.
    std::fs::remove_dir_all(&target).map_err(|error| format!("无法删除: {error}"))?;
    Ok(target.to_string_lossy().replace('\\', "/"))
}

// ---------------------------------------------------------------- internals

fn library_dir(work_root: &Path) -> Result<PathBuf, String> {
    let root = work_root
        .canonicalize()
        .map_err(|error| format!("项目目录不存在: {error}"))?;
    let dir = root.join(DIRNAME);
    std::fs::create_dir_all(&dir).map_err(|error| format!("无法创建方案目录: {error}"))?;
    dir.canonicalize()
        .map_err(|error| format!("方案目录不可用: {error}"))
}

/// One library-relative file path, contained to `方案/`.
fn resolve_file(work_root: &Path, path: &str) -> Result<PathBuf, String> {
    let dir = library_dir(work_root)?;
    let cleaned = path.trim().replace('\\', "/");
    let relative = cleaned
        .strip_prefix(&format!("{DIRNAME}/"))
        .unwrap_or(&cleaned)
        .trim_matches('/')
        .to_owned();
    if relative.is_empty() {
        return Err("路径不能为空".into());
    }
    for segment in relative.split('/') {
        clean_segment(segment, "路径")?;
    }
    let target = dir.join(&relative);
    let canonical = target
        .canonicalize()
        .map_err(|_| "原文件不存在".to_owned())?;
    if !canonical.starts_with(&dir) || !canonical.is_file() {
        return Err("路径越出了方案文件夹".into());
    }
    Ok(canonical)
}

/// Validates one on-disk segment: a name, never a path.
fn clean_segment(name: &str, kind: &str) -> Result<String, String> {
    let cleaned = name.trim().trim_matches('.').trim().to_owned();
    if cleaned.is_empty() {
        return Err(format!("{kind}不能为空"));
    }
    if cleaned.contains('/')
        || cleaned.contains('\\')
        || cleaned.contains(':')
        || cleaned == "."
        || cleaned == ".."
    {
        return Err(format!("{kind}不能包含路径分隔符"));
    }
    if cleaned
        .chars()
        .any(|character| "*?\"<>|".contains(character) || character.is_control())
    {
        return Err(format!("{kind}含有不允许的字符"));
    }
    Ok(cleaned)
}

/// Validates a folder path inside the library, one segment at a time.
fn clean_relative_dir(relative: &str) -> Result<String, String> {
    let cleaned = relative.trim().replace('\\', "/");
    let cleaned = cleaned.trim_matches('/');
    if cleaned.is_empty() {
        return Ok(String::new());
    }
    let segments: Vec<String> = cleaned
        .split('/')
        .filter(|segment| !segment.trim().is_empty())
        .map(|segment| clean_segment(segment, "文件夹名称"))
        .collect::<Result<_, _>>()?;
    Ok(segments.join("/"))
}

fn folder_for(path: &Path, root: &Path, entries: &[PlanEntry]) -> Option<PlanFolder> {
    let dir = path
        .strip_prefix(root)
        .ok()?
        .to_string_lossy()
        .replace('\\', "/");
    let name = path.file_name()?.to_string_lossy().into_owned();
    let count = entries.iter().filter(|entry| entry.folder == dir).count();
    Some(PlanFolder {
        name,
        path: format!("{DIRNAME}/{dir}"),
        parent: dir
            .rsplit_once('/')
            .map(|(head, _)| head.to_owned())
            .unwrap_or_default(),
        dir,
        count,
    })
}

fn entry_for(path: &Path, root: &Path) -> Option<PlanEntry> {
    let stat = std::fs::metadata(path).ok()?;
    let name = path.file_name()?.to_string_lossy().into_owned();
    let folder = path
        .parent()
        .and_then(|parent| parent.strip_prefix(root).ok())
        .map(|value| value.to_string_lossy().replace('\\', "/"))
        .unwrap_or_default();
    let text = std::fs::read_to_string(path).unwrap_or_default();
    let (fields, body) = split_frontmatter(&text);
    let status = normalize_status(
        fields
            .iter()
            .find(|(key, _)| key == "状态" || key == "status")
            .map(|(_, value)| value.as_str()),
    );
    let summary = fields
        .iter()
        .find(|(key, _)| key == "摘要" || key == "summary")
        .map(|(_, value)| value.clone())
        .unwrap_or_default();
    let favorite = fields
        .iter()
        .find(|(key, _)| key == "收藏")
        .map(|(_, value)| {
            matches!(
                value.trim().to_lowercase().as_str(),
                "true" | "yes" | "1" | "是" | "y" | "on"
            )
        })
        .unwrap_or(false);
    let title = plan_title(&body, &name);
    Some(PlanEntry {
        path: if folder.is_empty() {
            format!("{DIRNAME}/{name}")
        } else {
            format!("{DIRNAME}/{folder}/{name}")
        },
        folder,
        name,
        title,
        status,
        summary,
        favorite,
        size: stat.len(),
        updated_at: stat
            .modified()
            .ok()
            .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|elapsed| elapsed.as_secs())
            .unwrap_or(0),
    })
}

/// The `key: value` lines between the first two `---` lines, and the body.
///
/// A document without frontmatter comes back with no fields and its text intact: the body
/// is still readable, which is the whole point of a plain file.
fn split_frontmatter(text: &str) -> (Vec<(String, String)>, String) {
    if !text.starts_with("---") {
        return (Vec::new(), text.to_owned());
    }
    let lines: Vec<&str> = text.lines().collect();
    for index in 1..lines.len() {
        if lines[index].trim() == "---" {
            let mut fields = Vec::new();
            for line in &lines[1..index] {
                if let Some((key, value)) = line.split_once(':') {
                    if !key.trim().is_empty() {
                        fields.push((key.trim().to_lowercase(), value.trim().to_owned()));
                    }
                }
            }
            return (fields, lines[index + 1..].join("\n"));
        }
    }
    (Vec::new(), text.to_owned())
}

/// Sets or removes one frontmatter field. The body is never touched.
fn set_field(text: &str, key: &str, value: Option<&str>) -> String {
    let key_pattern = format!("{}:", key.to_lowercase());
    let lines: Vec<&str> = text.lines().collect();
    if text.starts_with("---") {
        for index in 1..lines.len() {
            if lines[index].trim() == "---" {
                let mut head: Vec<String> = lines[1..index]
                    .iter()
                    .filter(|line| !line.trim().to_lowercase().starts_with(&key_pattern))
                    .map(|line| (*line).to_owned())
                    .collect();
                if let Some(value) = value {
                    head.push(format!("{key}: {value}"));
                }
                let body = lines[index + 1..].join("\n");
                return format!("---\n{}\n---\n{body}", head.join("\n"));
            }
        }
    }
    match value {
        None => text.to_owned(),
        Some(value) => format!("---\n{key}: {value}\n---\n{text}"),
    }
}

fn normalize_status(raw: Option<&str>) -> String {
    match raw.unwrap_or_default().trim().to_lowercase().as_str() {
        "就绪" | "ready" => "ready",
        "执行中" | "executing" => "executing",
        "完成" | "done" => "done",
        _ => "draft",
    }
    .to_owned()
}

fn plan_title(body: &str, filename: &str) -> String {
    for line in body.lines() {
        if let Some(title) = line.trim().strip_prefix("# ") {
            let title = title.trim();
            if !title.is_empty() {
                return title.to_owned();
            }
        }
    }
    filename.strip_suffix(".md").unwrap_or(filename).to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn project() -> tempfile::TempDir {
        tempfile::tempdir().unwrap()
    }

    #[test]
    fn a_new_plan_is_listed_with_its_title_and_draft_state() {
        let dir = project();
        let entry = create_file(dir.path(), "第一期", "").unwrap();
        assert_eq!(entry.status, "draft");
        assert_eq!(entry.title, "第一期");
        assert_eq!(entry.path, "方案/第一期.md");
        let listed = scan(dir.path());
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].name, "第一期.md");
    }

    #[test]
    fn a_created_plan_is_a_plain_markdown_file_with_frontmatter() {
        let dir = project();
        create_file(dir.path(), "草稿", "").unwrap();
        let text = std::fs::read_to_string(dir.path().join("方案/草稿.md")).unwrap();
        assert!(text.starts_with("---\n状态: 草稿\n"));
        assert!(text.contains("# 草稿"));
    }

    #[test]
    fn the_same_name_twice_is_refused_rather_than_overwritten() {
        let dir = project();
        create_file(dir.path(), "重复", "").unwrap();
        assert!(create_file(dir.path(), "重复", "").is_err());
        assert!(create_file(dir.path(), "重复.md", "").is_err());
    }

    #[test]
    fn nested_folders_are_listed_with_their_parent() {
        let dir = project();
        create_folder(dir.path(), "归档/2026").unwrap();
        let folders = folders(dir.path());
        assert_eq!(folders.len(), 2, "{folders:?}");
        assert_eq!(folders[0].dir, "归档");
        assert_eq!(folders[0].parent, "");
        assert_eq!(folders[1].dir, "归档/2026");
        assert_eq!(folders[1].parent, "归档");
    }

    #[test]
    fn a_plan_moves_between_folders() {
        let dir = project();
        create_file(dir.path(), "计划", "").unwrap();
        create_folder(dir.path(), "归档").unwrap();
        let moved = move_to(dir.path(), "方案/计划.md", "归档").unwrap();
        assert_eq!(moved.path, "方案/归档/计划.md");
        assert_eq!(moved.folder, "归档");
    }

    #[test]
    fn starring_a_plan_writes_its_frontmatter() {
        let dir = project();
        create_file(dir.path(), "收藏项", "").unwrap();
        let starred = favorite(dir.path(), "方案/收藏项.md", true).unwrap();
        assert!(starred.favorite);
        let text = std::fs::read_to_string(dir.path().join("方案/收藏项.md")).unwrap();
        assert!(text.contains("收藏: true"), "{text}");
        // and unstarring removes the line instead of writing false.
        let plain = favorite(dir.path(), "方案/收藏项.md", false).unwrap();
        assert!(!plain.favorite);
        let text = std::fs::read_to_string(dir.path().join("方案/收藏项.md")).unwrap();
        assert!(!text.contains("收藏:"), "{text}");
    }

    #[test]
    fn renaming_keeps_the_document() {
        let dir = project();
        create_file(dir.path(), "旧名", "").unwrap();
        let renamed = rename(dir.path(), "方案/旧名.md", "新名").unwrap();
        assert_eq!(renamed.name, "新名.md");
        assert!(!dir.path().join("方案/旧名.md").exists());
    }

    #[test]
    fn deleting_removes_the_file_and_the_folder() {
        let dir = project();
        create_file(dir.path(), "一份", "子目录").unwrap();
        delete_file(dir.path(), "方案/子目录/一份.md").unwrap();
        assert!(!dir.path().join("方案/子目录/一份.md").exists());
        delete_folder(dir.path(), "子目录").unwrap();
        assert!(!dir.path().join("方案/子目录").exists());
    }

    /// A name is a name: it can never smuggle in a separator or a parent hop.
    #[test]
    fn a_path_that_leaves_the_library_is_refused() {
        let dir = project();
        assert!(create_file(dir.path(), "../偷跑", "").is_err());
        assert!(create_file(dir.path(), "a/b", "").is_err());
        assert!(create_file(dir.path(), "x", "../../etc").is_err());
        assert!(resolve_file(dir.path(), "方案/../../etc/passwd").is_err());
        assert!(delete_folder(dir.path(), "..").is_err());
    }

    #[test]
    fn a_document_without_frontmatter_still_lists() {
        let dir = project();
        std::fs::create_dir_all(dir.path().join("方案")).unwrap();
        std::fs::write(dir.path().join("方案/手写.md"), "# 手写标题\n\n正文\n").unwrap();
        let listed = scan(dir.path());
        assert_eq!(listed[0].title, "手写标题");
        assert_eq!(listed[0].status, "draft");
        assert!(listed[0].summary.is_empty());
    }

    #[test]
    fn a_ready_plan_reports_its_state() {
        let dir = project();
        std::fs::create_dir_all(dir.path().join("方案")).unwrap();
        std::fs::write(
            dir.path().join("方案/就绪.md"),
            "---\n状态: 就绪\n摘要: 一句话\n收藏: 是\n---\n# 名称\n",
        )
        .unwrap();
        let entry = &scan(dir.path())[0];
        assert_eq!(entry.status, "ready");
        assert_eq!(entry.summary, "一句话");
        assert!(entry.favorite);
        assert_eq!(entry.title, "名称");
    }
}
