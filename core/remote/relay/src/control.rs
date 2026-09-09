//! Persistent control-plane storage for the LamTools relay.
//!
//! The relay never stores Core work data.  This module owns only server
//! identity, accounts, registered nodes/workspaces, grants, short-lived
//! access sessions and one-time connection tickets.

use std::{
    collections::HashSet,
    fs,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

use argon2::{
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use getrandom::fill as fill_random;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

const ACCESS_TTL_MS: i64 = 30 * 60 * 1000;
const REFRESH_TTL_MS: i64 = 30 * 24 * 60 * 60 * 1000;
const TICKET_TTL_MS: i64 = 60 * 1000;
const PAIRING_TICKET_TTL_MS: i64 = 60 * 1000;
const DESKTOP_NODE_LIMIT: i64 = 5;
const MOBILE_NODE_LIMIT: i64 = 10;

#[derive(Clone)]
pub struct ControlPlane {
    db: Arc<Mutex<Connection>>,
    database_path: PathBuf,
    server_id: String,
    registration_mode: String,
}

#[derive(Clone, Debug)]
pub struct ControlError {
    pub status: u16,
    pub code: &'static str,
    pub message: String,
}

impl ControlError {
    pub(crate) fn new(status: u16, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
        }
    }

    pub(crate) fn bad_request(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(400, code, message)
    }

    pub(crate) fn unauthorized(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(401, code, message)
    }

    pub(crate) fn forbidden(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(403, code, message)
    }

    pub(crate) fn not_found(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(404, code, message)
    }

    pub(crate) fn conflict(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(409, code, message)
    }

    pub(crate) fn unavailable(code: &'static str, message: impl Into<String>) -> Self {
        Self::new(503, code, message)
    }

    pub(crate) fn internal(message: impl Into<String>) -> Self {
        Self::new(500, "SERVER_ERROR", message)
    }
}

impl std::fmt::Display for ControlError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for ControlError {}

#[derive(Clone, Debug)]
pub struct AuthContext {
    pub user_id: String,
    pub node_id: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthTokens {
    pub server_id: String,
    pub access_token: String,
    pub refresh_token: String,
    pub access_expires_at_ms: i64,
    pub refresh_expires_at_ms: i64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UserRecord {
    pub user_id: String,
    pub username: String,
    pub created_at_ms: i64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeRegistration {
    pub node_id: String,
    pub public_key: String,
    pub display_name: String,
    pub platform: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeUpdate {
    #[serde(default)]
    pub display_name: Option<String>,
    #[serde(default)]
    pub platform: Option<String>,
    #[serde(default)]
    pub public_key: Option<String>,
    #[serde(default)]
    pub capabilities: Option<Vec<String>>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeRecord {
    pub node_id: String,
    pub display_name: String,
    pub platform: String,
    pub public_key: String,
    pub capabilities: Vec<String>,
    pub created_at_ms: i64,
    pub last_seen_at_ms: Option<i64>,
    pub revoked_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceRegistration {
    pub node_id: String,
    #[serde(default)]
    pub display_name: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceUpdate {
    #[serde(default)]
    pub display_name: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceRecord {
    pub workspace_id: String,
    pub host_node_id: String,
    pub owner_user_id: String,
    pub display_name: String,
    pub online: bool,
    pub host: Option<NodeRecord>,
    pub role: String,
    pub created_at_ms: i64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GrantRequest {
    pub username: String,
    #[serde(default = "default_access_role")]
    pub role: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GrantRecord {
    pub grant_id: String,
    pub workspace_id: String,
    pub owner_user_id: String,
    pub grantee_user_id: String,
    pub grantee_username: String,
    pub role: String,
    pub created_at_ms: i64,
    pub revoked_at_ms: Option<i64>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConnectionTicket {
    pub ticket: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_host_node_id: String,
    pub expires_at_ms: i64,
}

#[derive(Clone, Debug)]
pub struct ConsumedTicket {
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_host_node_id: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingTicket {
    pub ticket: String,
    pub pairing_id: String,
    pub source_node_id: String,
    pub target_host_node_id: String,
    pub expires_at_ms: i64,
}

#[derive(Clone, Debug)]
pub struct ConsumedPairingTicket {
    pub pairing_id: String,
    pub source_node_id: String,
    pub target_host_node_id: String,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NodeRegistrationResult {
    pub node: NodeRecord,
    pub workspace: Option<WorkspaceRecord>,
}

impl ControlPlane {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ControlError> {
        let database_path = path.as_ref().to_path_buf();
        if let Some(parent) = database_path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| ControlError::internal(format!("database directory: {error}")))?;
        }
        let connection = Connection::open(&database_path)
            .map_err(|error| ControlError::internal(format!("database open: {error}")))?;
        connection
            .busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|error| ControlError::internal(format!("database busy timeout: {error}")))?;
        connection
            .pragma_update(None, "journal_mode", "WAL")
            .map_err(|error| ControlError::internal(format!("database WAL: {error}")))?;
        connection
            .pragma_update(None, "foreign_keys", "ON")
            .map_err(|error| ControlError::internal(format!("database foreign keys: {error}")))?;
        migrate(&connection)?;
        let server_id =
            config_value(&connection, "server_id")?.unwrap_or_else(|| Uuid::new_v4().to_string());
        if config_value(&connection, "server_id")?.is_none() {
            set_config_value(&connection, "server_id", &server_id)?;
            let private_key = random_token(32)
                .map_err(|error| ControlError::internal(format!("server identity: {error}")))?;
            let public_key = URL_SAFE_NO_PAD.encode(Sha256::digest(private_key.as_bytes()));
            set_config_value(&connection, "server_private_key", &private_key)?;
            set_config_value(&connection, "server_public_key", &public_key)?;
        }
        let registration_mode = std::env::var("REGISTRATION_MODE")
            .unwrap_or_else(|_| "open".to_string())
            .to_ascii_lowercase();
        Ok(Self {
            db: Arc::new(Mutex::new(connection)),
            database_path,
            server_id,
            registration_mode,
        })
    }

    pub fn database_path(&self) -> &Path {
        &self.database_path
    }

    pub fn server_id(&self) -> &str {
        &self.server_id
    }

    pub fn registration_mode(&self) -> &str {
        &self.registration_mode
    }

    pub fn register(&self, username: &str, password: &str) -> Result<AuthTokens, ControlError> {
        if self.registration_mode == "closed" {
            return Err(ControlError::new(
                403,
                "REGISTRATION_CLOSED",
                "当前服务器已关闭注册",
            ));
        }
        let (display, normalized) = normalize_username(username)?;
        validate_password(password)?;
        let password_hash = hash_password(password)?;
        let user_id = Uuid::new_v4().to_string();
        let created_at_ms = now_ms();
        let connection = self.connection()?;
        connection
            .execute(
                "INSERT INTO users (id, username, username_normalized, password_hash, created_at_ms) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![user_id, display, normalized, password_hash, created_at_ms],
            )
            .map_err(|error| {
                if error.to_string().contains("UNIQUE") {
                    ControlError::conflict("USERNAME_TAKEN", "用户名已存在")
                } else {
                    ControlError::internal(format!("user registration: {error}"))
                }
            })?;
        issue_tokens(&connection, &self.server_id, &user_id, None)
    }

    pub fn login(&self, username: &str, password: &str) -> Result<AuthTokens, ControlError> {
        let normalized = normalize_username(username)?.1;
        let connection = self.connection()?;
        let row = connection
            .query_row(
                "SELECT id, password_hash, disabled_at_ms FROM users WHERE username_normalized = ?1",
                params![normalized],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, Option<i64>>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("user login: {error}")))?;
        let Some((user_id, password_hash, disabled_at)) = row else {
            return Err(ControlError::unauthorized(
                "AUTH_INVALID",
                "用户名或密码错误",
            ));
        };
        if disabled_at.is_some() || !verify_password(&password_hash, password) {
            return Err(ControlError::unauthorized(
                "AUTH_INVALID",
                "用户名或密码错误",
            ));
        }
        issue_tokens(&connection, &self.server_id, &user_id, None)
    }

    pub fn refresh(&self, refresh_token: &str) -> Result<AuthTokens, ControlError> {
        let token_hash = hash_token(refresh_token);
        let now = now_ms();
        let connection = self.connection()?;
        let row = connection
            .query_row(
                "SELECT user_id, node_id, expires_at_ms, revoked_at_ms FROM refresh_tokens WHERE token_hash = ?1",
                params![token_hash],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?,
                        row.get::<_, i64>(2)?,
                        row.get::<_, Option<i64>>(3)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("refresh lookup: {error}")))?;
        let Some((user_id, node_id, expires_at_ms, revoked_at_ms)) = row else {
            return Err(ControlError::unauthorized("AUTH_INVALID", "刷新凭据无效"));
        };
        if revoked_at_ms.is_some() || expires_at_ms <= now || !user_enabled(&connection, &user_id)?
        {
            return Err(ControlError::unauthorized("AUTH_INVALID", "刷新凭据已失效"));
        }
        connection
            .execute(
                "UPDATE refresh_tokens SET revoked_at_ms = ?1 WHERE token_hash = ?2",
                params![now, token_hash],
            )
            .map_err(|error| ControlError::internal(format!("refresh revoke: {error}")))?;
        issue_tokens(&connection, &self.server_id, &user_id, node_id.as_deref())
    }

    pub fn logout(&self, refresh_token: &str) -> Result<(), ControlError> {
        let connection = self.connection()?;
        connection
            .execute(
                "UPDATE refresh_tokens SET revoked_at_ms = ?1 WHERE token_hash = ?2",
                params![now_ms(), hash_token(refresh_token)],
            )
            .map_err(|error| ControlError::internal(format!("logout: {error}")))?;
        Ok(())
    }

    pub fn authenticate(&self, access_token: &str) -> Result<AuthContext, ControlError> {
        let token_hash = hash_token(access_token);
        let connection = self.connection()?;
        let row = connection
            .query_row(
                "SELECT user_id, node_id, expires_at_ms, revoked_at_ms FROM access_tokens WHERE token_hash = ?1",
                params![token_hash],
                |row| Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, Option<i64>>(3)?,
                )),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("access lookup: {error}")))?;
        let Some((user_id, node_id, expires_at_ms, revoked_at_ms)) = row else {
            return Err(ControlError::unauthorized(
                "AUTH_REQUIRED",
                "需要登录服务器账号",
            ));
        };
        if revoked_at_ms.is_some()
            || expires_at_ms <= now_ms()
            || !user_enabled(&connection, &user_id)?
        {
            return Err(ControlError::unauthorized(
                "AUTH_INVALID",
                "登录已过期，请重新登录",
            ));
        }
        if let Some(node_id) = node_id.as_deref() {
            if node_revoked(&connection, node_id)? {
                return Err(ControlError::forbidden("NODE_REVOKED", "设备已被撤销"));
            }
        }
        Ok(AuthContext { user_id, node_id })
    }

    /// Issues a fresh device-bound session after an account session claims a
    /// Node. The original account-only access token remains independently
    /// revocable; clients should replace it with the returned pair for all
    /// device operations.
    pub fn bind_node_session(
        &self,
        access_token: &str,
        node_id: &str,
    ) -> Result<AuthTokens, ControlError> {
        let auth = self.authenticate(access_token)?;
        let node_id = node_id.trim();
        if node_id.is_empty() {
            return Err(ControlError::bad_request(
                "INVALID_NODE",
                "Node 身份不能为空",
            ));
        }
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1 AND revoked_at_ms IS NULL",
                params![node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("node bind lookup: {error}")))?;
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "Node 不属于当前账号或已撤销",
            ));
        }
        issue_tokens(&connection, &self.server_id, &auth.user_id, Some(node_id))
    }

    pub fn register_node(
        &self,
        auth: &AuthContext,
        request: NodeRegistration,
    ) -> Result<NodeRegistrationResult, ControlError> {
        let node_id = request.node_id.trim();
        let public_key = request.public_key.trim();
        if node_id.is_empty()
            || node_id.len() > 128
            || public_key.is_empty()
            || public_key.len() > 512
        {
            return Err(ControlError::bad_request(
                "INVALID_NODE",
                "Node 身份字段无效",
            ));
        }
        let display_name = if request.display_name.trim().is_empty() {
            node_id.to_string()
        } else {
            request.display_name.trim().chars().take(128).collect()
        };
        let platform = if request.platform.trim().is_empty() {
            "unknown"
        } else {
            request.platform.trim()
        };
        let capabilities = normalize_capabilities(&request.capabilities);
        let connection = self.connection()?;
        let existing_owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1",
                params![node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("node lookup: {error}")))?;
        if existing_owner
            .as_deref()
            .is_some_and(|owner| owner != auth.user_id)
        {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "Node 已属于其他账号",
            ));
        }
        if existing_owner.is_none()
            && node_count(&connection, &auth.user_id, platform)? >= node_limit(platform)
        {
            return Err(ControlError::new(
                403,
                "DEVICE_LIMIT_REACHED",
                "已达到该类型设备数量上限",
            ));
        }
        let now = now_ms();
        connection
            .execute(
                "INSERT INTO nodes (id, owner_user_id, display_name, platform, public_key, capabilities_json, created_at_ms, last_seen_at_ms, revoked_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, NULL) ON CONFLICT(id) DO UPDATE SET owner_user_id = excluded.owner_user_id, display_name = excluded.display_name, platform = excluded.platform, public_key = excluded.public_key, capabilities_json = excluded.capabilities_json, last_seen_at_ms = excluded.last_seen_at_ms, revoked_at_ms = NULL",
                params![node_id, auth.user_id, display_name, platform, public_key, serde_json::to_string(&capabilities).unwrap_or_else(|_| "[]".into()), now, now],
            )
            .map_err(|error| ControlError::internal(format!("node register: {error}")))?;
        let node = node_record(&connection, node_id)?
            .ok_or_else(|| ControlError::internal("registered Node disappeared"))?;
        let workspace = if is_host_capable(&capabilities) || is_desktop_platform(platform) {
            Some(self.ensure_workspace_locked(&connection, auth, node_id, "")?)
        } else {
            None
        };
        Ok(NodeRegistrationResult { node, workspace })
    }

    pub fn update_node(
        &self,
        auth: &AuthContext,
        node_id: &str,
        request: NodeUpdate,
    ) -> Result<NodeRecord, ControlError> {
        let node_id = node_id.trim();
        if node_id.is_empty() {
            return Err(ControlError::bad_request(
                "INVALID_NODE",
                "Node 身份不能为空",
            ));
        }
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1",
                params![node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("node update lookup: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::not_found("NODE_NOT_FOUND", "设备不存在"));
        }
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden("ACCESS_DENIED", "无权修改该设备"));
        }
        let current = node_record(&connection, node_id)?
            .ok_or_else(|| ControlError::not_found("NODE_NOT_FOUND", "设备不存在"))?;
        if current.revoked_at_ms.is_some() {
            return Err(ControlError::forbidden(
                "NODE_REVOKED",
                "设备已被撤销，请重新注册",
            ));
        }
        let display_name = request
            .display_name
            .map(|value| value.trim().chars().take(128).collect::<String>())
            .filter(|value| !value.is_empty())
            .unwrap_or(current.display_name);
        let platform = request
            .platform
            .map(|value| value.trim().chars().take(64).collect::<String>())
            .filter(|value| !value.is_empty())
            .unwrap_or(current.platform);
        let public_key = request
            .public_key
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty() && value.len() <= 512)
            .unwrap_or(current.public_key);
        if public_key.is_empty() || public_key.len() > 512 {
            return Err(ControlError::bad_request("INVALID_NODE", "Node 公钥无效"));
        }
        let capabilities = request
            .capabilities
            .map(|values| normalize_capabilities(&values))
            .unwrap_or(current.capabilities);
        connection
            .execute(
                "UPDATE nodes SET display_name = ?1, platform = ?2, public_key = ?3, capabilities_json = ?4, last_seen_at_ms = ?5 WHERE id = ?6",
                params![
                    display_name,
                    platform,
                    public_key,
                    serde_json::to_string(&capabilities).unwrap_or_else(|_| "[]".into()),
                    now_ms(),
                    node_id,
                ],
            )
            .map_err(|error| ControlError::internal(format!("node update: {error}")))?;
        node_record(&connection, node_id)?
            .ok_or_else(|| ControlError::internal("updated Node disappeared"))
    }

    pub fn list_nodes(&self, auth: &AuthContext) -> Result<Vec<NodeRecord>, ControlError> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare("SELECT id FROM nodes WHERE owner_user_id = ?1 ORDER BY created_at_ms, id")
            .map_err(|error| ControlError::internal(format!("node list: {error}")))?;
        let ids = statement
            .query_map(params![auth.user_id], |row| row.get::<_, String>(0))
            .map_err(|error| ControlError::internal(format!("node list: {error}")))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| ControlError::internal(format!("node list: {error}")))?;
        ids.iter()
            .map(|id| {
                node_record(&connection, id)?
                    .ok_or_else(|| ControlError::internal("listed Node disappeared"))
            })
            .collect()
    }

    pub fn touch_node(&self, node_id: &str) -> Result<(), ControlError> {
        let connection = self.connection()?;
        connection
            .execute(
                "UPDATE nodes SET last_seen_at_ms = ?1 WHERE id = ?2",
                params![now_ms(), node_id],
            )
            .map_err(|error| ControlError::internal(format!("node heartbeat: {error}")))?;
        Ok(())
    }

    pub fn revoke_node(&self, auth: &AuthContext, node_id: &str) -> Result<(), ControlError> {
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1",
                params![node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("node revoke lookup: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::not_found("NODE_NOT_FOUND", "设备不存在"));
        }
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden("ACCESS_DENIED", "无权撤销该设备"));
        }
        let now = now_ms();
        connection
            .execute(
                "UPDATE nodes SET revoked_at_ms = ?1 WHERE id = ?2",
                params![now, node_id],
            )
            .map_err(|error| ControlError::internal(format!("node revoke: {error}")))?;
        connection
            .execute(
                "UPDATE refresh_tokens SET revoked_at_ms = ?1 WHERE node_id = ?2",
                params![now, node_id],
            )
            .map_err(|error| ControlError::internal(format!("node token revoke: {error}")))?;
        connection
            .execute(
                "UPDATE access_tokens SET revoked_at_ms = ?1 WHERE node_id = ?2",
                params![now, node_id],
            )
            .map_err(|error| ControlError::internal(format!("node access revoke: {error}")))?;
        Ok(())
    }

    pub fn ensure_workspace(
        &self,
        auth: &AuthContext,
        node_id: &str,
        display_name: &str,
    ) -> Result<WorkspaceRecord, ControlError> {
        let connection = self.connection()?;
        self.ensure_workspace_locked(&connection, auth, node_id, display_name)
    }

    pub fn register_workspace(
        &self,
        auth: &AuthContext,
        request: WorkspaceRegistration,
    ) -> Result<WorkspaceRecord, ControlError> {
        self.ensure_workspace(auth, &request.node_id, &request.display_name)
    }

    pub fn update_workspace(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
        request: WorkspaceUpdate,
    ) -> Result<WorkspaceRecord, ControlError> {
        let workspace_id = workspace_id.trim();
        if workspace_id.is_empty() {
            return Err(ControlError::bad_request(
                "INVALID_WORKSPACE",
                "工作环境 ID 不能为空",
            ));
        }
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM workspaces WHERE id = ?1",
                params![workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| format!("workspace update lookup: {error}"))
            .map_err(ControlError::internal)?;
        let Some(owner) = owner else {
            return Err(ControlError::not_found(
                "WORKSPACE_NOT_FOUND",
                "工作环境不存在",
            ));
        };
        if owner != auth.user_id {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "只有工作环境 owner 可以修改名称",
            ));
        }
        let current = connection
            .query_row(
                "SELECT display_name FROM workspaces WHERE id = ?1",
                params![workspace_id],
                |row| row.get::<_, String>(0),
            )
            .map_err(|error| ControlError::internal(format!("workspace update read: {error}")))?;
        let display_name = request
            .display_name
            .map(|value| value.trim().chars().take(128).collect::<String>())
            .filter(|value| !value.is_empty())
            .unwrap_or(current);
        connection
            .execute(
                "UPDATE workspaces SET display_name = ?1 WHERE id = ?2",
                params![display_name, workspace_id],
            )
            .map_err(|error| ControlError::internal(format!("workspace update: {error}")))?;
        self.workspace_record_locked(&connection, auth, workspace_id, &HashSet::new())
    }

    pub fn list_workspaces(
        &self,
        auth: &AuthContext,
        online_nodes: &HashSet<String>,
    ) -> Result<Vec<WorkspaceRecord>, ControlError> {
        let connection = self.connection()?;
        let mut statement = connection.prepare("SELECT id FROM workspaces WHERE owner_user_id = ?1 UNION SELECT workspace_id FROM workspace_grants WHERE grantee_user_id = ?1 AND revoked_at_ms IS NULL ORDER BY id").map_err(|error| ControlError::internal(format!("workspace list: {error}")))?;
        let ids = statement
            .query_map(params![auth.user_id], |row| row.get::<_, String>(0))
            .map_err(|error| ControlError::internal(format!("workspace list: {error}")))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| ControlError::internal(format!("workspace list: {error}")))?;
        ids.iter()
            .map(|id| self.workspace_record_locked(&connection, auth, id, online_nodes))
            .collect()
    }

    pub fn workspace_access(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
    ) -> Result<(WorkspaceRecord, String), ControlError> {
        let connection = self.connection()?;
        let online_nodes = HashSet::new();
        let record =
            self.workspace_record_locked(&connection, auth, workspace_id, &online_nodes)?;
        Ok((record.clone(), record.host_node_id))
    }

    pub fn create_ticket(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
        online: bool,
    ) -> Result<ConnectionTicket, ControlError> {
        let connection = self.connection()?;
        let (record, target_host_node_id) =
            self.workspace_access_locked(&connection, auth, workspace_id)?;
        if !online {
            return Err(ControlError::unavailable(
                "WORKSPACE_OFFLINE",
                "目标工作环境当前离线",
            ));
        }
        let source_node_id = auth.node_id.clone().ok_or_else(|| {
            ControlError::bad_request("NODE_REQUIRED", "当前账号会话尚未绑定 Node")
        })?;
        if node_revoked(&connection, &source_node_id)? {
            return Err(ControlError::forbidden("NODE_REVOKED", "当前设备已被撤销"));
        }
        let source_owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1",
                params![source_node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("ticket source lookup: {error}")))?;
        if source_owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "当前设备不属于当前账号",
            ));
        }
        let ticket =
            random_token(32).map_err(|error| ControlError::internal(format!("ticket: {error}")))?;
        let expires_at_ms = now_ms().saturating_add(TICKET_TTL_MS);
        connection.execute("INSERT INTO connection_tickets (token_hash, source_user_id, source_node_id, workspace_id, target_host_node_id, expires_at_ms, used_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL)", params![hash_token(&ticket), auth.user_id, source_node_id, record.workspace_id, target_host_node_id, expires_at_ms]).map_err(|error| ControlError::internal(format!("ticket create: {error}")))?;
        Ok(ConnectionTicket {
            ticket,
            workspace_id: record.workspace_id,
            source_node_id,
            target_host_node_id,
            expires_at_ms,
        })
    }

    pub fn consume_ticket(
        &self,
        ticket: &str,
        source_node_id: &str,
    ) -> Result<ConsumedTicket, ControlError> {
        let connection = self.connection()?;
        let row = connection.query_row("SELECT source_node_id, workspace_id, target_host_node_id, expires_at_ms, used_at_ms FROM connection_tickets WHERE token_hash = ?1", params![hash_token(ticket)], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, i64>(3)?, row.get::<_, Option<i64>>(4)?))).optional().map_err(|error| ControlError::internal(format!("ticket lookup: {error}")))?;
        let Some((bound_source, workspace_id, target_host_node_id, expires_at_ms, used_at_ms)) =
            row
        else {
            return Err(ControlError::unauthorized(
                "CONNECTION_TICKET_EXPIRED",
                "连接 Ticket 无效或已过期",
            ));
        };
        if bound_source != source_node_id {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "连接 Ticket 未绑定当前设备",
            ));
        }
        if used_at_ms.is_some() {
            return Err(ControlError::unauthorized(
                "CONNECTION_TICKET_USED",
                "连接 Ticket 已使用",
            ));
        }
        if expires_at_ms <= now_ms() {
            return Err(ControlError::unauthorized(
                "CONNECTION_TICKET_EXPIRED",
                "连接 Ticket 已过期",
            ));
        }
        let changed = connection.execute("UPDATE connection_tickets SET used_at_ms = ?1 WHERE token_hash = ?2 AND used_at_ms IS NULL", params![now_ms(), hash_token(ticket)]).map_err(|error| ControlError::internal(format!("ticket consume: {error}")))?;
        if changed != 1 {
            return Err(ControlError::unauthorized(
                "CONNECTION_TICKET_USED",
                "连接 Ticket 已使用",
            ));
        }
        Ok(ConsumedTicket {
            workspace_id,
            source_node_id: bound_source,
            target_host_node_id,
        })
    }

    /// Issue a short-lived, one-time ticket for the first account-backed
    /// pairing handshake.  The six-digit code remains inside the encrypted
    /// Noise payload; this ticket only authorizes the relay route and binds it
    /// to the authenticated mobile Node.
    pub fn create_pairing_ticket(
        &self,
        auth: &AuthContext,
        pairing_id: &str,
        target_host_node_id: &str,
        online: bool,
    ) -> Result<PairingTicket, ControlError> {
        let pairing_id = pairing_id.trim();
        let target_host_node_id = target_host_node_id.trim();
        if pairing_id.is_empty() || pairing_id.len() > 128 || target_host_node_id.is_empty() {
            return Err(ControlError::bad_request("INVALID_PAIRING", "配对目标无效"));
        }
        if !online {
            return Err(ControlError::unavailable(
                "PAIRING_OFFLINE",
                "目标电脑当前离线",
            ));
        }
        let source_node_id = auth.node_id.clone().ok_or_else(|| {
            ControlError::bad_request("NODE_REQUIRED", "当前账号会话尚未绑定 Node")
        })?;
        let connection = self.connection()?;
        if node_revoked(&connection, &source_node_id)? {
            return Err(ControlError::forbidden("NODE_REVOKED", "当前设备已被撤销"));
        }
        let source_owner = connection
            .query_row(
                "SELECT owner_user_id FROM nodes WHERE id = ?1",
                params![source_node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| {
                ControlError::internal(format!("pairing ticket source lookup: {error}"))
            })?;
        if source_owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "当前设备不属于当前账号",
            ));
        }
        let target_exists = connection
            .query_row(
                "SELECT 1 FROM nodes WHERE id = ?1 AND revoked_at_ms IS NULL",
                params![target_host_node_id],
                |row| row.get::<_, i64>(0),
            )
            .optional()
            .map_err(|error| {
                ControlError::internal(format!("pairing ticket target lookup: {error}"))
            })?
            .is_some();
        if !target_exists {
            return Err(ControlError::not_found(
                "NODE_NOT_FOUND",
                "目标电脑未注册或已撤销",
            ));
        }
        let ticket = random_token(32)
            .map_err(|error| ControlError::internal(format!("pairing ticket: {error}")))?;
        let expires_at_ms = now_ms().saturating_add(PAIRING_TICKET_TTL_MS);
        connection
            .execute(
                "INSERT INTO pairing_tickets (token_hash, source_user_id, source_node_id, pairing_id, target_host_node_id, expires_at_ms, used_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL)",
                params![
                    hash_token(&ticket),
                    auth.user_id,
                    source_node_id,
                    pairing_id,
                    target_host_node_id,
                    expires_at_ms
                ],
            )
            .map_err(|error| ControlError::internal(format!("pairing ticket create: {error}")))?;
        Ok(PairingTicket {
            ticket,
            pairing_id: pairing_id.to_string(),
            source_node_id,
            target_host_node_id: target_host_node_id.to_string(),
            expires_at_ms,
        })
    }

    pub fn consume_pairing_ticket(
        &self,
        ticket: &str,
        source_node_id: &str,
    ) -> Result<ConsumedPairingTicket, ControlError> {
        let connection = self.connection()?;
        let token_hash = hash_token(ticket);
        let row = connection
            .query_row(
                "SELECT source_node_id, pairing_id, target_host_node_id, expires_at_ms, used_at_ms FROM pairing_tickets WHERE token_hash = ?1",
                params![token_hash],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, i64>(3)?,
                        row.get::<_, Option<i64>>(4)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("pairing ticket lookup: {error}")))?;
        let Some((bound_source, pairing_id, target_host_node_id, expires_at_ms, used_at_ms)) = row
        else {
            return Err(ControlError::unauthorized(
                "PAIRING_TICKET_EXPIRED",
                "配对 Ticket 无效或已过期",
            ));
        };
        if bound_source != source_node_id {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "配对 Ticket 未绑定当前设备",
            ));
        }
        if used_at_ms.is_some() {
            return Err(ControlError::unauthorized(
                "PAIRING_TICKET_USED",
                "配对 Ticket 已使用",
            ));
        }
        if expires_at_ms <= now_ms() {
            return Err(ControlError::unauthorized(
                "PAIRING_TICKET_EXPIRED",
                "配对 Ticket 已过期",
            ));
        }
        let changed = connection
            .execute(
                "UPDATE pairing_tickets SET used_at_ms = ?1 WHERE token_hash = ?2 AND used_at_ms IS NULL",
                params![now_ms(), token_hash],
            )
            .map_err(|error| ControlError::internal(format!("pairing ticket consume: {error}")))?;
        if changed != 1 {
            return Err(ControlError::unauthorized(
                "PAIRING_TICKET_USED",
                "配对 Ticket 已使用",
            ));
        }
        Ok(ConsumedPairingTicket {
            pairing_id,
            source_node_id: bound_source,
            target_host_node_id,
        })
    }

    pub fn create_grant(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
        request: GrantRequest,
    ) -> Result<GrantRecord, ControlError> {
        if request.role != "access" {
            return Err(ControlError::bad_request(
                "INVALID_ROLE",
                "V1 仅支持 access 权限",
            ));
        }
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM workspaces WHERE id = ?1",
                params![workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("grant workspace lookup: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::not_found(
                "WORKSPACE_NOT_FOUND",
                "工作环境不存在",
            ));
        }
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "只有工作环境 owner 可以授权",
            ));
        }
        let username_normalized = normalize_username(&request.username)?.1;
        let grantee = connection.query_row("SELECT id, username FROM users WHERE username_normalized = ?1 AND disabled_at_ms IS NULL", params![username_normalized], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))).optional().map_err(|error| ControlError::internal(format!("grant user lookup: {error}")))?;
        let Some((grantee_user_id, grantee_username)) = grantee else {
            return Err(ControlError::not_found(
                "USER_NOT_FOUND",
                "被授权用户不存在",
            ));
        };
        if grantee_user_id == auth.user_id {
            return Err(ControlError::bad_request(
                "INVALID_GRANTEE",
                "不能授权给自己",
            ));
        }
        let now = now_ms();
        let grant_id = Uuid::new_v4().to_string();
        connection.execute("INSERT INTO workspace_grants (id, workspace_id, owner_user_id, grantee_user_id, role, created_at_ms, revoked_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL) ON CONFLICT(workspace_id, grantee_user_id) DO UPDATE SET role = excluded.role, revoked_at_ms = NULL", params![grant_id, workspace_id, auth.user_id, grantee_user_id, request.role, now]).map_err(|error| ControlError::internal(format!("grant create: {error}")))?;
        let id = connection.query_row("SELECT id FROM workspace_grants WHERE workspace_id = ?1 AND grantee_user_id = ?2 AND revoked_at_ms IS NULL", params![workspace_id, grantee_user_id], |row| row.get::<_, String>(0)).map_err(|error| ControlError::internal(format!("grant readback: {error}")))?;
        Ok(GrantRecord {
            grant_id: id,
            workspace_id: workspace_id.to_string(),
            owner_user_id: auth.user_id.clone(),
            grantee_user_id,
            grantee_username,
            role: "access".to_string(),
            created_at_ms: now,
            revoked_at_ms: None,
        })
    }

    pub fn list_grants(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
    ) -> Result<Vec<GrantRecord>, ControlError> {
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM workspaces WHERE id = ?1",
                params![workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("grant list workspace: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::not_found(
                "WORKSPACE_NOT_FOUND",
                "工作环境不存在",
            ));
        }
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "只有 owner 可以查看授权",
            ));
        }
        let mut statement = connection.prepare("SELECT g.id, g.owner_user_id, g.grantee_user_id, u.username, g.role, g.created_at_ms, g.revoked_at_ms FROM workspace_grants g JOIN users u ON u.id = g.grantee_user_id WHERE g.workspace_id = ?1 ORDER BY g.created_at_ms, g.id").map_err(|error| ControlError::internal(format!("grant list: {error}")))?;
        let records = statement
            .query_map(params![workspace_id], |row| {
                Ok(GrantRecord {
                    grant_id: row.get(0)?,
                    workspace_id: workspace_id.to_string(),
                    owner_user_id: row.get(1)?,
                    grantee_user_id: row.get(2)?,
                    grantee_username: row.get(3)?,
                    role: row.get(4)?,
                    created_at_ms: row.get(5)?,
                    revoked_at_ms: row.get(6)?,
                })
            })
            .map_err(|error| ControlError::internal(format!("grant list: {error}")))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| ControlError::internal(format!("grant list: {error}")))?;
        Ok(records)
    }

    pub fn revoke_grant(
        &self,
        auth: &AuthContext,
        workspace_id: &str,
        grant_id: &str,
    ) -> Result<(), ControlError> {
        let connection = self.connection()?;
        let owner = connection
            .query_row(
                "SELECT owner_user_id FROM workspaces WHERE id = ?1",
                params![workspace_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("grant revoke workspace: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::not_found(
                "WORKSPACE_NOT_FOUND",
                "工作环境不存在",
            ));
        }
        if owner.as_deref() != Some(auth.user_id.as_str()) {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "只有 owner 可以撤销授权",
            ));
        }
        let changed = connection.execute("UPDATE workspace_grants SET revoked_at_ms = ?1 WHERE id = ?2 AND workspace_id = ?3 AND revoked_at_ms IS NULL", params![now_ms(), grant_id, workspace_id]).map_err(|error| ControlError::internal(format!("grant revoke: {error}")))?;
        if changed == 0 {
            return Err(ControlError::not_found(
                "GRANT_NOT_FOUND",
                "授权不存在或已撤销",
            ));
        }
        Ok(())
    }

    fn connection(&self) -> Result<std::sync::MutexGuard<'_, Connection>, ControlError> {
        self.db
            .lock()
            .map_err(|_| ControlError::internal("database lock poisoned"))
    }

    fn ensure_workspace_locked(
        &self,
        connection: &Connection,
        auth: &AuthContext,
        node_id: &str,
        display_name: &str,
    ) -> Result<WorkspaceRecord, ControlError> {
        let owner = connection.query_row("SELECT owner_user_id FROM nodes WHERE id = ?1 AND owner_user_id = ?2 AND revoked_at_ms IS NULL", params![node_id, auth.user_id], |row| row.get::<_, String>(0)).optional().map_err(|error| ControlError::internal(format!("workspace node lookup: {error}")))?;
        if owner.is_none() {
            return Err(ControlError::forbidden(
                "ACCESS_DENIED",
                "Node 不属于当前账号或已撤销",
            ));
        }
        let existing = connection
            .query_row(
                "SELECT id FROM workspaces WHERE host_node_id = ?1",
                params![node_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| ControlError::internal(format!("workspace lookup: {error}")))?;
        let id = existing.unwrap_or_else(|| Uuid::new_v4().to_string());
        let name = if display_name.trim().is_empty() {
            format!("{} 的工作环境", node_id)
        } else {
            display_name.trim().chars().take(128).collect()
        };
        let now = now_ms();
        connection.execute("INSERT INTO workspaces (id, host_node_id, owner_user_id, display_name, created_at_ms) VALUES (?1, ?2, ?3, ?4, ?5) ON CONFLICT(host_node_id) DO UPDATE SET display_name = CASE WHEN excluded.display_name <> '' THEN excluded.display_name ELSE workspaces.display_name END", params![id, node_id, auth.user_id, name, now]).map_err(|error| ControlError::internal(format!("workspace register: {error}")))?;
        self.workspace_record_locked(connection, auth, &id, &HashSet::new())
    }

    fn workspace_access_locked(
        &self,
        connection: &Connection,
        auth: &AuthContext,
        workspace_id: &str,
    ) -> Result<(WorkspaceRecord, String), ControlError> {
        let record =
            self.workspace_record_locked(connection, auth, workspace_id, &HashSet::new())?;
        Ok((record.clone(), record.host_node_id.clone()))
    }

    fn workspace_record_locked(
        &self,
        connection: &Connection,
        auth: &AuthContext,
        workspace_id: &str,
        online_nodes: &HashSet<String>,
    ) -> Result<WorkspaceRecord, ControlError> {
        let row = connection.query_row("SELECT w.id, w.host_node_id, w.owner_user_id, w.display_name, w.created_at_ms, n.id, n.display_name, n.platform, n.public_key, n.capabilities_json, n.created_at_ms, n.last_seen_at_ms, n.revoked_at_ms FROM workspaces w JOIN nodes n ON n.id = w.host_node_id WHERE w.id = ?1", params![workspace_id], |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?, row.get::<_, String>(2)?, row.get::<_, String>(3)?, row.get::<_, i64>(4)?, NodeRecord { node_id: row.get(5)?, display_name: row.get(6)?, platform: row.get(7)?, public_key: row.get(8)?, capabilities: parse_capabilities(&row.get::<_, String>(9)?), created_at_ms: row.get(10)?, last_seen_at_ms: row.get(11)?, revoked_at_ms: row.get(12)? }))).optional().map_err(|error| ControlError::internal(format!("workspace read: {error}")))?;
        let Some((id, host_node_id, owner_user_id, display_name, created_at_ms, host)) = row else {
            return Err(ControlError::not_found(
                "WORKSPACE_NOT_FOUND",
                "工作环境不存在",
            ));
        };
        let role = if owner_user_id == auth.user_id {
            "owner".to_string()
        } else {
            let allowed = connection.query_row("SELECT role FROM workspace_grants WHERE workspace_id = ?1 AND grantee_user_id = ?2 AND revoked_at_ms IS NULL", params![workspace_id, auth.user_id], |row| row.get::<_, String>(0)).optional().map_err(|error| ControlError::internal(format!("workspace access: {error}")))?;
            allowed.ok_or_else(|| {
                ControlError::forbidden("ACCESS_DENIED", "当前账号没有访问该工作环境的权限")
            })?
        };
        let online = online_nodes.contains(&host_node_id) && host.revoked_at_ms.is_none();
        Ok(WorkspaceRecord {
            workspace_id: id,
            host_node_id,
            owner_user_id,
            display_name,
            online,
            host: Some(host),
            role,
            created_at_ms,
        })
    }
}

fn migrate(connection: &Connection) -> Result<(), ControlError> {
    connection.execute_batch(
        "CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
         CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at_ms INTEGER NOT NULL);
         CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL, username_normalized TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at_ms INTEGER NOT NULL, disabled_at_ms INTEGER);
         CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, owner_user_id TEXT REFERENCES users(id), display_name TEXT NOT NULL, platform TEXT NOT NULL, public_key TEXT NOT NULL, capabilities_json TEXT NOT NULL, created_at_ms INTEGER NOT NULL, last_seen_at_ms INTEGER, revoked_at_ms INTEGER);
         CREATE INDEX IF NOT EXISTS idx_nodes_owner ON nodes(owner_user_id);
         CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, host_node_id TEXT NOT NULL UNIQUE REFERENCES nodes(id), owner_user_id TEXT NOT NULL REFERENCES users(id), display_name TEXT NOT NULL, created_at_ms INTEGER NOT NULL);
         CREATE TABLE IF NOT EXISTS workspace_grants (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), owner_user_id TEXT NOT NULL REFERENCES users(id), grantee_user_id TEXT NOT NULL REFERENCES users(id), role TEXT NOT NULL, created_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER, UNIQUE(workspace_id, grantee_user_id));
         CREATE INDEX IF NOT EXISTS idx_workspace_grants_grantee ON workspace_grants(grantee_user_id, revoked_at_ms);
         CREATE TABLE IF NOT EXISTS access_tokens (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), node_id TEXT REFERENCES nodes(id), expires_at_ms INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER);
         CREATE INDEX IF NOT EXISTS idx_access_tokens_user ON access_tokens(user_id);
         CREATE TABLE IF NOT EXISTS refresh_tokens (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), node_id TEXT REFERENCES nodes(id), expires_at_ms INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, revoked_at_ms INTEGER);
         CREATE TABLE IF NOT EXISTS connection_tickets (token_hash TEXT PRIMARY KEY, source_user_id TEXT NOT NULL REFERENCES users(id), source_node_id TEXT NOT NULL REFERENCES nodes(id), workspace_id TEXT NOT NULL REFERENCES workspaces(id), target_host_node_id TEXT NOT NULL REFERENCES nodes(id), expires_at_ms INTEGER NOT NULL, used_at_ms INTEGER);
         CREATE INDEX IF NOT EXISTS idx_tickets_expiry ON connection_tickets(expires_at_ms, used_at_ms);
         CREATE TABLE IF NOT EXISTS pairing_tickets (token_hash TEXT PRIMARY KEY, source_user_id TEXT NOT NULL REFERENCES users(id), source_node_id TEXT NOT NULL REFERENCES nodes(id), pairing_id TEXT NOT NULL, target_host_node_id TEXT NOT NULL REFERENCES nodes(id), expires_at_ms INTEGER NOT NULL, used_at_ms INTEGER);
         CREATE INDEX IF NOT EXISTS idx_pairing_tickets_expiry ON pairing_tickets(expires_at_ms, used_at_ms);",
    ).map_err(|error| ControlError::internal(format!("database migration: {error}")))?;
    connection
        .execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at_ms) VALUES (1, ?1)",
            params![now_ms()],
        )
        .map_err(|error| ControlError::internal(format!("migration version: {error}")))?;
    Ok(())
}

fn config_value(connection: &Connection, key: &str) -> Result<Option<String>, ControlError> {
    connection
        .query_row(
            "SELECT value FROM server_config WHERE key = ?1",
            params![key],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| ControlError::internal(format!("server config: {error}")))
}

fn set_config_value(connection: &Connection, key: &str, value: &str) -> Result<(), ControlError> {
    connection.execute("INSERT INTO server_config (key, value) VALUES (?1, ?2) ON CONFLICT(key) DO UPDATE SET value = excluded.value", params![key, value]).map_err(|error| ControlError::internal(format!("server config write: {error}")))?;
    Ok(())
}

fn issue_tokens(
    connection: &Connection,
    server_id: &str,
    user_id: &str,
    node_id: Option<&str>,
) -> Result<AuthTokens, ControlError> {
    let access_token = random_token(32)
        .map_err(|error| ControlError::internal(format!("access token: {error}")))?;
    let refresh_token = random_token(48)
        .map_err(|error| ControlError::internal(format!("refresh token: {error}")))?;
    let now = now_ms();
    let access_expires_at_ms = now.saturating_add(ACCESS_TTL_MS);
    let refresh_expires_at_ms = now.saturating_add(REFRESH_TTL_MS);
    connection.execute("INSERT INTO access_tokens (token_hash, user_id, node_id, expires_at_ms, created_at_ms, revoked_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, NULL)", params![hash_token(&access_token), user_id, node_id, access_expires_at_ms, now]).map_err(|error| ControlError::internal(format!("access token write: {error}")))?;
    connection.execute("INSERT INTO refresh_tokens (token_hash, user_id, node_id, expires_at_ms, created_at_ms, revoked_at_ms) VALUES (?1, ?2, ?3, ?4, ?5, NULL)", params![hash_token(&refresh_token), user_id, node_id, refresh_expires_at_ms, now]).map_err(|error| ControlError::internal(format!("refresh token write: {error}")))?;
    Ok(AuthTokens {
        server_id: server_id.to_string(),
        access_token,
        refresh_token,
        access_expires_at_ms,
        refresh_expires_at_ms,
    })
}

fn normalize_username(value: &str) -> Result<(String, String), ControlError> {
    let display = value.trim();
    let char_count = display.chars().count();
    if !(3..=32).contains(&char_count)
        || !display
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.'))
    {
        return Err(ControlError::bad_request(
            "INVALID_USERNAME",
            "用户名需为 3-32 位字母、数字、下划线、短横线或点号",
        ));
    }
    Ok((display.to_string(), display.to_ascii_lowercase()))
}

fn validate_password(value: &str) -> Result<(), ControlError> {
    if value.chars().count() < 8 || value.len() > 256 {
        return Err(ControlError::bad_request(
            "WEAK_PASSWORD",
            "密码至少需要 8 位",
        ));
    }
    Ok(())
}

fn hash_password(password: &str) -> Result<String, ControlError> {
    let mut salt = [0_u8; 16];
    fill_random(&mut salt)
        .map_err(|error| ControlError::internal(format!("password salt: {error}")))?;
    let salt = SaltString::encode_b64(&salt)
        .map_err(|error| ControlError::internal(format!("password salt: {error}")))?;
    Argon2::default()
        .hash_password(password.as_bytes(), &salt)
        .map(|hash| hash.to_string())
        .map_err(|error| ControlError::internal(format!("password hash: {error}")))
}

fn verify_password(encoded: &str, password: &str) -> bool {
    PasswordHash::new(encoded).ok().is_some_and(|hash| {
        Argon2::default()
            .verify_password(password.as_bytes(), &hash)
            .is_ok()
    })
}

fn random_token(size: usize) -> Result<String, String> {
    let mut bytes = vec![0_u8; size];
    fill_random(&mut bytes).map_err(|error| error.to_string())?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

fn hash_token(value: &str) -> String {
    hex::encode(Sha256::digest(value.as_bytes()))
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn user_enabled(connection: &Connection, user_id: &str) -> Result<bool, ControlError> {
    connection
        .query_row(
            "SELECT disabled_at_ms IS NULL FROM users WHERE id = ?1",
            params![user_id],
            |row| row.get::<_, bool>(0),
        )
        .optional()
        .map_err(|error| ControlError::internal(format!("user status: {error}")))
        .map(|value| value.unwrap_or(false))
}

fn node_revoked(connection: &Connection, node_id: &str) -> Result<bool, ControlError> {
    connection
        .query_row(
            "SELECT revoked_at_ms IS NOT NULL FROM nodes WHERE id = ?1",
            params![node_id],
            |row| row.get::<_, bool>(0),
        )
        .optional()
        .map_err(|error| ControlError::internal(format!("node status: {error}")))
        .map(|value| value.unwrap_or(true))
}

fn node_count(connection: &Connection, user_id: &str, platform: &str) -> Result<i64, ControlError> {
    let mobile = is_mobile_platform(platform);
    connection.query_row("SELECT COUNT(*) FROM nodes WHERE owner_user_id = ?1 AND revoked_at_ms IS NULL AND platform LIKE ?2", params![user_id, if mobile { "%mobile%" } else { "%desktop%" }], |row| row.get::<_, i64>(0)).map_err(|error| ControlError::internal(format!("node count: {error}")))
}

fn node_limit(platform: &str) -> i64 {
    if is_mobile_platform(platform) {
        MOBILE_NODE_LIMIT
    } else {
        DESKTOP_NODE_LIMIT
    }
}

fn is_mobile_platform(platform: &str) -> bool {
    let value = platform.to_ascii_lowercase();
    value.contains("mobile")
        || value.contains("android")
        || value.contains("ios")
        || value.contains("tablet")
}

fn is_desktop_platform(platform: &str) -> bool {
    matches!(
        platform.to_ascii_lowercase().as_str(),
        "desktop" | "windows" | "macos" | "linux" | "darwin"
    )
}

fn is_host_capable(capabilities: &[String]) -> bool {
    capabilities
        .iter()
        .any(|value| value == "workspace_host" || value == "agent_runtime")
}

fn normalize_capabilities(values: &[String]) -> Vec<String> {
    let allowed = [
        "workspace_client",
        "workspace_host",
        "local_cache",
        "filesystem",
        "terminal",
        "agent_runtime",
        "mobile_agent_runtime",
    ];
    let mut result = Vec::new();
    for value in values {
        let value = value.trim();
        if allowed.contains(&value) && !result.iter().any(|item| item == value) {
            result.push(value.to_string());
        }
    }
    result
}

fn parse_capabilities(value: &str) -> Vec<String> {
    serde_json::from_str(value).unwrap_or_default()
}

fn node_record(connection: &Connection, node_id: &str) -> Result<Option<NodeRecord>, ControlError> {
    connection.query_row("SELECT id, display_name, platform, public_key, capabilities_json, created_at_ms, last_seen_at_ms, revoked_at_ms FROM nodes WHERE id = ?1", params![node_id], |row| Ok(NodeRecord { node_id: row.get(0)?, display_name: row.get(1)?, platform: row.get(2)?, public_key: row.get(3)?, capabilities: parse_capabilities(&row.get::<_, String>(4)?), created_at_ms: row.get(5)?, last_seen_at_ms: row.get(6)?, revoked_at_ms: row.get(7)? })).optional().map_err(|error| ControlError::internal(format!("node read: {error}")))
}

fn default_access_role() -> String {
    "access".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_plane() -> ControlPlane {
        let path = std::env::temp_dir().join(format!("lamtools-control-{}.db", Uuid::new_v4()));
        ControlPlane::open(path).expect("control plane")
    }

    #[test]
    fn server_identity_and_auth_survive_reopen() {
        let path = std::env::temp_dir().join(format!("lamtools-control-{}.db", Uuid::new_v4()));
        let first = ControlPlane::open(&path).expect("first");
        let tokens = first
            .register("Alice", "correct horse battery")
            .expect("register");
        let server_id = first.server_id().to_string();
        assert_eq!(
            first
                .authenticate(&tokens.access_token)
                .expect("auth")
                .user_id
                .len(),
            36
        );
        drop(first);
        let second = ControlPlane::open(&path).expect("second");
        assert_eq!(second.server_id(), server_id);
        assert!(second.authenticate(&tokens.access_token).is_ok());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn ticket_is_bound_to_source_and_single_use() {
        let plane = test_plane();
        let owner_tokens = plane
            .register("owner", "correct horse battery")
            .expect("owner");
        let owner = plane
            .authenticate(&owner_tokens.access_token)
            .expect("owner auth");
        let host = plane
            .register_node(
                &owner,
                NodeRegistration {
                    node_id: "desktop-1".into(),
                    public_key: "host-key".into(),
                    display_name: "Desktop".into(),
                    platform: "desktop".into(),
                    capabilities: vec!["workspace_host".into()],
                },
            )
            .expect("host");
        let owner_tokens = plane
            .bind_node_session(&owner_tokens.access_token, &host.node.node_id)
            .expect("bind owner node");
        let owner = plane
            .authenticate(&owner_tokens.access_token)
            .expect("bound owner auth");
        let mobile_tokens = plane
            .register("mobile", "correct horse battery")
            .expect("mobile");
        let mobile_user = plane
            .authenticate(&mobile_tokens.access_token)
            .expect("mobile auth");
        let mobile = plane
            .register_node(
                &mobile_user,
                NodeRegistration {
                    node_id: "mobile-1".into(),
                    public_key: "mobile-key".into(),
                    display_name: "Phone".into(),
                    platform: "mobile".into(),
                    capabilities: vec!["workspace_client".into()],
                },
            )
            .expect("mobile");
        let workspace_id = host.workspace.expect("workspace").workspace_id;
        let ticket = plane
            .create_ticket(&owner, &workspace_id, true)
            .expect("ticket");
        assert!(plane
            .consume_ticket(&ticket.ticket, &mobile.node.node_id)
            .is_err());
        // A ticket is bound to the authenticated source Node used to issue it.
        let source_ticket = plane
            .create_ticket(&owner, &workspace_id, true)
            .expect("source ticket");
        assert!(plane
            .consume_ticket(
                &source_ticket.ticket,
                &owner.node_id.clone().unwrap_or_default()
            )
            .is_ok());
        assert!(plane
            .consume_ticket(
                &source_ticket.ticket,
                &owner.node_id.clone().unwrap_or_default()
            )
            .is_err());
    }

    #[test]
    fn browser_mobile_nodes_do_not_create_workspaces() {
        let plane = test_plane();
        let account = plane
            .register("mobile-web", "correct horse battery")
            .expect("account");
        let auth = plane.authenticate(&account.access_token).expect("auth");
        let result = plane
            .register_node(
                &auth,
                NodeRegistration {
                    node_id: "mobile-web-node".into(),
                    public_key: "mobile-web-key".into(),
                    display_name: "Browser Mobile".into(),
                    platform: "mobile-web".into(),
                    capabilities: vec!["workspace_client".into(), "local_cache".into()],
                },
            )
            .expect("mobile node");
        assert!(result.workspace.is_none());
    }
}
