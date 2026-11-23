//! The tunnel: frames over one encrypted QUIC stream pair.
//!
//! user:“远程能力：手机可以连接电脑上的 Sunday，访问会话、发送消息……优先复用现有
//! Core API，不重新实现业务逻辑”+(这一层搬的就是 Core 本来就在说的 JSON-RPC 帧：
//! 同一个 method、同一份 params，到了对面直接交给同一个 Python Core)。
//!
//! user:“网络切换后尽可能恢复连接及会话状态”+(读帧必须一直在跑：应答按 id 回给调用方，
//! 事件直接交给订阅者。否则界面发得出消息却看不到回复)。
//!
//! Framing is a 4-byte big-endian length followed by UTF-8 JSON: trivial to read from any
//! side, and impossible to desync because the length is authoritative.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use futures_util::stream::{FuturesUnordered, StreamExt as _};
use iroh::{Endpoint, EndpointAddr};
use serde::{Deserialize, Serialize};
use tokio::sync::{broadcast, oneshot, watch, Mutex};

use crate::trust::TrustStore;

/// One framed message on the wire.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Frame {
    /// First frame from the dialer.
    ///
    /// user:“扫码即可完成配对”+(手机扫到的那张一次性配对票原样带上来；已配对设备
    /// 重连时不带它，服务端按可信名单放行)。
    Hello {
        name: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        pair: Option<String>,
    },
    /// Answer to a hello.
    ///
    /// `name` is what the peer calls itself, so the device list shows "我的电脑" instead of
    /// a truncated node id. `#[serde(default)]` keeps a new dialer talking to an older
    /// server whose welcome had no name.
    Welcome {
        id: String,
        #[serde(default)]
        name: String,
        trusted: bool,
        /// 拒绝时给用户看的原因（“二维码用过了”之类），放行时为空。
        #[serde(default)]
        reason: String,
    },
    /// A Core-style call.
    Call { id: u64, method: String, params: serde_json::Value },
    /// Its answer.
    Reply { id: u64, result: serde_json::Value },
    /// A failed call.
    ///
    /// user:“撤权后 RPC 一律拒绝，返回明确错误码”+(`code` 是给界面与脚本判断用的
    /// 稳定标识（例如 `device_revoked`），`message` 是给人看的中文原因)。
    Error {
        id: u64,
        #[serde(default)]
        code: String,
        message: String,
    },
    /// An event the remote side should see as it happens.
    Event { method: String, params: serde_json::Value },
    Ping,
    Pong,
}

/// An event pushed by the far side.
#[derive(Debug, Clone)]
pub struct Event {
    pub method: String,
    pub params: serde_json::Value,
}

/// 这条连接实际走的是哪条路：直连，还是退回中继。
///
/// user:“真实路径显示：区分直连/中继，默认放在连接详情里，不占据主界面”+(以前界面只能
/// 说「连上了」：打洞成功和整条流量都在云端中继上，速度与隐私差别很大，用户没法判断此刻
/// 是哪种。iroh 知道每条连接开了哪些路径、当前选中的那条是不是中继，这里只把它翻成一个
/// 稳定的词)。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PathKind {
    /// 局域网或公网打洞成功：流量两端直连。
    Direct,
    /// 只能走中继：流量经过 relay 转发（仍是端到端加密的）。
    Relay,
    /// 还没判定出来（刚握手、路径还在协商）。
    Unknown,
}

impl PathKind {
    /// 给界面与日志用的稳定标识（不用匹配中文）。
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Relay => "relay",
            Self::Unknown => "unknown",
        }
    }

    /// 从标识还原（状态通道传的是字符串）。
    pub fn from_str(value: &str) -> Self {
        match value {
            "direct" => Self::Direct,
            "relay" => Self::Relay,
            _ => Self::Unknown,
        }
    }

    /// 给人看的一句话。
    pub fn explain(self) -> &'static str {
        match self {
            Self::Direct => "直连",
            Self::Relay => "经中继",
            Self::Unknown => "正在判定",
        }
    }
}

/// 把「当前选中的路径」与「存在哪些路径」翻成结论。
///
/// 判定只认选中那条：另外开着的直连路径还没承载数据，按它说「直连」就是骗人。没有选中
/// 信息时（握手早期），退一步用「有直连就算直连」——QUIC 有直连可用时不会继续用中继。
fn classify_path(
    selected_direct: bool,
    selected_relay: bool,
    any_direct: bool,
    any_relay: bool,
) -> PathKind {
    if selected_direct {
        return PathKind::Direct;
    }
    if selected_relay {
        return PathKind::Relay;
    }
    if any_direct {
        return PathKind::Direct;
    }
    if any_relay {
        return PathKind::Relay;
    }
    PathKind::Unknown
}

/// 读一次这条连接当前的路径快照。
fn path_kind(conn: &iroh::endpoint::Connection) -> PathKind {
    let paths = conn.paths();
    let mut selected_direct = false;
    let mut selected_relay = false;
    let mut any_direct = false;
    let mut any_relay = false;
    for path in paths.iter() {
        if path.is_ip() {
            any_direct = true;
        }
        if path.is_relay() {
            any_relay = true;
        }
        if path.is_selected() {
            if path.is_ip() {
                selected_direct = true;
            }
            if path.is_relay() {
                selected_relay = true;
            }
        }
    }
    classify_path(selected_direct, selected_relay, any_direct, any_relay)
}

/// A single frame has to carry a whole Core reply, and a thread snapshot on a long
/// conversation is tens of megabytes (the UI avoids asking for one, but `thread/resume`
/// and approval snapshots still can). 16 MB used to turn those into a closed tunnel;
/// this bound still refuses a hostile length while leaving room for a real reply.
const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;
const EVENT_BUFFER: usize = 256;

/// 客户端多久发一次心跳。
const PING_EVERY: Duration = Duration::from_secs(5);
/// 多久没收到 Pong 才认为这条连接已经没了。
///
/// user:“手机端远控电脑连接不稳定，频繁断连”+(26 秒判死等于两次心跳没回就断：手机切一下
/// 后台、地铁里抖一下、一个大回复把写锁占住十几秒，都会被当成断线。放宽到 60 秒，链路层
/// 另有 10 秒的 QUIC 保活，仍然远短于一次操作默认的 180 秒等待)。
/// 多久收不到 Pong 就认为这条连接已经没了。
///
/// user:“面对『对方 Core 没响应』时必须降级显示”“电脑被杀掉时界面不能一直显示连接正常”+
/// (以前是 120 秒：电脑进程被硬杀之后，手机要两分钟才肯承认断线，这两分钟里每一条操作
/// 都在等一个永远不会来的回复——这就是传输层的假在线。收到 25 秒还没 Pong 就判死，
/// 正在等回复的调用当场失败，界面立刻降级)。
///
/// 为什么不会重演历史上那次「频繁断连」：写锁被占说明这条连接正在发真实数据，那一路会
/// 刷新判死计时（见下面的 busy 分支），而服务端的读循环即使正在跑长任务也照样回 Pong。
/// 只有真的没有对端时，这个计时才会归零。
const PING_DEAD_AFTER_MILLIS: u64 = 25_000;
/// 服务端多久没收到任何帧就收掉连接。
///
/// user:“显示和电脑断联了”+(网络静默断开时 QUIC 既不报错也不关闭，读帧会一直挂着；
/// 客户端每 12 秒发一次 Ping，服务端两分钟看不到帧就把这条连接关掉，两端都能重连，
/// 而不是一直显示「已连接」)。
const IDLE_TIMEOUT: Duration = Duration::from_secs(120);

fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as u64)
        .unwrap_or(0)
}

async fn write_frame(send: &mut iroh::endpoint::SendStream, frame: &Frame) -> Result<()> {
    let bytes = serde_json::to_vec(frame).context("cannot encode a frame")?;
    if bytes.len() > MAX_FRAME_BYTES {
        bail!("一帧超过 {} 字节", MAX_FRAME_BYTES);
    }
    send.write_all(&(bytes.len() as u32).to_be_bytes())
        .await
        .context("cannot write a frame header")?;
    send.write_all(&bytes).await.context("cannot write a frame")?;
    Ok(())
}

async fn read_frame(recv: &mut iroh::endpoint::RecvStream) -> Result<Frame> {
    let mut header = [0u8; 4];
    recv.read_exact(&mut header)
        .await
        .context("peer closed the stream")?;
    let length = u32::from_be_bytes(header) as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        bail!("对端给了一个不合法的帧长度 {length}");
    }
    let mut buffer = vec![0u8; length];
    recv.read_exact(&mut buffer)
        .await
        .context("cannot read a frame")?;
    serde_json::from_slice(&buffer).context("cannot parse a frame")
}

/// The dialing side.
pub struct Client {
    conn: iroh::endpoint::Connection,
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value, String>>>>>,
    events: broadcast::Sender<Event>,
    /// 请求 id 用原子计数，`call` 就能拿 `&self`：多条请求可以同时在路上，不必互相排队。
    next_id: AtomicU64,
    /// 读帧的任务还在跑就说明隧道还活着。断了之后界面必须知道，否则会一直显示
    /// 「已连接」，而每一次操作都拿到一个看不懂的英文错误。
    alive: Arc<AtomicBool>,
    /// 最近一次收到 Pong 的时间，心跳任务据此判死。
    /// 存活状态的变化通知：`true` 是活着，`false` 是断了。
    ///
    /// user:“手机端远控电脑连接不稳定，频繁断连”+(断线要当场让正在等回复的调用失败，
    /// 而不是各自等满 180 秒；界面也能靠它立刻开始重连)。
    lost: Arc<watch::Sender<bool>>,
    /// 对端的显示名，来自握手；老服务端没有这个名字时是空串。
    pub peer_name: String,
    pub peer: String,
    /// 对端地址：配对成功之后重连用它，不需要再扫一次码。
    addr: EndpointAddr,
    /// 服务端在连接层面给出的拒绝原因（例如撤销授权）。
    ///
    /// user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+(连接被撤权收掉之后，
    /// 下一次调用必须报出这个原因，而不是让用户看到一句「连接断开了」)。
    refusal: Arc<Mutex<Option<String>>>,
}

impl Client {
    /// Dials a ticket and completes the hello/welcome exchange.
    ///
    /// `name` is what the peer shows the user; it is not an identity, the key is.
    pub async fn dial(endpoint: &Endpoint, ticket: &str, name: &str) -> Result<Self> {
        // user:“扫码即可完成配对，不给普通用户加额外步骤”+(一张票同时带地址与授权：
        // 扫到的就是它，扫完直接拨号。旧的 sunday1: 票据只说明地址，够已配对设备重连用)。
        let addr: EndpointAddr = crate::ticket::decode_any_ticket(ticket)?;
        let pair = if crate::pair::is_pairing_ticket(ticket) {
            Some(ticket.trim().to_owned())
        } else {
            None
        };
        let conn = endpoint
            .connect(addr.clone(), crate::ALPN)
            .await
            .context("无法连接到对端（可能需要对方在线，或走中继）")?;
        let (mut send, mut recv) = conn.open_bi().await.context("cannot open the tunnel")?;
        write_frame(
            &mut send,
            &Frame::Hello {
                name: name.to_owned(),
                pair,
            },
        )
        .await?;
        let welcome = read_frame(&mut recv).await?;
        let (peer, peer_name) = match welcome {
            Frame::Welcome {
                id,
                name,
                trusted,
                reason,
            } => {
                if !trusted {
                    // user:“重复使用要被拒绝并给出可读原因”+(服务端说为什么，
                    // 这里就显示那个原因；自己另编一句会把「码过期了」说成「被撤销了」)。
                    let reason = reason.trim().to_owned();
                    if reason.is_empty() {
                        bail!("对端没有接受这台设备，请在电脑的「设备连接」页重新生成二维码");
                    }
                    bail!("{reason}");
                }
                (id, name)
            }
            other => bail!("对端先说了别的话：{other:?}"),
        };

        let send = Arc::new(Mutex::new(send));
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Result<serde_json::Value, String>>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let (event_tx, _) = broadcast::channel(EVENT_BUFFER);
        let alive = Arc::new(AtomicBool::new(true));
        let last_pong = Arc::new(AtomicU64::new(now_millis()));
        // 断线只有一个出口：读帧失败或心跳判死时把它置 false，所有在等回复的调用当场返回。
        let (lost_tx, _) = watch::channel(true);
        let lost = Arc::new(lost_tx);

        // One reader for the whole connection: replies go to their caller, events go to
        // subscribers, and a closed stream fails every waiting call instead of hanging.
        let reader_pending = Arc::clone(&pending);
        let reader_events = event_tx.clone();
        let reader_conn = conn.clone();
        let reader_alive = Arc::clone(&alive);
        let reader_pong = Arc::clone(&last_pong);
        let reader_lost = Arc::clone(&lost);
        let refusal: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
        let reader_refusal = Arc::clone(&refusal);
        tauri_free_spawn(async move {
            loop {
                match read_frame(&mut recv).await {
                    Ok(Frame::Reply { id, result }) => {
                        if let Some(sender) = reader_pending.lock().await.remove(&id) {
                            let _ = sender.send(Ok(result));
                        }
                    }
                    Ok(Frame::Error { id, code, message }) => {
                        let message = if code.is_empty() {
                            message
                        } else {
                            format!("[{code}] {message}")
                        };
                        let waiting = reader_pending.lock().await.remove(&id);
                        match waiting {
                            Some(sender) => {
                                let _ = sender.send(Err(message));
                            }
                            // 没有人在等这一条：这是服务端在说「这条连接没权限了」。
                            None => {
                                *reader_refusal.lock().await = Some(message);
                            }
                        }
                    }
                    Ok(Frame::Event { method, params }) => {
                        let _ = reader_events.send(Event { method, params });
                    }
                    Ok(Frame::Pong) => {
                        reader_pong.store(now_millis(), Ordering::SeqCst);
                    }
                    Ok(_) => {}
                    Err(error) => {
                        println!("[sunday-p2p] reader stopped: {error:#}");
                        reader_alive.store(false, Ordering::SeqCst);
                        // user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+
                        // (服务端可能先发一条「这条连接没权限了」再断开；正在等回复的调用
                        // 要用那个原因收尾，而不是笼统的「对端关闭了流」)。
                        let refusal = reader_refusal.lock().await.clone();
                        let message = refusal.unwrap_or_else(|| error.to_string());
                        for (_, sender) in reader_pending.lock().await.drain() {
                            let _ = sender.send(Err(message.clone()));
                        }
                        let _ = reader_lost.send_replace(false);
                        reader_conn.close(0u32.into(), b"closed");
                        return;
                    }
                }
            }
        });

        // 心跳：一条已经静默断掉的连接既不报错也不会自己关闭，只能靠对端回 Pong 证明它还在。
        // user:“显示和电脑断联了”+(没有这条，下一次操作要等 180 秒超时才发现对方已经没了)。
        let ping_send = Arc::clone(&send);
        let ping_alive = Arc::clone(&alive);
        let ping_pong = Arc::clone(&last_pong);
        let ping_conn = conn.clone();
        let ping_lost = Arc::clone(&lost);
        tauri_free_spawn(async move {
            let mut beats: u64 = 0;
            loop {
                tokio::time::sleep(PING_EVERY).await;
                if !ping_alive.load(Ordering::SeqCst) {
                    return;
                }
                let last = ping_pong.load(Ordering::SeqCst);
                if now_millis().saturating_sub(last) > PING_DEAD_AFTER_MILLIS {
                    ping_alive.store(false, Ordering::SeqCst);
                    let _ = ping_lost.send_replace(false);
                    ping_conn.close(0u32.into(), b"heartbeat lost");
                    return;
                }
                // user:“手机端远控电脑连接不稳定，频繁断连”+(写方向正忙说明连接一定活着，
                // 而等锁会让心跳排队；QUIC 的空闲计时不看你是否在排队。拿不到锁就跳过这一轮)。
                let mut send = match ping_send.try_lock() {
                    Ok(guard) => guard,
                    Err(_) => {
                        // user:“手机端远控电脑连接不稳定，频繁断连”+(写锁被占说明这条连接
                        // 正在发真实数据，绝不是死连接；把它当成还活着。否则一次大回复就会
                        // 让心跳连续拿不到锁，60 秒后自己把一条好好的连接关掉)。
                        println!("[sunday-p2p] heartbeat skipped: the write lock is busy");
                        ping_pong.store(now_millis(), Ordering::SeqCst);
                        continue;
                    }
                };
                match write_frame(&mut send, &Frame::Ping).await {
                    Ok(()) => {
                        beats += 1;
                        // 诊断：30 秒一行，看清心跳有没有真的发出去。
                        if beats % 6 == 1 {
                            println!("[sunday-p2p] heartbeat #{beats} sent");
                        }
                    }
                    Err(error) => {
                        println!("[sunday-p2p] heartbeat write failed: {error:#}");
                        ping_alive.store(false, Ordering::SeqCst);
                        let _ = ping_lost.send_replace(false);
                        ping_conn.close(0u32.into(), b"heartbeat write failed");
                        return;
                    }
                }
            }
        });

        Ok(Self {
            conn,
            send,
            pending,
            events: event_tx,
            next_id: AtomicU64::new(1),
            alive,
            lost,
            peer_name,
            peer,
            addr,
            refusal,
        })
    }

    /// 重连用的地址票据：只说明往哪连，不代表授权。
    ///
    /// user:“已授权设备后续能自动重连，不要求每次重新扇”+(`sunday1:` 形式和老版本一样，手机把它存下来，下次直接拨号；授权由可信名单判定)。
    pub fn resume_ticket(&self) -> Result<String> {
        crate::ticket::encode_ticket(&self.addr)
    }

    /// 隧道是否还活着。
    pub fn is_alive(&self) -> bool {
        self.alive.load(Ordering::SeqCst)
    }

    /// 存活标志本身，给宿主做「断了就告诉界面」的监听。
    pub fn alive_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.alive)
    }

    /// One Core-style call. Matched by id, so a slow answer cannot be taken for the next one.
    ///
    /// `&self`：界面的项目、模型、会话是并发加载的，它们不该因为对方回答慢就互相排队。
    pub async fn call(&self, method: &str, params: serde_json::Value) -> Result<serde_json::Value> {
        // 已经断了就别发：写进一个死连接的帧不会有回答，只会让界面白等三分钟。
        if !self.alive.load(Ordering::SeqCst) {
            // user:“撤权后 RPC 一律拒绝，返回明确错误码”+(先报服务端给的原因)。
            if let Some(reason) = self.refusal.lock().await.clone() {
                bail!("{reason}");
            }
            bail!("和电脑的连接已经断开");
        }
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id, tx);
        {
            let mut send = self.send.lock().await;
            write_frame(
                &mut send,
                &Frame::Call {
                    id,
                    method: method.to_owned(),
                    params,
                },
            )
            .await?;
        }
        // user:“手机端远控电脑连接不稳定，频繁断连”+(断线发生在一轮调用中间时，以前这条
        // 调用要等满 180 秒才报超时，用户只看到卡住；现在连接一断就立刻返回，界面能当场
        // 显示断开并开始重连)。
        let mut lost = self.lost.subscribe();
        let mut answer = rx;
        let mut deadline = Box::pin(tokio::time::sleep(Duration::from_secs(180)));
        tokio::select! {
            // user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+(断链信号和拒绝帧
            // 常常同时到达；先看应答，才不会把「已被移除授权」说成「连接断开了」)。
            biased;
            result = &mut answer => match result {
                Ok(Ok(result)) => Ok(result),
                Ok(Err(message)) => bail!("{message}"),
                Err(_) => bail!("连接已关闭"),
            },
            _ = lost.changed() => {
                self.pending.lock().await.remove(&id);
                // 服务端上一刻说过「这条连接没权限了」：把它的原因报出来。
                if let Some(reason) = self.refusal.lock().await.clone() {
                    bail!("{reason}");
                }
                bail!("和电脑的连接断开了：正在重连")
            }
            _ = &mut deadline => {
                self.pending.lock().await.remove(&id);
                bail!("等待对端回答超时")
            }
        }
    }

    /// 这条连接此刻走的是直连还是中继（连接详情里显示）。
    ///
    /// user:“真实路径显示：区分直连/中继”+(每次问都读一次实时快照：打洞可能在连接建立
    /// 几秒后才成功，中继也可能在中途顶上，一次判定写死会一直显示错的)。
    pub fn path(&self) -> PathKind {
        path_kind(&self.conn)
    }

    /// 路径变了就回调一次（客户端侧；与 `ServerLink::watch_path` 对称）。
    pub fn watch_path<F>(&self, on_change: F) -> tokio::task::JoinHandle<()>
    where
        F: FnMut(PathKind) + Send + 'static,
    {
        watch_path_events(self.conn.clone(), on_change)
    }

    /// Events pushed by the far side.
    pub fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.events.subscribe()
    }

    pub fn close(&self) {
        self.alive.store(false, Ordering::SeqCst);
        let _ = self.lost.send_replace(false);
        self.conn.close(0u32.into(), b"done");
    }
}

/// Accepting side, one connection per `accept`, many connections per server.
pub struct ServerLink {
    conn: iroh::endpoint::Connection,
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    recv: iroh::endpoint::RecvStream,
    pub peer: String,
    /// 对方在握手时自称的名字：设备清单里显示它，而不是一串节点 id。
    ///
    /// user:“设备切换：多设备时切换当前连接”+(没有名字的话，两台设备的列表只能显示
    /// 两串十六进制，用户没法选对)。
    pub peer_name: String,
    pub trusted: bool,
    /// 可信名单。活跃连接每条调用前都要用它复核一次。
    trust: Arc<Mutex<TrustStore>>,
}

/// 活跃连接多久复核一次。
///
/// user:“用户移除设备后，当前已建立的连接立刻失去操作权限”+(每次调用前都会查；这条定时器负责
/// 「撤销之后对面什么都不做」的情况，让它最多一秒就被断开，而不是一直挂着)。
const REAUTHORIZE_EVERY: Duration = Duration::from_secs(1);

/// 拒绝说明送出之后、真正断链之前留的时间。
///
/// `Connection::close` 不会为已排队但未送达的流数据等一轮确认，紧接着关闭会让对端
/// 只看到「连接断开」而看不到错误码。
const REFUSAL_GRACE: Duration = Duration::from_millis(400);

/// 这条连接现在还能不能调用 Core。
async fn reauthorize(
    trust: &Arc<Mutex<TrustStore>>,
    peer: &str,
) -> Result<(), (&'static str, String)> {
    let mut store = trust.lock().await;
    // user:“撤权同步两处状态：持久信任记录（磁盘）+ 当前活跃连接（内存）”+
    // (宿主改的是磁盘上那份，这里每次都看一眼它有没有变)。
    store.reload_if_stale().ok();
    crate::gate::authorize(&store, peer)
}

impl ServerLink {
    /// Waits for one connection and runs the handshake.
    ///
    /// `Ok(None)` 表示端点已经关了，调用方该收工；握手失败则是 `Err`——一次失败只说明
    /// 那一次没成就，不能让调用方连带退出。手机在超时后放弃拨号时，留下的那次握手会
    /// 在服务端超时，这属于正常现象。
    pub async fn accept(
        endpoint: &Endpoint,
        trust: Arc<Mutex<TrustStore>>,
        grants: Arc<Mutex<crate::pair::PairingGrants>>,
        name: &str,
    ) -> Result<Option<Self>> {
        let Some(connecting) = endpoint.accept().await else {
            return Ok(None);
        };
        let conn = connecting.await.context("handshake failed")?;
        let peer = conn.remote_id().to_string();
        let (mut send, mut recv) = conn.accept_bi().await.context("no tunnel stream")?;
        let (peer_name, pair) = match read_frame(&mut recv).await? {
            Frame::Hello { name, pair } => (name, pair),
            other => bail!("expected hello, got {other:?}"),
        };
        let server_id = endpoint.id().to_string();
        let admission = {
            let mut store = trust.lock().await;
            // user:“撤销设备要真的生效”+(宿主撤销时改的是名单文件，传输进程手里是启动时
            // 读的那份内存副本；不重读就会出现「列表里没了、那台设备还能连」。
            // 每次握手前按文件时间戳重读一次，文件很小)。
            store.reload_if_stale().ok();
            let mut grants = grants.lock().await;
            let now = crate::pair::now();
            let admission = crate::gate::admit(
                &mut store,
                &mut grants,
                &server_id,
                &peer,
                &peer_name,
                pair.as_deref(),
                now,
            );
            if admission.is_accepted() {
                // user:“撤权同步两处状态”+(握手这一次决定要落盘；活跃连接读的是同一个文件)。
                grants.prune(now);
                grants.save().ok();
                store.save().ok();
            } else {
                // 用过的票也要落盘，否则进程重启后同一张码又能用。
                grants.prune(now);
                grants.save().ok();
            }
            admission
        };
        let trusted = admission.is_accepted();
        let reason = match &admission {
            crate::gate::Admission::Rejected { reason, .. } => reason.clone(),
            _ => String::new(),
        };
        write_frame(
            &mut send,
            &Frame::Welcome {
                id: server_id,
                name: name.to_owned(),
                trusted,
                reason,
            },
        )
        .await?;
        // user:“撤销设备要真的生效”+(不要在这一帧之后立刻断开：连接一关，对端可能还没读到
        // 这个 Welcome，只能看到「closed by peer」。让这一帧走到、由调用方决定怎么收尾)。
        Ok(Some(Self {
            conn,
            send: Arc::new(Mutex::new(send)),
            recv,
            peer,
            peer_name,
            trusted,
            trust: Arc::clone(&trust),
        }))
    }

    /// 这条连接此刻走的是直连还是中继（宿主显示在连接详情里）。
    pub fn path(&self) -> PathKind {
        path_kind(&self.conn)
    }

    /// 路径变了就回调一次（直连打洞成功、退回中继、断开）。
    ///
    /// user:“真实路径显示：区分直连/中继”+(打洞是异步的：连接刚建立时可能先走中继，
    /// 几秒后才切到直连。用 iroh 自己的 `path_events` 事件流，而不是定时轮询——没有变化
    /// 就没有唤醒)。返回的句柄随连接关闭自然结束，调用方不需要管理。
    pub fn watch_path<F>(&self, on_change: F) -> tokio::task::JoinHandle<()>
    where
        F: FnMut(PathKind) + Send + 'static,
    {
        watch_path_events(self.conn.clone(), on_change)
    }

    /// Pushes one event to the far side.
    pub async fn send_event(&self, method: &str, params: serde_json::Value) -> Result<()> {
        write_event(&self.send, method, params).await
    }

    /// The write half, for a task that pushes events while `serve` answers calls.
    ///
    /// Frames are written under the same lock, so an event never lands in the middle of a
    /// reply.
    pub fn sender(&self) -> Arc<Mutex<iroh::endpoint::SendStream>> {
        Arc::clone(&self.send)
    }

    /// Serves calls until the peer hangs up, answering with `handler`.
    ///
    /// 每条 Call 各自成任务、谁先答完谁先回，不再一条慢调用挡住后面的全部加载。
    /// user:“远程的时候打开界面要等很久”+(界面启动会并发读项目、模型、设置、大纲；
    /// 以前服务端逐条 await，一条冷启动的写在前面，后面全在排队)。
    pub async fn serve<F, Fut>(self, handler: F) -> Result<()>
    where
        F: Fn(String, serde_json::Value) -> Fut,
        Fut: std::future::Future<Output = Result<serde_json::Value>>,
    {
        let send = Arc::clone(&self.send);
        let trust = Arc::clone(&self.trust);
        let peer = self.peer.clone();
        let mut recv = self.recv;
        // user:“手机端远控电脑连接不稳定，频繁断连”+(读帧以前直接放在 select! 里，另一条
        // 分支先完成时这个 future 会被取消；QUIC 不接受这种取消，已经读走的那半个帧就丢了，
        // 下一次把半个体的字节当成帧头，读位置从此错乱，服务端会卡在一个永远读不满的长度
        // 上。手机端的写窗口随之堵住，心跳发不出去，最后以「对端长时间没有任何帧」收场。
        // 现在读帧放进独立任务，谁也不取消它；帧通过通道交回主循环)。
        let (frames, mut incoming) = tokio::sync::mpsc::channel::<Result<Frame>>(8);
        let reader = tokio::spawn(async move {
            loop {
                let frame = read_frame(&mut recv).await;
                let failed = frame.is_err();
                if frames.send(frame).await.is_err() {
                    break;
                }
                if failed {
                    break;
                }
            }
        });

        let mut inflight: FuturesUnordered<_> = FuturesUnordered::new();
        // 诊断：服务端到底有没有收到心跳。
        let mut pings: u64 = 0;
        // 写也走独立任务：一条几十 MB 的回复不该把读循环按在写上。
        let (outbox, mut outbox_rx) = tokio::sync::mpsc::channel::<Frame>(32);
        let send_for_writer = Arc::clone(&send);
        let writer = tokio::spawn(async move {
            while let Some(frame) = outbox_rx.recv().await {
                let mut send = send_for_writer.lock().await;
                if write_frame(&mut send, &frame).await.is_err() {
                    return;
                }
            }
        });

        let outcome: Result<()> = loop {
            tokio::select! {
                incoming_frame = tokio::time::timeout(IDLE_TIMEOUT, incoming.recv()) => {
                    match incoming_frame {
                        // 两分钟一个帧都没有：对端已经不在了，收掉这条连接等它重连。
                        Err(_) => break Err(anyhow::anyhow!("对端长时间没有任何帧（心跳超时）")),
                        // 读任务结束：对端干净关闭，或读失败，都不值得记成错误。
                        Ok(None) => break Ok(()),
                        Ok(Some(Err(_))) => break Ok(()),
                        Ok(Some(Ok(frame))) => match frame {
                            Frame::Call { id, method, params } => {
                                // user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+
                                // (每条调用前都问一次名单；拒绝时这条调用拿到错误码，
                                // 然后连接被收掉，不会变成一条“没反应”。)
                                if let Err((code, reason)) = reauthorize(&trust, &peer).await {
                                    // 直接写，不走 outbox：这条连接马上要关，排队的那一帧
                                    // 可能随着写任务被 abort 一起丢掉，对端就只看到断开。
                                    let refusal = Frame::Error {
                                        id,
                                        code: code.to_owned(),
                                        message: reason.clone(),
                                    };
                                    {
                                        let mut guard = send.lock().await;
                                        let _ = write_frame(&mut guard, &refusal).await;
                                    }
                                    // user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+
                                    // (写完立刻 close 会让这一帧在 QUIC 里被丢掉，对端就又只看到
                                    // 「连接断开了」；留一小段时间让它落地)。
                                    tokio::time::sleep(REFUSAL_GRACE).await;
                                    break Err(anyhow::anyhow!("{code}: {reason}"));
                                }
                                let answer = handler(method, params);
                                inflight.push(async move { (id, answer.await) });
                            }
                            Frame::Ping => {
                                // 队列满说明对端根本没在读：当场收掉，总比在这里等到超时好。
                                if outbox.try_send(Frame::Pong).is_err() {
                                    break Err(anyhow::anyhow!("对端来不及接收，先断开让它重连"));
                                }
                                pings += 1;
                                if pings % 6 == 1 {
                                    println!("[sunday-p2p] ping #{pings} received");
                                }
                            }
                            Frame::Hello { .. } | Frame::Welcome { .. } => {
                                break Err(anyhow::anyhow!("在一次连接里重复握手"));
                            }
                            other => break Err(anyhow::anyhow!("意外的帧：{other:?}")),
                        },
                    }
                }
                // 对面什么都不发的时候也要能被撤权断开。
                _ = tokio::time::sleep(REAUTHORIZE_EVERY) => {
                    if let Err((code, reason)) = reauthorize(&trust, &peer).await {
                        // user:“撤权后 RPC 一律拒绝，返回明确错误码，不静默通过”+
                        // (对面这一刻可能什么都没在调；先把「为什么」发过去再断开，
                        // 否则它只看到连接断了，会当成网络问题不停重连)。
                        let notice = Frame::Error {
                            id: 0,
                            code: code.to_owned(),
                            message: reason.clone(),
                        };
                        {
                            let mut guard = send.lock().await;
                            let _ = write_frame(&mut guard, &notice).await;
                        }
                        tokio::time::sleep(REFUSAL_GRACE).await;
                        break Err(anyhow::anyhow!("{code}: {reason}"));
                    }
                }
                Some((id, answer)) = inflight.next(), if !inflight.is_empty() => {
                    let reply = match answer {
                        Ok(result) => Frame::Reply { id, result },
                        Err(error) => Frame::Error {
                            id,
                            code: String::new(),
                            message: error.to_string(),
                        },
                    };
                    if outbox.try_send(reply).is_err() {
                        break Err(anyhow::anyhow!("对端来不及接收，先断开让它重连"));
                    }
                }
            }
        };

        drop(outbox);
        writer.abort();
        reader.abort();
        self.conn.close(0u32.into(), b"done");
        outcome
    }

    pub fn close(&self) {
        self.conn.close(0u32.into(), b"done");
    }
}

/// Writes one event frame through a shared write half.
pub async fn write_event(
    send: &Arc<Mutex<iroh::endpoint::SendStream>>,
    method: &str,
    params: serde_json::Value,
) -> Result<()> {
    let mut send = send.lock().await;
    write_frame(
        &mut send,
        &Frame::Event {
            method: method.to_owned(),
            params,
        },
    )
    .await
}

/// 订阅一条连接的路径事件流：先报一次当前状态，之后只在真的变了才回调。
fn watch_path_events<F>(conn: iroh::endpoint::Connection, mut on_change: F) -> tokio::task::JoinHandle<()>
where
    F: FnMut(PathKind) + Send + 'static,
{
    tokio::spawn(async move {
        use futures_util::StreamExt as _;
        let mut events = conn.path_events();
        let mut last = path_kind(&conn);
        on_change(last);
        while events.next().await.is_some() {
            let current = path_kind(&conn);
            if current != last {
                last = current;
                on_change(current);
            }
        }
    })
}

/// Spawns a task on whatever async runtime is current.
///
/// The crate is used from Tauri's runtime and from the CLI's; `tokio::spawn` needs the
/// caller to have entered a runtime, which both do.
fn tauri_free_spawn<F>(future: F)
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    tokio::spawn(future);
}

#[cfg(test)]
mod tests {
    use super::*;

    /// user:“真实路径显示：区分直连/中继”+(当前选中的那条说了算：正在用中继时，
    /// 旁边挂着一条还没承载数据的直连路径不等于「现在是直连」)。
    #[test]
    fn the_selected_path_decides_and_not_a_spare_candidate() {
        assert_eq!(
            classify_path(false, true, true, true),
            PathKind::Relay,
            "流量在中继上时不能因为存在直连候选就说直连"
        );
        assert_eq!(
            classify_path(true, false, true, true),
            PathKind::Direct
        );
    }

    /// 还没选中（握手早期）时按可用路径给个倾向，绝不假装成 Unknown 卡住界面。
    #[test]
    fn before_selection_any_usable_path_decides() {
        assert_eq!(classify_path(false, false, true, false), PathKind::Direct);
        assert_eq!(classify_path(false, false, false, true), PathKind::Relay);
        assert_eq!(classify_path(false, false, true, true), PathKind::Direct);
    }

    /// 一条路径都没有（刚连上、全都没建成）就是「正在判定」，不是任何一种。
    #[test]
    fn no_path_at_all_is_unknown() {
        assert_eq!(classify_path(false, false, false, false), PathKind::Unknown);
    }

    /// 标识是给界面、日志与状态通道用的稳定词，来回翻不能变形。
    #[test]
    fn the_labels_round_trip() {
        for kind in [PathKind::Direct, PathKind::Relay, PathKind::Unknown] {
            assert_eq!(PathKind::from_str(kind.as_str()), kind);
        }
        assert_eq!(PathKind::from_str(""), PathKind::Unknown);
        assert_eq!(PathKind::from_str("DIRECT"), PathKind::Unknown);
    }
}
