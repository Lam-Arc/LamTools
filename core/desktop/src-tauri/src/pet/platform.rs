//! Windows 原生能力：多屏几何、光标、截图、窗口层级与全局快捷键。
//!
//! 这里全部是"系统事实"，不做任何业务判断。所有函数在非 Windows 平台返回
//! 明确的"不支持"，因为桌宠覆盖层本身只能在 Windows 上成立。

use super::{MonitorInfo, OverlayBounds};
use tauri::WebviewWindow;

#[derive(Clone, Debug)]
pub struct HotkeySpec {
    pub accelerator: String,
    pub modifiers: u8,
    pub vk: i32,
}

pub const MOD_CTRL: u8 = 1;
pub const MOD_SHIFT: u8 = 2;
pub const MOD_ALT: u8 = 4;
pub const MOD_WIN: u8 = 8;

// ---------------------------------------------------------------------------
// 块 B：地形数据层的纯判定（L1 并集矩形 / L2 窗口资格）
// ---------------------------------------------------------------------------

/// L2 候选窗口的最小尺寸（宽/高，物理像素）。
///
/// user:“B2 不可见/零尺寸/工具窗口不产生黄线”+
/// (零尺寸/太小尺寸的窗口连"能站上去的桌面"都算不上，不得进 L2 报告。
///  数据层这道 120×80 比引擎侧 setWindows 的 160×90 地形资格线宽一档，
///  是有意的分层：SVG 遮挡遮罩需要全部真实窗口矩形，地形只要能站的那部分。)
pub const MIN_TERRAIN_WINDOW_WIDTH: i32 = 120;
pub const MIN_TERRAIN_WINDOW_HEIGHT: i32 = 80;

/// 多显示器并集矩形 = L1 屏幕边界的数据来源。
///
/// user:“B4 L1 蓝线完整围住屏幕四边（此前底边被裁）”+
/// (L1 的四条蓝线由 `TerrainField.setScreenBounds` 按这个矩形生成：
///  bottom/right 必须取所有显示器边缘的最大值而不是单屏尺寸，
///  副屏在负坐标区时 left/top 也要跟着扩，否则对应边的蓝线会被裁掉。)
pub fn union_bounds(list: &[MonitorInfo]) -> OverlayBounds {
    let min_x = list.iter().map(|m| m.x).min().unwrap_or(0);
    let min_y = list.iter().map(|m| m.y).min().unwrap_or(0);
    let max_x = list.iter().map(|m| m.x + m.width).max().unwrap_or(0);
    let max_y = list.iter().map(|m| m.y + m.height).max().unwrap_or(0);
    let scale = list
        .iter()
        .find(|m| m.primary)
        .or_else(|| list.first())
        .map(|m| m.scale)
        .unwrap_or(1.0);
    OverlayBounds {
        x: min_x,
        y: min_y,
        width: (max_x - min_x).max(1),
        height: (max_y - min_y).max(1),
        scale,
    }
}

/// 系统壳窗口类：对 EnumWindows 可见、用户却无感知（输入体验、开始菜单宿主等
/// UWP 宿主面），不构成"桌面上的地形"。
///
/// user:"你告诉我这个黄线凭什么在这儿，每一根黄线都跟我解释为什么它在这儿"+
/// (用户屏幕中部的莫名黄线来自"Windows 输入体验"（class Windows.UI.Core.CoreWindow，
///  2048×1152 全屏矩形）——它对可见/标题/工具窗/尺寸全部"合法"，但它不是用户
///  感知中的桌面内容，必须按类名剔除。)
const SHELL_WINDOW_CLASSES: &[&str] = &["Windows.UI.Core.CoreWindow"];

/// 单个顶层窗口能否进 L2 上报（B1/B2 的过滤语义，收拢成纯函数便于逐项验收）。
///
/// user:"B1 桌面上每个可见顶层窗口 ↔ 恰好一组黄线，逐一对号"+"B2 不可见/零尺寸/工具窗口不产生黄线"+
/// (黄线与报告一一对应，所以"谁有资格进报告"就是"谁该有黄线"：
///  不可见、最小化、披隐（cloaked，系统隐藏但 IsWindowVisible 为真）、
///  工具浮层（托盘/浮层不是桌面地形）、系统壳窗、空标题、
///  自己的窗口、小于最小尺寸的窗口都排除。)
pub fn is_terrain_window_candidate(
    visible: bool,
    minimized: bool,
    cloaked: bool,
    tool_window: bool,
    class_name: &str,
    title: &str,
    width: i32,
    height: i32,
    skip_titles: &[String],
) -> bool {
    if !visible || minimized || cloaked {
        return false;
    }
    if SHELL_WINDOW_CLASSES.iter().any(|shell| *shell == class_name) {
        return false;
    }
    if title.is_empty() {
        return false;
    }
    if tool_window {
        return false;
    }
    if skip_titles.iter().any(|skip| skip == title) {
        return false;
    }
    width >= MIN_TERRAIN_WINDOW_WIDTH && height >= MIN_TERRAIN_WINDOW_HEIGHT
}

// ---------------------------------------------------------------------------
// Windows 实现
// ---------------------------------------------------------------------------

#[cfg(windows)]
mod imp {
    use super::*;
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::Foundation::{HWND, LPARAM, POINT, RECT};
    use windows_sys::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_CLOAKED};
    use windows_sys::Win32::Graphics::Gdi::{
        BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, EnumDisplayMonitors,
        GetDC, GetDIBits, GetMonitorInfoW, MonitorFromPoint, ReleaseDC, SelectObject, BITMAPINFO,
        BITMAPINFOHEADER, BI_RGB, CAPTUREBLT, DIB_RGB_COLORS, HDC, HMONITOR, MONITORINFOEXW,
        MONITOR_DEFAULTTONEAREST, SRCCOPY,
    };
    use windows_sys::Win32::UI::HiDpi::GetDpiForMonitor;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetClassNameW, GetCursorPos, GetWindowLongPtrW, GetWindowRect, GetWindowTextW,
        GetWindowThreadProcessId, IsHungAppWindow, IsIconic, IsWindowVisible, PostMessageW,
        SetWindowLongPtrW, SetWindowPos, ShowWindow, GWL_EXSTYLE,
        HWND_BOTTOM, HWND_NOTOPMOST, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SW_HIDE, WM_CLOSE,
        WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    };

    fn sinfo_to_monitor(info: &MONITORINFOEXW, primary: bool, scale: f64) -> MonitorInfo {
        MonitorInfo {
            id: device_name(&info.szDevice),
            x: info.monitorInfo.rcMonitor.left,
            y: info.monitorInfo.rcMonitor.top,
            width: info.monitorInfo.rcMonitor.right - info.monitorInfo.rcMonitor.left,
            height: info.monitorInfo.rcMonitor.bottom - info.monitorInfo.rcMonitor.top,
            primary,
            scale,
        }
    }

    fn device_name(raw: &[u16; 32]) -> String {
        let end = raw.iter().position(|value| *value == 0).unwrap_or(raw.len());
        String::from_utf16_lossy(&raw[..end])
    }

    fn monitor_info(hmon: HMONITOR) -> Option<(MONITORINFOEXW, bool)> {
        unsafe {
            let mut info: MONITORINFOEXW = zeroed();
            info.monitorInfo.cbSize = size_of::<MONITORINFOEXW>() as u32;
            let ok = GetMonitorInfoW(hmon, &mut info.monitorInfo as *mut _);
            if ok == 0 {
                return None;
            }
            let primary = info.monitorInfo.dwFlags & 1 == 1; // MONITORINFOF_PRIMARY
            Some((info, primary))
        }
    }

    fn dpi_scale(hmon: HMONITOR) -> f64 {
        unsafe {
            let (mut dx, mut dy) = (96u32, 96u32);
            // MDT_EFFECTIVE_DPI = 0
            let hr = GetDpiForMonitor(hmon, 0, &mut dx, &mut dy);
            if hr < 0 {
                return 1.0;
            }
            (dx.max(1) as f64) / 96.0
        }
    }

    unsafe extern "system" fn enum_monitor(
        hmon: HMONITOR,
        _hdc: HDC,
        _rect: *mut RECT,
        data: LPARAM,
    ) -> windows_sys::core::BOOL {
        let list = &mut *(data as *mut Vec<MonitorInfo>);
        if let Some((info, primary)) = monitor_info(hmon) {
            let scale = dpi_scale(hmon);
            list.push(sinfo_to_monitor(&info, primary, scale));
        }
        1
    }

    pub fn monitors() -> Result<Vec<MonitorInfo>, String> {
        let mut list: Vec<MonitorInfo> = Vec::new();
        let ok = unsafe {
            EnumDisplayMonitors(
                std::ptr::null_mut(),
                std::ptr::null(),
                Some(enum_monitor),
                &mut list as *mut Vec<MonitorInfo> as LPARAM,
            )
        };
        if ok == 0 || list.is_empty() {
            return Err("no display monitors reported".into());
        }
        list.sort_by(|a, b| a.x.cmp(&b.x).then(a.y.cmp(&b.y)));
        Ok(list)
    }

    pub fn cursor_position() -> Result<(i32, i32), String> {
        unsafe {
            let mut point: POINT = zeroed();
            if GetCursorPos(&mut point) == 0 {
                return Err("GetCursorPos failed".into());
            }
            Ok((point.x, point.y))
        }
    }

    pub fn monitor_at(x: i32, y: i32) -> Result<MonitorInfo, String> {
        unsafe {
            let point = POINT { x, y };
            let hmon = MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST);
            if hmon.is_null() {
                return Err("MonitorFromPoint failed".into());
            }
            let (info, primary) = monitor_info(hmon).ok_or_else(|| "GetMonitorInfo failed".to_string())?;
            Ok(sinfo_to_monitor(&info, primary, dpi_scale(hmon)))
        }
    }

    pub fn virtual_screen_bounds() -> Result<OverlayBounds, String> {
        let list = monitors()?;
        // 并集计算收拢在纯函数 union_bounds（块 B 验收：四边必须包住所有显示器）。
        Ok(union_bounds(&list))
    }

    /// 抓取指定显示器的完整画面（物理像素，BGRA→RGBA）。
    pub fn capture(monitor: &MonitorInfo) -> Result<(u32, u32, Vec<u8>), String> {
        let width = monitor.width.max(1);
        let height = monitor.height.max(1);
        unsafe {
            // GetDC(0) 拿到的是整个虚拟桌面的 DC，坐标即虚拟屏幕坐标。
            let screen_dc = GetDC(std::ptr::null_mut());
            if screen_dc.is_null() {
                return Err("GetDC failed".into());
            }
            let memory_dc = CreateCompatibleDC(screen_dc);
            if memory_dc.is_null() {
                ReleaseDC(std::ptr::null_mut(), screen_dc);
                return Err("CreateCompatibleDC failed".into());
            }
            let bitmap = CreateCompatibleBitmap(screen_dc, width, height);
            if bitmap.is_null() {
                DeleteDC(memory_dc);
                ReleaseDC(std::ptr::null_mut(), screen_dc);
                return Err("CreateCompatibleBitmap failed".into());
            }
            let previous = SelectObject(memory_dc, bitmap);
            let copied = BitBlt(
                memory_dc,
                0,
                0,
                width,
                height,
                screen_dc,
                monitor.x,
                monitor.y,
                SRCCOPY | CAPTUREBLT,
            );
            if copied == 0 {
                SelectObject(memory_dc, previous);
                DeleteObject(bitmap);
                DeleteDC(memory_dc);
                ReleaseDC(std::ptr::null_mut(), screen_dc);
                return Err("BitBlt failed (the desktop may be locked or protected)".into());
            }
            let mut info: BITMAPINFO = zeroed();
            info.bmiHeader = BITMAPINFOHEADER {
                biSize: size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                // 负高度 = 自上而下扫描，前端不必再翻转。
                biHeight: -height,
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB,
                biSizeImage: 0,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            };
            let mut buffer = vec![0u8; (width as usize) * (height as usize) * 4];
            let lines = GetDIBits(
                memory_dc,
                bitmap,
                0,
                height as u32,
                buffer.as_mut_ptr() as *mut _,
                &mut info,
                DIB_RGB_COLORS,
            );
            SelectObject(memory_dc, previous);
            DeleteObject(bitmap);
            DeleteDC(memory_dc);
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            if lines == 0 {
                return Err("GetDIBits failed".into());
            }
            // GDI 给的是 BGRA，前端按 RGBA 使用。
            for pixel in buffer.chunks_exact_mut(4) {
                pixel.swap(0, 2);
                pixel[3] = 255;
            }
            Ok((width as u32, height as u32, buffer))
        }
    }

    /// 覆盖层不抢焦点、不进 Alt+Tab。
    ///
    /// user:“从你启动开始就一直是黑屏未响应状态”+
    /// (覆盖层绝不能再对截屏隐形：`WDA_EXCLUDEFROMCAPTURE` 会让任何抓屏式的
    ///  观看方式——远程桌面、录屏、屏幕共享——把这一整块屏幕变成纯黑，
    ///  用户看到的就是"黑屏、点什么都没反应"。Ping 需要干净底图时改为
    ///  截图前短暂隐藏覆盖层，见 `pet::capture_with_overlay_hidden`。)
    pub fn configure_overlay_window(window: &WebviewWindow) -> Result<(), String> {
        // 窗口刚建好时原生句柄可能还没登记到 Tao 那边（直接跑 exe 时见过
        // "the underlying handle is not available"），等一小会儿再取。
        let mut raw = None;
        for _ in 0..60 {
            if let Ok(value) = window.hwnd() {
                raw = Some(value.0);
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(16));
        }
        let hwnd = raw.ok_or_else(|| "overlay window handle never became available".to_string())?;
        unsafe {
            let current = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            let wanted = current | (WS_EX_NOACTIVATE as isize) | (WS_EX_TOOLWINDOW as isize);
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, wanted);
        }
        Ok(())
    }

    pub fn set_z_mode(window: &WebviewWindow, mode: &str) -> Result<(), String> {
        let hwnd = window.hwnd().map_err(|error| error.to_string())?.0;
        let insert_after = if mode == "behind" { HWND_BOTTOM } else { std::ptr::null_mut() };
        unsafe {
            // behind：把覆盖层压到普通窗口下面，别的窗口会真的挡住桌宠；
            // top：回到置顶（Tauri 的 always_on_top 已处理，这里兜底刷新一次）。
            SetWindowPos(
                hwnd,
                insert_after,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            );
        }
        Ok(())
    }

    /// Esc 是否处于按下状态（原生全局兜底：窗口没拿到键盘焦点也能退出）。
    pub fn escape_down() -> bool {
        unsafe { (GetAsyncKeyState(0x1B) as u16 & 0x8000) != 0 }
    }

    /// 截图窗口是否已被系统判定为无响应。
    pub fn is_window_hung(hwnd: isize) -> bool {
        unsafe { IsHungAppWindow(hwnd as HWND) != 0 }
    }

    /// 看门狗线程跨线程恢复桌面：直接隐藏窗口并取消置顶。
    /// ShowWindow/SetWindowPos 允许从其它线程调用，即使主事件循环卡死也能先让桌面可用。
    pub fn emergency_hide_window(hwnd: isize) {
        unsafe {
            ShowWindow(hwnd as HWND, SW_HIDE);
            SetWindowPos(
                hwnd as HWND,
                HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            );
        }
    }

    /// 框选/标注需要键盘（Esc 取消）：临时让覆盖层可激活并拿到焦点。
    ///
    /// user:“框选不可用…有没有esc退出框选？”+(覆盖层默认 WS_EX_NOACTIVATE，
    /// 键盘事件根本进不来；进入捕获模式时去掉该位，退出时恢复。)
    pub fn set_overlay_activatable(window: &WebviewWindow, activatable: bool) -> Result<(), String> {
        let hwnd = window.hwnd().map_err(|error| error.to_string())?.0;
        unsafe {
            let current = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
            let wanted = if activatable {
                current & !(WS_EX_NOACTIVATE as isize)
            } else {
                current | (WS_EX_NOACTIVATE as isize)
            };
            SetWindowLongPtrW(hwnd, GWL_EXSTYLE, wanted);
        }
        Ok(())
    }


    pub struct RawWindow {
        pub id: String,
        pub title: String,
        pub class_name: String,
        pub x: i32,
        pub y: i32,
        pub width: i32,
        pub height: i32,
        pub z: i32,
    }

    struct WindowCollector {
        list: Vec<RawWindow>,
        skip_titles: Vec<String>,
        /// 生产调用传本进程 id，排除主界面/覆盖层/卡片；测试传 None 才能
        /// 在测试进程内造出“普通窗口”来验证枚举逻辑。
        exclude_pid: Option<u32>,
    }

    fn wide_to_string(raw: &[u16]) -> String {
        let end = raw.iter().position(|value| *value == 0).unwrap_or(raw.len());
        String::from_utf16_lossy(&raw[..end])
    }

    /// DWM 披隐检测：被系统"披隐"的窗口（输入体验、UWP 宿主等）对
    /// `IsWindowVisible` 报告可见、用户却看不见，不当地形。
    fn is_cloaked(hwnd: HWND) -> bool {
        unsafe {
            let mut cloaked: u32 = 0;
            let hr = DwmGetWindowAttribute(
                hwnd,
                DWMWA_CLOAKED as u32,
                &mut cloaked as *mut u32 as *mut core::ffi::c_void,
                std::mem::size_of::<u32>() as u32,
            );
            hr == 0 && cloaked != 0
        }
    }

    unsafe extern "system" fn enum_window(hwnd: HWND, data: LPARAM) -> windows_sys::core::BOOL {
        let collector = &mut *(data as *mut WindowCollector);
        let visible = IsWindowVisible(hwnd) != 0;
        let minimized = IsIconic(hwnd) != 0;
        // 不可见/最小化的窗口连标题都不必取，直接跳过（判定与下方纯函数一致）。
        if !visible || minimized {
            return 1;
        }
        // 自己的窗口（主界面、桌宠/Ping 覆盖层、卡片）永远不是地形。按进程 id
        // 判定而不是标题：标题可被用户修改、也可能与别的程序重名。
        if let Some(excluded) = collector.exclude_pid {
            let mut owner_pid: u32 = 0;
            GetWindowThreadProcessId(hwnd, &mut owner_pid);
            if owner_pid == excluded {
                return 1;
            }
        }
        let mut title_raw = [0u16; 512];
        let title_length = GetWindowTextW(hwnd, title_raw.as_mut_ptr(), title_raw.len() as i32);
        if title_length <= 0 {
            return 1;
        }
        let title = wide_to_string(&title_raw[..title_length as usize]);
        let mut class_raw = [0u16; 256];
        let class_length = GetClassNameW(hwnd, class_raw.as_mut_ptr(), class_raw.len() as i32);
        let class_name = if class_length > 0 {
            wide_to_string(&class_raw[..class_length as usize])
        } else {
            String::new()
        };
        let ex_style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
        // 工具窗口（托盘、浮层）不是桌面地形。
        let tool_window = ex_style & (WS_EX_TOOLWINDOW as isize) != 0;
        let mut rect: RECT = std::mem::zeroed();
        if GetWindowRect(hwnd, &mut rect) == 0 {
            return 1;
        }
        let width = rect.right - rect.left;
        let height = rect.bottom - rect.top;
        let cloaked = is_cloaked(hwnd);
        // 资格判定收拢在纯函数 is_terrain_window_candidate（块 B 验收语义）。
        if !is_terrain_window_candidate(
            visible,
            minimized,
            cloaked,
            tool_window,
            &class_name,
            &title,
            width,
            height,
            &collector.skip_titles,
        ) {
            return 1;
        }
        collector.list.push(RawWindow {
            id: format!("{:x}", hwnd as isize),
            title,
            class_name,
            x: rect.left,
            y: rect.top,
            width,
            height,
            z: collector.list.len() as i32,
        });
        1
    }

    /// 紧急关闭桌宠/Ping 覆盖层窗口（panic 兜底）。
    ///
    /// user:"那个'强制置顶'，你一定要给我记着。如果它一旦发生错误，把它退出置顶
    /// 或者直接关闭。不然的话，就会出现无法访问，但是直接把我的屏幕全给占掉"+
    /// (进程 panic 时窗口可能来不及走正常隐藏流程；直接给覆盖层窗口投 WM_CLOSE，
    ///  让置顶窗口立刻消失，宁可桌宠没了也不能占住整屏。)
    pub fn close_overlay_windows() {
        unsafe extern "system" fn enum_close(hwnd: HWND, lparam: LPARAM) -> i32 {
            let titles = &*(lparam as *const Vec<&'static str>);
            let mut buffer = [0u16; 256];
            let length = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
            if length > 0 {
                let title = String::from_utf16_lossy(&buffer[..length as usize]);
                if titles.iter().any(|candidate| *candidate == title) {
                    PostMessageW(hwnd, WM_CLOSE, 0, 0);
                }
            }
            1
        }
        let titles: Vec<&'static str> = vec!["Sunday Pet", "Sunday Ping"];
        unsafe {
            EnumWindows(Some(enum_close), &titles as *const _ as LPARAM);
        }
    }

    /// 真实桌面窗口几何：L2 地形与"真实遮挡"调试面板的数据来源。
    pub fn desktop_windows(skip_titles: Vec<String>, exclude_pid: Option<u32>) -> Vec<RawWindow> {
        let mut collector = WindowCollector { list: Vec::new(), skip_titles, exclude_pid };
        unsafe {
            EnumWindows(Some(enum_window), &mut collector as *mut WindowCollector as LPARAM);
        }
        collector.list
    }

    fn vk_for_key(key: &str) -> Option<i32> {
        let upper = key.to_ascii_uppercase();
        let vk = match upper.as_str() {
            "SPACE" => 0x20,
            "TAB" => 0x09,
            "ENTER" | "RETURN" => 0x0D,
            "ESC" | "ESCAPE" => 0x1B,
            "BACKQUOTE" | "`" => 0xC0,
            "CTRL" | "CONTROL" => 0x11,
            "SHIFT" => 0x10,
            "ALT" | "MENU" => 0x12,
            "WIN" | "META" => 0x5B,
            other if other.len() == 1 => {
                let ch = other.chars().next()?;
                match ch {
                    'A'..='Z' | '0'..='9' => ch as i32,
                    _ => return None,
                }
            }
            other if other.starts_with('F') => other[1..].parse::<i32>().ok().filter(|n| (1..=24).contains(n)).map(|n| 0x6F + n)?,
            _ => return None,
        };
        Some(vk)
    }

    pub fn parse_hotkey(text: &str) -> Result<HotkeySpec, String> {
        let mut modifiers = 0u8;
        let mut main: Option<i32> = None;
        let parts: Vec<&str> = text.split('+').map(|part| part.trim()).filter(|part| !part.is_empty()).collect();
        if parts.is_empty() {
            return Err("快捷键为空".into());
        }
        for (index, part) in parts.iter().enumerate() {
            let is_last = index + 1 == parts.len();
            match part.to_ascii_uppercase().as_str() {
                "CTRL" | "CONTROL" => modifiers |= MOD_CTRL,
                "SHIFT" => modifiers |= MOD_SHIFT,
                "ALT" | "MENU" => modifiers |= MOD_ALT,
                "WIN" | "META" | "SUPER" => modifiers |= MOD_WIN,
                _ => {
                    let vk = vk_for_key(part).ok_or_else(|| format!("不认识的按键：{part}"))?;
                    if is_last {
                        main = Some(vk);
                    } else {
                        return Err(format!("修饰键位置不对：{part}"));
                    }
                }
            }
        }
        let vk = main.ok_or_else(|| "快捷键缺少主键".to_string())?;
        Ok(HotkeySpec {
            accelerator: text.trim().to_string(),
            modifiers,
            vk,
        })
    }

    fn key_down(vk: i32) -> bool {
        unsafe { (GetAsyncKeyState(vk) as u16 & 0x8000) != 0 }
    }

    pub fn hotkey_active(spec: &HotkeySpec) -> bool {
        let ctrl = key_down(0x11);
        let shift = key_down(0x10);
        let alt = key_down(0x12);
        let win = key_down(0x5B) || key_down(0x5C);
        if (spec.modifiers & MOD_CTRL) != 0 && !ctrl {
            return false;
        }
        if (spec.modifiers & MOD_SHIFT) != 0 && !shift {
            return false;
        }
        if (spec.modifiers & MOD_ALT) != 0 && !alt {
            return false;
        }
        if (spec.modifiers & MOD_WIN) != 0 && !win {
            return false;
        }
        // 未声明的修饰键也必须抬起，否则 Ctrl+Alt+Space 会在只按 Ctrl+Space 时触发。
        if (spec.modifiers & MOD_CTRL) == 0 && ctrl && spec.vk != 0x11 {
            return false;
        }
        if (spec.modifiers & MOD_ALT) == 0 && alt && spec.vk != 0x12 {
            return false;
        }
        if (spec.modifiers & MOD_SHIFT) == 0 && shift && spec.vk != 0x10 {
            return false;
        }
        key_down(spec.vk)
    }
}

#[cfg(windows)]
pub use imp::{
    capture, close_overlay_windows, configure_overlay_window, cursor_position, desktop_windows,
    emergency_hide_window, escape_down, hotkey_active, is_window_hung, monitor_at, monitors, parse_hotkey,
    set_overlay_activatable, set_z_mode, virtual_screen_bounds,
};

// ---------------------------------------------------------------------------
// 非 Windows：明确不支持
// ---------------------------------------------------------------------------

#[cfg(not(windows))]
mod stub {
    use super::*;

    pub fn monitors() -> Result<Vec<MonitorInfo>, String> {
        Ok(Vec::new())
    }

    pub fn cursor_position() -> Result<(i32, i32), String> {
        Err("cursor position is only implemented on Windows".into())
    }

    pub fn monitor_at(_x: i32, _y: i32) -> Result<MonitorInfo, String> {
        Err("monitor geometry is only implemented on Windows".into())
    }

    pub fn virtual_screen_bounds() -> Result<OverlayBounds, String> {
        Err("desktop pet overlay is only implemented on Windows".into())
    }

    pub fn capture(_monitor: &MonitorInfo) -> Result<(u32, u32, Vec<u8>), String> {
        Err("screen capture is only implemented on Windows".into())
    }

    pub fn configure_overlay_window(_window: &WebviewWindow) -> Result<(), String> {
        Ok(())
    }

    pub fn set_overlay_activatable(_window: &WebviewWindow, _activatable: bool) -> Result<(), String> {
        Ok(())
    }

    pub fn escape_down() -> bool {
        false
    }

    pub fn is_window_hung(_hwnd: isize) -> bool {
        false
    }

    pub fn emergency_hide_window(_hwnd: isize) {}

    pub fn set_z_mode(_window: &WebviewWindow, _mode: &str) -> Result<(), String> {
        Ok(())
    }

    pub fn close_overlay_windows() {}

    pub fn parse_hotkey(text: &str) -> Result<HotkeySpec, String> {
        Ok(HotkeySpec {
            accelerator: text.to_string(),
            modifiers: 0,
            vk: 0,
        })
    }

    pub fn hotkey_active(_spec: &HotkeySpec) -> bool {
        false
    }

    pub struct RawWindow {
        pub id: String,
        pub title: String,
        pub class_name: String,
        pub x: i32,
        pub y: i32,
        pub width: i32,
        pub height: i32,
        pub z: i32,
    }

    pub fn desktop_windows(_skip_titles: Vec<String>, _exclude_pid: Option<u32>) -> Vec<RawWindow> {
        Vec::new()
    }
}

#[cfg(not(windows))]
pub use stub::{
    capture, close_overlay_windows, configure_overlay_window, cursor_position, desktop_windows,
    hotkey_active, monitor_at, monitors, parse_hotkey, set_z_mode, virtual_screen_bounds,
};

// ---------------------------------------------------------------------------
// 块 B 验收测试（地图/地形数据层：L1 屏幕边界 / L2 真实窗口边缘）
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::{MonitorInfo, OverlayBounds};

    fn monitor(x: i32, y: i32, width: i32, height: i32, scale: f64, primary: bool) -> MonitorInfo {
        MonitorInfo { id: format!("{x}@{y}"), x, y, width, height, primary, scale }
    }

    fn contains(bounds: &OverlayBounds, m: &MonitorInfo) -> bool {
        bounds.x <= m.x
            && bounds.y <= m.y
            && bounds.x + bounds.width >= m.x + m.width
            && bounds.y + bounds.height >= m.y + m.height
    }

    // user:“B4 L1 蓝线完整围住屏幕四边（此前底边被裁）”+“MAP-01 L1 屏幕边界 + 跨屏坐标：`TerrainField.setScreenBounds` 用虚拟桌面矩形”+
    // (L1 的四条蓝线由报告矩形的四条边生成：left=x、top=y、right=x+width、
    //  bottom=y+height。数据层必须保证这个矩形是全部显示器的并集——尤其
    //  bottom/right 取所有显示器边缘的最大值，否则对应边的蓝线会被裁掉。)
    #[test]
    fn block_b_union_bounds_cover_every_monitor_including_bottom_edge() {
        let list = vec![
            monitor(0, 0, 1920, 1080, 1.0, true),
            monitor(1920, 200, 2560, 1440, 1.0, false),
        ];
        let bounds = super::union_bounds(&list);
        assert_eq!((bounds.x, bounds.y, bounds.width, bounds.height), (0, 0, 4480, 1640));
        for m in &list {
            assert!(contains(&bounds, m), "monitor {m:?} must be fully inside the union");
        }
        // 底边必须等于最深显示器的底边（"底边被裁"的根因类别）。
        assert_eq!(bounds.y + bounds.height, 1640);
        // 单屏也不能变形。
        let single = super::union_bounds(&[monitor(0, 0, 3840, 2160, 1.5, true)]);
        assert_eq!((single.x, single.y, single.width, single.height), (0, 0, 3840, 2160));
        assert_eq!(single.scale, 1.5, "主屏缩放要带出去，供覆盖层换算 CSS 像素");
    }

    // user:“MAP-01 L1 屏幕边界 + 跨屏坐标”+
    // (副屏在负坐标区（主屏左侧/上方）时，并集必须把负半区也包进来，
    //  跨屏坐标才成立。)
    #[test]
    fn block_b_union_bounds_keep_negative_cross_screen_region() {
        let list = vec![
            monitor(0, 0, 1920, 1080, 1.0, true),
            monitor(-1920, -200, 1920, 1080, 1.5, false),
        ];
        let bounds = super::union_bounds(&list);
        assert_eq!(bounds.x, -1920);
        assert_eq!(bounds.y, -200);
        assert!(contains(&bounds, &list[0]) && contains(&bounds, &list[1]));
    }

    // user:“B1 桌面上每个可见顶层窗口 ↔ 恰好一组黄线”+“B2 不可见/零尺寸/工具窗口不产生黄线”+
    // (黄线与报告一一对应，所以"谁有资格进报告"就是"谁该有黄线"：不可见、
    //  最小化、工具浮层、空标题、自己的窗口、小于最小尺寸的窗口都排除。)
    #[test]
    fn block_b_window_filter_blocks_invisible_zero_size_and_tool_windows() {
        let skip = vec!["Sunday Pet".to_string(), "Sunday".to_string()];
        let ok = |visible: bool, minimized: bool, tool: bool, title: &str, w: i32, h: i32| {
            super::is_terrain_window_candidate(visible, minimized, false, tool, "NormalApp", title, w, h, &skip)
        };
        // 普通可见顶层窗口是 B1 黄线的来源；120×80 是数据层的最小资格线。
        assert!(ok(true, false, false, "Visual Studio Code", 1280, 800));
        assert!(ok(true, false, false, "边界上的窗口", 120, 80));
        // B2 的三类必排除窗口。
        assert!(!ok(false, false, false, "隐藏的窗口", 1280, 800));
        assert!(!ok(true, true, false, "最小化的窗口", 1280, 800));
        assert!(!ok(true, false, false, "零尺寸", 0, 0));
        assert!(!ok(true, false, false, "太窄", 119, 800));
        assert!(!ok(true, false, false, "太矮", 1280, 79));
        assert!(!ok(true, false, true, "工具浮层", 300, 200));
        // 空标题与自己的窗口也不能当地形（否则覆盖层/主窗给自己画黄线）。
        assert!(!ok(true, false, false, "", 1280, 800));
        assert!(!ok(true, false, false, "Sunday Pet", 1920, 1080));
        assert!(!ok(true, false, false, "Sunday", 1920, 1080));
        // user:"你告诉我这个黄线凭什么在这儿，每一根黄线都跟我解释为什么它在这儿"+
        // (披隐窗口：IsWindowVisible 为真但用户看不见，不算桌面地形；
        //  CoreWindow 壳窗（"Windows 输入体验"）：即使全可见、全屏大小，
        //  也不是用户感知中的桌面内容，必须按类名剔除。)
        assert!(!super::is_terrain_window_candidate(
            true, false, true, false, "NormalApp", "被披隐的窗口", 1280, 800, &skip
        ));
        assert!(!super::is_terrain_window_candidate(
            true, false, false, false, "Windows.UI.Core.CoreWindow", "Windows 输入体验", 2048, 1152, &skip
        ));
    }

    #[cfg(windows)]
    mod real_windows {
        use super::super::desktop_windows;
        use super::super::imp::RawWindow;
        use super::super::{monitors, virtual_screen_bounds};
        use windows_sys::Win32::Foundation::{HWND, RECT};
        use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            CreateWindowExW, DefWindowProcW, DestroyWindow, GetWindowRect, RegisterClassW,
            SetWindowPos, SWP_NOSIZE, SWP_NOZORDER, WNDCLASSW, WS_EX_TOOLWINDOW,
            WS_OVERLAPPEDWINDOW, WS_POPUP, WS_VISIBLE,
        };

        fn wide(text: &str) -> Vec<u16> {
            text.encode_utf16().chain(std::iter::once(0)).collect()
        }

        /// 注册一次测试窗口类；重复注册失败没有关系（类已存在即可用）。
        fn ensure_class(name: &str) {
            let class_name = wide(name);
            unsafe {
                let mut class: WNDCLASSW = std::mem::zeroed();
                class.lpfnWndProc = Some(DefWindowProcW);
                class.hInstance = GetModuleHandleW(std::ptr::null());
                class.lpszClassName = class_name.as_ptr();
                RegisterClassW(&class);
            }
        }

        /// 测试探针窗口：销毁即清理，不留残留。
        struct ProbeWindow(HWND);

        impl ProbeWindow {
            unsafe fn create(
                class: &str,
                title: &str,
                ex_style: u32,
                style: u32,
                width: i32,
                height: i32,
            ) -> Self {
                let (class_w, title_w) = (wide(class), wide(title));
                let hwnd = CreateWindowExW(
                    ex_style,
                    class_w.as_ptr(),
                    title_w.as_ptr(),
                    style,
                    60,
                    60,
                    width,
                    height,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    GetModuleHandleW(std::ptr::null()),
                    std::ptr::null(),
                );
                assert!(
                    !hwnd.is_null(),
                    "测试窗口必须能创建：cargo test 需要跑在有交互桌面的会话里"
                );
                ProbeWindow(hwnd)
            }

            fn id(&self) -> String {
                format!("{:x}", self.0 as isize)
            }

            /// 直接问系统的矩形，用来和上报值对号。
            fn rect(&self) -> (i32, i32, i32, i32) {
                unsafe {
                    let mut rect: RECT = std::mem::zeroed();
                    assert_ne!(GetWindowRect(self.0, &mut rect), 0);
                    (rect.left, rect.top, rect.right, rect.bottom)
                }
            }

            fn move_to(&self, x: i32, y: i32) {
                unsafe {
                    SetWindowPos(self.0, std::ptr::null_mut(), x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER);
                }
            }
        }

        impl Drop for ProbeWindow {
            fn drop(&mut self) {
                unsafe { DestroyWindow(self.0) };
            }
        }

        fn find_all<'a>(report: &'a [RawWindow], title: &str) -> Vec<&'a RawWindow> {
            report.iter().filter(|w| w.title == title).collect()
        }

        // user:“B1 桌面上每个可见顶层窗口 ↔ 恰好一组黄线，逐一对号”+
        // (数据层的对号保证：每个符合资格的顶层窗口在报告里恰好出现一次，
        //  id 与 HWND 一一对应且全局唯一——前端 setWindows 按 id 生成"一组黄线"，
        //  报告重复或遗漏都会直接变成黄线多画/漏画。z 序随枚举顺序递增。)
        #[test]
        fn block_b_enumwindows_lists_normal_window_exactly_once_with_unique_ids() {
            ensure_class("SundayPetBlockBTestClass");
            let tag = format!("{:x}", std::process::id());
            let title = format!("B1-NORMAL-{tag}");
            let probe = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &title,
                    0,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    900,
                    600,
                )
            };
            let (left, top, right, bottom) = probe.rect();
            let report = desktop_windows(vec!["Sunday Pet".to_string(), "Sunday".to_string()], None);

            let mine = find_all(&report, &title);
            assert_eq!(mine.len(), 1, "可见顶层窗口必须恰好对应一条报告");
            assert_eq!(mine[0].id, probe.id(), "报告 id 必须就是该窗口的 HWND");
            assert_eq!(
                (mine[0].x, mine[0].y, mine[0].width, mine[0].height),
                (left, top, right - left, bottom - top),
                "上报矩形必须与系统矩形一致"
            );
            // 一对一的全局面：id 全局唯一，z 严格等于枚举序号。
            let mut ids: Vec<&str> = report.iter().map(|w| w.id.as_str()).collect();
            ids.sort_unstable();
            let before = ids.len();
            ids.dedup();
            assert_eq!(ids.len(), before, "一个 HWND 只能有一条报告（黄线一对号的前提）");
            for (index, window) in report.iter().enumerate() {
                assert_eq!(window.z, index as i32, "z 序必须随枚举顺序递增");
            }
        }

        // user:“B2 不可见/零尺寸/工具窗口不产生黄线”+
        // (在真实 EnumWindows 通道上验证：三种窗口都不会进报告，
        //  而同场的普通可见窗口照常上报。)
        #[test]
        fn block_b_enumwindows_skips_invisible_zero_size_and_tool_windows() {
            ensure_class("SundayPetBlockBTestClass");
            let tag = format!("{:x}", std::process::id());
            let _normal = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &format!("B2-NORMAL-{tag}"),
                    0,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    800,
                    600,
                )
            };
            let _hidden = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &format!("B2-HIDDEN-{tag}"),
                    0,
                    WS_OVERLAPPEDWINDOW,
                    800,
                    600,
                )
            };
            let _zero = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &format!("B2-ZERO-{tag}"),
                    0,
                    WS_POPUP | WS_VISIBLE,
                    0,
                    0,
                )
            };
            let _tool = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &format!("B2-TOOL-{tag}"),
                    WS_EX_TOOLWINDOW,
                    WS_POPUP | WS_VISIBLE,
                    300,
                    200,
                )
            };

            let report = desktop_windows(vec!["Sunday Pet".to_string(), "Sunday".to_string()], None);
            let count = |title: String| find_all(&report, &title).len();
            assert_eq!(count(format!("B2-NORMAL-{tag}")), 1, "同场普通窗口必须照常上报");
            assert_eq!(count(format!("B2-HIDDEN-{tag}")), 0, "不可见窗口不得进报告");
            assert_eq!(count(format!("B2-ZERO-{tag}")), 0, "零尺寸窗口不得进报告");
            assert_eq!(count(format!("B2-TOOL-{tag}")), 0, "工具窗口不得进报告");
        }

        // user:“B3 拖动真实窗口，黄线跟随”+
        // (跟随的数据前提：窗口每被枚举一次就带出当时的最新矩形，且 id 跨轮次稳定
        //  ——前端 applyWindows/moveWindowSource 正是按 id 匹配上一帧位置来平移黄线；
        //  id 不稳定会被当成"旧窗没了、新窗出现"，黄线就不会跟随。)
        #[test]
        fn block_b_enumwindows_reports_moved_geometry_with_stable_id() {
            ensure_class("SundayPetBlockBTestClass");
            let tag = format!("{:x}", std::process::id());
            let title = format!("B3-MOVE-{tag}");
            let probe = unsafe {
                ProbeWindow::create(
                    "SundayPetBlockBTestClass",
                    &title,
                    0,
                    WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                    700,
                    500,
                )
            };
            let first = desktop_windows(vec!["Sunday Pet".to_string(), "Sunday".to_string()], None);
            let before = find_all(&first, &title);
            assert_eq!(before.len(), 1, "移动前必须已上报");
            let id_before = before[0].id.clone();
            let (x0, y0, _, _) = probe.rect();

            probe.move_to(x0 + 37, y0 + 11);

            let second = desktop_windows(vec!["Sunday Pet".to_string(), "Sunday".to_string()], None);
            let after = find_all(&second, &title);
            assert_eq!(after.len(), 1, "移动后必须仍在报告里");
            assert_eq!(after[0].id, id_before, "id 跨轮次稳定（跟随按 id 匹配）");
            let (x1, y1, right, bottom) = probe.rect();
            assert_eq!(
                (after[0].x, after[0].y, after[0].width, after[0].height),
                (x1, y1, right - x1, bottom - y1),
                "上报矩形必须跟着窗口走"
            );
            assert_eq!((after[0].x - before[0].x, after[0].y - before[0].y), (37, 11));
        }

        // user:“B4 L1 蓝线完整围住屏幕四边（此前底边被裁）”+
        // (真机通道核验：报告的虚拟桌面矩形必须完整包住每一个显示器——
        //  底边、右边取所有显示器边缘的最大值，而不是单屏尺寸。)
        #[test]
        fn block_b_virtual_screen_bounds_contain_every_monitor() {
            let list = monitors().expect("Windows 上必须能枚举显示器");
            let bounds = virtual_screen_bounds().expect("虚拟桌面矩形必须可得");
            assert!(bounds.width >= 1 && bounds.height >= 1);
            for m in &list {
                assert!(bounds.x <= m.x && bounds.y <= m.y, "monitor {m:?} 左上越界");
                assert!(
                    bounds.x + bounds.width >= m.x + m.width,
                    "右边必须够到最靠右的显示器"
                );
                assert!(
                    bounds.y + bounds.height >= m.y + m.height,
                    "底边必须够到最靠下的显示器（此前底边被裁）"
                );
            }
        }
    }
}

/// 截图二进制帧：`PETC` + u32 宽 + u32 高 + i32 屏幕 x + i32 屏幕 y + f64 缩放 + RGBA。
/// 用二进制而不是 base64，4K 截图不必额外膨胀 1/3。
pub fn encode_capture_bytes(
    x: i32,
    y: i32,
    scale: f64,
    width: u32,
    height: u32,
    pixels: Vec<u8>,
) -> Vec<u8> {
    let mut frame = Vec::with_capacity(24 + pixels.len());
    frame.extend_from_slice(b"PETC");
    frame.extend_from_slice(&width.to_le_bytes());
    frame.extend_from_slice(&height.to_le_bytes());
    frame.extend_from_slice(&x.to_le_bytes());
    frame.extend_from_slice(&y.to_le_bytes());
    frame.extend_from_slice(&scale.to_le_bytes());
    frame.extend_from_slice(&pixels);
    frame
}

pub fn encode_capture(
    x: i32,
    y: i32,
    scale: f64,
    width: u32,
    height: u32,
    pixels: Vec<u8>,
) -> tauri::ipc::Response {
    tauri::ipc::Response::new(encode_capture_bytes(x, y, scale, width, height, pixels))
}
