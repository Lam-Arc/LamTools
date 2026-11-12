use std::{error::Error, io, net::TcpListener};

type StartupResult<T> = Result<T, Box<dyn Error>>;

pub fn retry_port_conflict<T>(mut start: impl FnMut() -> StartupResult<T>, mut cleanup: impl FnMut()) -> StartupResult<T> {
    // user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(空闲端口检查与后端监听之间存在竞争，只有确认的端口冲突才清理重试，最多三次)。
    for attempt in 0..3 {
        match start() {
            Ok(value) => return Ok(value),
            Err(error) => {
                let conflict = error.downcast_ref::<io::Error>()
                    .is_some_and(|cause| cause.kind() == io::ErrorKind::AddrInUse);
                if !conflict || attempt == 2 { return Err(error); }
                cleanup();
            }
        }
    }
    unreachable!("bounded startup loop always returns")
}

pub fn exited_backend_error(port: u16, status: impl std::fmt::Display) -> Box<dyn Error> {
    match TcpListener::bind(("127.0.0.1", port)) {
        Err(error) if error.kind() == io::ErrorKind::AddrInUse =>
            io::Error::new(io::ErrorKind::AddrInUse, format!("backend exited ({status}); port {port} was taken")).into(),
        _ => io::Error::other(format!("backend exited before readiness ({status})")).into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    // user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(启动端口竞争可有限重试；其他失败立即保留原因，重试前须清理上次进程)。
    #[test]
    fn retries_address_conflict_after_cleanup() {
        let starts = Cell::new(0);
        let cleanups = Cell::new(0);
        let result = retry_port_conflict(|| {
            starts.set(starts.get() + 1);
            if starts.get() == 1 { return Err(io::Error::from(io::ErrorKind::AddrInUse).into()); }
            assert_eq!(cleanups.get(), 1);
            Ok("ready")
        }, || cleanups.set(cleanups.get() + 1));
        assert_eq!(result.unwrap(), "ready");
        assert_eq!(starts.get(), 2);
    }

    #[test]
    fn repeated_conflicts_stop_after_three_attempts() {
        let starts = Cell::new(0);
        let result: StartupResult<()> = retry_port_conflict(|| {
            starts.set(starts.get() + 1);
            Err(io::Error::from(io::ErrorKind::AddrInUse).into())
        }, || {});
        assert!(result.is_err());
        assert_eq!(starts.get(), 3);
    }

    #[test]
    fn other_startup_failures_are_not_retried() {
        let starts = Cell::new(0);
        let result: StartupResult<()> = retry_port_conflict(|| {
            starts.set(starts.get() + 1);
            Err(io::Error::from(io::ErrorKind::PermissionDenied).into())
        }, || panic!("non-retryable failure must stay intact"));
        assert_eq!(result.unwrap_err().downcast_ref::<io::Error>().unwrap().kind(), io::ErrorKind::PermissionDenied);
        assert_eq!(starts.get(), 1);
    }

    #[test]
    fn exited_child_with_occupied_port_is_a_conflict() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let error = exited_backend_error(listener.local_addr().unwrap().port(), 3);
        assert_eq!(error.downcast_ref::<io::Error>().unwrap().kind(), io::ErrorKind::AddrInUse);
    }
}
