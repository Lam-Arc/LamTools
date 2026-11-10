//! Renders any text as an SVG QR code, reusing the ticket renderer.
//!
//! The download page needs a QR code for the APK URL, and the crate already has a
//! renderer whose quiet zone and module output are verified by `qr::tests`.
//!
//!     cargo run --example qr_text -- https://example.com/file.apk > code.svg

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let text = std::env::args()
        .nth(1)
        .ok_or("usage: qr_text <text>")?;
    print!("{}", sunday_p2p::ticket_qr_svg(&text)?);
    Ok(())
}
