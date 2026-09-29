use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;

const PROFILE_SOURCES: &[&str] = &[
    include_str!("../../config/llm_adapters/always-on.jsonc"),
    include_str!("../../config/llm_adapters/anthropic-adaptive.jsonc"),
    include_str!("../../config/llm_adapters/anthropic-always-on.jsonc"),
    include_str!("../../config/llm_adapters/anthropic-messages.jsonc"),
    include_str!("../../config/llm_adapters/deepseek-chat.jsonc"),
    include_str!("../../config/llm_adapters/deepseek-reasoner.jsonc"),
    include_str!("../../config/llm_adapters/gemini-25-flash.jsonc"),
    include_str!("../../config/llm_adapters/gemini-25-pro.jsonc"),
    include_str!("../../config/llm_adapters/gemini-3-flash.jsonc"),
    include_str!("../../config/llm_adapters/gemini-3-pro.jsonc"),
    include_str!("../../config/llm_adapters/gemini-media.jsonc"),
    include_str!("../../config/llm_adapters/gemini-non-reasoning.jsonc"),
    include_str!("../../config/llm_adapters/gemini.jsonc"),
    include_str!("../../config/llm_adapters/glm.jsonc"),
    include_str!("../../config/llm_adapters/grok-always-on.jsonc"),
    include_str!("../../config/llm_adapters/grok-media.jsonc"),
    include_str!("../../config/llm_adapters/grok-non-reasoning.jsonc"),
    include_str!("../../config/llm_adapters/grok.jsonc"),
    include_str!("../../config/llm_adapters/kimi.jsonc"),
    include_str!("../../config/llm_adapters/openai-chat.jsonc"),
    include_str!("../../config/llm_adapters/openai-compatible.jsonc"),
    include_str!("../../config/llm_adapters/openai-media.jsonc"),
    include_str!("../../config/llm_adapters/openai-responses.jsonc"),
    include_str!("../../config/llm_adapters/qwen.jsonc"),
    include_str!("../../config/llm_adapters/xfyun-coding-plan.jsonc"),
];

pub(crate) fn resolve_profile(
    api_type: &str,
    base_url: &str,
    model_id: &str,
    provider_name: &str,
    provider_extra: &Value,
    model_extra: &Value,
) -> Value {
    let profiles = embedded_profiles();
    let mut profile = profile_from_extra(model_extra, &profiles)
        .or_else(|| profile_from_extra(provider_extra, &profiles))
        .or_else(|| best_match(&profiles, "match_model", model_id, api_type))
        .or_else(|| best_match(&profiles, "match_provider", provider_name, api_type))
        .or_else(|| {
            profiles
                .values()
                .find(|candidate| {
                    protocol_matches(candidate, api_type)
                        && matches_text(base_url, candidate.get("match_base_url"))
                })
                .cloned()
        })
        .or_else(|| profiles.get(default_profile_id(api_type)).cloned())
        .unwrap_or_else(|| serde_json::json!({"id": default_profile_id(api_type)}));

    for extra in [provider_extra, model_extra] {
        if let Some(override_value) = extra
            .get("adapter_profile_override")
            .or_else(|| extra.get("llm_adapter_override"))
        {
            deep_merge(&mut profile, override_value);
        }
        if let Some(reasoning) = extra.get("reasoning").filter(|value| value.is_object()) {
            if !profile.get("reasoning").is_some_and(Value::is_object) {
                profile["reasoning"] = Value::Object(Map::new());
            }
            deep_merge(&mut profile["reasoning"], reasoning);
        }
    }
    profile
}

pub(crate) fn apply_request_profile(
    payload: &mut Value,
    profile: &Value,
    provider_extra: &Value,
    model_extra: &Value,
    reasoning_level: &str,
    thinking_budget: u32,
) {
    let request = profile.get("request").unwrap_or(&Value::Null);
    let variables = serde_json::json!({
        "thinking_budget": thinking_budget,
        "thinking_budget_light": clamp_budget(thinking_budget, 2_048, 1_024),
        "thinking_budget_high": clamp_budget(thinking_budget, 8_192, 1_024),
        "thinking_budget_max": thinking_budget.max(1_024),
    });

    if let Some(body) = request
        .get("body")
        .or_else(|| request.get("extra_body"))
        .filter(|value| value.is_object())
    {
        set_fields(payload, &render_templates(body, &variables));
    }
    for extra in [provider_extra, model_extra] {
        if let Some(body) = extra.get("request_body").filter(|value| value.is_object()) {
            set_fields(payload, &render_templates(body, &variables));
        }
    }

    let mut level = normalize_level(reasoning_level);
    if level == "off" && !reasoning_off_supported(profile) {
        level = normalize_level(
            request
                .pointer("/reasoning/off_fallback")
                .and_then(Value::as_str)
                .unwrap_or("light"),
        );
        if level == "off" {
            level = "light";
        }
    }

    if let Some(reasoning) = request.get("reasoning").filter(|value| value.is_object()) {
        if let Some(cleanup) = reasoning
            .get("cleanup")
            .or_else(|| reasoning.get("cleanup_fields"))
        {
            for path in string_values(cleanup) {
                unset_path(payload, &path);
            }
        }
        if let Some(preset) = reasoning
            .get("presets")
            .and_then(|presets| presets.get(level))
            .filter(|value| value.is_object())
        {
            if let Some(unset) = preset.get("unset") {
                for path in string_values(unset) {
                    unset_path(payload, &path);
                }
            }
            if let Some(fields) = preset.get("set").filter(|value| value.is_object()) {
                set_fields(payload, &render_templates(fields, &variables));
            }
            if let Some(fields) = preset.as_object() {
                let compact = Value::Object(
                    fields
                        .iter()
                        .filter(|(key, _)| key.as_str() != "set" && key.as_str() != "unset")
                        .map(|(key, value)| (key.clone(), value.clone()))
                        .collect(),
                );
                set_fields(payload, &render_templates(&compact, &variables));
            }
        } else if let (Some(field), Some(values)) = (
            reasoning.get("field").and_then(Value::as_str),
            reasoning.get("values").and_then(Value::as_object),
        ) {
            if let Some(value) = values.get(level) {
                set_path(payload, field, render_templates(value, &variables));
            } else {
                unset_path(payload, field);
            }
        }
    }

    if level != "off"
        && request
            .get("omit_temperature_when_reasoning")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        && request.pointer("/body/temperature").is_none()
        && request.pointer("/extra_body/temperature").is_none()
    {
        unset_path(payload, "temperature");
    }
    if let Some(fields) = request.get("unsupported_fields") {
        for field in string_values(fields) {
            unset_path(payload, &field);
        }
    }
}

fn embedded_profiles() -> BTreeMap<String, Value> {
    PROFILE_SOURCES
        .iter()
        .map(|source| {
            let profile: Value = serde_json::from_str(&normalize_profile_source(source))
                .expect("bundled LLM adapter profile must be valid JSONC");
            let id = profile
                .get("id")
                .and_then(Value::as_str)
                .expect("bundled LLM adapter profile must have an id")
                .to_owned();
            (id, profile)
        })
        .collect()
}

/// Read one `.jsonc` profile the way the desktop's Python loader does.
///
/// The profiles under `core/config/llm_adapters/` are JSONC: they may carry
/// `//` and `/* */` comments and a comma before a closing bracket, and the
/// desktop tolerates both (`strip_jsonc` + `strip_trailing_commas` in
/// `llm/profiles.py`).  Parsing them strictly here would make the phone refuse
/// profiles the desktop loads happily, so the same two allowances are applied
/// before the document reaches the JSON parser.
///
/// String literals are copied verbatim, so a `//` inside a URL survives.
fn normalize_profile_source(text: &str) -> String {
    let source: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut index = 0;
    let mut in_string = false;
    let mut escaped = false;
    while index < source.len() {
        let ch = source[index];
        if in_string {
            out.push(ch);
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_string = false;
            }
            index += 1;
            continue;
        }
        match ch {
            '"' => {
                in_string = true;
                out.push(ch);
                index += 1;
            }
            '/' if source.get(index + 1) == Some(&'/') => {
                index += 2;
                while index < source.len() && source[index] != '\n' {
                    index += 1;
                }
            }
            '/' if source.get(index + 1) == Some(&'*') => {
                index += 2;
                while index + 1 < source.len()
                    && !(source[index] == '*' && source[index + 1] == '/')
                {
                    index += 1;
                }
                index = (index + 2).min(source.len());
            }
            ',' => {
                let mut look = index + 1;
                while look < source.len() && source[look].is_whitespace() {
                    look += 1;
                }
                if matches!(source.get(look), Some(']') | Some('}')) {
                    // A comma before a closing bracket: drop it, keep the layout.
                    index += 1;
                    continue;
                }
                out.push(ch);
                index += 1;
            }
            _ => {
                out.push(ch);
                index += 1;
            }
        }
    }
    out
}

fn profile_from_extra(extra: &Value, profiles: &BTreeMap<String, Value>) -> Option<Value> {
    for key in ["adapter_profile", "llm_adapter"] {
        match extra.get(key) {
            Some(value) if value.is_object() => return Some(value.clone()),
            Some(Value::String(id)) => {
                if let Some(profile) = profiles.get(id) {
                    return Some(profile.clone());
                }
            }
            _ => {}
        }
    }
    for key in ["adapter_profile_id", "llm_adapter_id"] {
        if let Some(id) = extra.get(key).and_then(Value::as_str) {
            if let Some(profile) = profiles.get(id) {
                return Some(profile.clone());
            }
        }
    }
    None
}

fn best_match(
    profiles: &BTreeMap<String, Value>,
    key: &str,
    value: &str,
    api_type: &str,
) -> Option<Value> {
    profiles
        .values()
        .filter(|profile| protocol_matches(profile, api_type))
        .filter_map(|profile| {
            let score = matching_patterns(value, profile.get(key))
                .into_iter()
                .map(|pattern| pattern.len())
                .max()?;
            Some((score, profile.clone()))
        })
        .max_by_key(|(score, _)| *score)
        .map(|(_, profile)| profile)
}

fn protocol_matches(profile: &Value, api_type: &str) -> bool {
    let protocol = profile
        .get("protocol")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    let api = api_type.trim().to_ascii_lowercase();
    if protocol.is_empty() || api.is_empty() {
        return true;
    }
    match api.as_str() {
        "anthropic" | "anthropic-messages" => protocol == "anthropic-messages",
        "gemini" | "gemini-generative-language" | "google" | "google-gemini" => {
            matches!(protocol.as_str(), "gemini" | "gemini-generative-language")
        }
        "responses" | "openai-responses" => {
            matches!(protocol.as_str(), "responses" | "openai-responses")
        }
        "openai" | "openai-chat" | "openai-compatible" | "grok" | "xai" => matches!(
            protocol.as_str(),
            "openai" | "openai-chat" | "openai-chat-completions" | "openai-compatible"
        ),
        _ => true,
    }
}

fn default_profile_id(api_type: &str) -> &'static str {
    match api_type.trim().to_ascii_lowercase().as_str() {
        "anthropic" | "anthropic-messages" => "anthropic-messages",
        "responses" | "openai-responses" => "openai-responses",
        "gemini" | "gemini-generative-language" | "google" | "google-gemini" => "gemini",
        _ => "openai-compatible",
    }
}

fn matches_text(value: &str, patterns: Option<&Value>) -> bool {
    !matching_patterns(value, patterns).is_empty()
}

fn matching_patterns(value: &str, patterns: Option<&Value>) -> Vec<String> {
    let lowered = value.to_ascii_lowercase();
    string_values(patterns.unwrap_or(&Value::Null))
        .into_iter()
        .filter(|pattern| !pattern.is_empty() && lowered.contains(&pattern.to_ascii_lowercase()))
        .collect()
}

fn string_values(value: &Value) -> Vec<String> {
    match value {
        Value::String(value) => vec![value.clone()],
        Value::Array(values) => values
            .iter()
            .filter_map(|value| value.as_str().map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

fn reasoning_off_supported(profile: &Value) -> bool {
    profile
        .pointer("/reasoning/off_supported")
        .and_then(Value::as_bool)
        != Some(false)
}

fn normalize_level(value: &str) -> &str {
    match value.trim().to_ascii_lowercase().as_str() {
        "none" | "disabled" | "off" | "" => "off",
        "minimal" | "low" | "light" => "light",
        "medium" => "medium",
        "high" => "high",
        "xh" | "xhigh" => "xhigh",
        "ultra" | "max" => "max",
        _ => "off",
    }
}

/// One grade a model declares, in the model's own order and wording.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeclaredReasoningLevel {
    pub value: String,
    pub label: String,
}

/// The reasoning ladder a resolved profile declares, plus whether that profile
/// can honor the product's `off`.
///
/// This is the Rust half of the Python `declared_reasoning_levels` contract
/// (`llm/profiles.py`): for one model, desktop and phone must offer the same
/// grades.  It describes what a profile accepts, so nothing here is part of
/// building a request.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReasoningDeclaration {
    pub levels: Vec<DeclaredReasoningLevel>,
    pub off_supported: bool,
}

/// The ladder a resolved profile declares, in its own order.
///
/// `reasoning.levels` is written either as canonical level ids
/// (`["light", "medium", "max"]`) or as `{"id": …, "label": …}` objects when the
/// model uses its own names for the grades.  A profile that declares nothing
/// returns an empty ladder, so callers keep their product-wide one instead of
/// having one invented for that model.
///
/// Unknown ids, duplicates and an `off` the profile cannot honor are dropped
/// here, so no surface can offer a level the request builder would not accept.
pub fn reasoning_declaration(profile: &Value) -> ReasoningDeclaration {
    let off_supported = reasoning_off_supported(profile);
    let Some(declared) = profile
        .pointer("/reasoning/levels")
        .and_then(Value::as_array)
    else {
        return ReasoningDeclaration {
            levels: Vec::new(),
            off_supported,
        };
    };
    let mut levels: Vec<DeclaredReasoningLevel> = Vec::new();
    for item in declared {
        // An object names the grade in `id`, `value` or `level`; a bare string is
        // the grade itself.  Python reads the same three keys with `or`, so an
        // empty one falls through to the next.
        let named = DECLARED_LEVEL_KEYS
            .iter()
            .find_map(|key| declaration_text(item.get(*key)));
        let text = named.or_else(|| declaration_text(Some(item)));
        let Some(value) = text.as_deref().and_then(declaration_level) else {
            continue;
        };
        if value == "off" && !off_supported {
            continue;
        }
        if levels.iter().any(|level| level.value == value) {
            continue;
        }
        let label = DECLARED_LABEL_KEYS
            .iter()
            .find_map(|key| declaration_text(item.get(*key)))
            .unwrap_or_default();
        levels.push(DeclaredReasoningLevel {
            value: value.to_string(),
            label,
        });
    }
    ReasoningDeclaration {
        levels,
        off_supported,
    }
}

const DECLARED_LEVEL_KEYS: [&str; 3] = ["id", "value", "level"];
const DECLARED_LABEL_KEYS: [&str; 2] = ["label", "name"];

/// The text of a declared field, or `None` when Python's `or` would have
/// skipped it (absent, empty, zero or `false`).
fn declaration_text(value: Option<&Value>) -> Option<String> {
    match value? {
        Value::String(text) => {
            let text = text.trim();
            (!text.is_empty()).then(|| text.to_owned())
        }
        Value::Number(number) => {
            (*number != serde_json::Number::from(0)).then(|| number.to_string())
        }
        Value::Bool(true) => Some("True".to_owned()),
        Value::Bool(false) | Value::Null => None,
        other => {
            let text = other.to_string();
            (text != "{}" && text != "[]").then_some(text)
        }
    }
}

/// The canonical grade for a declared name, or `None` when the model used a
/// name the product does not know.
///
/// Deliberately stricter than `normalize_level`, which falls back to `off` for
/// anything unrecognized: a declared ladder has to drop a name it cannot honor
/// rather than offer `off` in its place.
fn declaration_level(value: &str) -> Option<&'static str> {
    match value.trim().to_ascii_lowercase().as_str() {
        "none" | "disabled" | "off" => Some("off"),
        "minimal" | "low" | "light" => Some("light"),
        "medium" => Some("medium"),
        "high" => Some("high"),
        "xh" | "xhigh" => Some("xhigh"),
        "ultra" | "max" => Some("max"),
        _ => None,
    }
}

fn clamp_budget(configured: u32, target: u32, minimum: u32) -> u32 {
    configured.max(minimum).min(target.max(minimum))
}

fn render_templates(value: &Value, variables: &Value) -> Value {
    match value {
        Value::String(template) if template.starts_with('$') => variables
            .get(template.trim_start_matches('$'))
            .cloned()
            .unwrap_or_else(|| value.clone()),
        Value::Array(values) => Value::Array(
            values
                .iter()
                .map(|value| render_templates(value, variables))
                .collect(),
        ),
        Value::Object(values) => Value::Object(
            values
                .iter()
                .map(|(key, value)| (key.clone(), render_templates(value, variables)))
                .collect(),
        ),
        _ => value.clone(),
    }
}

fn set_fields(payload: &mut Value, fields: &Value) {
    if let Some(fields) = fields.as_object() {
        for (path, value) in fields {
            set_path(payload, path, value.clone());
        }
    }
}

fn set_path(payload: &mut Value, path: &str, value: Value) {
    let parts = path
        .split('.')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    if parts.is_empty() {
        return;
    }
    let mut current = payload;
    for part in &parts[..parts.len() - 1] {
        if !current.get(*part).is_some_and(Value::is_object) {
            current[*part] = Value::Object(Map::new());
        }
        current = &mut current[*part];
    }
    current[parts[parts.len() - 1]] = value;
}

fn unset_path(payload: &mut Value, path: &str) {
    let parts = path
        .split('.')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>();
    unset_parts(payload, &parts);
}

fn unset_parts(current: &mut Value, parts: &[&str]) -> bool {
    let Some((head, tail)) = parts.split_first() else {
        return false;
    };
    let Some(object) = current.as_object_mut() else {
        return false;
    };
    if tail.is_empty() {
        object.remove(*head);
    } else if let Some(child) = object.get_mut(*head) {
        if unset_parts(child, tail) && child.as_object().is_some_and(Map::is_empty) {
            object.remove(*head);
        }
    }
    object.is_empty()
}

fn deep_merge(base: &mut Value, override_value: &Value) {
    match (base, override_value) {
        (Value::Object(base), Value::Object(override_object)) => {
            for (key, value) in override_object {
                if let Some(existing) = base.get_mut(key) {
                    deep_merge(existing, value);
                } else {
                    base.insert(key.clone(), value.clone());
                }
            }
        }
        (base, override_value) => *base = override_value.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_profile_wins_and_uses_official_reasoning_shape() {
        let profile = resolve_profile(
            "openai",
            "https://api.commandcode.ai/provider/v1",
            "Qwen/Qwen3.8-Max",
            "Command Code",
            &serde_json::json!({"adapter_profile_id":"openai-chat"}),
            &serde_json::json!({"adapter_profile_id":"qwen"}),
        );
        assert_eq!(profile["id"], "qwen");
        let mut payload = serde_json::json!({"temperature":0.7,"reasoning_effort":"stale"});
        apply_request_profile(
            &mut payload,
            &profile,
            &Value::Null,
            &Value::Null,
            "medium",
            10_000,
        );
        assert_eq!(payload["enable_thinking"], true);
        assert_eq!(payload["reasoning_effort"], "medium");
    }

    #[test]
    fn model_request_body_overrides_provider_and_glm_cannot_turn_reasoning_off() {
        let provider = serde_json::json!({
            "adapter_profile_id":"openai-chat",
            "request_body":{"vendor":{"mode":"provider"}}
        });
        let model = serde_json::json!({
            "adapter_profile_id":"glm",
            "request_body":{"vendor":{"mode":"model"}}
        });
        let profile = resolve_profile(
            "openai",
            "https://example.invalid/v1",
            "glm-5",
            "P",
            &provider,
            &model,
        );
        let mut payload = serde_json::json!({});
        apply_request_profile(&mut payload, &profile, &provider, &model, "off", 10_000);
        assert_eq!(
            payload.pointer("/vendor/mode"),
            Some(&Value::String("model".into()))
        );
        assert_eq!(
            payload.pointer("/thinking/type"),
            Some(&Value::String("enabled".into()))
        );
        assert_eq!(payload["reasoning_effort"], "low");
    }

    fn declared_for(
        api_type: &str,
        base_url: &str,
        model_id: &str,
        provider_name: &str,
        provider_extra: &Value,
        model_extra: &Value,
    ) -> ReasoningDeclaration {
        reasoning_declaration(&resolve_profile(
            api_type,
            base_url,
            model_id,
            provider_name,
            provider_extra,
            model_extra,
        ))
    }

    fn values(declaration: &ReasoningDeclaration) -> Vec<&str> {
        declaration
            .levels
            .iter()
            .map(|level| level.value.as_str())
            .collect()
    }

    /// Every compiled profile must parse: a failure here is a panic on the
    /// phone's request path, because the request builder resolves a profile for
    /// every model call.
    #[test]
    fn every_compiled_profile_parses() {
        let profiles = embedded_profiles();
        assert_eq!(profiles.len(), PROFILE_SOURCES.len());
        assert_eq!(profiles["deepseek-chat"]["id"], "deepseek-chat");
    }

    #[test]
    fn jsonc_comments_and_trailing_commas_survive_but_strings_do_not() {
        let normalized = normalize_profile_source(
            r#"{
                // a line comment
                "id": "jsonc", /* a block comment */
                "base_url": "https://api.invalid/v1", // the // must survive
                "match_model": ["a", "b",],
                "reasoning": { "levels": ["light", "max",], "off_supported": false, },
            }"#,
        );
        let profile: Value = serde_json::from_str(&normalized).expect("normalized JSONC parses");
        assert_eq!(profile["id"], "jsonc");
        assert_eq!(profile["base_url"], "https://api.invalid/v1");
        assert_eq!(profile["match_model"], serde_json::json!(["a", "b"]));
        assert_eq!(profile["reasoning"]["levels"], serde_json::json!(["light", "max"]));
        assert!(!reasoning_off_supported(&profile));
    }

    /// The ladders below are read from the profiles `include_str!` compiles in,
    /// so this fails if the shipped data and the parser ever disagree — the
    /// phone answers the same model with the same grades the desktop does.
    #[test]
    fn compiled_profiles_declare_the_ladders_this_contract_promises() {
        let deepseek = declared_for(
            "openai",
            "https://api.deepseek.com/v1",
            "deepseek-v4-flash",
            "DeepSeek",
            &serde_json::json!({"adapter_profile_id":"deepseek-chat"}),
            &Value::Null,
        );
        assert_eq!(values(&deepseek), ["max", "high", "light", "off"]);
        assert_eq!(deepseek.levels[0].label, "极高");
        assert!(deepseek.off_supported);

        // A profile that cannot switch reasoning off declares no `off` at all.
        let glm = declared_for(
            "openai",
            "https://open.bigmodel.cn/api/paas/v4",
            "glm-5.3",
            "Zhipu",
            &serde_json::json!({"adapter_profile_id":"glm"}),
            &Value::Null,
        );
        assert_eq!(values(&glm), ["max", "high", "light"]);
        assert!(!glm.off_supported);

        let qwen = declared_for(
            "openai",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "Qwen/Qwen3.8-Max",
            "Aliyun",
            &serde_json::json!({"adapter_profile_id":"qwen"}),
            &Value::Null,
        );
        assert_eq!(values(&qwen), ["xhigh", "medium", "light", "off"]);

        // A model that carries no profile id still resolves one by name, which is
        // how a hand-written model config reaches its ladder.
        let kimi = declared_for(
            "openai",
            "https://api.moonshot.cn/v1",
            "kimi-k2-turbo",
            "Moonshot",
            &Value::Null,
            &Value::Null,
        );
        assert_eq!(kimi.levels[0].value, "max");
        assert!(!kimi.off_supported);
    }

    #[test]
    fn a_models_own_declaration_wins_over_its_provider() {
        let provider = serde_json::json!({"adapter_profile_id":"deepseek-chat"});
        let model = serde_json::json!({
            "reasoning":{"levels":[{"id":"light","label":"轻"},{"id":"max","label":"极高"}]}
        });
        let declaration = declared_for(
            "openai",
            "https://api.deepseek.com/v1",
            "deepseek-v4-flash",
            "DeepSeek",
            &provider,
            &model,
        );
        assert_eq!(values(&declaration), ["light", "max"]);

        // Provider-level `off_supported` still governs a model that declares its
        // own ladder without one.
        let glm_provider = serde_json::json!({"adapter_profile_id":"glm"});
        let model = serde_json::json!({
            "reasoning":{"levels":[{"id":"off","label":"关闭"},{"id":"high","label":"高"}]}
        });
        let declaration = declared_for(
            "openai",
            "https://open.bigmodel.cn/api/paas/v4",
            "glm-5.3",
            "Zhipu",
            &glm_provider,
            &model,
        );
        assert_eq!(values(&declaration), ["high"]);
        assert!(!declaration.off_supported);
    }

    #[test]
    fn unknown_duplicate_and_unhonorable_grades_are_dropped() {
        let declaration = reasoning_declaration(&serde_json::json!({
            "reasoning":{
                "levels":["max","light","light","nonsense","off",{"value":"MAX"},""],
                "off_supported":false,
            }
        }));
        assert_eq!(values(&declaration), ["max", "light"]);
        assert!(!declaration.off_supported);

        // `name` is accepted as a label the same way the desktop accepts it.
        let declaration = reasoning_declaration(&serde_json::json!({
            "reasoning":{"levels":[{"id":"off","name":"关闭"},{"id":"max","label":"极高"}]}
        }));
        assert_eq!(values(&declaration), ["off", "max"]);
        assert_eq!(declaration.levels[0].label, "关闭");
        assert!(declaration.off_supported);

        // A label-less grade is kept; the surface supplies its own wording.
        let declaration = reasoning_declaration(&serde_json::json!({
            "reasoning":{"levels":["light","HIGH"]}
        }));
        assert_eq!(values(&declaration), ["light", "high"]);
        assert_eq!(declaration.levels[1].label, "");
    }

    #[test]
    fn a_profile_that_declares_nothing_keeps_the_product_ladder() {
        assert!(reasoning_declaration(&serde_json::json!({})).levels.is_empty());
        assert!(reasoning_declaration(&serde_json::json!({"reasoning":{}}))
            .levels
            .is_empty());
        assert!(reasoning_declaration(&serde_json::json!({"reasoning":{"levels":"max"}}))
            .levels
            .is_empty());
    }

    #[test]
    fn reading_the_ladder_never_filters_a_request() {
        // `medium` is not in deepseek-chat's declared ladder, and asking for it
        // must still build the preset that profile carries.
        let provider = serde_json::json!({"adapter_profile_id":"deepseek-chat"});
        let profile = resolve_profile(
            "openai",
            "https://api.deepseek.com/v1",
            "deepseek-v4-flash",
            "DeepSeek",
            &provider,
            &Value::Null,
        );
        assert_eq!(values(&reasoning_declaration(&profile)), ["max", "high", "light", "off"]);
        let mut payload = serde_json::json!({});
        apply_request_profile(&mut payload, &profile, &provider, &Value::Null, "medium", 10_000);
        assert_eq!(payload["reasoning_effort"], "high");
    }
}
