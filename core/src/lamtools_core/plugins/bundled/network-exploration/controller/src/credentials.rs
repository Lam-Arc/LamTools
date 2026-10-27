// user:“实现这个插件，也正好实验我们的新插件架构”+(凭据使用当前 Windows 用户的 DPAPI 加密，不依赖命令行模块，不进入日志)。
#[cfg(windows)]
fn crypt(bytes: &[u8], decrypt: bool) -> Result<Vec<u8>, String> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{CryptProtectData, CryptUnprotectData, CRYPT_INTEGER_BLOB},
    };
    if bytes.is_empty() || bytes.len() > 4 * 1024 * 1024 {
        return Err("凭据大小无效".into());
    }
    let input = CRYPT_INTEGER_BLOB {
        cbData: bytes.len() as u32,
        pbData: bytes.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: std::ptr::null_mut(),
    };
    // SAFETY: both blobs live for the call; the input slice remains valid, and
    // Windows allocates output with LocalAlloc. Copy and release it exactly once.
    let ok = unsafe {
        if decrypt {
            CryptUnprotectData(
                &input,
                std::ptr::null_mut(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                1,
                &mut output,
            )
        } else {
            CryptProtectData(
                &input,
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                std::ptr::null(),
                1,
                &mut output,
            )
        }
    };
    if ok == 0 {
        return Err("Windows 凭据保护失败；请使用保存凭据时的 Windows 账户".into());
    }
    let result =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe {
        for index in 0..output.cbData as usize {
            std::ptr::write_volatile(output.pbData.add(index), 0);
        }
        LocalFree(output.pbData.cast());
    }
    Ok(result)
}
#[cfg(not(windows))]
fn crypt(_bytes: &[u8], _decrypt: bool) -> Result<Vec<u8>, String> {
    Err("凭据保护当前仅支持 Windows".into())
}

pub fn protect(text: &str) -> Result<String, String> {
    let bytes = crypt(text.as_bytes(), false)?;
    Ok(format!(
        "dpapi1:{}",
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    ))
}
pub fn unprotect(text: &str) -> Result<String, String> {
    let value = text.strip_prefix("dpapi1:").ok_or("未知的凭据格式")?;
    if value.len() % 2 != 0 || value.len() > 8 * 1024 * 1024 {
        return Err("凭据格式无效".into());
    }
    let bytes: Result<Vec<u8>, _> = value
        .as_bytes()
        .chunks_exact(2)
        .map(|chunk| {
            std::str::from_utf8(chunk)
                .ok()
                .and_then(|s| u8::from_str_radix(s, 16).ok())
                .ok_or("凭据格式无效")
        })
        .collect();
    String::from_utf8(crypt(&bytes?, true)?).map_err(|_| "凭据编码无效".into())
}
#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    fn dpapi_roundtrip_and_tamper_detection() {
        let secret = "订阅凭据—test-token";
        let cipher = protect(secret).unwrap();
        assert!(!cipher.contains("test-token"));
        assert_eq!(unprotect(&cipher).unwrap(), secret);
        let mut tampered = cipher;
        tampered.replace_range(8..10, "ff");
        assert!(unprotect(&tampered).is_err());
    }
}
