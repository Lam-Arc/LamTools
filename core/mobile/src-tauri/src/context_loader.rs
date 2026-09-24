//! Mobile counterpart of the desktop ProjectContextLoader. The caller keeps
//! Study isolated and supplies only host-owned project/config roots.
use lamtools_runtime::AgentContext;
use serde_json::Value;
use std::{
    collections::BTreeSet,
    fs,
    path::{Component, Path},
};

const MAX_CHARS: usize = 20_000;

#[derive(Clone)]
struct ContextSpec {
    name: String,
    priority: i64,
    memory: bool,
}

pub fn load_project_context(
    root: &Path,
    mut context: AgentContext,
    global_config: &Value,
) -> Result<AgentContext, String> {
    let project_config = read_project_config(root)?;
    let mut specs = vec![
        ContextSpec { name: "AGENTS.md".into(), priority: 10, memory: false },
        ContextSpec { name: "CLAUDE.md".into(), priority: 10, memory: false },
        ContextSpec { name: "CONTEXT.md".into(), priority: 10, memory: false },
        ContextSpec { name: "MEMORY.md".into(), priority: 20, memory: true },
    ];
    let mut excluded = BTreeSet::new();
    for config in [global_config, &project_config] {
        if let Some(additions) = config.get("addition").and_then(Value::as_array) {
            for item in additions {
                let Some(name) = item.get("name").and_then(Value::as_str) else { continue };
                if !safe_context_name(name) { continue; }
                specs.push(ContextSpec {
                    name: name.into(),
                    priority: item.get("priority").and_then(Value::as_i64).unwrap_or(50),
                    memory: item.get("kind").and_then(Value::as_str) == Some("memory"),
                });
            }
        }
        if let Some(exceptions) = config.get("except").and_then(Value::as_array) {
            for item in exceptions {
                if let Some(name) = item.as_str() { excluded.insert(name.to_owned()); }
            }
        }
    }
    specs.retain(|spec| !excluded.contains(&spec.name));
    specs.sort_by(|left, right| left.priority.cmp(&right.priority).then(left.name.cmp(&right.name)));
    for spec in specs {
        if !safe_context_name(&spec.name) { continue; }
        let path = root.join(&spec.name);
        if !safe_regular_file(root, &path)? { continue; }
        let raw = match fs::read(&path) {
            Ok(raw) => raw,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error.to_string()),
        };
        let mut content = String::from_utf8_lossy(&raw).into_owned();
        if content.trim().is_empty() { continue; }
        if content.chars().count() > MAX_CHARS {
            content = content.chars().take(MAX_CHARS).collect::<String>();
            content.push_str("\n\n[Instruction file truncated. Read the file directly if exact later sections matter.]");
        }
        let section = format!("Instructions from: {}\n{}", spec.name, content.trim());
        let target = if spec.memory { &mut context.memory } else { &mut context.project_instructions };
        if !target.trim().is_empty() { target.push_str("\n\n"); }
        target.push_str(&section);
    }
    Ok(context)
}

fn read_project_config(root: &Path) -> Result<Value, String> {
    let path = root.join("load_context.jsonc");
    if !safe_regular_file(root, &path)? { return Ok(Value::Null); }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    // json5 supports JSONC comments and trailing commas; malformed optional
    // configuration keeps the desktop loader's default-file behavior.
    Ok(json5::from_str(&raw).unwrap_or(Value::Null))
}

fn safe_context_name(name: &str) -> bool {
    !name.is_empty()
        && !name.contains('\\')
        && Path::new(name).components().all(|part| matches!(part, Component::Normal(_)))
}

fn safe_regular_file(root: &Path, path: &Path) -> Result<bool, String> {
    let relative = path.strip_prefix(root).map_err(|error| error.to_string())?;
    let mut current = root.to_path_buf();
    for component in relative.components() {
        if !matches!(component, Component::Normal(_)) { return Ok(false); }
        current.push(component);
        let metadata = match fs::symlink_metadata(&current) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(error.to_string()),
        };
        if metadata.file_type().is_symlink() { return Ok(false); }
    }
    Ok(fs::metadata(path).map(|metadata| metadata.is_file()).unwrap_or(false))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loads_default_and_configured_files_with_exclusions_and_memory() {
        let root = std::env::temp_dir().join(format!("sunday-context-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("AGENTS.md"), "base").unwrap();
        fs::write(root.join("CLAUDE.md"), "claude").unwrap();
        fs::write(root.join("MEMORY.md"), "remember").unwrap();
        fs::write(root.join("custom.md"), "added").unwrap();
        fs::write(root.join("load_context.jsonc"), "{addition:[{name:'custom.md',kind:'system'}],except:['CLAUDE.md']}").unwrap();
        let context = load_project_context(&root, AgentContext::default(), &Value::Null).unwrap();
        assert!(context.project_instructions.contains("base"));
        assert!(context.project_instructions.contains("added"));
        assert!(!context.project_instructions.contains("claude"));
        assert!(context.memory.contains("remember"));
        let excluded = load_project_context(&root, AgentContext::default(), &serde_json::json!({"except":["AGENTS.md"]})).unwrap();
        assert!(!excluded.project_instructions.contains("base"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_context_traversal() {
        assert!(!safe_context_name("../secret.md"));
        assert!(!safe_context_name("C:\\secret.md"));
        assert!(!safe_context_name("sub/../secret.md"));
    }
}
