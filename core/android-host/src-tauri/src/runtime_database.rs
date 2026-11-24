use std::{
    fs::{self, File},
    io::{self, Read},
    path::Path,
};

fn copy_synced(from: &Path, to: &Path) -> io::Result<()> {
    let expected = fs::metadata(from)?.len();
    if fs::copy(from, to)? != expected || fs::metadata(from)?.len() != expected {
        return Err(io::Error::other("legacy database changed during migration"));
    }
    File::options().write(true).open(to)?.sync_all()
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> io::Result<()> {
    File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_: &Path) -> io::Result<()> {
    Ok(())
}

/// user:“修”+(旧版镜像里的数据库和 SQLite 日志一起迁出，迁移失败时保留旧镜像)。
pub(super) fn migrate_legacy_database(old_data: &Path, data: &Path) -> io::Result<()> {
    let source = old_data.join("core.db");
    let destination = data.join("core.db");
    if !source.try_exists()? {
        return Ok(());
    }
    if destination.try_exists()? {
        return sync_directory(data);
    }
    // The old guest has stopped. The journal or WAL may still contain committed changes.
    let mut header = [0; 16];
    File::open(&source)?.read_exact(&mut header)?;
    if &header != b"SQLite format 3\0" {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "invalid legacy SQLite header",
        ));
    }

    fs::create_dir_all(data)?;
    let staged = data.join("core.db.migrating");
    copy_synced(&source, &staged)?;
    for name in ["core.db-wal", "core.db-journal"] {
        let source = old_data.join(name);
        let destination = data.join(name);
        if source.try_exists()? {
            let staged = data.join(format!("{name}.migrating"));
            copy_synced(&source, &staged)?;
            fs::rename(staged, destination)?;
        } else if destination.try_exists()? {
            // Only an interrupted migration can have left a sidecar without the database.
            fs::remove_file(destination)?;
        }
    }
    // Publish the main DB last. On interruption the original DB is still the source.
    sync_directory(data)?;
    fs::rename(staged, destination)?;
    sync_directory(data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    const DATABASE: &[u8] = b"SQLite format 3\0legacy database bytes";

    #[test]
    fn migrates_legacy_database_with_wal_and_retries_without_overwriting() {
        let temp = tempfile::tempdir().unwrap();
        let old_data = temp.path().join("rootfs-previous/opt/sunday/data");
        let data = temp.path().join("userdata/data");
        fs::create_dir_all(&old_data).unwrap();
        fs::create_dir_all(&data).unwrap();
        fs::write(old_data.join("core.db"), DATABASE).unwrap();
        fs::write(old_data.join("core.db-wal"), b"uncheckpointed updates").unwrap();
        fs::write(old_data.join("core.db-shm"), b"process cache").unwrap();
        migrate_legacy_database(&old_data, &data).unwrap();
        assert_eq!(fs::read(data.join("core.db")).unwrap(), DATABASE);
        assert_eq!(
            fs::read(data.join("core.db-wal")).unwrap(),
            b"uncheckpointed updates"
        );
        assert!(!data.join("core.db-shm").exists());
        fs::write(data.join("core.db"), b"newer database").unwrap();
        migrate_legacy_database(&old_data, &data).unwrap();
        assert_eq!(fs::read(data.join("core.db")).unwrap(), b"newer database");
    }

    #[test]
    fn invalid_legacy_database_is_kept_and_never_published() {
        let temp = tempfile::tempdir().unwrap();
        let old_data = temp.path().join("old");
        let data = temp.path().join("data");
        fs::create_dir_all(&old_data).unwrap();
        let source = old_data.join("core.db");
        fs::write(&source, b"truncated").unwrap();
        assert!(migrate_legacy_database(&old_data, &data).is_err());
        assert!(source.is_file());
        assert!(!data.join("core.db").exists());
    }
}
