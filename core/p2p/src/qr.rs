//! Turning a ticket into something a camera can read.
//!
//! user:“设备配对：支持二维码、配对码等简单方式”+(票据本身就是二维码的内容，
//! 生成放在 Rust 里，桌面与手机共用一份，界面不用引第三方 JS 库)。

use anyhow::{Context, Result};

/// Renders the ticket as an SVG QR code.
///
/// A four-module quiet zone is part of the spec: scanners need the margin, and a code that
/// only fails on some phones is worse than one that is slightly larger.
pub fn ticket_qr_svg(ticket: &str) -> Result<String> {
    let code = qrcode::QrCode::new(ticket.as_bytes()).context("票据无法编码成二维码")?;
    let width = code.width();
    let colors = code.to_colors();
    let quiet = 4usize;
    let side = width + quiet * 2;

    let mut svg = String::with_capacity(side * side * 8);
    svg.push_str(&format!(
        r#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" width="{side}" height="{side}" shape-rendering="crispEdges" role="img">"#
    ));
    svg.push_str(r##"<rect width="100%" height="100%" fill="#ffffff"/>"##);
    for y in 0..width {
        for x in 0..width {
            // `to_colors` is row-major; Light modules are the background we already filled.
            let dark = matches!(
                colors.get(y * width + x),
                Some(qrcode::Color::Dark)
            );
            if dark {
                svg.push_str(&format!(
                    r##"<rect x="{}" y="{}" width="1" height="1" fill="#000000"/>"##,
                    x + quiet,
                    y + quiet
                ));
            }
        }
    }
    svg.push_str("</svg>");
    Ok(svg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_a_scannable_square() {
        let svg = ticket_qr_svg("sunday1:abc").expect("qr");
        assert!(svg.starts_with("<svg"));
        assert!(svg.contains("viewBox"));
        assert!(svg.ends_with("</svg>"));
    }
}
