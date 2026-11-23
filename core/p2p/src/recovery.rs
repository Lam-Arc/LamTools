//! 断线恢复与发送回执：什么时候重试、凭什么不重复写、什么才算送达。
//!
//! user:“自动恢复：Wi-Fi/移动网络切换、电脑休眠唤醒、Core 重启后自动恢复”“短暂断线尽量
//! 无感（不弹提示），持续异常才轻量提示”+(恢复不是「一直重试」，也不是「试一次就放弃」：
//! 先快后慢、有上限，短断线把提示压住，超过阈值才让用户知道)。
//!
//! user:“未确认送达不得显示发送成功”“断线恢复后不得重复执行写操作（幂等键要落地）”“不
//! 确定送达时先查询状态，不盲目重发”+(所以外发记录只有四种状态：未知、在途、已被接受、
//! 失败；只有「已被接受」能显示成已发送，而重发永远复用同一个幂等键)。

use std::collections::BTreeMap;
use std::time::Duration;

/// 重试节奏：先快后慢，有上限，重试次数也有上限。
///
/// 蜂窝网络切换、电脑休眠唤醒通常几秒内就能回去；超过这个窗口还没成，多半是电脑关机
/// 或者被撤权，继续每 100ms 撞一次只会耗电。
#[derive(Debug, Clone)]
pub struct Backoff {
    attempt: u32,
    base: Duration,
    cap: Duration,
    max_attempts: u32,
    /// 连续失败超过这么久才值得提示用户。
    notify_after: Duration,
}

impl Default for Backoff {
    fn default() -> Self {
        Self {
            attempt: 0,
            base: Duration::from_secs(1),
            cap: Duration::from_secs(30),
            max_attempts: 10,
            notify_after: Duration::from_secs(20),
        }
    }
}

impl Backoff {
    pub fn new(base: Duration, cap: Duration, max_attempts: u32, notify_after: Duration) -> Self {
        Self {
            attempt: 0,
            base,
            cap,
            max_attempts,
            notify_after,
        }
    }

    /// 已经试过几次。
    pub fn attempt(&self) -> u32 {
        self.attempt
    }

    /// 这一次用完后，下一次等多久；`None` 表示该放弃了。
    ///
    /// user:“持续异常才轻量提示”+(翻倍到上限就一直按上限试，直到次数用完)。
    pub fn next_delay(&mut self) -> Option<Duration> {
        if self.attempt >= self.max_attempts {
            return None;
        }
        let delay = self.base.saturating_mul(1u32 << self.attempt.min(16)).min(self.cap);
        self.attempt += 1;
        Some(delay)
    }

    /// 连上了：下一次失败重新从最短间隔开始。
    pub fn reset(&mut self) {
        self.attempt = 0;
    }

    /// 连续中断多久才提示用户：短断线无感，长断线才说话。
    ///
    /// user:“短暂断线尽量无感（不弹提示）”+(界面自己决定提示时机，策略放在这里，
    /// 两端共用一份，测试也不用真的等 20 秒)。
    pub fn should_notify(&self, uninterrupted: Duration) -> bool {
        uninterrupted >= self.notify_after
    }

    pub fn notify_after(&self) -> Duration {
        self.notify_after
    }
}

/// 一条外发操作的送达状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Delivery {
    /// 不知道有没有到（断线、超时）：**不能**当成已发送。
    Unknown,
    /// 已经在路上，还没有回执。
    Pending,
    /// 对端给了接受回执（例如 `turn/accepted`）。
    Acknowledged,
    /// 确定失败。
    Failed,
}

/// 同一次发送的两种结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SendStart {
    /// 这次是新写。
    New,
    /// 同一个幂等键已经在路上：不要再写一次，等回执即可。
    Duplicate,
}

/// 重连之后「先查状态」的结论。
///
/// user:“不确定送达时先查询状态，不盲目重发”+(只有三种收尾：对端日志里已经有这条
/// →算送达、绝不重发；确认没有→可以用同一个幂等键重发；查不出来→维持未知，既不
/// 说发成功，也不偷偷再写一遍)。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reconcile {
    /// 对端已经有这条：算送达。
    Accepted,
    /// 对端确认没有：可以用同一个键重发。
    Resend,
    /// 查不出来（没会话、查询失败）：保持未知，等下一次再查。
    Unknown,
}

impl Reconcile {
    /// 稳定标识：日志与脚本用它断言，不用匹配中文。
    pub fn code(self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Resend => "resend",
            Self::Unknown => "unknown",
        }
    }
}

/// 外发账本。
///
/// user:“断线恢复后不得重复执行写操作（幂等键要落地）”+(核心已有的 `client_message_id`
/// 是服务端的幂等键；这里记的是「这一条已经在路上」，重发时复用同一个键，绝不新生成，
/// 于是服务端无论如何只会执行一次)。
#[derive(Debug, Default, Clone)]
pub struct Outbox {
    entries: BTreeMap<String, Delivery>,
}

impl Outbox {
    /// 开始一次发送。同一个键再来一次就是 `Duplicate`，不会产生第二次写。
    pub fn send(&mut self, key: &str) -> SendStart {
        match self.entries.get(key) {
            // 已经拿到回执：仍然不重写（服务端会按幂等键去重，但没必要白跑一趟）。
            Some(Delivery::Acknowledged) => SendStart::Duplicate,
            // 在途或结果未知：复用同一个键，等回执。
            Some(Delivery::Pending) | Some(Delivery::Unknown) => SendStart::Duplicate,
            // 明确失败过：允许用同一个键重试（服务端失败就没写进日志）。
            Some(Delivery::Failed) | None => {
                self.entries.insert(key.to_owned(), Delivery::Pending);
                SendStart::New
            }
        }
    }

    /// 收到接受回执：这一步之前，界面不能说「已发送」。
    pub fn acknowledge(&mut self, key: &str) {
        self.entries.insert(key.to_owned(), Delivery::Acknowledged);
    }

    /// 连接断了：在途的写变成「不知道有没有到」。
    ///
    /// user:“不确定送达时先查询状态，不盲目重发”+(这里只改状态，重发由调用方先查询；
    /// 查询也查不到才用同一个键重试)。
    pub fn mark_uncertain(&mut self) {
        for state in self.entries.values_mut() {
            if *state == Delivery::Pending {
                *state = Delivery::Unknown;
            }
        }
    }

    /// 确认失败。
    pub fn fail(&mut self, key: &str) {
        self.entries.insert(key.to_owned(), Delivery::Failed);
    }

    pub fn state(&self, key: &str) -> Delivery {
        self.entries
            .get(key)
            .copied()
            .unwrap_or(Delivery::Unknown)
    }

    /// user:“未确认送达不得显示发送成功”+(界面只认这一条：只有回执到了才算发出去)。
    pub fn shows_as_sent(&self, key: &str) -> bool {
        self.state(key) == Delivery::Acknowledged
    }

    /// 断线恢复后要先查询的键（在途 + 结果未知）。
    pub fn needs_reconcile(&self) -> Vec<String> {
        self.entries
            .iter()
            .filter(|(_, state)| matches!(state, Delivery::Pending | Delivery::Unknown))
            .map(|(key, _)| key.clone())
            .collect()
    }

    /// 恢复一条「上次进程里没收到回执」的写。
    ///
    /// user:“不确定送达时先查询状态，不盲目重发”+(宿主进程可能被杀在「已经发出去、还没
    /// 收到回执」的那一刻。重启之后这条写既不是新写也不是明确失败，只能记成「未知」，
    /// 等下一次连上先查日志再决定)。
    pub fn restore(&mut self, key: &str) {
        self.entries.insert(key.to_owned(), Delivery::Unknown);
    }

    /// 查完状态之后收尾：把「查到的事实」写回账本。
    ///
    /// user:“不确定送达时先查询状态，不盲目重发”+(这一步以前根本不存在：账本能记
    /// 「未知」，却没有任何入口把查询结果写回来，于是重发路径上要么永远不敢发、要么
    /// 直接当成新写。现在查询结果只有两种可用事实：有 / 没有，其余一律维持未知)。
    pub fn settle(&mut self, key: &str, found: Option<bool>) -> Reconcile {
        match found {
            Some(true) => {
                self.acknowledge(key);
                Reconcile::Accepted
            }
            Some(false) => {
                self.fail(key);
                Reconcile::Resend
            }
            // 查不出来：不动账本。下一次重连再查，绝不在这里猜一个结果。
            None => Reconcile::Unknown,
        }
    }

    /// 宿主界面要显示的状态（只有 `Acknowledged` 才能说「已发送」）。
    pub fn display_state(&self, key: &str) -> &'static str {
        match self.state(key) {
            Delivery::Acknowledged => "sent",
            Delivery::Pending => "sending",
            Delivery::Unknown => "unknown",
            Delivery::Failed => "failed",
        }
    }

    pub fn forget(&mut self, key: &str) {
        self.entries.remove(key);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 先快后慢，到上限就停在上限。
    #[test]
    fn retries_start_fast_and_back_off_to_the_cap() {
        let mut backoff = Backoff::new(
            Duration::from_secs(1),
            Duration::from_secs(8),
            5,
            Duration::from_secs(20),
        );
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(1)));
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(2)));
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(4)));
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(8)));
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(8)));
        assert_eq!(backoff.next_delay(), None, "次数用完就该放弃");
        assert_eq!(backoff.attempt(), 5);
    }

    /// 连上之后计数归零：下一次断线又是一条好汉，不因为历史失败提前放弃。
    #[test]
    fn a_successful_reconnect_resets_the_schedule() {
        let mut backoff = Backoff::default();
        let _ = backoff.next_delay();
        let _ = backoff.next_delay();
        backoff.reset();
        assert_eq!(backoff.attempt(), 0);
        assert_eq!(backoff.next_delay(), Some(Duration::from_secs(1)));
    }

    /// user:“短暂断线尽量无感（不弹提示），持续异常才轻量提示”+(阈值之内不提示)。
    #[test]
    fn short_outages_stay_silent_and_long_ones_do_not() {
        let backoff = Backoff::default();
        assert!(!backoff.should_notify(Duration::from_secs(3)));
        assert!(!backoff.should_notify(Duration::from_secs(19)));
        assert!(backoff.should_notify(Duration::from_secs(20)));
        assert!(backoff.should_notify(Duration::from_secs(120)));
    }

    /// user:“断线恢复后不得重复执行写操作（幂等键要落地）”+(同一个键不产生第二次写)。
    #[test]
    fn the_same_idempotency_key_never_starts_a_second_write() {
        let mut outbox = Outbox::default();
        assert_eq!(outbox.send("turn-1"), SendStart::New);
        assert_eq!(outbox.send("turn-1"), SendStart::Duplicate);
        assert_eq!(outbox.state("turn-1"), Delivery::Pending);
    }

    /// user:“未确认送达不得显示发送成功”+(回执之前一律不算已发送)。
    #[test]
    fn nothing_counts_as_sent_until_the_acknowledgement_arrives() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        assert!(!outbox.shows_as_sent("turn-1"));
        outbox.mark_uncertain();
        assert_eq!(outbox.state("turn-1"), Delivery::Unknown);
        assert!(!outbox.shows_as_sent("turn-1"), "断线之后更不该说已发送");
        outbox.acknowledge("turn-1");
        assert!(outbox.shows_as_sent("turn-1"));
    }

    /// user:“不确定送达时先查询状态，不盲目重发”+(断线后要查询的键就是这些)。
    #[test]
    fn uncertain_writes_are_listed_for_reconciliation() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        outbox.send("turn-2");
        outbox.acknowledge("turn-2");
        outbox.mark_uncertain();
        assert_eq!(outbox.needs_reconcile(), vec!["turn-1".to_owned()]);
    }

    /// 明确失败过的那条可以用同一个键重试（服务端没写进去）。
    #[test]
    fn a_definite_failure_can_be_retried_with_the_same_key() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        outbox.fail("turn-1");
        assert_eq!(outbox.send("turn-1"), SendStart::New);
        outbox.acknowledge("turn-1");
        assert!(outbox.shows_as_sent("turn-1"));
    }

    /// user:“不确定送达时先查询状态，不盲目重发”+(查到有→算送达；查到没有→允许同键
    /// 重发；查不到→维持未知，下一次再查)。
    #[test]
    fn a_reconciliation_result_is_written_back_into_the_ledger() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        outbox.mark_uncertain();

        // 查不到：什么都不改，既不算发出也不能重写。
        assert_eq!(outbox.settle("turn-1", None), Reconcile::Unknown);
        assert_eq!(outbox.state("turn-1"), Delivery::Unknown);
        assert_eq!(outbox.send("turn-1"), SendStart::Duplicate);

        // 查到已经在对方日志里：算送达，之后不再重发。
        assert_eq!(outbox.settle("turn-1", Some(true)), Reconcile::Accepted);
        assert!(outbox.shows_as_sent("turn-1"));
        assert_eq!(outbox.send("turn-1"), SendStart::Duplicate);

        // 查到没有：用同一个键重发（服务端按幂等键去重，所以不会写两次）。
        let mut other = Outbox::default();
        other.send("turn-2");
        other.mark_uncertain();
        assert_eq!(other.settle("turn-2", Some(false)), Reconcile::Resend);
        assert!(!other.shows_as_sent("turn-2"));
        assert_eq!(other.send("turn-2"), SendStart::New);
        assert_eq!(other.state("turn-2"), Delivery::Pending);
    }

    /// 恢复出来的「未知」写必须出现在待查清单里：否则宿主永远不会去查它。
    #[test]
    fn a_restored_write_waits_for_reconciliation() {
        let mut outbox = Outbox::default();
        outbox.restore("turn-9");
        assert_eq!(outbox.state("turn-9"), Delivery::Unknown);
        assert_eq!(outbox.needs_reconcile(), vec!["turn-9".to_owned()]);
        assert!(!outbox.shows_as_sent("turn-9"));
    }

    /// 界面上只有拿到回执的那条才叫「已发送」。
    #[test]
    fn the_display_state_only_calls_it_sent_after_the_ack() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        assert_eq!(outbox.display_state("turn-1"), "sending");
        outbox.mark_uncertain();
        assert_eq!(outbox.display_state("turn-1"), "unknown");
        outbox.fail("turn-1");
        assert_eq!(outbox.display_state("turn-1"), "failed");
        outbox.send("turn-1");
        outbox.acknowledge("turn-1");
        assert_eq!(outbox.display_state("turn-1"), "sent");
    }

    /// 已确认的那条即使被再调一次也不会重写。
    #[test]
    fn an_acknowledged_write_is_never_resent() {
        let mut outbox = Outbox::default();
        outbox.send("turn-1");
        outbox.acknowledge("turn-1");
        assert_eq!(outbox.send("turn-1"), SendStart::Duplicate);
        assert!(outbox.needs_reconcile().is_empty());
    }
}
