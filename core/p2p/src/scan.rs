//! Reading a ticket back off a photo.
//!
//! user:“设备配对：支持二维码、配对码等简单方式”+(桌面出码，手机用相机扫回来)。
//!
//! Decoding lives next to encoding so both sides share one dependency story: the phone
//! captures a JPEG through the system camera, this reads it, and the caller gets the same
//! `sunday1:` text a paste would have produced.

use std::path::Path;

use anyhow::{bail, Context, Result};

/// Finds the first QR code in an image and returns its text.
pub fn scan_qr_file(path: &Path) -> Result<String> {
    // A photo from the camera can be forty megapixels; decoding at native size is slow and
    // buys nothing, so the image is downscaled to a size QR detectors handle well.
    let image = image::open(path)
        .with_context(|| format!("打不开这张图片：{}", path.display()))?
        .to_luma8();
    let image = if image.width() > 1600 || image.height() > 1600 {
        image::imageops::resize(&image, 1600, 1600, image::imageops::FilterType::Triangle)
    } else {
        image
    };
    let mut prepared = rqrr::PreparedImage::prepare(image);
    let grids = prepared.detect_grids();
    for grid in grids {
        match grid.decode() {
            Ok((_meta, content)) => return Ok(content),
            Err(_) => continue,
        }
    }
    bail!("画面里没有识别到二维码，靠近一点、让码完整落在框里再试一次")
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A generated code must scan back to exactly the text it was made from.
    ///
    /// This is the real contract of the feature: what the desktop paints is what the phone
    /// reads, byte for byte, including the `sunday1:` prefix.
    #[test]
    fn round_trips_through_the_encoder() {
        let ticket = "sunday1:round-trip-2f9ac1";
        let code = qrcode::QrCode::new(ticket.as_bytes()).expect("encode");
        let image = code
            .render::<image::Luma<u8>>()
            .quiet_zone(true)
            .module_dimensions(8, 8)
            .build();
        let directory = std::env::temp_dir().join("sunday-p2p-scan-test");
        std::fs::create_dir_all(&directory).expect("temp dir");
        let path = directory.join("ticket.png");
        image.save(&path).expect("save png");
        let scanned = scan_qr_file(&path).expect("decode");
        assert_eq!(scanned, ticket);
    }
}
