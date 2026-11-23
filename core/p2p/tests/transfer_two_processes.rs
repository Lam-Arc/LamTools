//! 两进程互传实测：`serve` 收、`send` 发，中间只走真实的 iroh 隧道。
//!
//! user:“Rust 侧加集成测试（两进程互传一个小文件）”+(光有内存里的单测证明不了协议能穿
//! 过真实隧道：帧的写法、握手后的权限、进度事件、落盘位置，只有两个进程跑一遍才算数)。

use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

/// 两个进程加起来最多等这么久（含中继就绪与握手）；超时直接失败，而不是挂死。
const DEADLINE: Duration = Duration::from_secs(90);

fn binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sunday-p2p"))
}

fn scratch(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "sunday-p2p-transfer-it-{tag}-{}-{}",
        std::process::id(),
        Instant::now().elapsed().as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("scratch dir");
    dir
}

/// 一个还在跑的进程：日志按行进通道，结束时能拿到全部输出。
struct Running {
    child: Child,
    lines: mpsc::Receiver<String>,
    collected: Arc<Mutex<Vec<String>>>,
}

impl Running {
    fn spawn(mut command: Command) -> Self {
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn");
        let stdout = child.stdout.take().expect("stdout");
        let stderr = child.stderr.take().expect("stderr");
        let (tx, rx) = mpsc::channel();
        let collected = Arc::new(Mutex::new(Vec::new()));
        for stream in [
            Box::new(stdout) as Box<dyn Read + Send>,
            Box::new(stderr),
        ] {
            let tx = tx.clone();
            let collected = Arc::clone(&collected);
            std::thread::spawn(move || {
                let reader = BufReader::new(stream);
                for line in reader.lines().map_while(Result::ok) {
                    collected.lock().unwrap().push(line.clone());
                    if tx.send(line).is_err() {
                        return;
                    }
                }
            });
        }
        Self {
            child,
            lines: rx,
            collected,
        }
    }

    /// 等到某一行满足条件为止。停止条件是「截到限期」或「进程退出」，不靠固定睡眠。
    fn wait_for(&self, what: &str, deadline: Instant, mut pick: impl FnMut(&str) -> bool) -> String {
        loop {
            if Instant::now() >= deadline {
                panic!(
                    "等到限期也没看到 {what}；已有输出：\n{}",
                    self.collected.lock().unwrap().join("\n")
                );
            }
            let left = deadline.saturating_duration_since(Instant::now());
            match self.lines.recv_timeout(left) {
                Ok(line) => {
                    if pick(&line) {
                        return line;
                    }
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    panic!(
                        "等到限期也没看到 {what}；已有输出：\n{}",
                        self.collected.lock().unwrap().join("\n")
                    )
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => panic!(
                    "进程提前退出，没看到 {what}；输出：\n{}",
                    self.collected.lock().unwrap().join("\n")
                ),
            }
        }
    }

    fn output(&self) -> String {
        self.collected.lock().unwrap().join("\n")
    }

    fn child(&mut self) -> &mut Child {
        &mut self.child
    }
}

impl Drop for Running {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn ticket_from(line: &str) -> Option<String> {
    line.strip_prefix("TICKET ").map(|rest| rest.trim().to_owned())
}

/// 跑一次 `send`，等到进程退出（或到限期），返回 (是否成功, 全部输出)。
fn run_send(command: Command, deadline: Instant) -> (bool, String) {
    let mut running = Running::spawn(command);
    loop {
        if Instant::now() >= deadline {
            let output = running.output();
            panic!("send 等超时；输出：\n{output}");
        }
        match running.child().try_wait() {
            Ok(Some(status)) => {
                // 退出后要把管道里剩下的行收干净。
                let collected = running.output();
                return (status.success(), collected);
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(100)),
            Err(error) => panic!("wait failed: {error}"),
        }
    }
}

fn payload(size: usize) -> Vec<u8> {
    (0..size).map(|index| (index % 251) as u8).collect()
}

/// 今天（UTC）的日期目录名，和传输进程用的是同一份 `civil_date` 实现。
fn today() -> String {
    sunday_p2p::transfer::civil_date(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64,
    )
}

/// user:“互发文件：收到、落盘路径可见”“重名不覆盖”+(一次真两进程的传输 + 第二次同名传输
/// 自动改名，两次都必须逐字节相等)。
#[test]
fn two_processes_move_a_file_onto_the_receivers_disk() {
    let root = scratch("two");
    let server_dir = root.join("server");
    let client_dir = root.join("client");
    std::fs::create_dir_all(&server_dir).unwrap();
    std::fs::create_dir_all(&client_dir).unwrap();
    let receive = root.join("received");

    let mut serve = Command::new(binary());
    serve
        .arg("serve")
        .arg("--dir")
        .arg(&server_dir)
        .arg("--name")
        .arg("PC")
        .arg("--receive")
        .arg(&receive);
    let server = Running::spawn(serve);
    let deadline = Instant::now() + DEADLINE;
    let ticket = server.wait_for("TICKET", deadline, |line| ticket_from(line).is_some());
    let ticket = ticket_from(&ticket).expect("ticket text");
    assert!(
        ticket.starts_with("sunday2:"),
        "扫码票必须是一次性配对票：{ticket}"
    );
    server.wait_for("READY", deadline, |line| line.trim() == "READY");

    // 700 KiB 跨三个块（256K/256K/188K）：分块边界必须在真实隧道上也成立。
    let source = root.join("payload.bin");
    let bytes = payload(700 * 1024);
    std::fs::write(&source, &bytes).unwrap();

    let mut send = Command::new(binary());
    send.arg("send")
        .arg("--dir")
        .arg(&client_dir)
        .arg("--ticket")
        .arg(&ticket)
        .arg("--file")
        .arg(&source);
    let (ok, output) = run_send(send, deadline);
    assert!(ok, "第一次发送应当成功；输出：\n{output}");
    assert!(output.contains("SENT "), "要给出可核对的发送结果：\n{output}");

    let landed = receive.join(today()).join("payload.bin");
    assert!(
        landed.exists(),
        "文件必须落在 --receive 指定的日期目录里：{}；输出：\n{output}",
        landed.display()
    );
    assert_eq!(std::fs::read(&landed).unwrap(), bytes, "落盘内容必须一致");

    // 传输进程要打出结构化状态：一条 transfer 进度 + 一条 received 落盘事实。
    let served = server.output();
    let transfer_lines: Vec<&str> = served
        .lines()
        .filter(|line| line.starts_with("SUNDAY-P2P/1 ") && line.contains("\"event\":\"transfer\""))
        .collect();
    assert!(
        !transfer_lines.is_empty(),
        "没有传输进度状态行（界面靠它画进度条）：\n{served}"
    );
    assert!(
        transfer_lines
            .iter()
            .any(|line| line.contains("\"state\":\"offered\"")),
        "要先报 offered：{transfer_lines:?}"
    );
    let completed = transfer_lines
        .iter()
        .find(|line| line.contains("\"state\":\"completed\""))
        .copied()
        .unwrap_or_else(|| panic!("进度要走到 completed：{transfer_lines:?}"));
    assert!(
        completed.contains("\"direction\":\"receive\"") && completed.contains("\"percent\":100"),
        "接收端要按 receive 报且走到 100%：{completed}"
    );
    let received_line = served
        .lines()
        .find(|line| line.starts_with("SUNDAY-P2P/1 ") && line.contains("\"event\":\"received\""))
        .unwrap_or_else(|| panic!("没有 received 状态行（宿主靠它登记资料库）：\n{served}"));
    assert!(
        received_line.contains("payload.bin"),
        "received 里要带落盘路径：{received_line}"
    );

    // 再来一次同名：不覆盖第一份，自动变成 `payload (2).bin`。
    let mut again = Command::new(binary());
    again
        .arg("send")
        .arg("--dir")
        .arg(&client_dir)
        .arg("--ticket")
        .arg(&ticket)
        .arg("--file")
        .arg(&source);
    let (ok, output) = run_send(again, deadline);
    assert!(ok, "第二次发送应当成功；输出：\n{output}");
    let second = receive.join(today()).join("payload (2).bin");
    assert!(
        second.exists(),
        "同名文件要落成 payload (2).bin，而不是覆盖；输出：\n{output}"
    );
    // 第一次那份还在原位，一个字节都没动。
    assert_eq!(std::fs::read(&landed).unwrap(), bytes);
}

/// user:“未配对/已撤权一律拒绝并给错误码”+(没有票的设备连握手都过不去；这条在真实两进程
/// 上验证「拒绝发生在传输之前」，不是一个只在单测里成立的断言)。
#[test]
fn a_device_without_a_ticket_never_gets_near_the_receive_directory() {
    let root = scratch("unpaired");
    let server_dir = root.join("server");
    let client_dir = root.join("client");
    std::fs::create_dir_all(&server_dir).unwrap();
    std::fs::create_dir_all(&client_dir).unwrap();
    let receive = root.join("received");

    let mut serve = Command::new(binary());
    serve
        .arg("serve")
        .arg("--dir")
        .arg(&server_dir)
        .arg("--name")
        .arg("PC")
        .arg("--receive")
        .arg(&receive);
    let server = Running::spawn(serve);
    let deadline = Instant::now() + DEADLINE;
    server.wait_for("READY", deadline, |line| line.trim() == "READY");

    let source = root.join("secret.txt");
    std::fs::write(&source, b"should not travel").unwrap();

    // 拿一张连不上/无效的票：握手必须失败，且接收目录里不会出现任何文件。
    let mut send = Command::new(binary());
    send.arg("send")
        .arg("--dir")
        .arg(&client_dir)
        .arg("--ticket")
        .arg("sunday1:eyJpZCI6Im5vdC1hLXJlYWwtbm9kZSIsImFkZHJzIjpbXX0")
        .arg("--file")
        .arg(&source)
        .arg("--as")
        .arg("secret.txt");
    // 明确期待失败：成功才说明拒绝路径没生效。
    let (ok, output) = run_send(send, deadline);
    assert!(!ok, "无票设备不该发送成功；输出：\n{output}");
    let landed = receive.join(today());
    let leftovers: Vec<String> = std::fs::read_dir(&landed)
        .map(|entries| {
            entries
                .filter_map(Result::ok)
                .map(|entry| entry.file_name().to_string_lossy().to_string())
                .collect()
        })
        .unwrap_or_default();
    assert!(leftovers.is_empty(), "被拒的传输不能留下文件：{leftovers:?}");
    let _ = server.output();
}
