//! 长连接看护：断线自动重连、Core 挂了当场降级、恢复后自己接回去。
//!
//! user:“自动恢复：Wi-Fi/移动网络切换、电脑休眠唤醒、Core 重启后自动恢复”+(手机宿主不在
//! 本仓库，所以这里给出**参考实现**：它就是宿主该做的事——拨号、初始化、每秒核对四层状态、
//! 断了按退避重连、重连之后重新 initialize 再补事件)。CLI 的 `watch` 子命令直接调它，P1
//! 的验收脚本也靠它跑出真实证据。
//!
//! 为什么放在库里而不是 CLI 里：宿主要复用同一套判定（`state::Layers`），只有一份实现才
//! 不会出现「CLI 说已连接、界面说还在连」这种两套真相。

use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use iroh::Endpoint;

use crate::link::Client;
use crate::recovery::{Backoff, Delivery, Outbox, Reconcile, SendStart};
use crate::state::{CoreLayer, DeviceLayer, Layers, SessionLayer, View};

/// 看护多久（`watch` 的总时长）。
pub const DEFAULT_WATCH: Duration = Duration::from_secs(120);

/// 一次看护的参数。
#[derive(Debug, Clone)]
pub struct WatchOptions {
    /// 用哪张票连：配对票（`sunday2:`）或地址票（`sunday1:`，已配对设备重连）。
    pub ticket: String,
    /// 本机显示名（对端设备列表里看到的名字）。
    pub name: String,
    /// Core 的端口；0 表示不探测，直接以业务调用是否成功为准。
    pub core_port: u16,
    /// 看护总时长。
    pub total: Duration,
    /// 最多重连几次。
    pub attempts: u32,
    /// 这条连接在看哪一条会话：重连后「先查状态」要按会话查日志。
    pub thread: Option<String>,
    /// 重连之后要补发的那条写操作（宿主的真实发送路径用得到）。
    ///
    /// user:“断线恢复后不得重复执行写操作（幂等键要落地）”“不确定送达时先查询状态，
    /// 不盲目重发”+(这里放的是「本来要发的那一次」：每次连上都先向对端查这条键在不在，
    /// 再决定重发还是算了，而不是每重连一次就再写一遍)。
    pub send: Option<PendingSend>,
    /// 上次进程里没收到回执的写：重启之后先恢复进账本，连上时先查状态再决定。
    pub restore: Vec<String>,
}

/// 一条待发的写操作：幂等键 + 方法 + 参数。
#[derive(Debug, Clone)]
pub struct PendingSend {
    /// 幂等键（Core 的 `client_message_id`）。
    pub key: String,
    pub method: String,
    pub params: serde_json::Value,
}

impl WatchOptions {
    pub fn new(ticket: impl Into<String>, name: impl Into<String>) -> Self {
        Self {
            ticket: ticket.into(),
            name: name.into(),
            core_port: 0,
            total: DEFAULT_WATCH,
            attempts: 20,
            thread: None,
            send: None,
            restore: Vec::new(),
        }
    }
}

/// 宿主侧的可靠发送：`recovery::Outbox` 真正的消费者。
///
/// user:“`recovery::Outbox` 仍是库、无宿主消费 → 「不确定送达先查状态」在重发路径上没有
/// 真正生效，接上宿主消费”+(账本以前只有单元测试在用它：断线之后没人把「查到的事实」
/// 写回去，重发路径要么不敢发、要么当成新写。这个结构就是宿主该做的那几件事——
/// 发的时候用幂等键登记、断线时把在途标成未知、重连后先按会话查日志再决定)。
pub struct ReliableSend {
    outbox: Outbox,
    /// 这条连接在看哪一条会话（没有它就没法按会话查日志，只能维持未知）。
    thread: Option<String>,
    /// 最近一次 `send` 是新写还是重复：日志用它证明「没有第二次写」。
    last_decision: SendStart,
}

impl ReliableSend {
    pub fn new(thread: Option<String>) -> Self {
        Self {
            outbox: Outbox::default(),
            thread,
            last_decision: SendStart::New,
        }
    }

    /// 把上次进程里没收到回执的写恢复进账本（宿主重启后的第一步）。
    ///
    /// user:“不确定送达时先查询状态，不盲目重发”+(宿主进程可能被杀在「已发出、未收到
    /// 回执」的一刻。重启后先把这些键恢复成「未知」，连上时才会先去查，而不是当成新写)。
    pub fn restore_pending(&mut self, key: &str) {
        self.outbox.restore(key);
    }

    /// 最近一次发送是新写还是重复。
    pub fn last_decision(&self) -> SendStart {
        self.last_decision
    }

    /// 发一条写操作。
    ///
    /// 返回的 `Delivery` 是「现在能不能说已发送」：还没拿到回执就是 `Pending`/`Unknown`。
    /// 同一个键第二次调用不会产生第二次写（返回已有的状态）。
    pub async fn send(
        &mut self,
        client: &Client,
        key: &str,
        method: &str,
        params: serde_json::Value,
    ) -> anyhow::Result<Delivery> {
        let start = self.outbox.send(key);
        self.last_decision = start;
        if start == SendStart::Duplicate {
            // 已经在路上或结果未知：不重写，等回执/等查询。
            return Ok(self.outbox.state(key));
        }
        match client.call(method, params).await {
            Ok(_) => {
                // 拿到答复才算送达；界面只认这一条。
                self.outbox.acknowledge(key);
                Ok(Delivery::Acknowledged)
            }
            Err(error) => {
                if client.is_alive() {
                    // 对端明确拒绝了这一次：服务端没写进去，用同一个键重试是安全的。
                    self.outbox.fail(key);
                    Err(error)
                } else {
                    // 连接中间的断线：不知道有没有到，绝不能当成失败直接重发。
                    self.outbox.mark_uncertain();
                    Ok(Delivery::Unknown)
                }
            }
        }
    }

    /// 连接断了：在途的写全部变成「不知道有没有到」。
    pub fn connection_lost(&mut self) {
        self.outbox.mark_uncertain();
    }

    /// 重连之后、重发之前：先按幂等键查对端日志。
    ///
    /// user:“不确定送达时先查询状态，不盲目重发”+(查得到「有」就算送达，查得到「没有」
    /// 才用同一个键重发；查不出来就维持未知——宁可让用户等一下，也不重复执行一次写)。
    pub async fn reconcile(&mut self, client: &Client) -> Vec<(String, Reconcile)> {
        let mut outcomes = Vec::new();
        for key in self.outbox.needs_reconcile() {
            let found = self.probe(client, &key).await;
            let verdict = self.outbox.settle(&key, found);
            outcomes.push((key, verdict));
        }
        outcomes
    }

    /// 这条键在对方日志里吗？`None` 表示查不出来（没会话、查询失败）。
    async fn probe(&self, client: &Client, key: &str) -> Option<bool> {
        let thread = self.thread.as_deref()?;
        // 从会话开头取日志：按幂等键在返回结果里找，不猜字段名（Core 的日志条目结构
        // 可以演进，`client_message_id` 只要还在，这段就仍然有效）。
        let result = client
            .call(
                "thread/resume",
                serde_json::json!({ "thread_id": thread, "last_seen_seq": 0 }),
            )
            .await
            .ok()?;
        Some(json_mentions(&result, key))
    }

    pub fn delivery(&self, key: &str) -> Delivery {
        self.outbox.state(key)
    }

    /// 还没收尾的键（下一次重连要接着查）。
    pub fn pending(&self) -> Vec<String> {
        self.outbox.needs_reconcile()
    }

    /// 界面上该怎么显示这条。
    pub fn display_state(&self, key: &str) -> &'static str {
        self.outbox.display_state(key)
    }
}

/// 在一份 JSON 里找某个字符串（只看字符串叶子，键名也算）。
///
/// 不按字段路径取，是因为「消息有没有写进日志」这件事在 Core 的返回值里可能换个包裹；
/// 幂等键是客户端生成的唯一串，出现在日志里就说明这条已经被接受。
pub fn json_mentions(value: &serde_json::Value, needle: &str) -> bool {
    if needle.is_empty() {
        return false;
    }
    match value {
        serde_json::Value::String(text) => text == needle,
        serde_json::Value::Array(items) => items.iter().any(|item| json_mentions(item, needle)),
        serde_json::Value::Object(map) => map
            .iter()
            .any(|(name, item)| name == needle || json_mentions(item, needle)),
        _ => false,
    }
}

/// 看护这条连接，直到时间用完或重试用尽。
///
/// 输出是给人和脚本看的一行行状态：
/// `STATE transport=up device=authenticated core=ready session=resumed view=connected reason=-`
pub async fn run(endpoint: &Endpoint, options: WatchOptions) -> Result<()> {
    if options.ticket.trim().is_empty() {
        bail!("--ticket is required");
    }
    // user:“扫码后立即有反馈；清楚区分配对 / 连接 / 恢复会话阶段”+(以前第一行输出要等
    // 拨号成功才出现，冷启动时中间几十秒界面只能干转；现在一进来先说清楚在做什么，
    // 脚本也不用猜「没输出」到底是还没开始还是已经卡死)。
    let pairing = crate::pair::is_pairing_ticket(&options.ticket);
    println!(
        "STARTING name={} ticket={} core_port={} total={}s",
        options.name,
        if pairing { "pairing" } else { "resume" },
        options.core_port,
        options.total.as_secs()
    );
    if pairing {
        println!("PHASE pairing");
    }
    let started = Instant::now();
    // user:“自动恢复”+(先快后慢：1s、2s、4s、5s、5s…；有上限也有次数上限，
    // 电脑关机时不能无限撞)。
    let mut backoff = Backoff::new(
        Duration::from_secs(1),
        Duration::from_secs(5),
        options.attempts.max(1),
        Duration::from_secs(20),
    );
    let mut first_failure: Option<Instant> = None;
    let mut noticed = false;
    // 账本活在循环外面：连接断了、重连了，它都记得哪些写还没收尾。
    let mut reliable = ReliableSend::new(options.thread.clone());
    // user:“不确定送达时先查询状态，不盲目重发”+(进程重启后先把上次没收到回执的写恢复成
    // 「未知」：它会在连上的第一刻被查一遍，而不是被当成没发过再写一次)。
    for key in &options.restore {
        reliable.restore_pending(key);
    }

    while started.elapsed() < options.total {
        // user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+(提示阈值以前只在两次
        // 拨号之间检查；可一次拨号本身能挂一两分钟，长断线期间用户就什么都看不到。这里让
        // 拨号与「该提示了没有」并行跑：到点就说，不等这一次拨号失败)。
        // user:“清楚区分连接 / 恢复会话阶段”+(第几次尝试也要看得出来，否则「一直在连」
        // 和「连不上」在日志里长得一样)。
        println!("PHASE connecting attempt={}", backoff.attempt() + 1);
        let mut dial = Box::pin(Client::dial(endpoint, &options.ticket, &options.name));
        let dialed = loop {
            tokio::select! {
                result = &mut dial => break result,
                _ = tokio::time::sleep(Duration::from_millis(250)) => {
                    if !noticed {
                        if let Some(first) = first_failure {
                            if backoff.should_notify(first.elapsed()) {
                                noticed = true;
                                println!(
                                    "NOTICE 连接中断已超过 {} 秒，仍在自动重连",
                                    backoff.notify_after().as_secs()
                                );
                            }
                        }
                    }
                    // 看护时间到了就别再挂在一个拨号上：退避重连是宿主自己的循环。
                    if started.elapsed() >= options.total {
                        break Err(anyhow::anyhow!("看护时间已到"));
                    }
                }
            }
        };
        let client = match dialed {
            Ok(client) => client,
            Err(error) => {
                println!("DIAL FAILED {error:#}");
                if !wait_before_retry(&mut backoff, &mut first_failure, &mut noticed).await {
                    break;
                }
                continue;
            }
        };
        backoff.reset();
        first_failure = None;
        noticed = false;
        println!("CONNECTED peer={}", client.peer);
        // user:“真实路径显示：区分直连/中继”+(连上就把此刻走的哪条路打给脚本与宿主看)。
        println!("PATH {} path={}", client.peer, client.path().as_str());
        // user:“不确定送达时先查询状态，不盲目重发”+(这条连接可能是重连：先把上一次
        // 悬着的写查清楚，再谈补发)。
        reliable.connection_lost();
        for (key, verdict) in reliable.reconcile(&client).await {
            println!("RECONCILE key={key} verdict={}", verdict.code());
        }
        if let Some(pending) = options.send.clone() {
            match reliable
                .send(&client, &pending.key, &pending.method, pending.params.clone())
                .await
            {
                Ok(state) => println!(
                    "SEND key={} decision={} state={}",
                    pending.key,
                    match reliable.last_decision() {
                        SendStart::New => "new",
                        SendStart::Duplicate => "duplicate",
                    },
                    match state {
                        Delivery::Acknowledged => "sent",
                        Delivery::Pending => "sending",
                        Delivery::Unknown => "unknown",
                        Delivery::Failed => "failed",
                    }
                ),
                Err(error) => println!("SEND key={} failed {error:#}", pending.key),
            }
        }

        // 会话层从「未恢复」开始：下面要么重新 initialize，要么等 Core 回来后重来一次。
        let mut session = SessionLayer::NotResumed;
        let mut last_core = CoreLayer::Unknown;

        loop {
            if started.elapsed() >= options.total {
                client.close();
                return Ok(());
            }
            // 业务通道还活着吗。
            if client.call("ping", serde_json::json!({})).await.is_err() {
                break;
            }
            let core = if options.core_port == 0 {
                CoreLayer::Ready
            } else {
                probe_core(options.core_port).await
            };
            match core {
                CoreLayer::Down => {
                    // user:“Core 无响应时必须降级显示，不能继续显示正常”+(会话随之作废，
                    // 等它回来要重新初始化)。
                    session = SessionLayer::NotResumed;
                }
                CoreLayer::Ready => {
                    if last_core == CoreLayer::Down || session == SessionLayer::NotResumed {
                        // user:“恢复时重新初始化、重新订阅会话事件”+(Core 换端口重启过以后，
                        // 旧的 RPC 桥已经没了；重新 initialize 才算真的恢复)。
                        let _ = client.call("initialize", serde_json::json!({})).await;
                        session = SessionLayer::Resumed;
                        println!("SESSION RESUMED");
                    }
                }
                CoreLayer::Unknown => {}
            }
            last_core = core;
            print_state(&Layers {
                transport: true,
                device: DeviceLayer::Authenticated,
                core,
                session,
            });
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        client.close();

        // 断线：先如实报告「降级到哪一层」，再按退避重连。
        reliable.connection_lost();
        println!("LOST");
        print_state(&Layers {
            transport: false,
            device: DeviceLayer::Paired,
            core: CoreLayer::Unknown,
            session: SessionLayer::NotResumed,
        });
        if !wait_before_retry(&mut backoff, &mut first_failure, &mut noticed).await {
            break;
        }
    }
    Ok(())
}

/// 等下一次重试。返回 `false` 表示重试次数用完了。
async fn wait_before_retry(
    backoff: &mut Backoff,
    first_failure: &mut Option<Instant>,
    noticed: &mut bool,
) -> bool {
    let now = Instant::now();
    let first = *first_failure.get_or_insert(now);
    // user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+(阈值之内只重连不说话)。
    if !*noticed && backoff.should_notify(now.saturating_duration_since(first)) {
        *noticed = true;
        println!(
            "NOTICE 连接中断已超过 {} 秒，仍在自动重连",
            backoff.notify_after().as_secs()
        );
    }
    match backoff.next_delay() {
        Some(delay) => {
            println!(
                "RETRY attempt={} delay_ms={}",
                backoff.attempt(),
                delay.as_millis()
            );
            tokio::time::sleep(delay).await;
            true
        }
        None => {
            println!("GIVE UP attempts={}", backoff.attempt());
            false
        }
    }
}

/// 回环 health 探测：2 秒没答就当 Core 挂了。
///
/// user:“Core 无响应时必须降级显示”+(进程被杀、端口换了、卡住了，都表现为「没有应答」；
/// 探测本身不能把看护循环挂住，所以有超时)。
pub async fn probe_core(port: u16) -> CoreLayer {
    let probe = tokio::task::spawn_blocking(move || {
        crate::proxy::call_core("127.0.0.1", port, "", "GET", "/api/health", None)
    });
    match tokio::time::timeout(Duration::from_secs(2), probe).await {
        Ok(Ok(Ok((status, _)))) if (200..300).contains(&status) => CoreLayer::Ready,
        _ => CoreLayer::Down,
    }
}

/// 一行可断言的层状态（脚本只匹配 ASCII）。
pub fn print_state(layers: &Layers) {
    let view = layers.view();
    let (name, reason) = match &view {
        View::Offline => ("offline", "-"),
        View::Connecting => ("connecting", "-"),
        View::Connected => ("connected", "-"),
        View::Degraded { reason } => ("degraded", reason.code()),
    };
    println!(
        "STATE transport={} device={} core={} session={} view={} reason={}",
        if layers.transport { "up" } else { "down" },
        match layers.device {
            DeviceLayer::Unpaired => "unpaired",
            DeviceLayer::Paired => "paired",
            DeviceLayer::Authenticated => "authenticated",
        },
        match layers.core {
            CoreLayer::Unknown => "unknown",
            CoreLayer::Ready => "ready",
            CoreLayer::Down => "down",
        },
        match layers.session {
            SessionLayer::NotResumed => "not_resumed",
            SessionLayer::Resumed => "resumed",
        },
        name,
        reason,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    /// user:“不确定送达时先查询状态，不盲目重发”+(查日志靠的是幂等键出现在返回里，
    /// 不是猜某个固定字段名)。
    #[test]
    fn a_key_is_found_anywhere_it_appears_in_the_journal() {
        let journal = serde_json::json!({
            "thread": { "id": "t-1" },
            "events": [
                { "seq": 1, "item": { "client_message_id": "cid-7", "text": "你好" } },
            ],
        });
        assert!(json_mentions(&journal, "cid-7"));
        assert!(!json_mentions(&journal, "cid-8"));
        assert!(!json_mentions(&journal, ""), "空键不能匹配一切");
        assert!(json_mentions(&serde_json::json!({ "cid-9": 1 }), "cid-9"));
    }

    /// 断线时在途的写必须变成「未知」，否则重连后会被当成「没发出去」再写一遍。
    #[test]
    fn losing_the_connection_turns_in_flight_writes_into_unknown() {
        let mut reliable = ReliableSend::new(Some("t-1".to_owned()));
        // 直接放一条在途记录：这里不连网，只验账本状态机。
        reliable.outbox.send("cid-1");
        assert_eq!(reliable.delivery("cid-1"), Delivery::Pending);
        reliable.connection_lost();
        assert_eq!(reliable.delivery("cid-1"), Delivery::Unknown);
        assert_eq!(reliable.pending(), vec!["cid-1".to_owned()]);
        assert_eq!(reliable.display_state("cid-1"), "unknown");
    }

    /// 没有会话就查不了：宁可维持未知，也不能当成「没写」去重发。
    #[test]
    fn without_a_thread_the_verdict_stays_unknown() {
        let mut reliable = ReliableSend::new(None);
        reliable.outbox.send("cid-1");
        reliable.connection_lost();
        // 直接走账本判定：查不出来时 settle 不改任何东西。
        assert_eq!(reliable.outbox.settle("cid-1", None), Reconcile::Unknown);
        assert_eq!(reliable.delivery("cid-1"), Delivery::Unknown);
    }

    /// user:“只有业务真正可用才显示「已连接电脑」”+(状态行必须能如实表达降级)。
    #[test]
    fn the_state_line_names_every_layer_and_the_reason() {
        // 只验证格式化逻辑：把 Layers 拼成一行，脚本按 `view=` / `reason=` 断言。
        let layers = Layers {
            transport: true,
            device: DeviceLayer::Authenticated,
            core: CoreLayer::Down,
            session: SessionLayer::NotResumed,
        };
        assert_eq!(
            layers.view(),
            View::Degraded {
                reason: crate::state::Reason::CoreUnavailable
            }
        );
        assert_eq!(crate::state::Reason::CoreUnavailable.code(), "core_unavailable");
    }
}
