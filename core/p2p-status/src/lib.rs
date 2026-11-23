//! 传输进程 → 宿主的结构化状态通道。
//!
//! user:“SESSION 依赖解析子进程 stdout 文本（弱契约）→ 改为结构化状态通道（或至少加版本
//! 前缀 + 解析失败即明确报错，不要静默）”+(以前宿主靠 `SESSION <id>`、`PEER <id>
//! trusted=true`、`PEER-CLOSED <id>` 这些自由文本认连接走到哪一步：加一个字段就要改切
//! 空格的下标，改错一个位置就是「界面上一直显示没连上」，而日志里看不出任何异常)。
//!
//! 现在的契约是：一行一条，前缀带版本号，后面是 JSON。三条规矩：
//!
//! 1. 老版本会继续打印旧的自由文本行（别的脚本还在读），宿主只认带前缀的行；
//! 2. 前缀对但内容坏掉 = 明确的错误（`StatusError`），调用方必须报出来，不能当成「没有
//!    这条状态」；
//! 3. 没有前缀的行不是状态行（`None`），不是错误。
//!
//! 这一层不碰网络、不碰进程：它只是把「一行」这件事定死，两端各引一份同一实现。

use serde::{Deserialize, Serialize};

/// 状态行的版本前缀。
///
/// 带空格结尾：`SUNDAY-P2P/1 {...}`，这样用 `strip_prefix` 就能拿到纯 JSON，不需要再
/// 猜分隔符。以后字段大改就换成 `/2`，老宿主会因为版本不认识而报错，而不是把新字段当
/// 旧字段用。
pub const PREFIX: &str = "SUNDAY-P2P/1 ";

/// 一条状态。
///
/// `event` 是稳定标识（脚本与界面都用它判断，不用匹配中文），其余字段按事件各自定义。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum StatusEvent {
    /// 出了一张新票据（网络切换会重新出票，旧码当场作废）。
    Ticket {
        ticket: String,
        expires_at: u64,
    },
    /// 中继信息（只用于排障展示）。
    Relay { summary: String },
    /// 一台设备连上来了（握手通过或未通过都会说）。
    Peer {
        peer: String,
        #[serde(default)]
        name: String,
        #[serde(default)]
        trusted: bool,
        /// `direct` / `relay` / `unknown`；还没判定出来是空串。
        #[serde(default)]
        path: String,
    },
    /// 一条连接收掉了。
    PeerClosed {
        peer: String,
        /// 空表示对端正常断开；否则是收掉它的原因。
        #[serde(default)]
        reason: String,
    },
    /// 对端在这条连接上完成了 `initialize`：业务真的可用了。
    Session { peer: String },
    /// 这条连接走的路径变了（直连打洞成功、退回中继，或者反过来）。
    Path { peer: String, path: String },
    /// 一次文件互传的进度（发送或接收）。
    ///
    /// user:“发送与接收都要有可观察进度（百分比或已传字节）”+(宿主拿到这条就发
    /// `p2p-transfer`，界面不需要自己猜传输到哪一步；字段名与 `transfer::Progress`
    /// 完全一致，两边对不上会在这里被序列化测试抓住)。
    Transfer {
        transfer_id: String,
        /// `send` / `receive`：这一行是传输进程视角的方向。
        direction: String,
        name: String,
        total: u64,
        transferred: u64,
        percent: u8,
        /// `offered` / `transferring` / `completed` / `failed` / `cancelled`。
        state: String,
        #[serde(default)]
        code: String,
        #[serde(default)]
        message: String,
        #[serde(default)]
        path: String,
    },
    /// 一个文件已经落盘（接收端）。
    ///
    /// user:“收到文件后落盘到约定目录，登记为 artifact 条目，并给出「打开预览/所在文件夹」
    /// 的入口”+(宿主只认这一条来登记资料库；它比 `transfer.state=completed` 多带了
    /// `peer`，因为资料库要记清是谁发来的)。
    Received {
        transfer_id: String,
        path: String,
        name: String,
        size: u64,
        #[serde(default)]
        peer: String,
        #[serde(default)]
        from: String,
    },
    /// Core 这一层的事实（宿主用它决定是否降级，不用自己去猜）。
    Core { state: String },
}

/// 解析一条状态行失败的原因。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StatusError {
    /// 前缀是这一版，但后面的内容不是合法 JSON / 不是已知事件。
    Malformed(String),
    /// 前缀的版本号不是这一版认识的（升级/降级混跑时会出现）。
    UnknownVersion(String),
}

impl std::fmt::Display for StatusError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(detail) => write!(formatter, "状态行内容不合法：{detail}"),
            Self::UnknownVersion(version) => {
                write!(formatter, "不认识的状态通道版本：{version}")
            }
        }
    }
}

impl std::error::Error for StatusError {}

impl StatusEvent {
    /// 这一条该打印成的那一行（含版本前缀与换行）。
    pub fn render(&self) -> String {
        let body = serde_json::to_string(self).unwrap_or_else(|_| "{}".to_owned());
        format!("{PREFIX}{body}\n")
    }

    /// 稳定标识，日志和断言用它。
    pub fn name(&self) -> &'static str {
        match self {
            Self::Ticket { .. } => "ticket",
            Self::Relay { .. } => "relay",
            Self::Peer { .. } => "peer",
            Self::PeerClosed { .. } => "peer_closed",
            Self::Session { .. } => "session",
            Self::Path { .. } => "path",
            Self::Transfer { .. } => "transfer",
            Self::Received { .. } => "received",
            Self::Core { .. } => "core",
        }
    }
}

/// 解析一行。
///
/// - `None`：这一行不是状态行（旧格式的自由文本、日志尾巴等等）；
/// - `Some(Err(..))`：**看起来**是状态行但坏了。调用方必须报错，不能跳过。
pub fn parse_line(line: &str) -> Option<Result<StatusEvent, StatusError>> {
    let trimmed = line.trim_end_matches(['\r', '\n']);
    let Some(rest) = trimmed.strip_prefix("SUNDAY-P2P/") else {
        return None;
    };
    let (version, body) = match rest.split_once(' ') {
        Some((version, body)) => (version, body),
        // 只有 `SUNDAY-P2P/` 没有版本号与内容：这明显是想发状态行但发坏了。
        None => {
            return Some(Err(StatusError::UnknownVersion(rest.trim().to_owned())));
        }
    };
    if version != "1" {
        return Some(Err(StatusError::UnknownVersion(version.to_owned())));
    }
    match serde_json::from_str::<StatusEvent>(body) {
        Ok(event) => Some(Ok(event)),
        Err(error) => Some(Err(StatusError::Malformed(error.to_string()))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 每一种状态都能原样走一圈：宿主拿到的字段就是传输进程写下的字段。
    #[test]
    fn every_event_survives_a_round_trip() {
        let events = [
            StatusEvent::Ticket {
                ticket: "sunday2:abc".to_owned(),
                expires_at: 1_700_000_000,
            },
            StatusEvent::Relay {
                summary: "relay.example:443".to_owned(),
            },
            StatusEvent::Peer {
                peer: "node-id".to_owned(),
                name: "我的电脑".to_owned(),
                trusted: true,
                path: "direct".to_owned(),
            },
            StatusEvent::PeerClosed {
                peer: "node-id".to_owned(),
                reason: "device_revoked".to_owned(),
            },
            StatusEvent::Session {
                peer: "node-id".to_owned(),
            },
            StatusEvent::Path {
                peer: "node-id".to_owned(),
                path: "relay".to_owned(),
            },
            StatusEvent::Transfer {
                transfer_id: "t-1".to_owned(),
                direction: "receive".to_owned(),
                name: "a.txt".to_owned(),
                total: 200,
                transferred: 50,
                percent: 25,
                state: "transferring".to_owned(),
                code: String::new(),
                message: String::new(),
                path: String::new(),
            },
            StatusEvent::Received {
                transfer_id: "t-1".to_owned(),
                path: "C:/recv/2026-11-17/a.txt".to_owned(),
                name: "a.txt".to_owned(),
                size: 200,
                peer: "node-id".to_owned(),
                from: "手机".to_owned(),
            },
            StatusEvent::Core {
                state: "down".to_owned(),
            },
        ];
        for event in events {
            let line = event.render();
            assert!(line.starts_with(PREFIX), "每一条都带版本前缀：{line}");
            assert!(line.ends_with('\n'));
            let parsed = parse_line(&line)
                .expect("带前缀的行必须被当成状态行")
                .expect("自己写出来的行必须解析得回来");
            assert_eq!(parsed, event);
        }
    }

    /// user:“解析失败即明确报错，不要静默”+(前缀对、内容坏 → 出错，不能当成「没有状态」)。
    #[test]
    fn a_broken_line_behind_the_prefix_is_an_error_not_a_silent_skip() {
        let broken = format!("{PREFIX}{{\"event\":\"peer\"");
        match parse_line(&broken) {
            Some(Err(StatusError::Malformed(_))) => {}
            other => panic!("坏行必须报 Malformed，实际：{other:?}"),
        }
        // 已知前缀但不认识的事件名同样不能被当成「没事」。
        let unknown = format!("{PREFIX}{{\"event\":\"teleport\"}}");
        assert!(matches!(
            parse_line(&unknown),
            Some(Err(StatusError::Malformed(_)))
        ));
    }

    /// 版本不认识就要说版本不认识：两种版本混跑时，报错比猜字段安全。
    #[test]
    fn another_version_is_reported_as_a_version_problem() {
        assert_eq!(
            parse_line("SUNDAY-P2P/2 {\"event\":\"session\",\"peer\":\"x\"}"),
            Some(Err(StatusError::UnknownVersion("2".to_owned())))
        );
        assert_eq!(
            parse_line("SUNDAY-P2P/"),
            Some(Err(StatusError::UnknownVersion("".to_owned())))
        );
    }

    /// 旧格式的自由文本行不是状态行，也不是错误（两版同时打印时宿主只认新行）。
    #[test]
    fn legacy_free_text_is_not_a_status_line_and_not_an_error() {
        assert_eq!(parse_line("SESSION node-id\n"), None);
        assert_eq!(parse_line("PEER node-id trusted=true"), None);
        assert_eq!(parse_line(""), None);
    }

    /// JSON 里没有 `event` 就没有意义：宁可报错，也不要静默给一个空状态。
    #[test]
    fn a_payload_without_an_event_name_is_rejected() {
        let line = format!("{PREFIX}{{\"peer\":\"x\"}}");
        assert!(matches!(
            parse_line(&line),
            Some(Err(StatusError::Malformed(_)))
        ));
    }
}
