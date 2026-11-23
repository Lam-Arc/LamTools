//! 连接状态分层：网络、设备认证、Core、会话各说各话，界面只认最后的「能不能用」。
//!
//! user:“把状态拆成可区分的层：网络可达 / 设备已认证 / Core 就绪 / 会话已恢复”“只有业务
//! 真正可用才显示「已连接电脑」；Core 无响应时必须降级显示，不能继续显示正常”+(以前只有
//! 一个 `connected` 布尔：隧道还在就显示已连接，电脑那边的 Core 已经被杀掉了，界面照样说
//! 连接正常，用户每发一条消息都失败，却看不出为什么)。
//!
//! 这一层不碰网络：输入是四个事实，输出是一个可展示的结论和一句原因。宿主、手机、CLI
//! 都用它，测试也不需要真的连一台设备。

/// 设备认证这一层。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceLayer {
    /// 还没配对过，也没有可用的地址票。
    Unpaired,
    /// 配对过（可信名单里有它），但这条连接还没握手成功。
    Paired,
    /// 这条连接已经握手并确认可信。
    Authenticated,
}

/// 对端 Core 这一层。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreLayer {
    /// 还没探测过。
    Unknown,
    /// 探测通过（/api/health 有应答）。
    Ready,
    /// 探测失败：进程不在、端口换了、或者卡住了。
    Down,
}

/// 会话（工作台）这一层。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionLayer {
    /// 还没恢复会话，界面没有可用的线程上下文。
    NotResumed,
    /// 已经按 `last_seen_seq` 补过事件，界面可以正常读写。
    Resumed,
}

/// 四个事实。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Layers {
    /// 隧道本身通不通（QUIC 连接活着）。
    pub transport: bool,
    pub device: DeviceLayer,
    pub core: CoreLayer,
    pub session: SessionLayer,
}

impl Default for Layers {
    fn default() -> Self {
        Self {
            transport: false,
            device: DeviceLayer::Unpaired,
            core: CoreLayer::Unknown,
            session: SessionLayer::NotResumed,
        }
    }
}

/// 给用户看的结论。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum View {
    /// 没有要连的对端（或用户切回了本机）。
    Offline,
    /// 正在连：还没握手，或者握手了但 Core 还没就绪。
    Connecting,
    /// 业务真的可用：隧道、认证、Core、会话四层都成立。
    Connected,
    /// 有一部分不成立，但还在尝试：必须显示降级原因，不能显示成连上了。
    Degraded { reason: Reason },
}

/// 降级原因（可翻译，也方便脚本断言）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    /// 隧道断了。
    TransportDown,
    /// 对端没有接受这台设备（未配对/被撤权）。
    DeviceRejected,
    /// 电脑上的 Sunday 没响应。
    CoreUnavailable,
    /// 隧道和 Core 都在，但会话还没恢复。
    SessionNotResumed,
}

impl View {
    /// 给界面分阶段用的名字（与 `view` 同义，但把「降级」拆出可读阶段）。
    ///
    /// user:“配对/连接/恢复会话分阶段可见”+(界面按这些阶段换文案：
    /// waiting=在等对方连进来，connecting=握手或恢复会话，connected=真的可用，
    /// degraded=有一层不成立，offline=没有在连)。
    pub fn phase(&self) -> &'static str {
        match self {
            Self::Offline => "offline",
            Self::Connecting => "connecting",
            Self::Connected => "connected",
            Self::Degraded { .. } => "degraded",
        }
    }
}

impl Reason {
    /// 一句话原因：界面直接显示，用户能看懂为什么不是「已连接」。
    pub fn explain(&self) -> &'static str {
        match self {
            Self::TransportDown => "和电脑的连接断了",
            Self::DeviceRejected => "这台设备没有被电脑接受（可能已被移除授权）",
            Self::CoreUnavailable => "电脑上的 Sunday 没有响应",
            Self::SessionNotResumed => "正在恢复会话",
        }
    }

    /// 稳定的机器标识，日志与脚本用它，不用匹配中文。
    pub fn code(&self) -> &'static str {
        match self {
            Self::TransportDown => "transport_down",
            Self::DeviceRejected => "device_rejected",
            Self::CoreUnavailable => "core_unavailable",
            Self::SessionNotResumed => "session_not_resumed",
        }
    }
}

impl Layers {
    /// 业务是否真的可用。
    ///
    /// user:“只有业务真正可用才显示「已连接电脑」”+(隧道通、设备可信、Core 有应答、
    /// 会话已恢复，四件事同时成立才算连上；少一件都只是「正在连」或「降级」)。
    pub fn usable(&self) -> bool {
        self.transport
            && self.device == DeviceLayer::Authenticated
            && self.core == CoreLayer::Ready
            && self.session == SessionLayer::Resumed
    }

    /// 当前该显示什么。
    pub fn view(&self) -> View {
        if !self.transport {
            return View::Offline;
        }
        if self.device != DeviceLayer::Authenticated {
            // 握手都没成：要么在连，要么被拒。被判过死刑（撤权）的由调用方标记为降级。
            return match self.device {
                DeviceLayer::Unpaired => View::Connecting,
                DeviceLayer::Paired => View::Connecting,
                DeviceLayer::Authenticated => View::Connecting,
            };
        }
        match self.core {
            CoreLayer::Unknown => View::Connecting,
            CoreLayer::Down => View::Degraded {
                reason: Reason::CoreUnavailable,
            },
            CoreLayer::Ready => match self.session {
                SessionLayer::NotResumed => View::Connecting,
                SessionLayer::Resumed => View::Connected,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn all_ok() -> Layers {
        Layers {
            transport: true,
            device: DeviceLayer::Authenticated,
            core: CoreLayer::Ready,
            session: SessionLayer::Resumed,
        }
    }

    /// user:“只有业务真正可用才显示「已连接电脑」”+(四层齐了才是连上)。
    #[test]
    fn only_a_fully_working_stack_counts_as_connected() {
        assert_eq!(all_ok().view(), View::Connected);
        assert!(all_ok().usable());
    }

    /// user:“Core 无响应时必须降级显示，不能继续显示正常”+(隧道还在也不行)。
    #[test]
    fn a_dead_core_degrades_instead_of_claiming_connected() {
        let layers = Layers {
            core: CoreLayer::Down,
            ..all_ok()
        };
        assert_eq!(
            layers.view(),
            View::Degraded {
                reason: Reason::CoreUnavailable
            }
        );
        assert!(!layers.usable());
        assert_eq!(Reason::CoreUnavailable.explain(), "电脑上的 Sunday 没有响应");
    }

    /// 隧道断了就是断了，不能显示「正在恢复会话」这种好听的话。
    #[test]
    fn a_dead_tunnel_is_offline_not_connected() {
        let layers = Layers {
            transport: false,
            ..all_ok()
        };
        assert_eq!(layers.view(), View::Offline);
    }

    /// 会话还没恢复：这是「正在连」，不是「已连接」。
    #[test]
    fn an_unresumed_session_is_still_connecting() {
        let layers = Layers {
            session: SessionLayer::NotResumed,
            ..all_ok()
        };
        assert_eq!(layers.view(), View::Connecting);
        assert!(!layers.usable());
    }

    /// 未知的 Core 状态不能乐观地当成正常。
    #[test]
    fn an_unknown_core_never_claims_connected() {
        let layers = Layers {
            core: CoreLayer::Unknown,
            ..all_ok()
        };
        assert_eq!(layers.view(), View::Connecting);
        assert!(!layers.usable());
    }

    /// 握手没完成时算「正在连」，不是「已连接」。
    #[test]
    fn an_unauthenticated_tunnel_is_connecting() {
        let layers = Layers {
            device: DeviceLayer::Paired,
            ..all_ok()
        };
        assert_eq!(layers.view(), View::Connecting);
        assert!(!layers.usable());
    }

    /// user:“配对/连接/恢复会话分阶段可见”+(阶段名稳定，界面按它换文案)。
    #[test]
    fn every_view_has_a_stable_phase_name() {
        assert_eq!(View::Offline.phase(), "offline");
        assert_eq!(View::Connecting.phase(), "connecting");
        assert_eq!(View::Connected.phase(), "connected");
        assert_eq!(
            View::Degraded {
                reason: Reason::CoreUnavailable
            }
            .phase(),
            "degraded"
        );
        // 降级不因为原因不同而换阶段名；原因另有 `code()`。
        assert_eq!(
            View::Degraded {
                reason: Reason::TransportDown
            }
            .phase(),
            "degraded"
        );
    }

    /// 原因码稳定：脚本与日志断言不依赖中文文案。
    #[test]
    fn reasons_have_stable_codes() {
        assert_eq!(Reason::TransportDown.code(), "transport_down");
        assert_eq!(Reason::DeviceRejected.code(), "device_rejected");
        assert_eq!(Reason::CoreUnavailable.code(), "core_unavailable");
        assert_eq!(Reason::SessionNotResumed.code(), "session_not_resumed");
    }
}
