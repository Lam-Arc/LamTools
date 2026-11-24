//! 谁能进来，以及进来之后还能不能继续说话。
//!
//! user:“未知设备不得自动进入可信列表”“用户移除设备后，当前已建立的连接立刻失去操作权限”
//! +(以前这套判定散在 `link.rs::accept` 里：第一次见面就写进名单，之后再也不看名单；
//! 撤权要等到下一次握手才生效。这里把它抽成不碰网络的纯逻辑，握手和每一次远程调用都问
//! 同一个问题，测试也就不需要真的连一台设备)。
//!
//! 判定顺序就是安全边界：撤销记录优先于「已信任」与「首次配对」，否则一台被移除的设备
//! 只要再扫一次旧码就能回来。

use crate::pair::{self, PairingGrants, PairingRequest};
use crate::trust::TrustStore;

/// 设备没有配对过（旧版本里这种情况会被自动信任）。
pub const CODE_UNPAIRED: &str = "device_unpaired";
/// 设备已扫码，但电脑还没确认这次配对。
pub const CODE_PAIRING_PENDING: &str = "pairing_pending";
/// 设备被用户移除过，且这次没有带上新的配对票。
pub const CODE_REVOKED: &str = "device_revoked";
/// 配对票过期。
pub const CODE_PAIRING_EXPIRED: &str = "pairing_expired";
/// 配对票已经用过（同一张码不能连第二台设备）。
pub const CODE_PAIRING_USED: &str = "pairing_used";
/// 配对票被伪造、篡改，或者不是给这台机器的。
pub const CODE_PAIRING_INVALID: &str = "pairing_invalid";

/// 一次握手的判定结果。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Admission {
    /// 名单里本来就有这台设备。
    Trusted,
    /// 刚用一张有效的一次性票完成配对。
    Paired,
    /// 票有效，但还在等电脑上的用户确认；这次连接不授权。
    Pending { reason: String },
    /// 拒绝。
    Rejected { code: &'static str, reason: String },
}

impl Admission {
    /// user:“电脑显示待确认设备，用户确认配对”+(待确认不是已授权：这次连接不能调用
    /// 任何远程能力)。
    pub fn is_accepted(&self) -> bool {
        matches!(self, Self::Trusted | Self::Paired)
    }
}

/// 握手授权：要不要放这台设备进来。
///
/// `pair` 是拨号方带来的配对票原文（`sunday2:` 开头）；已配对设备重连时是 `None`。
/// 会改动 `store` 与 `grants`（新配对写名单、票据记成已用），但不会自己落盘——落盘由调用方
/// 决定，这样测试可以在内存里跑完整流程。
pub fn admit(
    store: &mut TrustStore,
    grants: &mut PairingGrants,
    server_id: &str,
    peer: &str,
    peer_name: &str,
    pair: Option<&str>,
    now: u64,
) -> Admission {
    let revoked = store.is_revoked(peer);
    let trusted = store.is_trusted(peer);

    // 一张送进来的票只有在这一步才会被检查：签名、有效期、是不是给这台机器的。
    let presented = pair.map(|text| pair::verify(text, Some(server_id), now));
    let valid_ticket = match &presented {
        Some(Ok(ticket)) => Some(ticket.clone()),
        _ => None,
    };

    if revoked {
        // user:“撤权后是否允许重新配对：按「必须重新扫码」处理，不允许旧票据复活”+
        // (新码也要经过电脑确认；撤销记录直到确认那一刻才清掉)。
        return match valid_ticket {
            Some(ticket) => match grants.request(
                &ticket.nonce,
                peer,
                peer_name,
                ticket.expires_at,
                now,
            ) {
                PairingRequest::Waiting => Admission::Pending {
                    reason: pending_reason(),
                },
                PairingRequest::TicketBusy | PairingRequest::TicketUsed => {
                    Admission::Rejected {
                        code: CODE_PAIRING_USED,
                        reason: used_reason(),
                    }
                }
            },
            None => Admission::Rejected {
                code: CODE_REVOKED,
                reason: "这台设备已被移除授权；要重新连接，请在电脑上重新生成二维码并扫码"
                    .to_owned(),
            },
        };
    }

    if trusted {
        // 老用户重连：不要求重新扫码。带了票也要消费掉，否则同一张码还能给第三台设备用。
        if let Some(ticket) = valid_ticket {
            grants.consume(&ticket.nonce, ticket.expires_at);
        }
        // 已经在名单里：任何过期的待确认申请都不该继续展示。
        grants.cancel(peer);
        return Admission::Trusted;
    }

    // user:“陌生设备不能自动获得信任”+(有效票只登记申请，电脑确认前不写可信名单)。
    match presented {
        None => Admission::Rejected {
            code: CODE_UNPAIRED,
            reason: "这台设备还没有配对；请扫电脑上「设备连接」页的二维码".to_owned(),
        },
        Some(Err(error)) => {
            let text = error.to_string();
            let code = if text.contains("已过期") {
                CODE_PAIRING_EXPIRED
            } else {
                CODE_PAIRING_INVALID
            };
            Admission::Rejected { code, reason: text }
        }
        Some(Ok(ticket)) => match grants.request(
            &ticket.nonce,
            peer,
            peer_name,
            ticket.expires_at,
            now,
        ) {
            PairingRequest::Waiting => Admission::Pending {
                reason: pending_reason(),
            },
            PairingRequest::TicketBusy => Admission::Rejected {
                code: CODE_PAIRING_USED,
                reason: "这张配对二维码正在给另一台设备申请配对，请重新生成一张".to_owned(),
            },
            PairingRequest::TicketUsed => Admission::Rejected {
                code: CODE_PAIRING_USED,
                reason: used_reason(),
            },
        },
    }
}

fn pending_reason() -> String {
    "这台设备正在等待电脑确认：请在电脑的「设备连接」页点「确认」后再连接".to_owned()
}

fn used_reason() -> String {
    "这张配对二维码已经用过了，请在电脑上重新生成一张".to_owned()
}

pub fn authorize(store: &TrustStore, peer: &str) -> Result<(), (&'static str, String)> {
    if store.is_revoked(peer) {
        return Err((
            CODE_REVOKED,
            "这台设备已被移除授权，远程调用已拒绝；要重新连接，请在电脑上重新生成二维码并扫码"
                .to_owned(),
        ));
    }
    if !store.is_trusted(peer) {
        return Err((
            CODE_UNPAIRED,
            "这台设备不在可信名单里，远程调用已拒绝".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pair::issue;
    use iroh::{EndpointId, SecretKey, TransportAddr};

    fn addr_for(secret: &SecretKey) -> iroh::EndpointAddr {
        let mut addrs = std::collections::BTreeSet::new();
        addrs.insert(TransportAddr::Ip("127.0.0.1:4242".parse().unwrap()));
        iroh::EndpointAddr {
            id: EndpointId::from(secret.public()),
            addrs,
        }
    }

    struct Setup {
        secret: SecretKey,
        server_id: String,
        grants: PairingGrants,
        store: TrustStore,
    }

    fn setup() -> Setup {
        let secret = SecretKey::generate();
        let server_id = addr_for(&secret).id.to_string();
        Setup {
            secret,
            server_id,
            grants: PairingGrants::default(),
            store: TrustStore::default(),
        }
    }

    impl Setup {
        fn ticket(&self, now: u64) -> String {
            let addr = addr_for(&self.secret);
            issue(&self.secret, &addr, std::time::Duration::from_secs(300), now)
                .unwrap()
                .text
        }
    }

    /// user:“未知设备不得自动进入可信列表”+(没有票的陌生设备被拒绝，而且名单里不会多出它)。
    #[test]
    fn an_unknown_device_without_a_ticket_is_rejected_and_not_trusted() {
        let mut s = setup();
        let result = admit(&mut s.store, &mut s.grants, &s.server_id, "phone-1", "Phone", None, 1_000);
        assert_eq!(
            result,
            Admission::Rejected {
                code: CODE_UNPAIRED,
                reason: result_reason(&result),
            }
        );
        assert!(!s.store.is_trusted("phone-1"));
        assert!(s.store.devices.is_empty());
    }

    fn result_reason(result: &Admission) -> String {
        match result {
            Admission::Rejected { reason, .. } => reason.clone(),
            _ => String::new(),
        }
    }

    /// user:“电脑显示待确认设备，用户确认配对”+(扫码只登记申请；确认后才写名单)。
    #[test]
    fn a_valid_ticket_waits_for_the_computer_to_confirm() {
        let mut s = setup();
        let ticket = s.ticket(1_000);
        let result = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&ticket),
            1_010,
        );
        assert!(matches!(result, Admission::Pending { .. }));
        assert!(!result.is_accepted());
        assert!(!s.store.is_trusted("phone-1"));
        assert_eq!(s.grants.pending_devices().len(), 1);
        let nonce = pair::verify(&ticket, None, 1_010).unwrap().nonce;
        assert!(!s.grants.is_used(&nonce));

        // 电脑点了「确认」：写可信名单并消费这张票。
        let pending = s.grants.confirm("phone-1").expect("pending");
        s.store.trust(&pending.id, &pending.name);
        assert!(s.store.is_trusted("phone-1"));
        assert!(s.grants.is_used(&nonce));
    }

    /// user:“配对授权不等于授予全部远程控制权限”+(确认之前任何调用都不能通过)。
    #[test]
    fn a_pending_device_has_no_rights_until_it_is_confirmed() {
        let mut s = setup();
        let ticket = s.ticket(1_000);
        let _ = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&ticket),
            1_010,
        );
        assert!(authorize(&s.store, "phone-1").is_err());
        let pending = s.grants.confirm("phone-1").expect("pending");
        s.store.trust(&pending.id, &pending.name);
        assert!(authorize(&s.store, "phone-1").is_ok());
    }

    /// user:“用过即失效”“重复使用要被拒绝”+(同一张票第二台设备拿来用必须失败)。
    #[test]
    fn the_same_ticket_cannot_pair_a_second_device() {
        let mut s = setup();
        let ticket = s.ticket(1_000);
        assert!(matches!(
            admit(&mut s.store, &mut s.grants, &s.server_id, "phone-1", "Phone", Some(&ticket), 1_010),
            Admission::Pending { .. }
        ));
        // 第一台还没确认，票还在 pending 里；第二台不能拿同一张码插队。
        let second = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "tablet-9",
            "Tablet",
            Some(&ticket),
            1_020,
        );
        assert_eq!(
            second,
            Admission::Rejected {
                code: CODE_PAIRING_USED,
                reason: result_reason(&second),
            }
        );
        assert!(!s.store.is_trusted("tablet-9"));
    }

    /// 过期的票连第一次都用不了。
    #[test]
    fn an_expired_ticket_is_rejected_with_its_own_code() {
        let mut s = setup();
        let ticket = s.ticket(1_000);
        let result = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&ticket),
            1_400,
        );
        match result {
            Admission::Rejected { code, reason } => {
                assert_eq!(code, CODE_PAIRING_EXPIRED);
                assert!(reason.contains("已过期"), "unexpected reason: {reason}");
            }
            other => panic!("expected a rejection, got {other:?}"),
        }
        assert!(!s.store.is_trusted("phone-1"));
    }

    /// 伪造的票（别人用自己的密钥签的）过不了。
    #[test]
    fn a_forged_ticket_is_rejected() {
        let mut s = setup();
        let other = SecretKey::generate();
        let forged = issue(
            &other,
            &addr_for(&other),
            std::time::Duration::from_secs(300),
            1_000,
        )
        .unwrap()
        .text;
        let result = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&forged),
            1_010,
        );
        assert!(matches!(
            result,
            Admission::Rejected {
                code: CODE_PAIRING_INVALID,
                ..
            }
        ));
        assert!(!s.store.is_trusted("phone-1"));
    }

    /// user:“已授权设备后续能自动重连，不要求每次重新扫”+(重连不带票也放行)。
    #[test]
    fn a_paired_device_reconnects_without_scanning_again() {
        let mut s = setup();
        s.store.trust("phone-1", "Phone");
        let result = admit(&mut s.store, &mut s.grants, &s.server_id, "phone-1", "Phone", None, 9_999);
        assert_eq!(result, Admission::Trusted);
    }

    /// user:“不允许旧票据复活”+(被移除的设备拿旧票回来必须拒绝)。
    #[test]
    fn a_revoked_device_cannot_come_back_with_an_old_ticket() {
        let mut s = setup();
        let ticket = s.ticket(1_000);
        assert!(matches!(
            admit(&mut s.store, &mut s.grants, &s.server_id, "phone-1", "Phone", Some(&ticket), 1_010),
            Admission::Pending { .. }
        ));
        let pending = s.grants.confirm("phone-1").expect("pending");
        s.store.trust(&pending.id, &pending.name);
        s.store.revoke("phone-1");
        let result = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&ticket),
            1_020,
        );
        // 旧票已经用过，所以是「用过了」而不是直接放行——两种拒绝都不放它进来。
        assert!(!result.is_accepted());
        assert!(!s.store.is_trusted("phone-1"));
    }

    /// user:“撤权后是否允许重新配对：按「必须重新扫码」处理”+(新扫一张新码可以回来)。
    #[test]
    fn a_revoked_device_can_come_back_with_a_brand_new_ticket() {
        let mut s = setup();
        s.store.trust("phone-1", "Phone");
        s.store.revoke("phone-1");
        let fresh = s.ticket(2_000);
        let result = admit(
            &mut s.store,
            &mut s.grants,
            &s.server_id,
            "phone-1",
            "Phone",
            Some(&fresh),
            2_010,
        );
        assert!(matches!(result, Admission::Pending { .. }));
        let pending = s.grants.confirm("phone-1").expect("pending");
        s.store.allow("phone-1");
        s.store.trust(&pending.id, &pending.name);
        assert!(s.store.is_trusted("phone-1"));
        assert!(!s.store.is_revoked("phone-1"));
    }

    /// user:“撤权后 RPC 一律拒绝，返回明确错误码”+(这里就是每次远程调用前的那一问)。
    #[test]
    fn an_active_connection_loses_its_rights_as_soon_as_the_device_is_revoked() {
        let mut s = setup();
        s.store.trust("phone-1", "Phone");
        assert!(authorize(&s.store, "phone-1").is_ok());
        s.store.revoke("phone-1");
        let (code, reason) = authorize(&s.store, "phone-1").unwrap_err();
        assert_eq!(code, CODE_REVOKED);
        assert!(reason.contains("已拒绝"), "unexpected reason: {reason}");
    }
}
