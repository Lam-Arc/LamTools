//! `generate_image` for hosts without the Python tool stack.
//!
//! Ports the desktop text-to-image path: `POST {api_url}/images/generations`
//! with an OpenAI-compatible body, Bearer auth when a key is configured, then
//! the image is stored through a host-provided sink so the runtime stays
//! independent of where a given platform keeps user-visible files.
//!
//! Reference-image editing is desktop-only for now. The desktop resolves
//! references from http(s) URLs or workspace paths; the mobile equivalent would
//! be attachment ids, which is a different contract, so the schema here does not
//! advertise `reference_urls` and the tool rejects it explicitly instead of
//! silently generating from the prompt alone.
use crate::{
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use serde::Deserialize;
use serde_json::{json, Value};
use std::time::Duration;

const GENERATE_ENDPOINT: &str = "images/generations";
/// Image generation takes 1–3 minutes; the desktop kernel allows a 240 s read.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(240);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_COUNT: u32 = 4;
const DEFAULT_SIZE: &str = "1024x1024";

/// Runtime configuration, resolved by the host from `core.imagegen`.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Eq)]
pub struct ImageGenConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub api_url: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub model: String,
}

impl ImageGenConfig {
    /// The desktop host hides the tool when the settings are missing or invalid,
    /// and a base URL without a scheme is invalid for the same reason.
    pub fn is_configured(&self) -> bool {
        self.enabled && self.api_url.starts_with("http") && !self.base_url().is_empty()
    }

    fn base_url(&self) -> String {
        self.api_url.trim().trim_end_matches('/').to_owned()
    }
}

/// Somewhere the host can keep a generated image and later show it.
///
/// The returned string is what the model is told about the image; it must let
/// the user locate it, so hosts return a stable id or path rather than bytes.
#[async_trait]
pub trait ImageSink: Send + Sync {
    async fn save_image(
        &self,
        filename: &str,
        mime: &str,
        bytes: &[u8],
    ) -> Result<String, RuntimeError>;
}

/// Identify an image from its magic bytes, falling back to the item's URL.
fn sniff_image_type(bytes: &[u8], url: &str) -> (&'static str, &'static str) {
    if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        return ("image/jpeg", ".jpeg");
    }
    if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        return ("image/png", ".png");
    }
    if bytes.starts_with(b"RIFF") && bytes.len() >= 12 && &bytes[8..12] == b"WEBP" {
        return ("image/webp", ".webp");
    }
    if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        return ("image/gif", ".gif");
    }
    let lowered = url.to_ascii_lowercase();
    for (mime, extension) in [
        ("image/jpeg", ".jpg"),
        ("image/png", ".png"),
        ("image/webp", ".webp"),
        ("image/gif", ".gif"),
    ] {
        if lowered.ends_with(extension) || (extension == ".jpg" && lowered.ends_with(".jpeg")) {
            return (mime, extension);
        }
    }
    ("image/png", ".png")
}

fn decode_base64(value: &str) -> Option<Vec<u8>> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD
        .decode(value.trim())
        .ok()
}

/// Resolve one `data[]` entry to bytes: inline base64 first, then its URL.
async fn image_bytes(
    http: &reqwest::Client,
    item: &Value,
) -> Result<Option<Vec<u8>>, RuntimeError> {
    if let Some(encoded) = item.get("b64_json").and_then(Value::as_str) {
        if !encoded.trim().is_empty() {
            if let Some(bytes) = decode_base64(encoded) {
                return Ok(Some(bytes));
            }
        }
    }
    let Some(url) = item.get("url").and_then(Value::as_str) else {
        return Ok(None);
    };
    if url.trim().is_empty() {
        return Ok(None);
    }
    let response = http
        .get(url)
        .send()
        .await
        .map_err(|error| RuntimeError::Tool(format!("下载生成图片失败: {error}")))?;
    if !response.status().is_success() {
        return Err(RuntimeError::Tool(format!(
            "下载生成图片失败: HTTP {}",
            response.status().as_u16()
        )));
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|error| RuntimeError::Tool(format!("读取生成图片失败: {error}")))?;
    Ok(Some(bytes.to_vec()))
}

pub struct GenerateImageTools {
    config: ImageGenConfig,
    sink: std::sync::Arc<dyn ImageSink>,
    request_timeout: Duration,
}

impl GenerateImageTools {
    pub fn new(config: ImageGenConfig, sink: std::sync::Arc<dyn ImageSink>) -> Self {
        Self {
            config,
            sink,
            request_timeout: REQUEST_TIMEOUT,
        }
    }

    /// Tests and slow hosts can shorten the wait.
    pub fn with_request_timeout(mut self, timeout: Duration) -> Self {
        self.request_timeout = timeout;
        self
    }

    fn http(&self) -> Result<reqwest::Client, RuntimeError> {
        reqwest::Client::builder()
            .timeout(self.request_timeout)
            .connect_timeout(CONNECT_TIMEOUT)
            .build()
            .map_err(|error| RuntimeError::Tool(error.to_string()))
    }
}

#[async_trait]
impl ToolRuntime for GenerateImageTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        if !self.config.is_configured() {
            // Matches the desktop host: unconfigured image generation is hidden
            // from the model rather than offered and then failed.
            return Vec::new();
        }
        vec![ToolDefinition {
            name: "generate_image".into(),
            description: "Generate images from a text prompt through the configured image API. \
                          Generated images are saved and shown in the conversation."
                .into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Prompt describing the desired image."
                    },
                    "count": {
                        "type": "integer",
                        "description": "How many images to generate (default 1, maximum 4)."
                    },
                    "size": {
                        "type": "string",
                        "description": "Image size, default 1024x1024."
                    }
                },
                "required": ["prompt"]
            }),
        }]
    }

    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        // The bundled manifest declares ask_user: generating costs the user
        // money at a third-party API, so it is never auto-approved.
        ToolPermission::AskUser
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let arguments = call.arguments.as_object();
        let prompt = arguments
            .and_then(|map| map.get("prompt"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if prompt.is_empty() {
            return Err(RuntimeError::Tool("Missing 'prompt' argument".into()));
        }
        if arguments
            .and_then(|map| map.get("reference_urls"))
            .is_some()
        {
            return Err(RuntimeError::Tool(
                "reference-image editing is not available on this host; send only a prompt"
                    .into(),
            ));
        }
        if !self.config.is_configured() {
            return Err(RuntimeError::Tool(
                "生图未配置：请在设置 → 生图中配置 API 地址并启用".into(),
            ));
        }
        let count = arguments
            .and_then(|map| map.get("count"))
            .and_then(Value::as_u64)
            .map(|value| value as u32)
            .unwrap_or(1)
            .clamp(1, MAX_COUNT);
        let size = arguments
            .and_then(|map| map.get("size"))
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or(DEFAULT_SIZE)
            .to_owned();

        let mut payload = json!({"prompt": prompt, "n": count, "size": size});
        if !self.config.model.trim().is_empty() {
            payload["model"] = json!(self.config.model.trim());
        }
        let http = self.http()?;
        let mut request = http
            .post(format!(
                "{}/{GENERATE_ENDPOINT}",
                self.config.base_url()
            ))
            .json(&payload);
        if !self.config.api_key.trim().is_empty() {
            request = request.bearer_auth(self.config.api_key.trim());
        }
        let response = request.send().await.map_err(|error| {
            if error.is_timeout() {
                RuntimeError::Tool("生图 API 超时（生成较慢可稍后重试）".into())
            } else {
                RuntimeError::Tool(format!("生图 API 请求失败: {error}"))
            }
        })?;
        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(RuntimeError::Tool(format!(
                "生图 API 返回 HTTP {}: {}",
                status.as_u16(),
                body.chars().take(200).collect::<String>()
            )));
        }
        let body: Value = response
            .json()
            .await
            .map_err(|error| RuntimeError::Tool(format!("生图响应不是合法 JSON: {error}")))?;
        let items = body
            .get("data")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if items.is_empty() {
            return Err(RuntimeError::Tool(format!(
                "images/generations 响应缺少 data: {}",
                body.to_string().chars().take(200).collect::<String>()
            )));
        }

        let stamp = chrono::Local::now().format("%Y%m%d-%H%M%S").to_string();
        let mut saved: Vec<(String, String, usize)> = Vec::new();
        for (index, item) in items.iter().take(count as usize).enumerate() {
            let Some(bytes) = image_bytes(&http, item).await? else {
                continue;
            };
            let (mime, extension) = sniff_image_type(
                &bytes,
                item.get("url").and_then(Value::as_str).unwrap_or_default(),
            );
            let filename = format!("{stamp}_{index}{extension}");
            let location = self.sink.save_image(&filename, mime, &bytes).await?;
            saved.push((mime.to_owned(), location, bytes.len()));
        }
        if saved.is_empty() {
            return Err(RuntimeError::Tool("未能从生图响应中解析出任何图片".into()));
        }

        let lines = saved
            .iter()
            .map(|(_, location, _)| format!("- {location}"))
            .collect::<Vec<_>>()
            .join("\n");
        Ok(json!({
            "ok": true,
            "content": format!(
                "[generate_image] 已生成 {} 张图片:\n{lines}",
                saved.len()
            ),
            "prompt": prompt,
            "images": saved
                .iter()
                .map(|(mime, location, size)| json!({
                    "mime_type": mime,
                    "size_bytes": size,
                    "location": location,
                }))
                .collect::<Vec<_>>(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct RecordingSink {
        saved: Mutex<Vec<(String, String, usize)>>,
    }

    #[async_trait]
    impl ImageSink for RecordingSink {
        async fn save_image(
            &self,
            filename: &str,
            mime: &str,
            bytes: &[u8],
        ) -> Result<String, RuntimeError> {
            self.saved
                .lock()
                .unwrap()
                .push((filename.to_owned(), mime.to_owned(), bytes.len()));
            Ok(format!("attachment://{filename}"))
        }
    }

    fn configured() -> ImageGenConfig {
        ImageGenConfig {
            enabled: true,
            api_url: "http://127.0.0.1:1/v1/".into(),
            api_key: "secret".into(),
            model: "image-model".into(),
        }
    }

    /// Serve one request with a canned response and return what was received.
    fn serve_once(
        response: String,
    ) -> (
        std::net::SocketAddr,
        std::thread::JoinHandle<String>,
    ) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            let mut buffer = [0u8; 4096];
            loop {
                let size = match socket.read(&mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(size) => size,
                };
                request.extend_from_slice(&buffer[..size]);
                if let Some(end) = request.windows(4).position(|part| part == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..end]).to_owned();
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .and_then(|value| value.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if request.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            socket
                .write_all(response.as_bytes())
                .expect("write response");
            String::from_utf8_lossy(&request).into_owned()
        });
        (address, handle)
    }

    #[test]
    fn the_tool_is_hidden_until_it_is_configured_and_enabled() {
        let sink = Arc::new(RecordingSink::default());
        let offline = DeviceCapabilities::default();
        let disabled = GenerateImageTools::new(
            ImageGenConfig {
                enabled: false,
                ..configured()
            },
            sink.clone(),
        );
        assert!(disabled.definitions(&offline).is_empty());

        let no_url = GenerateImageTools::new(
            ImageGenConfig {
                api_url: String::new(),
                ..configured()
            },
            sink.clone(),
        );
        assert!(no_url.definitions(&offline).is_empty());

        let ready = GenerateImageTools::new(configured(), sink);
        let definitions = ready.definitions(&offline);
        assert_eq!(definitions.len(), 1);
        assert_eq!(definitions[0].name, "generate_image");
        let schema = &definitions[0].input_schema;
        assert_eq!(schema["required"], json!(["prompt"]));
        // Reference-image editing is desktop-only, so it must not be offered.
        assert!(schema["properties"].get("reference_urls").is_none());
    }

    #[test]
    fn image_type_comes_from_the_bytes_before_the_url() {
        assert_eq!(
            sniff_image_type(&[0xFF, 0xD8, 0xFF, 0xE0], "https://x/y.png"),
            ("image/jpeg", ".jpeg")
        );
        assert_eq!(
            sniff_image_type(b"\x89PNG\r\n\x1a\nrest", ""),
            ("image/png", ".png")
        );
        assert_eq!(
            sniff_image_type(b"RIFF0000WEBPVP8 ", ""),
            ("image/webp", ".webp")
        );
        // Unknown bytes fall back to the URL hint.
        assert_eq!(
            sniff_image_type(b"??", "https://x/y.webp"),
            ("image/webp", ".webp")
        );
        assert_eq!(sniff_image_type(b"??", ""), ("image/png", ".png"));
    }

    #[tokio::test]
    async fn generation_posts_the_prompt_and_stores_what_came_back() {
        let png = b"\x89PNG\r\n\x1a\nfake-image-bytes";
        use base64::Engine;
        let encoded = base64::engine::general_purpose::STANDARD.encode(png);
        let body = json!({"data": [{"b64_json": encoded}]}).to_string();
        let (address, server) = serve_once(format!(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        ));
        let sink = Arc::new(RecordingSink::default());
        let tools = GenerateImageTools::new(
            ImageGenConfig {
                api_url: format!("http://{address}/v1"),
                ..configured()
            },
            sink.clone(),
        );

        let result = tools
            .execute(&ToolCall {
                id: "call-1".into(),
                name: "generate_image".into(),
                arguments: json!({"prompt": "一只在雨里骑车的鹈鹕", "count": 1}),
            })
            .await
            .expect("generation succeeds");

        assert_eq!(result["ok"], json!(true));
        assert_eq!(result["images"][0]["mime_type"], json!("image/png"));
        assert_eq!(result["images"][0]["size_bytes"], json!(png.len()));
        assert!(result["content"]
            .as_str()
            .unwrap()
            .contains("已生成 1 张图片"));
        let stored = sink.saved.lock().unwrap().clone();
        assert_eq!(stored.len(), 1);
        assert_eq!(stored[0].1, "image/png");
        assert_eq!(stored[0].2, png.len());

        let request = server.join().unwrap();
        assert!(request.starts_with("POST /v1/images/generations"));
        assert!(request.contains("authorization: Bearer secret"));
        assert!(request.contains("一只在雨里骑车的鹈鹕"));
    }

    #[tokio::test]
    async fn a_missing_prompt_or_reference_images_fail_before_any_request() {
        let tools = GenerateImageTools::new(configured(), Arc::new(RecordingSink::default()));
        let missing = tools
            .execute(&ToolCall {
                id: "call-1".into(),
                name: "generate_image".into(),
                arguments: json!({}),
            })
            .await
            .expect_err("empty prompt must fail");
        assert!(missing.to_string().contains("Missing 'prompt' argument"));

        let references = tools
            .execute(&ToolCall {
                id: "call-2".into(),
                name: "generate_image".into(),
                arguments: json!({"prompt": "x", "reference_urls": ["https://example.com/a.png"]}),
            })
            .await
            .expect_err("reference editing is unavailable");
        assert!(references
            .to_string()
            .contains("reference-image editing is not available"));
    }
}
