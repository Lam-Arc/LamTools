//! WebView2 CompositionController + DirectComposition 统一视觉合成托管层。
//!
//! user:“迁移”+(用同窗口 DirectComposition 合成树托管内置浏览器子 WebView，
//! 主界面通过透明窗口区域透出底层实时网页，菜单/浮层/拖拽虚影天然压在网页之上，无需截图冻结。)

use std::cell::RefCell;
use std::collections::HashMap;
use std::path::PathBuf;
use tauri::{AppHandle, Emitter};

use crate::browser::webview::Bounds;
use crate::browser::BrowserError;

#[cfg(windows)]
fn pixel_size(bounds: Bounds) -> (i32, i32) {
    (bounds.width.round().max(1.0) as i32, bounds.height.round().max(1.0) as i32)
}

// user:“可使用Rust重写相关代码”+(只在原生属性确实变化时更新 WebView2 和合成树)。
#[cfg(windows)]
fn bounds_changes(previous: Option<Bounds>, next: Bounds) -> (bool, bool, bool) {
    let Some(previous) = previous else { return (true, true, true) };
    let moved = (previous.x as f32, previous.y as f32) != (next.x as f32, next.y as f32);
    (moved, pixel_size(previous) != pixel_size(next), previous.visible != next.visible)
}

// user:“传递容器尺寸，优化这种尺寸不恰当的问题”+(响应式网页保持原比例，超出视口的页面才缩小，沿用网页手动缩放的下限)。
#[cfg(any(windows, test))]
fn viewport_fit_zoom(preferred: f64, viewport: f64, content: f64) -> f64 {
    if !viewport.is_finite() || !content.is_finite() || viewport <= 1.0 || content - viewport <= 2.0 {
        return preferred;
    }
    let fit = (preferred * (viewport - 1.0) / content * 100.0).floor() / 100.0;
    fit.max(preferred.min(0.25))
}

#[cfg(test)]
mod viewport_fit_tests {
    use super::viewport_fit_zoom;

    #[test]
    fn viewport_fit_shrinks_a_desktop_page_in_a_narrow_container() {
        assert_eq!(viewport_fit_zoom(1.0, 460.0, 880.0), 0.52);
        assert_eq!(viewport_fit_zoom(1.25, 400.0, 800.0), 0.62);
    }

    #[test]
    fn viewport_fit_keeps_responsive_pages_and_user_zoom_as_the_upper_bound() {
        assert_eq!(viewport_fit_zoom(1.25, 460.0, 461.0), 1.25);
        assert_eq!(viewport_fit_zoom(0.8, 860.0, 800.0), 0.8);
        assert_eq!(viewport_fit_zoom(0.2, 300.0, 1600.0), 0.2);
        assert_eq!(viewport_fit_zoom(1.0, 300.0, 1600.0), 0.25);
        assert_eq!(viewport_fit_zoom(1.0, 0.0, 880.0), 1.0);
    }
}

/// 视觉总序（低 → 高）：分屏永远在前，浮窗永远在后；同类按前端给的 stack_index，同层再按 id 稳定排序。
///
/// user:“浮层网页层级不对，被分屏遮挡了”+(层级必须有一份可复算的总序，
/// 不能只靠“相对某个兄弟节点插一下”的增量结果；增量一旦漂移就没有任何步骤能纠回来)。
#[cfg(any(windows, test))]
fn stack_order<'a>(mut tabs: Vec<(&'a str, bool, u32)>) -> Vec<(&'a str, bool, u32)> {
    tabs.sort_by(|left, right| {
        (u32::from(left.1), left.2, left.0).cmp(&(u32::from(right.1), right.2, right.0))
    });
    tabs
}

#[cfg(test)]
mod stack_order_tests {
    use super::stack_order;

    fn ids(tabs: Vec<(&str, bool, u32)>) -> Vec<&str> {
        stack_order(tabs).into_iter().map(|(id, _, _)| id).collect()
    }

    #[test]
    fn splits_stay_below_every_float() {
        assert_eq!(
            ids(vec![("float-a", true, 1), ("split-b", false, 0), ("split-a", false, 0)]),
            vec!["split-a", "split-b", "float-a"],
        );
    }

    #[test]
    fn floats_keep_the_order_the_front_end_asked_for() {
        assert_eq!(
            ids(vec![("float-b", true, 2), ("split", false, 0), ("float-a", true, 1)]),
            vec!["split", "float-a", "float-b"],
        );
    }

    #[test]
    fn a_float_stays_on_top_even_if_a_split_carries_a_stale_higher_index() {
        assert_eq!(
            ids(vec![("split-high", false, 5), ("float-low", true, 0)]),
            vec!["split-high", "float-low"],
        );
    }
}

#[cfg(windows)]
mod win {
    use super::*;
    use std::time::{Duration, Instant};
    use crate::browser::session::ProfileEnvironment;
    use crate::browser::url_policy::allowed_navigation;
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        CreateCoreWebView2EnvironmentWithOptions, ICoreWebView2, ICoreWebView2CompositionController,
        ICoreWebView2Controller, ICoreWebView2Controller3, ICoreWebView2Environment,
        ICoreWebView2Environment10, ICoreWebView2Environment3, ICoreWebView2EnvironmentOptions,
        ICoreWebView2_4, COREWEBVIEW2_BOUNDS_MODE_USE_RAW_PIXELS, COREWEBVIEW2_DOWNLOAD_STATE_COMPLETED,
        COREWEBVIEW2_DOWNLOAD_STATE_INTERRUPTED, COREWEBVIEW2_MOUSE_EVENT_KIND,
        COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS, COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC,
    };
    use webview2_com::{
        CoreWebView2EnvironmentOptions, CreateCoreWebView2CompositionControllerCompletedHandler,
        CreateCoreWebView2EnvironmentCompletedHandler, DownloadStartingEventHandler, ExecuteScriptCompletedHandler,
        NavigationCompletedEventHandler, NavigationStartingEventHandler,
        NewWindowRequestedEventHandler, SourceChangedEventHandler, StateChangedEventHandler,
    };
    use windows::core::{Interface, HSTRING, PCWSTR, PWSTR};
    use windows::Win32::Foundation::{HMODULE, HWND, POINT, RECT};
    use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
    use windows::Win32::Graphics::Direct3D11::{
        D3D11CreateDevice, D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_SDK_VERSION,
    };
    use windows::Win32::Graphics::DirectComposition::{
        DCompositionCreateDevice, IDCompositionDevice, IDCompositionTarget, IDCompositionVisual,
    };
    use windows::Win32::Graphics::Dxgi::IDXGIDevice;

    struct ComposedTab {
        controller: ICoreWebView2Controller,
        comp: ICoreWebView2CompositionController,
        core: ICoreWebView2,
        visual: IDCompositionVisual,
        bounds: Bounds,
        bounds_applied: bool,
        stack_index: u32,
        /// 是否是浮窗；浮窗永远排在所有分屏之上，不依赖增量插入恰好算对。
        is_float: bool,
        preferred_zoom: f64,
        fit_revision: u64,
        fit_due: Option<Instant>,
    }

    struct CompositorHost {
        hwnd: HWND,
        dcomp: IDCompositionDevice,
        _target: IDCompositionTarget,
        root_visual: IDCompositionVisual,
        envs: HashMap<Option<PathBuf>, ICoreWebView2Environment>,
        tabs: HashMap<String, ComposedTab>,
        /// 上次真正下发给合成树的顺序，只在变化时打日志，避免拖拽时刷屏。
        last_order: String,
    }

    thread_local! {
        static HOST: RefCell<Option<CompositorHost>> = const { RefCell::new(None) };
    }

    /// 前端下发的网络出口：`accelerator` 用 EasyNet 的本机加速端口，`system` 回到系统代理，
    /// `direct` 不走代理。None 表示还没同步过，按原来的系统代理行为走。
    static NETWORK_OVERRIDE: std::sync::Mutex<Option<(String, String)>> = std::sync::Mutex::new(None);

    fn network_override() -> Option<(String, String)> {
        NETWORK_OVERRIDE.lock().ok().and_then(|slot| slot.clone())
    }

    /// 记录新出口并丢掉已缓存的环境，让之后创建的网页用新出口（已打开的不受影响）。
    pub fn set_network_state(mode: &str, endpoint: &str) -> bool {
        let mode = match mode.trim() {
            "accelerator" | "direct" | "system" => mode.trim().to_string(),
            _ => "system".to_string(),
        };
        if let Ok(mut slot) = NETWORK_OVERRIDE.lock() {
            *slot = Some((mode, endpoint.trim().to_string()));
        }
        clear_environment_cache();
        true
    }

    pub fn clear_environment_cache() {
        HOST.with(|cell| {
            if let Some(host) = cell.borrow_mut().as_mut() {
                host.envs.clear();
            }
        });
    }

    fn take_pwstr(ptr: PWSTR) -> String {
        if ptr.is_null() {
            return String::new();
        }
        unsafe {
            let text = ptr.to_string().unwrap_or_default();
            windows::Win32::System::Com::CoTaskMemFree(Some(ptr.0 as *const _));
            text
        }
    }

    fn ensure_host(hwnd: HWND) -> Result<(), BrowserError> {
        HOST.with(|cell| {
            let mut slot = cell.borrow_mut();
            if let Some(existing) = slot.as_ref() {
                if existing.hwnd == hwnd {
                    return Ok(());
                }
            }
            unsafe {
                let mut d3d_device = None;
                D3D11CreateDevice(
                    None,
                    D3D_DRIVER_TYPE_HARDWARE,
                    HMODULE::default(),
                    D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                    None,
                    D3D11_SDK_VERSION,
                    Some(&mut d3d_device),
                    None,
                    None,
                )
                .map_err(|e| BrowserError::internal(format!("初始化 D3D11 失败：{e}")))?;
                let d3d_device = d3d_device.ok_or_else(|| BrowserError::internal("D3D11 设备为空"))?;
                let dxgi: IDXGIDevice = d3d_device
                    .cast()
                    .map_err(|e| BrowserError::internal(format!("获取 DXGI 失败：{e}")))?;
                let dcomp: IDCompositionDevice = DCompositionCreateDevice(&dxgi)
                    .map_err(|e| BrowserError::internal(format!("创建 DirectComposition 失败：{e}")))?;
                // topmost = false：合成树画在主窗口底层，Tauri 透明主界面自然压在上方。
                let target = dcomp
                    .CreateTargetForHwnd(hwnd, false)
                    .map_err(|e| BrowserError::internal(format!("绑定窗口合成目标失败：{e}")))?;
                let root_visual = dcomp
                    .CreateVisual()
                    .map_err(|e| BrowserError::internal(format!("创建根视觉节点失败：{e}")))?;
                target
                    .SetRoot(&root_visual)
                    .map_err(|e| BrowserError::internal(format!("设置根视觉节点失败：{e}")))?;
                dcomp
                    .Commit()
                    .map_err(|e| BrowserError::internal(format!("提交合成树失败：{e}")))?;
                *slot = Some(CompositorHost {
                    hwnd,
                    dcomp,
                    _target: target,
                    root_visual,
                    envs: HashMap::new(),
                    tabs: HashMap::new(),
                    last_order: String::new(),
                });
                Ok(())
            }
        })
    }

    fn with_env(
        data_dir: Option<PathBuf>,
        callback: impl FnOnce(Result<ICoreWebView2Environment, BrowserError>) + 'static,
    ) {
        let cached = HOST.with(|cell| {
            cell.borrow()
                .as_ref()
                .and_then(|h| h.envs.get(&data_dir).cloned())
        });
        if let Some(env) = cached {
            callback(Ok(env));
            return;
        }
        let dir_key = data_dir.clone();
        let dir_h = data_dir
            .as_ref()
            .map(|p| HSTRING::from(p.to_string_lossy().as_ref()));
        let mut cb = Some(callback);
        let handler = CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(move |res, env| {
            let Some(cb) = cb.take() else { return Ok(()) };
            if let Err(e) = res {
                cb(Err(BrowserError::internal(format!("创建 WebView2 环境失败：{e}"))));
                return Ok(());
            }
            let Some(env) = env else {
                cb(Err(BrowserError::internal("WebView2 环境为空")));
                return Ok(());
            };
            HOST.with(|cell| {
                if let Some(host) = cell.borrow_mut().as_mut() {
                    host.envs.insert(dir_key.clone(), env.clone());
                }
            });
            cb(Ok(env));
            Ok(())
        }));
        let pcwstr = dir_h
            .as_ref()
            .map(|h| PCWSTR(h.as_ptr()))
            .unwrap_or(PCWSTR::null());
        let env_opts = build_environment_options();
        if let Err(e) = unsafe { CreateCoreWebView2EnvironmentWithOptions(PCWSTR::null(), pcwstr, &env_opts, &handler) } {
            // Note: handler may not have been invoked if CreateCoreWebView2EnvironmentWithOptions failed synchronously.
            let _ = e;
        }
    }

    fn read_reg_dword(hkey: windows::Win32::System::Registry::HKEY, name: &str) -> Option<u32> {
        use windows::Win32::System::Registry::{RegQueryValueExW, REG_DWORD, REG_VALUE_TYPE};
        let mut val = 0u32;
        let mut size = std::mem::size_of::<u32>() as u32;
        let mut kind = REG_VALUE_TYPE::default();
        let wname = HSTRING::from(name);
        let status = unsafe {
            RegQueryValueExW(
                hkey,
                &wname,
                None,
                Some(&mut kind),
                Some((&mut val as *mut u32).cast::<u8>()),
                Some(&mut size),
            )
        };
        if status.is_ok() && kind == REG_DWORD {
            Some(val)
        } else {
            None
        }
    }

    fn read_reg_string(hkey: windows::Win32::System::Registry::HKEY, name: &str) -> Option<String> {
        use windows::Win32::System::Registry::{RegQueryValueExW, REG_EXPAND_SZ, REG_SZ, REG_VALUE_TYPE};
        let wname = HSTRING::from(name);
        let mut kind = REG_VALUE_TYPE::default();
        let mut size = 0u32;
        if unsafe { RegQueryValueExW(hkey, &wname, None, Some(&mut kind), None, Some(&mut size)) }.is_err()
            || size < 2
        {
            return None;
        }
        let mut buf = vec![0u16; (size as usize).div_ceil(2)];
        let status = unsafe {
            RegQueryValueExW(
                hkey,
                &wname,
                None,
                Some(&mut kind),
                Some(buf.as_mut_ptr().cast::<u8>()),
                Some(&mut size),
            )
        };
        if status.is_err() || (kind != REG_SZ && kind != REG_EXPAND_SZ) {
            return None;
        }
        let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        let s = String::from_utf16_lossy(&buf[..end]).trim().to_string();
        if s.is_empty() { None } else { Some(s) }
    }

    fn windows_system_proxy() -> (Option<String>, Option<String>) {
        use windows::Win32::System::Registry::{RegCloseKey, RegOpenKeyExW, HKEY, HKEY_CURRENT_USER, KEY_READ};
        let mut hkey = HKEY::default();
        let subkey = HSTRING::from(r"Software\Microsoft\Windows\CurrentVersion\Internet Settings");
        if unsafe { RegOpenKeyExW(HKEY_CURRENT_USER, &subkey, Some(0), KEY_READ, &mut hkey) }.is_ok() {
            let enabled = read_reg_dword(hkey, "ProxyEnable").unwrap_or(0) == 1;
            let server = if enabled { read_reg_string(hkey, "ProxyServer") } else { None };
            let bypass = if enabled { read_reg_string(hkey, "ProxyOverride") } else { None };
            unsafe { let _ = RegCloseKey(hkey); }
            if server.is_some() {
                return (server, bypass);
            }
        }
        let env_proxy = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"]
            .iter()
            .find_map(|k| std::env::var(k).ok().map(|v| v.trim().to_string()).filter(|v| !v.is_empty()));
        (env_proxy, None)
    }

    pub(crate) fn format_environment_args(
        base: &str,
        proxy_server: Option<&str>,
        proxy_bypass: Option<&str>,
    ) -> String {
        // user:“直接优化”+(内嵌网页使用独立 WebView2 环境，隐藏时恢复默认后台节流)。
        let base = base.strip_prefix(crate::pet::BASE_BROWSER_ARGS).unwrap_or(base);
        let mut args = base.trim().to_string();
        if !args.contains("msSmartScreenProtection") {
            if !args.is_empty() {
                args.push(' ');
            }
            args.push_str("--disable-features=msSmartScreenProtection");
        }
        // user:“就是纯粹的慢，起码对谷歌是这样，到了 10s 级以上”+
        // (走 HTTP 代理时禁用 QUIC/HTTP3，避免 Google 等站点先尝试 UDP QUIC 超时回退拖慢 10 秒以上)
        if !args.contains("--disable-quic") {
            if !args.is_empty() {
                args.push(' ');
            }
            args.push_str("--disable-quic");
        }
        if let Some(proxy) = proxy_server.map(str::trim).filter(|s| !s.is_empty()) {
            if !args.is_empty() {
                args.push(' ');
            }
            args.push_str("--proxy-server=");
            args.push_str(proxy);
            if let Some(bypass) = proxy_bypass.map(str::trim).filter(|s| !s.is_empty()) {
                args.push_str(" --proxy-bypass-list=");
                args.push_str(bypass);
            }
        }
        args
    }

    fn build_environment_options() -> ICoreWebView2EnvironmentOptions {
        // user:“我在 Chrome 或者 Edge 搜索就是毫秒级响应，这里要卡很久”+
        // (把 Windows 系统代理显式传给合成 WebView2 环境，避免 WinHTTP 为 Direct 时直连超时)
        // user:“EasyNet 开了加速，浏览器立刻用上”+(出口由前端下发，没有下发时仍按系统代理)。
        let (proxy, bypass) = match network_override() {
            Some((mode, endpoint)) if mode == "accelerator" && !endpoint.is_empty() => {
                (Some(endpoint), Some("localhost;127.*".to_string()))
            }
            Some((mode, _)) if mode == "direct" => (None, None),
            _ => windows_system_proxy(),
        };
        let args = format_environment_args(
            &crate::pet::browser_args_from_env(),
            proxy.as_deref(),
            bypass.as_deref(),
        );
        let opts = CoreWebView2EnvironmentOptions::default();
        unsafe {
            opts.set_additional_browser_arguments(args);
        }
        opts.into()
    }

    fn apply_bounds(host: &CompositorHost, tab: &mut ComposedTab, bounds: Bounds) {
        let previous = tab.bounds_applied.then_some(tab.bounds);
        let (moved, resized, visibility_changed) = bounds_changes(previous, bounds);
        tab.bounds = bounds;
        if !moved && !resized && !visibility_changed {
            return;
        }
        unsafe {
            let mut applied = true;
            if moved {
                applied &= tab.visual.SetOffsetX2(bounds.x as f32).is_ok();
                applied &= tab.visual.SetOffsetY2(bounds.y as f32).is_ok();
            }
            if resized {
                let (right, bottom) = pixel_size(bounds);
                applied &= tab.controller.SetBounds(RECT { left: 0, top: 0, right, bottom }).is_ok();
            }
            if visibility_changed {
                applied &= tab.controller.SetIsVisible(bounds.visible).is_ok();
            }
            applied &= host.dcomp.Commit().is_ok();
            tab.bounds_applied = applied;
        }
    }

    const FIT_DELAY: Duration = Duration::from_millis(140);
    // Read layout only. This is neither a navigation hook nor a script that the page needs to load.
    const VIEWPORT_WIDTHS: &str = "(() => { const root = document.documentElement; return root && document.readyState !== 'loading' ? [root.clientWidth, Math.max(root.scrollWidth, document.body?.scrollWidth ?? 0)] : null; })()";

    fn request_viewport_fit(app: &AppHandle, tab: &str) {
        let schedule = HOST.with(|cell| {
            let mut slot = cell.borrow_mut();
            let Some(entry) = slot.as_mut().and_then(|host| host.tabs.get_mut(tab)) else { return false };
            entry.fit_revision = entry.fit_revision.wrapping_add(1);
            if !entry.bounds.visible || entry.preferred_zoom != 1.0 {
                return false;
            }
            entry.fit_due.replace(Instant::now() + FIT_DELAY).is_none()
        });
        if schedule {
            wait_for_viewport_fit(app.clone(), tab.to_owned(), FIT_DELAY);
        }
    }

    fn wait_for_viewport_fit(app: AppHandle, tab: String, delay: Duration) {
        tauri::async_runtime::spawn_blocking(move || {
            std::thread::sleep(delay);
            let dispatcher = app.clone();
            let _ = dispatcher.run_on_main_thread(move || {
                let next = HOST.with(|cell| {
                    let mut slot = cell.borrow_mut();
                    let entry = slot.as_mut()?.tabs.get_mut(&tab)?;
                    let due = entry.fit_due?;
                    let delay = due.saturating_duration_since(Instant::now());
                    if !delay.is_zero() {
                        return Some(Err(delay));
                    }
                    entry.fit_due = None;
                    if !entry.bounds.visible || entry.preferred_zoom != 1.0 { return None; }
                    Some(Ok((entry.core.clone(), entry.controller.clone(), entry.fit_revision)))
                });
                match next {
                    Some(Ok((core, controller, revision))) => fit_viewport(&tab, core, controller, revision),
                    Some(Err(delay)) => wait_for_viewport_fit(app, tab, delay),
                    None => {}
                }
            });
        });
    }

    fn fit_viewport(tab: &str, core: ICoreWebView2, controller: ICoreWebView2Controller, revision: u64) {
        // Recheck at 100% so a wider container can restore the normal page zoom.
        let _ = unsafe { controller.SetZoomFactor(1.0) };
        let id = tab.to_owned();
        let handler = ExecuteScriptCompletedHandler::create(Box::new(move |result, value| {
            if result.is_ok() {
                if let Ok([viewport, content]) = serde_json::from_str::<[f64; 2]>(&value) {
                    let zoom = viewport_fit_zoom(1.0, viewport, content);
                    HOST.with(|cell| {
                        let slot = cell.borrow();
                        if let Some(entry) = slot.as_ref().and_then(|host| host.tabs.get(&id)) {
                            if entry.fit_revision == revision && entry.bounds.visible && zoom < 1.0 {
                                let _ = unsafe { entry.controller.SetZoomFactor(zoom) };
                            }
                        }
                    });
                }
            }
            Ok(())
        }));
        let _ = unsafe { core.ExecuteScript(&HSTRING::from(VIEWPORT_WIDTHS), &handler) };
    }

    pub fn has_tab(tab: &str) -> bool {
        HOST.with(|cell| cell.borrow().as_ref().is_some_and(|h| h.tabs.contains_key(tab)))
    }

    pub async fn create_tab(
        app: &AppHandle,
        hwnd_raw: isize,
        tab: &str,
        url: &url::Url,
        bounds: Bounds,
        env_profile: ProfileEnvironment,
    ) -> Result<(), BrowserError> {
        let (tx, rx) = std::sync::mpsc::sync_channel::<Result<(), BrowserError>>(1);
        let app_clone = app.clone();
        let tab_id = tab.to_string();
        let url_str = url.to_string();

        app.run_on_main_thread(move || {
            let hwnd = HWND(hwnd_raw as *mut std::ffi::c_void);
            if let Err(e) = ensure_host(hwnd) {
                let _ = tx.send(Err(e));
                return;
            }
            let already = has_tab(&tab_id);
            if already {
                let _ = tx.send(Err(BrowserError::new("tab_exists", "这个浏览器标签已经打开", false)));
                return;
            }
            let mut tx_opt = Some(tx);
            with_env(env_profile.data_directory, move |env_res| {
                let env = match env_res {
                    Ok(e) => e,
                    Err(err) => {
                        if let Some(tx) = tx_opt.take() {
                            let _ = tx.send(Err(err));
                        }
                        return;
                    }
                };
                let Ok(env3) = env.cast::<ICoreWebView2Environment3>() else {
                    if let Some(tx) = tx_opt.take() {
                        let _ = tx.send(Err(BrowserError::unsupported("当前 WebView2 运行时不支持 CompositionController")));
                    }
                    return;
                };
                let app_in = app_clone.clone();
                let tab_in = tab_id.clone();
                let url_in = url_str.clone();
                let comp_handler = CreateCoreWebView2CompositionControllerCompletedHandler::create(Box::new(
                    move |res, comp| {
                        let Some(tx) = tx_opt.take() else { return Ok(()) };
                        if let Err(e) = res {
                            let _ = tx.send(Err(BrowserError::internal(format!("创建合成浏览器失败：{e}"))));
                            return Ok(());
                        }
                        let Some(comp) = comp else {
                            let _ = tx.send(Err(BrowserError::internal("CompositionController 为空")));
                            return Ok(());
                        };
                        let controller: ICoreWebView2Controller = match comp.cast() {
                            Ok(c) => c,
                            Err(e) => {
                                let _ = tx.send(Err(BrowserError::internal(format!("获取 Controller 失败：{e}"))));
                                return Ok(());
                            }
                        };
                        // user:“传递容器尺寸”+(前端已经把 CSS 坐标换成物理像素，内置网页直接按物理像素接收)。
                        if let Ok(controller3) = controller.cast::<ICoreWebView2Controller3>() {
                            let _ = unsafe { controller3.SetBoundsMode(COREWEBVIEW2_BOUNDS_MODE_USE_RAW_PIXELS) };
                        }
                        let core = match unsafe { controller.CoreWebView2() } {
                            Ok(c) => c,
                            Err(e) => {
                                let _ = tx.send(Err(BrowserError::internal(format!("获取 CoreWebView2 失败：{e}"))));
                                return Ok(());
                            }
                        };

                        // 1) 顶层导航策略
                        let nav_app = app_in.clone();
                        let nav_tab = tab_in.clone();
                        let nav_handler = NavigationStartingEventHandler::create(Box::new(move |_, args| {
                            let Some(args) = args else { return Ok(()) };
                            let mut uri = PWSTR::null();
                            if unsafe { args.Uri(&mut uri) }.is_ok() {
                                let raw = take_pwstr(uri);
                                if let Ok(parsed) = url::Url::parse(&raw) {
                                    if !allowed_navigation(&parsed) {
                                        let _ = unsafe { args.SetCancel(true) };
                                        let _ = nav_app.emit_to(
                                            "main",
                                            crate::browser::EVENT_ERROR,
                                            crate::browser::ErrorPayload {
                                                tab: nav_tab.clone(),
                                                code: "blocked_scheme".to_string(),
                                                message: format!("已阻止网页跳转到 {}: 链接", parsed.scheme()),
                                                retriable: false,
                                                host: Some(parsed.scheme().to_string()),
                                            },
                                        );
                                        return Ok(());
                                    }
                                }
                            }
                            HOST.with(|cell| {
                                if let Ok(mut slot) = cell.try_borrow_mut() {
                                    if let Some(entry) = slot.as_mut().and_then(|host| host.tabs.get_mut(&nav_tab)) {
                                        entry.fit_revision = entry.fit_revision.wrapping_add(1);
                                    }
                                }
                            });
                            let load_tab = nav_tab.clone();
                            if crate::browser::with_runtime(|rt| {
                                if let Ok(state) = rt.tabs.get_mut(&load_tab) {
                                    state.loading = true;
                                    state.crashed = false;
                                }
                                Ok(())
                            })
                            .is_ok()
                            {
                                crate::browser::emit_state(&nav_app, &nav_tab);
                            }
                            Ok(())
                        }));
                        let mut tok = 0i64;
                        let _ = unsafe { core.add_NavigationStarting(&nav_handler, &mut tok) };

                        // 2) 加载完成 & URL 变更
                        let done_app = app_in.clone();
                        let done_tab = tab_in.clone();
                        let done_handler = NavigationCompletedEventHandler::create(Box::new(move |sender, _| {
                            let current = sender
                                .and_then(|s| {
                                    let mut uri = PWSTR::null();
                                    unsafe { s.Source(&mut uri) }.ok().map(|()| take_pwstr(uri))
                                })
                                .unwrap_or_default();
                            if crate::browser::with_runtime(|rt| {
                                if let Ok(state) = rt.tabs.get_mut(&done_tab) {
                                    state.loading = false;
                                    if !current.is_empty() {
                                        state.url = current.clone();
                                    }
                                    state.crashed = false;
                                }
                                Ok(())
                            })
                            .is_ok()
                            {
                                crate::browser::emit_state(&done_app, &done_tab);
                            }
                            request_viewport_fit(&done_app, &done_tab);
                            Ok(())
                        }));
                        let _ = unsafe { core.add_NavigationCompleted(&done_handler, &mut tok) };

                        let src_app = app_in.clone();
                        let src_tab = tab_in.clone();
                        let src_handler = SourceChangedEventHandler::create(Box::new(move |sender, _| {
                            let current = sender
                                .and_then(|s| {
                                    let mut uri = PWSTR::null();
                                    unsafe { s.Source(&mut uri) }.ok().map(|()| take_pwstr(uri))
                                })
                                .unwrap_or_default();
                            if !current.is_empty()
                                && crate::browser::with_runtime(|rt| {
                                    if let Ok(state) = rt.tabs.get_mut(&src_tab) {
                                        state.url = current.clone();
                                    }
                                    Ok(())
                                })
                                .is_ok()
                            {
                                crate::browser::emit_state(&src_app, &src_tab);
                            }
                            Ok(())
                        }));
                        let _ = unsafe { core.add_SourceChanged(&src_handler, &mut tok) };

                        // 3) target=_blank 弹窗拦截
                        let pop_app = app_in.clone();
                        let pop_tab = tab_in.clone();
                        let pop_handler = NewWindowRequestedEventHandler::create(Box::new(move |_, args| {
                            let Some(args) = args else { return Ok(()) };
                            let mut uri = PWSTR::null();
                            if unsafe { args.Uri(&mut uri) }.is_ok() {
                                let url = take_pwstr(uri);
                                let _ = unsafe { args.SetHandled(true) };
                                crate::browser::emit_pending_tab(
                                    &pop_app,
                                    crate::browser::PendingTabPayload {
                                        tab: pop_tab.clone(),
                                        url,
                                        opener: Some(pop_tab.clone()),
                                        user_initiated: false,
                                    },
                                );
                            }
                            Ok(())
                        }));
                        let _ = unsafe { core.add_NewWindowRequested(&pop_handler, &mut tok) };

                        // 4) 下载接管
                        if let Ok(core4) = core.cast::<ICoreWebView2_4>() {
                            let dl_app = app_in.clone();
                            let dl_tab = tab_in.clone();
                            let dl_handler = DownloadStartingEventHandler::create(Box::new(move |_, args| {
                                let Some(args) = args else { return Ok(()) };
                                let Some(dir) = crate::browser::download_dir(&dl_app) else {
                                    let _ = unsafe { args.SetCancel(true) };
                                    return Ok(());
                                };
                                let Ok(op) = (unsafe { args.DownloadOperation() }) else { return Ok(()) };
                                let mut uri_ptr = PWSTR::null();
                                let dl_url = if unsafe { op.Uri(&mut uri_ptr) }.is_ok() {
                                    take_pwstr(uri_ptr)
                                } else {
                                    String::new()
                                };
                                let suggested = crate::browser::download::suggested_filename(&dl_url);
                                let target = crate::browser::download::download_target(&dir, &suggested, |p| p.exists());
                                let _ = unsafe { args.SetResultFilePath(&HSTRING::from(target.to_string_lossy().as_ref())) };
                                let _ = unsafe { args.SetHandled(true) };
                                let now = crate::browser::security::iso_from_unix(
                                    std::time::SystemTime::now()
                                        .duration_since(std::time::UNIX_EPOCH)
                                        .map(|e| e.as_secs())
                                        .unwrap_or(0),
                                );
                                crate::browser::record_download_started(&dl_app, &dl_tab, &dl_url, &target, &now);
                                let fin_app = dl_app.clone();
                                let fin_tab = dl_tab.clone();
                                let fin_url = dl_url.clone();
                                let fin_target = target.clone();
                                let state_handler = StateChangedEventHandler::create(Box::new(move |sender, _| {
                                    let Some(op) = sender else { return Ok(()) };
                                    let mut st = webview2_com::Microsoft::Web::WebView2::Win32::COREWEBVIEW2_DOWNLOAD_STATE::default();
                                    if unsafe { op.State(&mut st) }.is_ok() {
                                        if st == COREWEBVIEW2_DOWNLOAD_STATE_COMPLETED {
                                            crate::browser::record_download_finished(&fin_app, &fin_tab, &fin_url, Some(&fin_target), true);
                                        } else if st == COREWEBVIEW2_DOWNLOAD_STATE_INTERRUPTED {
                                            crate::browser::record_download_finished(&fin_app, &fin_tab, &fin_url, Some(&fin_target), false);
                                        }
                                    }
                                    Ok(())
                                }));
                                let mut dt = 0i64;
                                let _ = unsafe { op.add_StateChanged(&state_handler, &mut dt) };
                                Ok(())
                            }));
                            let _ = unsafe { core4.add_DownloadStarting(&dl_handler, &mut tok) };
                        }

                        // 5) 注入桥脚本 + 挂载 platform_win 能力与 WebMessage
                        let _ = unsafe {
                            core.AddScriptToExecuteOnDocumentCreated(
                                &HSTRING::from(crate::browser::bridge::BRIDGE_SCRIPT),
                                None,
                            )
                        };
                        crate::browser::platform_win::attach_core(&app_in, &tab_in, &core, Some(&controller));
                        if let Err(err) = crate::browser::platform_win::attach_bridge_core(&app_in, &tab_in, &core) {
                            let _ = app_in.emit_to(
                                "main",
                                crate::browser::EVENT_ERROR,
                                crate::browser::ErrorPayload {
                                    tab: tab_in.clone(),
                                    code: err.code,
                                    message: err.message,
                                    retriable: false,
                                    host: None,
                                },
                            );
                        }

                        // 6) 创建视觉节点并加入 DirectComposition 树
                        let bind_res = HOST.with(|cell| {
                            let mut borrow = cell.borrow_mut();
                            let host = borrow.as_mut().ok_or_else(|| BrowserError::internal("合成宿主未初始化"))?;
                            unsafe {
                                let visual = host
                                    .dcomp
                                    .CreateVisual()
                                    .map_err(|e| BrowserError::internal(format!("创建网页视觉节点失败：{e}")))?;
                                comp.SetRootVisualTarget(&visual)
                                    .map_err(|e| BrowserError::internal(format!("绑定网页视觉节点失败：{e}")))?;
                                add_visual_at_bottom(&host.root_visual, &visual)
                                    .map_err(|e| BrowserError::internal(format!("挂载网页视觉节点失败：{e}")))?;
                                let mut tab_entry = ComposedTab {
                                    controller: controller.clone(),
                                    comp,
                                    core: core.clone(),
                                    visual,
                                    bounds,
                                    bounds_applied: false,
                                    stack_index: 0,
                                    is_float: false,
                                    preferred_zoom: 1.0,
                                    fit_revision: 0,
                                    fit_due: None,
                                };
                                apply_bounds(host, &mut tab_entry, bounds);
                                let _ = core.Navigate(&HSTRING::from(url_in.as_str()));
                                host.tabs.insert(tab_in.clone(), tab_entry);
                                Ok::<_, BrowserError>(())
                            }
                        });
                        let _ = tx.send(bind_res);
                        Ok(())
                    },
                ));

                if env_profile.incognito {
                    if let Ok(env10) = env.cast::<ICoreWebView2Environment10>() {
                        if let Ok(opts) = unsafe { env10.CreateCoreWebView2ControllerOptions() } {
                            let _ = unsafe { opts.SetIsInPrivateModeEnabled(true) };
                            let _ = unsafe {
                                env10.CreateCoreWebView2CompositionControllerWithOptions(
                                    hwnd,
                                    &opts,
                                    &comp_handler,
                                )
                            };
                            return;
                        }
                    }
                }
                let _ = unsafe {
                    env3.CreateCoreWebView2CompositionController(hwnd, &comp_handler)
                };
            });
        })
        .map_err(|e| BrowserError::internal(format!("投递主线程创建失败：{e}")))?;

        tauri::async_runtime::spawn_blocking(move || {
            rx.recv_timeout(std::time::Duration::from_secs(15))
                .map_err(|_| BrowserError::internal("创建合成浏览器超时或被取消"))
                .and_then(|r| r)
        })
        .await
        .map_err(|_| BrowserError::internal("创建合成浏览器任务中断"))?
    }

    /// user:“浮层网页层级不对，被分屏遮挡了”+
    /// (DirectComposition 的 NULL 参考节点语义很容易写反：insertAbove=false 才是放到所有兄弟之上，
    ///  true 是放到最下面。把方向封成两个名字，调用处不再直接写布尔值)。
    fn add_visual_on_top(root: &IDCompositionVisual, visual: &IDCompositionVisual) -> windows::core::Result<()> {
        unsafe { root.AddVisual(visual, false, None) }
    }

    fn add_visual_at_bottom(root: &IDCompositionVisual, visual: &IDCompositionVisual) -> windows::core::Result<()> {
        unsafe { root.AddVisual(visual, true, None) }
    }

    /// user:“浮层网页层级不对，被分屏遮挡了”+
    /// (层级不是「把某个节点移到某个兄弟旁边」，而是一份总序：分屏永远在底、浮窗按 floatOrder 依次在上。
    ///  顺序真的变化时按总序重建一次兄弟链；任何一步失败都不许把网页沉到最底层 ——
    ///  旧实现失败时落到最底，缓存的 stack_index 又让后续更新直接返回，于是一旦漂移就永远被分屏盖住)。
    fn restack(host: &mut CompositorHost, tab_id: &str, entry: &mut ComposedTab, is_float: bool, stack_index: u32) {
        entry.is_float = is_float;
        entry.stack_index = stack_index;
        let mut items: Vec<(String, bool, u32)> = host
            .tabs
            .iter()
            .map(|(id, tab)| (id.clone(), tab.is_float, tab.stack_index))
            .collect();
        items.push((tab_id.to_string(), is_float, stack_index));
        let ordered = stack_order(
            items
                .iter()
                .map(|(id, is_float, index)| (id.as_str(), *is_float, *index))
                .collect(),
        );
        let mut visuals: HashMap<String, IDCompositionVisual> = host
            .tabs
            .iter()
            .map(|(id, tab)| (id.clone(), tab.visual.clone()))
            .collect();
        visuals.insert(tab_id.to_string(), entry.visual.clone());
        // 先全部摘下，再按总序从低到高逐个放到最上面：最后一个就是最顶层。
        for (id, _, _) in &ordered {
            if let Some(visual) = visuals.get(*id) {
                let _ = unsafe { host.root_visual.RemoveVisual(visual) };
            }
        }
        let mut failed = Vec::new();
        for (id, _, _) in &ordered {
            if let Some(visual) = visuals.get(*id) {
                // 按总序从低到高依次放到最上面：后加的盖住先加的，最后一个就是最顶层。
                let added = add_visual_on_top(&host.root_visual, visual);
                if added.is_err() && add_visual_on_top(&host.root_visual, visual).is_err() {
                    failed.push(id.to_string());
                }
            }
        }
        let _ = unsafe { host.dcomp.Commit() };
        let signature = ordered
            .iter()
            .map(|(id, is_float, index)| format!("{id}:{}:{index}", u8::from(*is_float)))
            .collect::<Vec<_>>()
            .join(",");
        if signature != host.last_order || !failed.is_empty() {
            eprintln!(
                "[browser-stack] focus={tab_id} float={is_float} index={stack_index} order=[{signature}] failed={failed:?}"
            );
            host.last_order = signature;
        }
    }

    pub fn set_bounds(app: &AppHandle, tab: &str, bounds: Bounds) -> Result<(), BrowserError> {
        set_stacked_bounds(app, tab, false, bounds, None)
    }

    pub fn set_stacked_bounds(
        app: &AppHandle,
        tab: &str,
        is_float: bool,
        bounds: Bounds,
        stack_index: Option<u32>,
    ) -> Result<(), BrowserError> {
        let tab_id = tab.to_string();
        let fit_app = app.clone();
        app.run_on_main_thread(move || {
            let width_changed = HOST.with(|cell| {
                let mut borrow = cell.borrow_mut();
                let Some(host) = borrow.as_mut() else { return false };
                let Some(mut entry) = host.tabs.remove(&tab_id) else { return false };
                let changed = entry.bounds.width != bounds.width || entry.bounds.visible != bounds.visible;
                if let Some(index) = stack_index {
                    // user:“浮层网页层级不对，被分屏遮挡了”+(只在类别/顺序真的变化时按总序重建，
                    //  不在每帧 bounds 上重排：拖拽跟手性不受影响)。
                    if entry.is_float != is_float || entry.stack_index != index {
                        restack(host, &tab_id, &mut entry, is_float, index);
                    }
                }
                apply_bounds(host, &mut entry, bounds);
                host.tabs.insert(tab_id.clone(), entry);
                changed
            });
            if width_changed {
                request_viewport_fit(&fit_app, &tab_id);
            }
        })
        .map_err(|e| BrowserError::internal(format!("设置矩形失败：{e}")))
    }

    pub fn send_mouse(
        app: &AppHandle,
        tab: &str,
        kind: i32,
        virtual_keys: i32,
        wheel_delta: u32,
        x: i32,
        y: i32,
    ) -> Result<(), BrowserError> {
        let tab_id = tab.to_string();
        app.run_on_main_thread(move || {
            HOST.with(|cell| {
                let borrow = cell.borrow();
                let Some(host) = borrow.as_ref() else { return };
                let Some(entry) = host.tabs.get(&tab_id) else { return };
                unsafe {
                    if kind == 0x0201 || kind == 0x0204 || kind == 0x0207 {
                        let _ = entry
                            .controller
                            .MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
                    }
                    let _ = entry.comp.SendMouseInput(
                        COREWEBVIEW2_MOUSE_EVENT_KIND(kind),
                        COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS(virtual_keys),
                        wheel_delta,
                        POINT { x, y },
                    );
                }
            });
        })
        .map_err(|e| BrowserError::internal(format!("路由鼠标事件失败：{e}")))
    }

    pub fn close_tab(app: &AppHandle, tab: &str) -> Result<(), BrowserError> {
        let tab_id = tab.to_string();
        app.run_on_main_thread(move || {
            HOST.with(|cell| {
                let mut borrow = cell.borrow_mut();
                let Some(host) = borrow.as_mut() else { return };
                if let Some(entry) = host.tabs.remove(&tab_id) {
                    unsafe {
                        let _ = host.root_visual.RemoveVisual(&entry.visual);
                        let _ = entry.controller.Close();
                        let _ = host.dcomp.Commit();
                    }
                }
            });
        })
        .map_err(|e| BrowserError::internal(format!("关闭标签失败：{e}")))
    }

    pub fn with_core<R: Send + 'static>(
        app: &AppHandle,
        tab: &str,
        f: impl FnOnce(&ICoreWebView2, &ICoreWebView2Controller) -> R + Send + 'static,
    ) -> Result<R, BrowserError> {
        let (tx, rx) = std::sync::mpsc::channel::<Result<R, BrowserError>>();
        let tab_id = tab.to_string();
        app.run_on_main_thread(move || {
            let res = HOST.with(|cell| {
                let borrow = cell.borrow();
                let host = borrow.as_ref().ok_or_else(BrowserError::tab_not_found)?;
                let entry = host.tabs.get(&tab_id).ok_or_else(BrowserError::tab_not_found)?;
                Ok(f(&entry.core, &entry.controller))
            });
            let _ = tx.send(res);
        })
        .map_err(|e| BrowserError::internal(format!("主线程调度失败：{e}")))?;
        rx.recv_timeout(std::time::Duration::from_secs(3))
            .map_err(|_| BrowserError::internal("主线程响应超时或中断"))?
    }

    pub fn with_core_async(
        app: &AppHandle,
        tab: &str,
        f: impl FnOnce(&ICoreWebView2, &ICoreWebView2Controller) + Send + 'static,
    ) -> Result<(), BrowserError> {
        let tab_id = tab.to_string();
        app.run_on_main_thread(move || {
            HOST.with(|cell| {
                let borrow = cell.borrow();
                let Some(host) = borrow.as_ref() else { return };
                let Some(entry) = host.tabs.get(&tab_id) else { return };
                f(&entry.core, &entry.controller);
            });
        })
        .map_err(|e| BrowserError::internal(format!("主线程投递失败：{e}")))
    }

    pub fn set_zoom(app: &AppHandle, tab: &str, zoom: f64) -> Result<(), BrowserError> {
        let tab = tab.to_owned();
        let fit_app = app.clone();
        app.run_on_main_thread(move || {
            let controller = HOST.with(|cell| {
                let mut slot = cell.borrow_mut();
                let entry = slot.as_mut()?.tabs.get_mut(&tab)?;
                entry.preferred_zoom = zoom;
                Some(entry.controller.clone())
            });
            if let Some(controller) = controller {
                let _ = unsafe { controller.SetZoomFactor(zoom) };
                request_viewport_fit(&fit_app, &tab);
            }
        })
        .map_err(|e| BrowserError::internal(format!("设置缩放失败：{e}")))
    }

    pub fn navigate(app: &AppHandle, tab: &str, url: &str) -> Result<(), BrowserError> {
        let url_s = url.to_string();
        with_core_async(app, tab, move |core, _| {
            let _ = unsafe { core.Navigate(&HSTRING::from(url_s.as_str())) };
        })
    }

    pub fn eval(app: &AppHandle, tab: &str, script: &str) -> Result<(), BrowserError> {
        let script_s = script.to_string();
        with_core_async(app, tab, move |core, _| {
            let _ = unsafe { core.ExecuteScript(&HSTRING::from(script_s.as_str()), None) };
        })
    }

    pub fn current_url(app: &AppHandle, tab: &str) -> Result<String, BrowserError> {
        with_core(app, tab, |core, _| {
            let mut uri = PWSTR::null();
            if unsafe { core.Source(&mut uri) }.is_ok() {
                take_pwstr(uri)
            } else {
                String::new()
            }
        })
    }

    pub fn capture_viewport(app: &AppHandle, tab: &str, timeout: std::time::Duration) -> Result<Vec<u8>, BrowserError> {
        let (tx, rx) = std::sync::mpsc::channel::<Result<Vec<u8>, String>>();
        let tab_id = tab.to_string();
        app.run_on_main_thread(move || {
            HOST.with(|cell| {
                let borrow = cell.borrow();
                let Some(host) = borrow.as_ref() else {
                    let _ = tx.send(Err("拿不到合成宿主".to_string()));
                    return;
                };
                let Some(entry) = host.tabs.get(&tab_id) else {
                    let _ = tx.send(Err("标签不存在".to_string()));
                    return;
                };
                crate::browser::platform_win::capture_viewport_with_core(&entry.core, tx);
            });
        })
        .map_err(|e| BrowserError::internal(format!("截图调度失败：{e}")))?;
        match rx.recv_timeout(timeout) {
            Ok(Ok(bytes)) => Ok(bytes),
            Ok(Err(msg)) => Err(BrowserError::new("unsupported", msg, true)),
            Err(_) => Err(BrowserError::new("timeout", "截图超时", true)),
        }
    }
}

#[cfg(windows)]
pub use win::*;

#[cfg(all(test, windows))]
mod tests {
    use super::{bounds_changes, win::format_environment_args, Bounds};

    // user:“直接优化”+(隐藏网页恢复 WebView2 的后台节流，保留调试和代理参数)。
    #[test]
    fn frame_pacing_keeps_debug_and_proxy_args_but_allows_background_throttling() {
        let base = crate::pet::browser_args(Some("--remote-debugging-port=0"));
        let out = format_environment_args(&base, Some("127.0.0.1:7897"), Some("localhost"));
        assert!(out.contains("--remote-debugging-port=0"));
        assert!(out.contains("--proxy-server=127.0.0.1:7897 --proxy-bypass-list=localhost"));
        for flag in crate::pet::BASE_BROWSER_ARGS.split_whitespace() {
            assert!(!out.split_whitespace().any(|arg| arg == flag), "{flag}");
        }
    }

    // user:“可使用Rust重写相关代码”+(在 Rust 按实际变化更新网页位置、尺寸和可见性)。
    #[test]
    fn frame_pacing_skips_unchanged_controller_properties() {
        let original = Bounds { x: 2.0, y: 3.0, width: 400.0, height: 240.0, visible: true };
        assert_eq!(bounds_changes(None, original), (true, true, true));
        assert_eq!(bounds_changes(Some(original), original), (false, false, false));
        let moved = Bounds { x: 8.0, width: 400.2, ..original };
        assert_eq!(bounds_changes(Some(original), moved), (true, false, false));
        let resized = Bounds { height: 241.0, ..moved };
        assert_eq!(bounds_changes(Some(moved), resized), (false, true, false));
        let hidden = Bounds { visible: false, ..resized };
        assert_eq!(bounds_changes(Some(resized), hidden), (false, false, true));
        assert_eq!(bounds_changes(Some(hidden), resized), (false, false, true));
    }

    #[test]
    fn formats_proxy_and_bypass_with_base_args() {
        let out = format_environment_args(
            "--disable-backgrounding-tabs",
            Some("127.0.0.1:7897"),
            Some("localhost;127.*"),
        );
        assert_eq!(
            out,
            "--disable-backgrounding-tabs --disable-features=msSmartScreenProtection --disable-quic --proxy-server=127.0.0.1:7897 --proxy-bypass-list=localhost;127.*"
        );
        assert_eq!(
            format_environment_args("--flag", None, None),
            "--flag --disable-features=msSmartScreenProtection --disable-quic"
        );
    }
}
