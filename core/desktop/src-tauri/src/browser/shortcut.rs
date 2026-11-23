// user:“Ctrl+F 在网页聚焦时也要能唤起 Sunday 的查找”+(网页拿到焦点后按键直接进 WebView2，
// 所以必须在 `ICoreWebView2Controller::add_AcceleratorKeyPressed` 里同步拦下并转成自家命令)。
//
// 这一层只做「按键 → 动作」的纯映射：回调在 UI 线程，不能阻塞、不能做业务。

/// Windows 虚拟键码（只列本模块用到的，避免为一个常数引入 Win32 feature）。
pub const VK_F: u32 = 0x46;
pub const VK_0: u32 = 0x30;
pub const VK_NUMPAD0: u32 = 0x60;
pub const VK_ADD: u32 = 0x6B;
pub const VK_SUBTRACT: u32 = 0x6D;
pub const VK_OEM_PLUS: u32 = 0xBB;
pub const VK_OEM_MINUS: u32 = 0xBD;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Shortcut {
    /// 打开/聚焦页内查找。
    Find,
    ZoomIn,
    ZoomOut,
    ZoomReset,
}

impl Shortcut {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Find => "find",
            Self::ZoomIn => "zoom_in",
            Self::ZoomOut => "zoom_out",
            Self::ZoomReset => "zoom_reset",
        }
    }
}

/// user:“命中 Ctrl+F / Ctrl+加/减/0 时 SetHandled(true)”+(非 Ctrl 组合一律不拦，页面自己的按键要照常工作)。
///
/// `key_down` 为 false（抬起事件）时永不命中：拦抬起会让页面收到「没有按下的抬起」。
pub fn resolve(virtual_key: u32, ctrl: bool, key_down: bool) -> Option<Shortcut> {
    if !ctrl || !key_down {
        return None;
    }
    match virtual_key {
        VK_F => Some(Shortcut::Find),
        VK_OEM_PLUS | VK_ADD => Some(Shortcut::ZoomIn),
        VK_OEM_MINUS | VK_SUBTRACT => Some(Shortcut::ZoomOut),
        VK_0 | VK_NUMPAD0 => Some(Shortcut::ZoomReset),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ctrl_f_opens_find() {
        assert_eq!(resolve(VK_F, true, true), Some(Shortcut::Find));
    }

    #[test]
    fn zoom_shortcuts_cover_main_and_numpad_keys() {
        assert_eq!(resolve(VK_OEM_PLUS, true, true), Some(Shortcut::ZoomIn));
        assert_eq!(resolve(VK_ADD, true, true), Some(Shortcut::ZoomIn));
        assert_eq!(resolve(VK_OEM_MINUS, true, true), Some(Shortcut::ZoomOut));
        assert_eq!(resolve(VK_SUBTRACT, true, true), Some(Shortcut::ZoomOut));
        assert_eq!(resolve(VK_0, true, true), Some(Shortcut::ZoomReset));
        assert_eq!(resolve(VK_NUMPAD0, true, true), Some(Shortcut::ZoomReset));
    }

    #[test]
    fn keys_without_ctrl_stay_with_the_page() {
        // user:“页面自己的按键要照常工作”+(不按 Ctrl 时输入框里打 f 不能变成查找)。
        for key in [VK_F, VK_0, VK_OEM_PLUS, VK_OEM_MINUS] {
            assert_eq!(resolve(key, false, true), None, "{key}");
        }
    }

    #[test]
    fn key_up_events_are_never_intercepted() {
        for key in [VK_F, VK_0, VK_OEM_PLUS, VK_OEM_MINUS] {
            assert_eq!(resolve(key, true, false), None, "{key}");
        }
    }

    #[test]
    fn unrelated_keys_are_ignored() {
        for key in [0x41, 0x54, 0x1B, 0x7B] {
            assert_eq!(resolve(key, true, true), None, "{key}");
        }
        assert_eq!(Shortcut::Find.label(), "find");
    }
}
