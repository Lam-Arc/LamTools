use crate::{
    hooks::HookMcpCaller, DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition,
    ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, process::Stdio, sync::Arc, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command},
    sync::Mutex,
    time::timeout,
};

const MAX_MESSAGE_BYTES: usize = 32 * 1024 * 1024;
const MAX_HEADER_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum McpTransport {
    #[default]
    Headers,
    JsonLines,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpServerConfig {
    pub name: String,
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: f64,
    #[serde(default = "ask_user_permission")]
    pub permission: ToolPermission,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub builtin: bool,
    #[serde(default)]
    pub transport: McpTransport,
}

fn default_timeout() -> f64 {
    30.0
}

fn ask_user_permission() -> ToolPermission {
    ToolPermission::AskUser
}

fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpTool {
    pub server: String,
    pub name: String,
    pub function_name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub input_schema: Value,
    #[serde(default = "ask_user_permission")]
    pub permission: ToolPermission,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct McpLoadReport {
    pub servers: Vec<String>,
    pub tools: Vec<McpTool>,
    pub errors: Vec<String>,
}

pub fn load_server_configs(raw: &Value) -> Vec<McpServerConfig> {
    let servers = raw
        .get("mcpServers")
        .or_else(|| raw.get("servers"))
        .unwrap_or(raw);
    let Some(servers) = servers.as_object() else {
        return Vec::new();
    };
    servers
        .iter()
        .filter_map(|(key, raw)| {
            let raw = raw.as_object()?;
            let command = raw.get("command")?.as_str()?.trim();
            if command.is_empty() {
                return None;
            }
            let enabled = raw.get("enabled").and_then(Value::as_bool).unwrap_or(true);
            if !enabled {
                return None;
            }
            let permission = match raw.get("permission").and_then(Value::as_str) {
                Some("auto_allow") => ToolPermission::AutoAllow,
                Some("hard_block") => ToolPermission::HardBlock,
                _ => ToolPermission::AskUser,
            };
            let transport = match raw.get("transport").and_then(Value::as_str) {
                Some("json_lines") => McpTransport::JsonLines,
                _ => McpTransport::Headers,
            };
            Some(McpServerConfig {
                name: raw
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or(key)
                    .to_owned(),
                command: command.to_owned(),
                args: raw
                    .get("args")
                    .and_then(Value::as_array)
                    .map(|items| {
                        items
                            .iter()
                            .filter_map(|item| item.as_str().map(str::to_owned))
                            .collect()
                    })
                    .unwrap_or_default(),
                env: raw
                    .get("env")
                    .and_then(Value::as_object)
                    .map(|entries| {
                        entries
                            .iter()
                            .filter_map(|(key, value)| {
                                value.as_str().map(|value| (key.clone(), value.to_owned()))
                            })
                            .collect()
                    })
                    .unwrap_or_default(),
                timeout_seconds: raw
                    .get("timeout_seconds")
                    .or_else(|| raw.get("timeout"))
                    .and_then(Value::as_f64)
                    .filter(|value| value.is_finite() && *value > 0.0)
                    .unwrap_or_else(default_timeout),
                permission,
                enabled,
                builtin: raw.get("builtin").and_then(Value::as_bool).unwrap_or(false),
                transport,
            })
        })
        .collect()
}

struct McpClient {
    config: McpServerConfig,
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

impl McpClient {
    async fn start(config: McpServerConfig) -> Result<Self, String> {
        let mut command = Command::new(&config.command);
        command
            .args(&config.args)
            .envs(&config.env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        let mut child = command.spawn().map_err(|error| {
            format!(
                "MCP server '{}' could not start '{}': {error}",
                config.name, config.command
            )
        })?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| format!("MCP server '{}' has no stdin", config.name))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| format!("MCP server '{}' has no stdout", config.name))?;
        let mut client = Self {
            config,
            child,
            stdin,
            stdout: BufReader::new(stdout),
            next_id: 1,
        };
        client
            .request(
                "initialize",
                serde_json::json!({
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "LamToolsCore", "version": env!("CARGO_PKG_VERSION")},
                }),
            )
            .await?;
        client
            .notify("notifications/initialized", serde_json::json!({}))
            .await?;
        Ok(client)
    }

    async fn list_tools(&mut self) -> Result<Vec<McpTool>, String> {
        let result = self.request("tools/list", serde_json::json!({})).await?;
        let Some(tools) = result.get("tools").and_then(Value::as_array) else {
            return Ok(Vec::new());
        };
        Ok(tools
            .iter()
            .filter_map(|raw| {
                let raw = raw.as_object()?;
                let name = raw.get("name")?.as_str()?.trim();
                if name.is_empty() {
                    return None;
                }
                Some(McpTool {
                    server: self.config.name.clone(),
                    name: name.to_owned(),
                    function_name: encode_tool_name(&self.config.name, name),
                    description: raw
                        .get("description")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    input_schema: normalized_schema(raw.get("inputSchema").cloned()),
                    permission: self.config.permission,
                })
            })
            .collect())
    }

    async fn call_tool(&mut self, name: &str, arguments: Value) -> Result<Value, String> {
        self.request(
            "tools/call",
            serde_json::json!({"name": name, "arguments": arguments}),
        )
        .await
    }

    async fn request(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;
        let timeout_duration = Duration::from_secs_f64(self.config.timeout_seconds);
        let exchange = async {
            self.send(&serde_json::json!({
                "jsonrpc": "2.0",
                "id": id,
                "method": method,
                "params": params,
            }))
            .await?;
            loop {
                let message = self.read_message().await?.ok_or_else(|| {
                    format!("MCP server '{}' closed the connection", self.config.name)
                })?;
                if message.get("id").and_then(Value::as_u64) != Some(id) {
                    continue;
                }
                if let Some(error) = message.get("error") {
                    return Err(format!("{}.{} failed: {error}", self.config.name, method));
                }
                return Ok(message
                    .get("result")
                    .cloned()
                    .unwrap_or_else(|| serde_json::json!({})));
            }
        };
        timeout(timeout_duration, exchange)
            .await
            .map_err(|_| format!("{}.{} timed out", self.config.name, method))?
    }

    async fn notify(&mut self, method: &str, params: Value) -> Result<(), String> {
        timeout(
            Duration::from_secs_f64(self.config.timeout_seconds),
            self.send(&serde_json::json!({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            })),
        )
        .await
        .map_err(|_| format!("{}.{} timed out", self.config.name, method))?
    }

    async fn send(&mut self, payload: &Value) -> Result<(), String> {
        let body = serde_json::to_vec(payload).map_err(|error| error.to_string())?;
        if body.len() > MAX_MESSAGE_BYTES {
            return Err("MCP request exceeds the 32 MiB safety limit".into());
        }
        match self.config.transport {
            McpTransport::Headers => {
                self.stdin
                    .write_all(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes())
                    .await
                    .map_err(|error| error.to_string())?;
                self.stdin
                    .write_all(&body)
                    .await
                    .map_err(|error| error.to_string())?;
            }
            McpTransport::JsonLines => {
                self.stdin
                    .write_all(&body)
                    .await
                    .map_err(|error| error.to_string())?;
                self.stdin
                    .write_all(b"\n")
                    .await
                    .map_err(|error| error.to_string())?;
            }
        }
        self.stdin.flush().await.map_err(|error| error.to_string())
    }

    async fn read_message(&mut self) -> Result<Option<Value>, String> {
        match self.config.transport {
            McpTransport::JsonLines => loop {
                let Some(line) = read_line_limited(&mut self.stdout, MAX_MESSAGE_BYTES).await?
                else {
                    return Ok(None);
                };
                let text = String::from_utf8_lossy(&line);
                if text.trim().is_empty() {
                    continue;
                }
                match serde_json::from_slice(&line) {
                    Ok(value) => return Ok(Some(value)),
                    Err(_) => continue,
                }
            },
            McpTransport::Headers => {
                let mut content_length = None;
                let mut header_bytes = 0;
                loop {
                    let Some(line) = read_line_limited(&mut self.stdout, MAX_HEADER_BYTES).await?
                    else {
                        return Ok(None);
                    };
                    header_bytes += line.len();
                    if header_bytes > MAX_HEADER_BYTES {
                        return Err("MCP response headers exceed the 64 KiB safety limit".into());
                    }
                    let text = String::from_utf8_lossy(&line);
                    if text.trim().is_empty() {
                        break;
                    }
                    if let Some((key, value)) = text.split_once(':') {
                        if key.trim().eq_ignore_ascii_case("content-length") {
                            content_length = value.trim().parse::<usize>().ok();
                        }
                    }
                }
                let length = content_length
                    .ok_or_else(|| "MCP response has no Content-Length".to_owned())?;
                if length == 0 || length > MAX_MESSAGE_BYTES {
                    return Err("MCP response exceeds the 32 MiB safety limit".into());
                }
                let mut body = vec![0; length];
                self.stdout
                    .read_exact(&mut body)
                    .await
                    .map_err(|error| error.to_string())?;
                serde_json::from_slice(&body)
                    .map(Some)
                    .map_err(|error| format!("MCP returned invalid JSON: {error}"))
            }
        }
    }
}

impl Drop for McpClient {
    fn drop(&mut self) {
        let _ = self.child.start_kill();
    }
}

async fn read_line_limited(
    reader: &mut BufReader<ChildStdout>,
    limit: usize,
) -> Result<Option<Vec<u8>>, String> {
    let mut line = Vec::new();
    while line.len() <= limit {
        let mut byte = [0u8; 1];
        match reader.read(&mut byte).await {
            Ok(0) if line.is_empty() => return Ok(None),
            Ok(0) => return Ok(Some(line)),
            Ok(_) => {
                line.push(byte[0]);
                if byte[0] == b'\n' {
                    return Ok(Some(line));
                }
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    Err(format!("MCP line exceeds the {limit}-byte safety limit"))
}

pub struct McpToolRuntime {
    tools: BTreeMap<String, McpTool>,
    clients: BTreeMap<String, Arc<Mutex<McpClient>>>,
    report: McpLoadReport,
}

impl McpToolRuntime {
    pub async fn load(configs: Vec<McpServerConfig>) -> Self {
        let mut tools = BTreeMap::new();
        let mut clients = BTreeMap::new();
        let mut report = McpLoadReport::default();
        for config in configs.into_iter().filter(|config| config.enabled) {
            let server_name = config.name.clone();
            match McpClient::start(config).await {
                Ok(mut client) => match client.list_tools().await {
                    Ok(server_tools) => {
                        for tool in &server_tools {
                            tools.insert(tool.function_name.clone(), tool.clone());
                        }
                        report.servers.push(server_name.clone());
                        report.tools.extend(server_tools);
                        clients.insert(server_name, Arc::new(Mutex::new(client)));
                    }
                    Err(error) => report.errors.push(error),
                },
                Err(error) => report.errors.push(error),
            }
        }
        Self {
            tools,
            clients,
            report,
        }
    }

    pub fn empty() -> Self {
        Self {
            tools: BTreeMap::new(),
            clients: BTreeMap::new(),
            report: McpLoadReport::default(),
        }
    }

    pub fn report(&self) -> &McpLoadReport {
        &self.report
    }

    async fn call_text(&self, tool_name: &str, arguments: Value) -> Result<String, String> {
        let tool = self
            .tools
            .get(tool_name)
            .ok_or_else(|| format!("MCP TOOL ERROR: unknown tool {tool_name}"))?;
        if tool.permission == ToolPermission::HardBlock {
            return Err(format!("MCP TOOL ERROR: tool {tool_name} is hard-blocked"));
        }
        let client = self
            .clients
            .get(&tool.server)
            .ok_or_else(|| format!("MCP TOOL ERROR: server {} is not connected", tool.server))?;
        let result = client
            .lock()
            .await
            .call_tool(&tool.name, clean_arguments(arguments))
            .await
            .map_err(|error| format!("MCP TOOL ERROR: {}.{}: {error}", tool.server, tool.name))?;
        Ok(format_result(&result))
    }
}

#[async_trait]
impl ToolRuntime for McpToolRuntime {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        self.tools
            .values()
            .filter(|tool| tool.permission != ToolPermission::HardBlock)
            .map(|tool| ToolDefinition {
                name: tool.function_name.clone(),
                description: format!(
                    "[MCP:{}] {}",
                    tool.server,
                    if tool.description.is_empty() {
                        &tool.name
                    } else {
                        &tool.description
                    }
                ),
                input_schema: tool.input_schema.clone(),
            })
            .collect()
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        self.tools
            .get(&call.name)
            .map(|tool| tool.permission)
            .unwrap_or(ToolPermission::HardBlock)
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        self.call_text(&call.name, call.arguments.clone())
            .await
            .map(|content| serde_json::json!({"ok": true, "content": content}))
            .map_err(RuntimeError::Tool)
    }
}

#[async_trait]
impl HookMcpCaller for McpToolRuntime {
    async fn call(&self, tool_name: &str, arguments: Value) -> Result<String, String> {
        self.call_text(tool_name, arguments).await
    }
}

fn normalized_schema(schema: Option<Value>) -> Value {
    match schema {
        Some(Value::Object(mut schema))
            if schema.get("type").and_then(Value::as_str) == Some("object") =>
        {
            schema
                .entry("properties")
                .or_insert_with(|| serde_json::json!({}));
            Value::Object(schema)
        }
        _ => serde_json::json!({"type": "object", "properties": {}}),
    }
}

fn clean_arguments(arguments: Value) -> Value {
    let Some(arguments) = arguments.as_object() else {
        return serde_json::json!({});
    };
    Value::Object(
        arguments
            .iter()
            .filter(|(key, _)| !key.starts_with('_'))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect(),
    )
}

pub fn format_result(result: &Value) -> String {
    if let Some(content) = result.get("content").and_then(Value::as_array) {
        let text = content
            .iter()
            .filter_map(|item| {
                if item.get("type").and_then(Value::as_str) == Some("text") {
                    item.get("text").and_then(Value::as_str).map(str::to_owned)
                } else {
                    serde_json::to_string(item).ok()
                }
            })
            .filter(|item| !item.is_empty())
            .collect::<Vec<_>>()
            .join("\n");
        if result.get("isError").and_then(Value::as_bool) == Some(true) {
            return format!("MCP TOOL ERROR: {text}");
        }
        if !text.is_empty() {
            return text;
        }
    }
    serde_json::to_string_pretty(result).unwrap_or_else(|_| "{}".into())
}

pub fn encode_tool_name(server: &str, tool: &str) -> String {
    format!("mcp__{}__{}", safe_name(server), safe_name(tool))
}

fn safe_name(value: &str) -> String {
    let value = value
        .chars()
        .map(|character| {
            if character.is_alphanumeric() || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect::<String>()
        .trim_matches('_')
        .to_owned();
    if value.is_empty() {
        "tool".into()
    } else {
        value
    }
}

pub struct CompositeToolRuntime {
    definitions: Vec<ToolDefinition>,
    owners: BTreeMap<String, usize>,
    runtimes: Vec<Arc<dyn ToolRuntime>>,
}

impl CompositeToolRuntime {
    pub fn new(capabilities: &DeviceCapabilities, runtimes: Vec<Arc<dyn ToolRuntime>>) -> Self {
        let mut definitions = Vec::new();
        let mut owners = BTreeMap::new();
        for (index, runtime) in runtimes.iter().enumerate() {
            for definition in runtime.definitions(capabilities) {
                if owners.insert(definition.name.clone(), index).is_none() {
                    definitions.push(definition);
                }
            }
        }
        Self {
            definitions,
            owners,
            runtimes,
        }
    }
}

#[async_trait]
impl ToolRuntime for CompositeToolRuntime {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        self.definitions.clone()
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        self.owners
            .get(&call.name)
            .and_then(|index| self.runtimes.get(*index))
            .map(|runtime| runtime.permission(call))
            .unwrap_or(ToolPermission::HardBlock)
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let runtime = self
            .owners
            .get(&call.name)
            .and_then(|index| self.runtimes.get(*index))
            .ok_or_else(|| RuntimeError::Tool(format!("unknown tool '{}'", call.name)))?;
        runtime.execute(call).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, Write};

    #[test]
    fn mock_mcp_server_process() {
        let Ok(mode) = std::env::var("LAMTOOLS_MCP_TEST_MODE") else {
            return;
        };
        let stdin = std::io::stdin();
        let mut lines = stdin.lock().lines();
        let mut stdout = std::io::stdout().lock();
        while let Some(Ok(line)) = lines.next() {
            let Ok(message) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            let method = message.get("method").and_then(Value::as_str);
            if method == Some("initialize") && mode == "initialize_hang" {
                std::thread::sleep(Duration::from_secs(10));
                return;
            }
            let result = match method {
                Some("initialize") => serde_json::json!({}),
                Some("tools/list") if mode == "list_hang" => {
                    std::thread::sleep(Duration::from_secs(10));
                    return;
                }
                Some("tools/list") => serde_json::json!({"tools": [{"name": "slow"}]}),
                Some("tools/call") if mode == "send_hang" => {
                    std::thread::sleep(Duration::from_secs(10));
                    return;
                }
                _ => continue,
            };
            let response =
                serde_json::json!({"jsonrpc": "2.0", "id": message["id"], "result": result});
            // The test harness writes its own stdout prefix; start a new JSON line.
            writeln!(stdout, "\n{response}").unwrap();
            stdout.flush().unwrap();
            if method == Some("tools/list") && mode == "send_hang" {
                std::thread::sleep(Duration::from_secs(10));
                return;
            }
        }
    }

    fn mock_config(mode: &str) -> McpServerConfig {
        McpServerConfig {
            name: mode.to_owned(),
            command: std::env::current_exe()
                .unwrap()
                .to_string_lossy()
                .into_owned(),
            args: vec![
                "--exact".into(),
                "mcp::tests::mock_mcp_server_process".into(),
                "--nocapture".into(),
            ],
            env: BTreeMap::from([("LAMTOOLS_MCP_TEST_MODE".into(), mode.into())]),
            timeout_seconds: 0.3,
            permission: ToolPermission::AutoAllow,
            enabled: true,
            builtin: false,
            transport: McpTransport::JsonLines,
        }
    }

    #[tokio::test]
    async fn startup_and_tool_discovery_report_hung_servers() {
        for mode in ["initialize_hang", "list_hang"] {
            let runtime = tokio::time::timeout(
                Duration::from_secs(4),
                McpToolRuntime::load(vec![mock_config(mode)]),
            )
            .await
            .expect("MCP load should finish within the request deadline");
            assert!(runtime.report().servers.is_empty());
            assert_eq!(
                runtime.report().errors,
                [format!(
                    "{mode}.{} timed out",
                    if mode == "initialize_hang" {
                        "initialize"
                    } else {
                        "tools/list"
                    }
                )]
            );
        }
    }

    #[tokio::test]
    async fn request_timeout_includes_blocked_stdin_write() {
        let runtime = tokio::time::timeout(
            Duration::from_secs(4),
            McpToolRuntime::load(vec![mock_config("send_hang")]),
        )
        .await
        .expect("MCP load should finish");
        assert_eq!(runtime.report().servers, ["send_hang"]);
        let client = runtime.clients.get("send_hang").unwrap();
        let result = tokio::time::timeout(
            Duration::from_secs(4),
            client.lock().await.call_tool(
                "slow",
                serde_json::json!({"payload": "x".repeat(8 * 1024 * 1024)}),
            ),
        )
        .await
        .expect("blocked stdin write should use the MCP request deadline");
        assert_eq!(result.unwrap_err(), "send_hang.tools/call timed out");
    }

    #[test]
    fn config_and_tool_names_match_the_existing_mcp_contract() {
        let configs = load_server_configs(&serde_json::json!({
            "mcpServers": {
                "local server": {
                    "command": "python",
                    "args": ["server.py"],
                    "permission": "auto_allow",
                    "transport": "json_lines"
                }
            }
        }));
        assert_eq!(configs.len(), 1);
        assert_eq!(configs[0].permission, ToolPermission::AutoAllow);
        assert_eq!(configs[0].transport, McpTransport::JsonLines);
        assert_eq!(
            encode_tool_name("local server", "echo-text"),
            "mcp__local_server__echo_text"
        );
    }

    #[test]
    fn results_and_runtime_only_expose_safe_tool_data() {
        assert_eq!(
            clean_arguments(serde_json::json!({"text":"hi", "_tool_call_id":"x"})),
            serde_json::json!({"text":"hi"})
        );
        assert_eq!(
            format_result(&serde_json::json!({"content":[{"type":"text","text":"hello"}]})),
            "hello"
        );
        assert_eq!(
            format_result(
                &serde_json::json!({"isError":true,"content":[{"type":"text","text":"bad"}]})
            ),
            "MCP TOOL ERROR: bad"
        );
    }
}
