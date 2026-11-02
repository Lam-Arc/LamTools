//! Ping 会话卡片的独立窗口。
//!
//! user:“卡片即窗口，把 ping 和桌宠拆分开”+(每张卡片一个自己的窗口，不再画在
//! 桌宠覆盖层里。)
//!
//! user:“不要再自作聪明了”“圆不圆角你就看 Sunday 本身是什么样”+(窗口方案不再
//! 自创：建窗参数、材质、生命周期全部照搬 Sunday 主窗口那一套——无边框、透明、
//! 系统阴影、可见创建，Acrylic 只套一次；不手动清 Win32 样式、不强制重绘、
//! 不自定义窗口圆角。页面自己画卡片外观和输入栏，原生长什么样由系统决定。)

use tauri::window::{Effect, EffectsBuilder};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};

/// 卡片窗口标签前缀；卡片 id（会话 id）跟在后面。
const LABEL_PREFIX: &str = "ping-card-";
/// 与主窗口启动玻璃同一组 Acrylic 着色（r, g, b, a）。
const ACRYLIC_COLOR: (u8, u8, u8, u8) = (58, 59, 63, 32);

pub fn label_for(card_id: &str) -> String {
    format!("{LABEL_PREFIX}{}", sanitize_id(card_id))
}

/// 打开（或唤起）一张卡片窗口。
/// rect：[x, y, width, height]，屏幕物理像素（前端按 DPI 换算后传入）。
pub fn open(
    app: &AppHandle,
    card_id: &str,
    session_id: &str,
    project_id: Option<&str>,
    title: &str,
    rect: [f64; 4],
) -> Result<(), String> {
    let label = label_for(card_id);
    if let Some(existing) = app.get_webview_window(&label) {
        // 同一个 card_id 可能已经切到别的会话（分叉/轮盘跳转）：窗口页面参数
        // 只在创建时读取，直接 show 会显示旧内容，必须销毁重建。
        let same_session = existing
            .url()
            .ok()
            .map(|url| {
                url.query_pairs()
                    .any(|(key, value)| key == "session" && value == session_id)
            })
            .unwrap_or(false);
        if same_session {
            let [x, y, width, height] = rect;
            let (x, y, width, height) = sanitize_rect(x, y, width, height);
            place_card(&existing, x, y, width, height)?;
            let _ = existing.show();
            return Ok(());
        }
        let _ = existing.destroy();
    }
    let url = format!(
        "card.html?card={}&session={}&project={}&title={}",
        urlencoding::encode(card_id),
        urlencoding::encode(session_id),
        urlencoding::encode(project_id.unwrap_or("")),
        urlencoding::encode(title),
    );
    // 与 tauri.conf.json 里的主窗口一致的建窗参数：
    // decorations=false / transparent / 透明背景色 / shadow=true / 创建即可见。
    // user:“为什么 Sunday 不会有这个东西”+(主窗口没有原生标题栏的配方直接照抄，
    // 不再用桌宠覆盖层的隐藏创建 + 无阴影方案。)
    let window = WebviewWindowBuilder::new(app, label.clone(), WebviewUrl::App(url.into()))
        .title("Sunday")
        .transparent(true)
        .background_color(tauri::window::Color(0, 0, 0, 0))
        .decorations(false)
        .shadow(true)
        .skip_taskbar(true)
        .resizable(false)
        .always_on_top(true)
        .build()
        .map_err(|error| format!("create ping card window failed: {error}"))?;

    // 与主窗口 enable_startup_glass 同一套材质，只套一次，不随后续操作重套。
    #[cfg(windows)]
    apply_acrylic(&window);

    let [x, y, width, height] = rect;
    let (x, y, width, height) = sanitize_rect(x, y, width, height);
    if let Err(error) = place_card(&window, x, y, width, height) {
        // 摆位失败时窗口已经建好，不销毁就会留下一块置顶、无定位的窗口。
        let _ = window.destroy();
        return Err(error);
    }
    Ok(())
}

/// 与覆盖层同一套物理像素摆位修正（某些缩放下系统会把物理像素再乘一次缩放）。
fn place_card(
    window: &tauri::WebviewWindow,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
) -> Result<(), String> {
    super::place_overlay(window, &super::OverlayBounds {
        x,
        y,
        width: width as i32,
        height: height as i32,
        scale: 1.0,
    })
    .map_err(|error| format!("place ping card window failed: {error}"))
}

/// 页面画出首帧后显示窗口。
///
/// 窗口创建时已经可见（与主窗口一致）；这里保留显式 show 作为幂等兜底。
pub fn show(app: &AppHandle, card_id: &str) -> Result<(), String> {
    let window = app
        .get_webview_window(&label_for(card_id))
        .ok_or_else(|| "ping card window is not open".to_string())?;
    window.show().map_err(|error| error.to_string())
}

pub fn close(app: &AppHandle, card_id: &str) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(&label_for(card_id)) {
        let _ = window.destroy();
    }
    Ok(())
}

fn sanitize_id(value: &str) -> String {
    let cleaned: String = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect();
    if cleaned.is_empty() {
        "card".to_string()
    } else {
        cleaned
    }
}

fn sanitize_rect(x: f64, y: f64, width: f64, height: f64) -> (i32, i32, u32, u32) {
    (
        x.round() as i32,
        y.round() as i32,
        width.max(1.0).round() as u32,
        height.max(1.0).round() as u32,
    )
}

/// 与主窗口相同的原生 Acrylic 磨砂。
#[cfg(windows)]
fn apply_acrylic(window: &tauri::WebviewWindow) {
    let (r, g, b, a) = ACRYLIC_COLOR;
    let _ = window.set_effects(
        EffectsBuilder::new()
            .effect(Effect::Acrylic)
            .color((r, g, b, a).into())
            .build(),
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn label_prefixes_and_sanitizes_card_ids() {
        assert_eq!(label_for("abc-123"), "ping-card-abc-123");
        assert_eq!(label_for("a/b:c"), "ping-card-a_b_c");
        assert_eq!(label_for(""), "ping-card-card");
    }

    #[test]
    fn sanitize_rect_keeps_windows_visible_and_bounded() {
        let (x, y, width, height) = sanitize_rect(12.4, -8.6, 0.0, -3.0);
        assert_eq!((x, y, width, height), (12, -9, 1, 1));
    }
}
