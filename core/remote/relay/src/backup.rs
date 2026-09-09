//! Consistent backup and verification for the relay control database.
//!
//! The relay database may be in WAL mode and can be written while the server
//! is running.  A byte-for-byte copy of `lamtools.db` is therefore not a
//! valid backup: recent committed pages may still be in `-wal`.  This module
//! uses SQLite's online backup API to read a consistent snapshot, then moves
//! the completed snapshot into place.

use std::{
    fs::{self, File, OpenOptions},
    io::Read,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use rusqlite::{backup::Backup, Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const CLI_USAGE: &str = r#"LamTools Relay

运行服务器（默认）：
  lamtools-relay

一致性备份：
  lamtools-relay backup --database /data/lamtools.db --output /data/backups
  lamtools-relay backup --database /data/lamtools.db --output /data/backups --force

备份校验：
  lamtools-relay verify --backup /data/backups
  lamtools-relay verify --database /data/lamtools.db

backup 输出目录包含 lamtools.db 和 manifest.json。备份使用 SQLite
online backup API，不直接复制 WAL 数据库。"#;

const BACKUP_FILE_NAME: &str = "lamtools.db";
const MANIFEST_FILE_NAME: &str = "manifest.json";
const BACKUP_FORMAT_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct BackupManifest {
    pub format_version: u32,
    pub created_at_ms: i64,
    pub database_file: String,
    pub server_id: String,
    pub schema_version: i64,
    pub database_size_bytes: u64,
    pub database_sha256: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DatabaseMetadata {
    pub server_id: String,
    pub schema_version: i64,
    pub size_bytes: u64,
    pub sha256: String,
}

pub fn create_backup(
    source_path: impl AsRef<Path>,
    output_dir: impl AsRef<Path>,
    overwrite: bool,
) -> Result<BackupManifest, String> {
    let source_path = source_path.as_ref();
    let output_dir = output_dir.as_ref();
    let source_path = fs::canonicalize(source_path)
        .map_err(|error| format!("open source database {}: {error}", source_path.display()))?;
    if !source_path.is_file() {
        return Err(format!(
            "source database is not a file: {}",
            source_path.display()
        ));
    }

    fs::create_dir_all(output_dir)
        .map_err(|error| format!("create backup directory {}: {error}", output_dir.display()))?;
    let output_dir = fs::canonicalize(output_dir)
        .map_err(|error| format!("resolve backup directory {}: {error}", output_dir.display()))?;
    let destination_path = output_dir.join(BACKUP_FILE_NAME);
    let manifest_path = output_dir.join(MANIFEST_FILE_NAME);
    if !overwrite && (destination_path.exists() || manifest_path.exists()) {
        return Err(format!(
            "backup already exists in {}; pass --force to replace it",
            output_dir.display()
        ));
    }
    if source_path == destination_path {
        return Err("source database and backup database must be different files".to_string());
    }

    let temporary_path = create_unique_file(&output_dir, "lamtools.db")?;
    let result = create_backup_snapshot(&source_path, &temporary_path).and_then(|metadata| {
        replace_file(&temporary_path, &destination_path, overwrite)?;
        let manifest = BackupManifest {
            format_version: BACKUP_FORMAT_VERSION,
            created_at_ms: now_ms(),
            database_file: BACKUP_FILE_NAME.to_string(),
            server_id: metadata.server_id,
            schema_version: metadata.schema_version,
            database_size_bytes: metadata.size_bytes,
            database_sha256: metadata.sha256,
        };
        write_manifest(&manifest_path, &manifest, overwrite)?;
        Ok(manifest)
    });
    if result.is_err() {
        let _ = fs::remove_file(&temporary_path);
    }
    result
}

pub fn verify_database(path: impl AsRef<Path>) -> Result<DatabaseMetadata, String> {
    let path = path.as_ref();
    let metadata = fs::metadata(path)
        .map_err(|error| format!("read database metadata {}: {error}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!("database is not a file: {}", path.display()));
    }
    let connection = open_read_only(path)?;
    verify_integrity(&connection)?;
    let (server_id, schema_version) = read_database_identity(&connection)?;
    drop(connection);
    Ok(DatabaseMetadata {
        server_id,
        schema_version,
        size_bytes: metadata.len(),
        sha256: sha256_file(path)?,
    })
}

pub fn verify_backup(output_dir: impl AsRef<Path>) -> Result<BackupManifest, String> {
    let output_dir = output_dir.as_ref();
    let manifest_path = output_dir.join(MANIFEST_FILE_NAME);
    let manifest_bytes = fs::read(&manifest_path)
        .map_err(|error| format!("read backup manifest {}: {error}", manifest_path.display()))?;
    let manifest: BackupManifest = serde_json::from_slice(&manifest_bytes)
        .map_err(|error| format!("parse backup manifest {}: {error}", manifest_path.display()))?;
    if manifest.format_version != BACKUP_FORMAT_VERSION {
        return Err(format!(
            "unsupported backup format version: {}",
            manifest.format_version
        ));
    }
    if manifest.database_file != BACKUP_FILE_NAME
        || Path::new(&manifest.database_file).components().count() != 1
    {
        return Err("backup manifest points outside its directory".to_string());
    }
    let database_path = output_dir.join(&manifest.database_file);
    let metadata = verify_database(&database_path)?;
    if manifest.server_id != metadata.server_id {
        return Err("backup manifest server_id does not match the database".to_string());
    }
    if manifest.schema_version != metadata.schema_version {
        return Err("backup manifest schema_version does not match the database".to_string());
    }
    if manifest.database_size_bytes != metadata.size_bytes {
        return Err("backup manifest database size does not match the database".to_string());
    }
    if manifest.database_sha256 != metadata.sha256 {
        return Err("backup manifest database hash does not match the database".to_string());
    }
    Ok(manifest)
}

pub fn run_backup_cli(arguments: Vec<String>) -> Result<(), String> {
    let options = parse_backup_options(&arguments)?;
    if options.help {
        println!("{CLI_USAGE}");
        return Ok(());
    }
    let database = options
        .database
        .ok_or_else(|| "backup requires --database <path>".to_string())?;
    let output = options
        .output
        .ok_or_else(|| "backup requires --output <directory>".to_string())?;
    let manifest = create_backup(database, output, options.force)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&manifest)
            .map_err(|error| format!("serialize backup result: {error}"))?
    );
    Ok(())
}

pub fn run_verify_cli(arguments: Vec<String>) -> Result<(), String> {
    let options = parse_verify_options(&arguments)?;
    if options.help {
        println!("{CLI_USAGE}");
        return Ok(());
    }
    match (options.backup, options.database) {
        (Some(backup), None) => {
            let manifest = verify_backup(backup)?;
            println!(
                "{}",
                serde_json::to_string_pretty(&manifest)
                    .map_err(|error| format!("serialize verify result: {error}"))?
            );
        }
        (None, Some(database)) => {
            let metadata = verify_database(database)?;
            println!(
                "{}",
                serde_json::json!({
                    "serverId": metadata.server_id,
                    "schemaVersion": metadata.schema_version,
                    "databaseSizeBytes": metadata.size_bytes,
                    "databaseSha256": metadata.sha256,
                })
            );
        }
        (Some(_), Some(_)) => {
            return Err("verify accepts exactly one of --backup or --database".to_string());
        }
        (None, None) => {
            return Err("verify requires --backup <directory> or --database <path>".to_string())
        }
    }
    Ok(())
}

struct BackupOptions {
    database: Option<PathBuf>,
    output: Option<PathBuf>,
    force: bool,
    help: bool,
}

struct VerifyOptions {
    backup: Option<PathBuf>,
    database: Option<PathBuf>,
    help: bool,
}

fn parse_backup_options(arguments: &[String]) -> Result<BackupOptions, String> {
    let mut options = BackupOptions {
        database: None,
        output: None,
        force: false,
        help: false,
    };
    let mut index = 0;
    while index < arguments.len() {
        match arguments[index].as_str() {
            "--database" | "-d" => {
                options.database = Some(next_path(arguments, &mut index, "--database")?);
            }
            "--output" | "-o" => {
                options.output = Some(next_path(arguments, &mut index, "--output")?);
            }
            "--force" => options.force = true,
            "--help" | "-h" => options.help = true,
            value => return Err(format!("unknown backup option: {value}")),
        }
        index += 1;
    }
    Ok(options)
}

fn parse_verify_options(arguments: &[String]) -> Result<VerifyOptions, String> {
    let mut options = VerifyOptions {
        backup: None,
        database: None,
        help: false,
    };
    let mut index = 0;
    while index < arguments.len() {
        match arguments[index].as_str() {
            "--backup" | "-b" => {
                options.backup = Some(next_path(arguments, &mut index, "--backup")?);
            }
            "--database" | "-d" => {
                options.database = Some(next_path(arguments, &mut index, "--database")?);
            }
            "--help" | "-h" => options.help = true,
            value => return Err(format!("unknown verify option: {value}")),
        }
        index += 1;
    }
    Ok(options)
}

fn next_path(arguments: &[String], index: &mut usize, option: &str) -> Result<PathBuf, String> {
    *index += 1;
    arguments
        .get(*index)
        .filter(|value| !value.starts_with('-'))
        .map(PathBuf::from)
        .ok_or_else(|| format!("{option} requires a path"))
}

fn create_backup_snapshot(
    source_path: &Path,
    temporary_path: &Path,
) -> Result<DatabaseMetadata, String> {
    let source = open_read_only(source_path)?;
    let source_identity = read_database_identity(&source)?;
    let mut destination = Connection::open(temporary_path).map_err(|error| {
        format!(
            "open temporary backup {}: {error}",
            temporary_path.display()
        )
    })?;
    destination
        .busy_timeout(Duration::from_secs(5))
        .map_err(|error| format!("set backup busy timeout: {error}"))?;
    destination
        .pragma_update(None, "journal_mode", "DELETE")
        .map_err(|error| format!("set backup journal mode: {error}"))?;
    destination
        .pragma_update(None, "foreign_keys", "ON")
        .map_err(|error| format!("set backup foreign keys: {error}"))?;
    {
        let backup = Backup::new(&source, &mut destination)
            .map_err(|error| format!("start SQLite online backup: {error}"))?;
        backup
            .run_to_completion(128, Duration::from_millis(10), None)
            .map_err(|error| format!("copy SQLite online backup: {error}"))?;
    }
    verify_integrity(&destination)?;
    drop(destination);
    let metadata = fs::metadata(temporary_path)
        .map_err(|error| format!("read temporary backup metadata: {error}"))?;
    Ok(DatabaseMetadata {
        server_id: source_identity.0,
        schema_version: source_identity.1,
        size_bytes: metadata.len(),
        sha256: sha256_file(temporary_path)?,
    })
}

fn open_read_only(path: &Path) -> Result<Connection, String> {
    let connection = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|error| format!("open read-only database {}: {error}", path.display()))?;
    connection
        .busy_timeout(Duration::from_secs(5))
        .map_err(|error| format!("set source busy timeout: {error}"))?;
    Ok(connection)
}

fn read_database_identity(connection: &Connection) -> Result<(String, i64), String> {
    let server_id = connection
        .query_row(
            "SELECT value FROM server_config WHERE key = 'server_id'",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| format!("read server identity: {error}"))?
        .ok_or_else(|| "database does not contain a server_id".to_string())?;
    let schema_version = connection
        .query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
            [],
            |row| row.get::<_, i64>(0),
        )
        .optional()
        .map_err(|error| format!("read schema version: {error}"))?
        .unwrap_or(0);
    Ok((server_id, schema_version))
}

fn verify_integrity(connection: &Connection) -> Result<(), String> {
    let result = connection
        .query_row("PRAGMA integrity_check", [], |row| row.get::<_, String>(0))
        .map_err(|error| format!("SQLite integrity check: {error}"))?;
    if result.eq_ignore_ascii_case("ok") {
        Ok(())
    } else {
        Err(format!("SQLite integrity check failed: {result}"))
    }
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file =
        File::open(path).map_err(|error| format!("hash database {}: {error}", path.display()))?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("read database {}: {error}", path.display()))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}

fn create_unique_file(directory: &Path, stem: &str) -> Result<PathBuf, String> {
    let now = now_ms();
    for attempt in 0..100_u32 {
        let path = directory.join(format!(
            ".{stem}.tmp-{}-{now}-{attempt}",
            std::process::id()
        ));
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(_) => return Ok(path),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "create temporary backup {}: {error}",
                    path.display()
                ))
            }
        }
    }
    Err("could not allocate a unique temporary backup path".to_string())
}

fn replace_file(source: &Path, destination: &Path, overwrite: bool) -> Result<(), String> {
    if destination.exists() {
        if !overwrite {
            return Err(format!(
                "backup destination already exists: {}",
                destination.display()
            ));
        }
        fs::remove_file(destination).map_err(|error| {
            format!("replace existing backup {}: {error}", destination.display())
        })?;
    }
    fs::rename(source, destination)
        .map_err(|error| format!("publish backup {}: {error}", destination.display()))
}

fn write_manifest(path: &Path, manifest: &BackupManifest, overwrite: bool) -> Result<(), String> {
    let temporary_path = create_unique_file(
        path.parent()
            .ok_or_else(|| "manifest has no parent directory".to_string())?,
        "manifest.json",
    )?;
    let result = (|| {
        let bytes = serde_json::to_vec_pretty(manifest)
            .map_err(|error| format!("serialize backup manifest: {error}"))?;
        fs::write(&temporary_path, bytes)
            .map_err(|error| format!("write temporary backup manifest: {error}"))?;
        if path.exists() {
            if !overwrite {
                return Err(format!(
                    "backup manifest already exists: {}",
                    path.display()
                ));
            }
            fs::remove_file(path)
                .map_err(|error| format!("replace existing backup manifest: {error}"))?;
        }
        fs::rename(&temporary_path, path)
            .map_err(|error| format!("publish backup manifest {}: {error}", path.display()))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary_path);
    }
    result
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

#[cfg(test)]
mod tests {
    use super::{create_backup, verify_backup, verify_database};
    use rusqlite::Connection;
    use std::{fs, path::PathBuf};
    use uuid::Uuid;

    fn test_directory() -> PathBuf {
        let path = std::env::temp_dir().join(format!("lamtools-relay-backup-{}", Uuid::new_v4()));
        fs::create_dir(&path).expect("test directory");
        path
    }

    #[test]
    fn online_backup_copies_wal_snapshot_and_identity() {
        let directory = test_directory();
        let source_path = directory.join("lamtools.db");
        let source = Connection::open(&source_path).expect("source");
        source
            .pragma_update(None, "journal_mode", "WAL")
            .expect("WAL");
        source
            .execute_batch(
                "CREATE TABLE server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                 INSERT INTO server_config VALUES ('server_id', 'server-test');
                 CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_ms INTEGER NOT NULL);
                 INSERT INTO schema_migrations VALUES (7, 1);
                 CREATE TABLE payload (value TEXT NOT NULL);
                 INSERT INTO payload VALUES ('committed in WAL');",
            )
            .expect("schema");

        let output_dir = directory.join("backup");
        let manifest = create_backup(&source_path, &output_dir, false).expect("backup");
        assert_eq!(manifest.server_id, "server-test");
        assert_eq!(manifest.schema_version, 7);
        assert_eq!(verify_backup(&output_dir).expect("verify"), manifest);
        let backup = Connection::open(output_dir.join("lamtools.db")).expect("backup db");
        let value: String = backup
            .query_row("SELECT value FROM payload", [], |row| row.get(0))
            .expect("payload");
        assert_eq!(value, "committed in WAL");
        drop(backup);
        drop(source);
        fs::remove_dir_all(directory).expect("cleanup");
    }

    #[test]
    fn verify_database_rejects_corrupted_copy() {
        let directory = test_directory();
        let source_path = directory.join("lamtools.db");
        let source = Connection::open(&source_path).expect("source");
        source
            .execute_batch(
                "CREATE TABLE server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                 INSERT INTO server_config VALUES ('server_id', 'server-test');
                 CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_ms INTEGER NOT NULL);
                 INSERT INTO schema_migrations VALUES (1, 1);",
            )
            .expect("schema");
        drop(source);
        let output_dir = directory.join("backup");
        create_backup(&source_path, &output_dir, false).expect("backup");
        fs::write(output_dir.join("lamtools.db"), b"not a sqlite database").expect("tamper");
        assert!(verify_backup(&output_dir).is_err());
        assert!(verify_database(output_dir.join("lamtools.db")).is_err());
        fs::remove_dir_all(directory).expect("cleanup");
    }
}
