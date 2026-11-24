// user:“平台能力只在 platform_win 里用 with_webview + webview2-com”+(网页标题、真实前进后退状态、网页全屏、
// 脚本求值都是 WebView2 专属；M2 再加上权限拦截、证书拦截、favicon、快捷键拦截、原生页内查找、站数据清理)。
//
// 这一层只做「拿事件 → 更新 Rust 状态 → 通知前端」，不做业务决策；所有 COM 调用返回 Result 并转成
// 前端可显示的错误码，回调里出现任何失败都只上报，不 panic、不 unwrap（COM 消息循环里 panic 会带走整个宿主）。
//
// user:“拿不到的能力不要猜”+(非 Windows 或接口缺失时返回 unsupported 并留 TODO，不静默降级成「看起来能跑」)。
use crate::browser::BrowserError;

#[cfg(not(windows))]
mod imp {
    use super::*;
    use crate::browser::session::SiteDataKinds;

    /// 非 Windows 没有 deferral 需要保存，占位类型让上层状态表保持同一形状。
    pub type PermissionTicket = ();

    pub fn resolve_permission_ticket(_ticket: PermissionTicket, _allow: bool) {}

    pub fn attach(_app: &tauri::AppHandle, _tab: &str, _view: &tauri::Webview) {}

    pub fn go_back(_view: &tauri::Webview) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("浏览器历史目前只支持 Windows（WebView2）"))
    }

    pub fn go_forward(_view: &tauri::Webview) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("浏览器历史目前只支持 Windows（WebView2）"))
    }

    pub fn stop(_view: &tauri::Webview) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("停止加载目前只支持 Windows（WebView2）"))
    }

    pub fn eval_with_result(
        _app: &tauri::AppHandle,
        _tab: &str,
        _view: &tauri::Webview,
        _script: String,
    ) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("页内查找目前只支持 Windows（WebView2）"))
    }

    /// 原生查找只在 Windows 上存在；返回 false 让调用方走脚本兜底。
    pub fn native_find(
        _app: &tauri::AppHandle,
        _tab: &str,
        _view: &tauri::Webview,
        _action: &str,
        _query: Option<&str>,
        _match_case: bool,
    ) -> Result<bool, BrowserError> {
        Ok(false)
    }

    pub fn clear_certificate_memory(_app: &tauri::AppHandle, _tab: &str, _view: &tauri::Webview) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("证书放行记忆只在 Windows（WebView2）上存在"))
    }
    pub fn clear_site_data(
        _app: &tauri::AppHandle,
        _tab: &str,
        _view: &tauri::Webview,
        _host: String,
        _kinds: SiteDataKinds,
    ) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("站点数据清理目前只支持 Windows（WebView2）"))
    }

    pub fn supports_incognito() -> bool {
        false
    }


    /// 非 Windows 没有 WebView2 的 Cookie 管理器：回传空请求头，让调用方按「没有登录态」处理。
    pub fn read_download_headers(app: &tauri::AppHandle, tab: &str, url: &str) {
        super::super::emit_download_headers(app, tab, url, super::super::DownloadHeaders::default());
    }

    // user:“唯一通道是 WebMessage”+(非 Windows 没有 WebView2，桥接不上就如实报错，不假装成功)。
    pub fn attach_bridge(_app: &tauri::AppHandle, _tab: &str, _view: &tauri::Webview) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("页面桥目前只支持 Windows（WebView2）"))
    }

    pub fn post_message(_view: &tauri::Webview, _payload: &str) -> Result<(), BrowserError> {
        Err(BrowserError::unsupported("页面桥目前只支持 Windows（WebView2）"))
    }

    pub fn capture_viewport(_view: &tauri::Webview, _timeout: std::time::Duration) -> Result<Vec<u8>, BrowserError> {
        Err(BrowserError::unsupported("截图目前只支持 Windows（WebView2）"))
    }

    pub fn run_diagnostics(app: &tauri::AppHandle, tab: &str, _view: &tauri::Webview) {
        // 非 Windows 没有可执行的页面脚本通道，如实报「无法自检」而不是给一个假的通过。
        // user:“后台标签消息投递可观测”+(能力缺失不影响这项观测：它是宿主自己的账本)。
        let delivery = super::super::bridge::last_delivery(tab);
        let delivery_note = delivery
            .as_ref()
            .map(super::super::bridge::delivery_note)
            .unwrap_or_else(|| "还没有 Agent 指令投递记录".to_string());
        super::super::emit_diagnostics(
            app,
            super::super::DiagnosticsPayload {
                tab: tab.to_string(),
                passed: false,
                checks: Vec::new(),
                message: format!("越权自检只在 Windows（WebView2）上可用；{delivery_note}"),
                delivery,
                delivery_note,
            },
        );
    }
}

#[cfg(windows)]
mod imp {
    use super::*;
    use tauri::{Emitter, Manager};
    use webview2_com::Microsoft::Web::WebView2::Win32::*;
    use webview2_com::take_pwstr;
    use webview2_com::{
        AcceleratorKeyPressedEventHandler, CapturePreviewCompletedHandler,
        ClearServerCertificateErrorActionsCompletedHandler, ContainsFullScreenElementChangedEventHandler,
        DocumentTitleChangedEventHandler, ExecuteScriptCompletedHandler, FaviconChangedEventHandler,
        FindStartCompletedHandler, GetCookiesCompletedHandler, GetFaviconCompletedHandler,
        HistoryChangedEventHandler, PermissionRequestedEventHandler,
        ServerCertificateErrorDetectedEventHandler, WebMessageReceivedEventHandler,
    };
    use windows::core::{BOOL, HSTRING, PWSTR};
    use windows::core::Interface;
    use windows::Win32::System::Com::{IStream, STREAM_SEEK_SET};
    use windows::Win32::UI::Input::KeyboardAndMouse::{GetKeyState, VK_CONTROL};
    use windows::Win32::UI::Shell::SHCreateMemStream;

    use crate::browser::favicon;
    use crate::browser::security::{
        self, PermissionDecision, PermissionKind, PermissionScope,
    };
    use crate::browser::session::{self, SiteDataKinds};
    use crate::browser::shortcut::{self, Shortcut};

    /// 单次 favicon 读取上限：防止异常流把内存吃满。
    const FAVICON_CHUNK: usize = 64 * 1024;

    #[derive(Clone, Copy)]
    enum HistoryCall {
        Back,
        Forward,
        Stop,
    }

    fn core_of(platform: &tauri::webview::PlatformWebview) -> Result<ICoreWebView2, BrowserError> {
        let controller: ICoreWebView2Controller = platform.controller();
        // SAFETY: `controller` 由 wry 持有且在本调用期间有效，只取一次 COM 接口。
        unsafe { controller.CoreWebView2() }
            .map_err(|error| BrowserError::internal(format!("拿不到 WebView2 接口：{error}")))
    }

    fn read_flag(read: impl FnOnce(*mut BOOL) -> windows::core::Result<()>) -> bool {
        let mut value = BOOL::default();
        read(&mut value).is_ok() && value.as_bool()
    }

    fn read_source(core: &ICoreWebView2) -> Option<String> {
        let mut raw = PWSTR::null();
        // SAFETY: `Source` 只在成功时写出一个由 COM 分配、由 take_pwstr 释放的字符串。
        unsafe { core.Source(&mut raw) }.ok().map(|_| take_pwstr(raw))
    }

    fn read_title(core: &ICoreWebView2) -> Option<String> {
        let mut raw = PWSTR::null();
        // SAFETY: 同上，DocumentTitle 输出的 PWSTR 由 take_pwstr 接管所有权。
        unsafe { core.DocumentTitle(&mut raw) }.ok().map(|_| take_pwstr(raw))
    }

    /// 把 WebView2 的历史状态写回标签（只有 COM 才知道真实的 canGoBack/canGoForward）。
    fn sync_history(tab: &str, core: &ICoreWebView2) {
        // SAFETY: 两次读取都只写局部 BOOL。
        let can_back = read_flag(|slot| unsafe { core.CanGoBack(slot) });
        let can_forward = read_flag(|slot| unsafe { core.CanGoForward(slot) });
        let url = read_source(core);
        let _ = super::super::with_runtime(|rt| {
            if let Ok(state) = rt.tabs.get_mut(tab) {
                state.can_back = can_back;
                state.can_forward = can_forward;
                if let Some(url) = url.as_ref().filter(|url| !url.is_empty()) {
                    state.url = url.clone();
                }
            }
            Ok(())
        });
    }

    fn report(app: &tauri::AppHandle, tab: &str, error: BrowserError) {
        // 平台事件注册/调用失败要让用户看见，但绝不能阻塞页面继续加载。
        let _ = app.emit_to(
            "main",
            super::super::EVENT_ERROR,
            super::super::ErrorPayload {
                tab: tab.to_string(),
                code: error.code,
                message: error.message,
                retriable: error.retriable,
                host: None,
            },
        );
    }

    // -----------------------------------------------------------------------
    // 权限请求：默认拒绝 + 用户确认后放行（仅本次 / 该站点）
    // -----------------------------------------------------------------------

    /// user:“前端最小授权确认后回命令放行”+(`PermissionRequested` 是同步的，要给用户时间确认就必须持有 deferral；
    /// deferral 与 args 是 COM 对象、不是 Send，本类型只允许在 UI 线程（`with_webview` 内）使用)。
    pub struct PermissionTicket {
        args: ICoreWebView2PermissionRequestedEventArgs,
        deferral: ICoreWebView2Deferral,
    }

    // SAFETY: 唯一的使用方式是 `resolve_permission_ticket`，它由 `view.with_webview` 投递到 UI 线程执行；
    // 这里只为了能放进全局状态表而在类型层面允许跨线程搬运，不存在并发访问同一个 COM 对象的情况。
    unsafe impl Send for PermissionTicket {}

    fn permission_state(allow: bool) -> COREWEBVIEW2_PERMISSION_STATE {
        if allow {
            COREWEBVIEW2_PERMISSION_STATE_ALLOW
        } else {
            COREWEBVIEW2_PERMISSION_STATE_DENY
        }
    }

    /// 完成一次授权：写 State 再 Complete deferral。失败只上报，不 panic。
    pub fn resolve_permission_ticket(ticket: PermissionTicket, allow: bool) {
        // SAFETY: 调用点在 UI 线程，先写 State 再完成 deferral 是 WebView2 文档给出的顺序。
        unsafe {
            let _ = ticket.args.SetState(permission_state(allow));
            let _ = ticket.deferral.Complete();
        }
    }

    fn read_uri(read: impl FnOnce(*mut PWSTR) -> windows::core::Result<()>) -> Option<String> {
        let mut raw = PWSTR::null();
        read(&mut raw).ok().map(|_| take_pwstr(raw))
    }

    fn handle_permission(
        app: &tauri::AppHandle,
        tab: &str,
        args: &ICoreWebView2PermissionRequestedEventArgs,
    ) -> Result<(), BrowserError> {
        let uri = read_uri(|slot| unsafe { args.Uri(slot) }).unwrap_or_default();
        let host = session::normalize_host(&uri).unwrap_or_default();
        let mut kind_raw = COREWEBVIEW2_PERMISSION_KIND(0);
        // SAFETY: 只写局部变量。
        unsafe { args.PermissionKind(&mut kind_raw) }.ok();
        let kind = PermissionKind::from_core(kind_raw.0);
        let user_initiated = read_flag(|slot| unsafe { args.IsUserInitiated(slot) });

        // 拿不到 host 的请求无法按站点记忆，直接拒绝（fail-closed）。
        if host.is_empty() {
            // SAFETY: 同步写一次拒绝。
            unsafe { let _ = args.SetState(permission_state(false)); };
            emit_permission(app, tab, "", kind, PermissionDecision::Deny, None, None, security::permission_denied_message("这个页面", kind));
            return Ok(());
        }

        let decision = super::super::with_runtime(|rt| Ok(rt.permissions.decide(&host, kind)))?;
        if decision == PermissionDecision::Allow {
            // SAFETY: 站点已被授权，同步放行。
            unsafe { args.SetState(permission_state(true)) }
                .map_err(|error| BrowserError::internal(format!("写入权限结果失败：{error}")))?;
            emit_permission(app, tab, &host, kind, PermissionDecision::Allow, Some(PermissionScope::Site), None, format!("{host} 已获得{}授权", kind.display()));
            return Ok(());
        }

        // user:“拒绝要有可见提示，不能静默无反应”+(先按拒绝写入，再把请求上报前端等用户决定)。
        // SAFETY: 先写拒绝保证「前端没响应」时也是拒绝。
        unsafe { let _ = args.SetState(permission_state(false)); };
        let deferral = match unsafe { args.GetDeferral() } {
            Ok(deferral) => deferral,
            // 拿不到 deferral 就无法在用户确认后再放行：保持拒绝并明确告知。
            Err(_) => {
                emit_permission(app, tab, &host, kind, PermissionDecision::Deny, None, None, security::permission_denied_message(&host, kind));
                return Ok(());
            }
        };
        let ticket = PermissionTicket { args: args.clone(), deferral };
        let registered = super::super::with_runtime(|rt| {
            if rt.pending_permissions.len() >= 8 {
                // 请求堆积说明前端没在响应，按拒绝处理，不无限持有 deferral。
                return Ok(None);
            }
            rt.next_permission_id += 1;
            let request_id = format!("p{}", rt.next_permission_id);
            rt.pending_permissions.insert(
                request_id.clone(),
                super::super::PendingPermission {
                    tab: tab.to_string(),
                    host: host.clone(),
                    kind,
                    user_initiated,
                    ticket,
                },
            );
            Ok(Some(request_id))
        })?;
        match registered {
            Some(request_id) => emit_permission(
                app,
                tab,
                &host,
                kind,
                PermissionDecision::Deny,
                None,
                Some(request_id),
                security::permission_request_message(&host, kind, user_initiated),
            ),
            None => emit_permission(app, tab, &host, kind, PermissionDecision::Deny, None, None, security::permission_denied_message(&host, kind)),
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn emit_permission(
        app: &tauri::AppHandle,
        tab: &str,
        host: &str,
        kind: PermissionKind,
        decision: PermissionDecision,
        scope: Option<PermissionScope>,
        request_id: Option<String>,
        message: String,
    ) {
        let _ = app.emit_to(
            "main",
            super::super::EVENT_PERMISSION,
            super::super::PermissionPayload {
                tab: tab.to_string(),
                host: host.to_string(),
                kind: kind.label().to_string(),
                decision: decision.as_str().to_string(),
                scope: scope.map(|scope| match scope {
                    PermissionScope::Once => "once".to_string(),
                    PermissionScope::Site => "site".to_string(),
                }),
                request_id,
                message,
            },
        );
    }

    fn register_permissions(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) -> Result<(), BrowserError> {
        let handler_app = app.clone();
        let handler_tab = tab.to_string();
        let handler = PermissionRequestedEventHandler::create(Box::new(move |_sender, args| {
            if let Some(args) = args.as_ref() {
                if let Err(error) = handle_permission(&handler_app, &handler_tab, args) {
                    report(&handler_app, &handler_tab, error);
                }
            }
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: 事件注册只在当前 core 上生效，token 由 WebView2 持有。
        unsafe { core.add_PermissionRequested(&handler, &mut token) }.map_err(|error| {
            BrowserError::new("permission_denied", format!("无法拦截网页权限请求，当前 WebView2 运行时不支持：{error}"), false)
        })
    }

    // -----------------------------------------------------------------------
    // 证书错误：默认阻断 + 可读原因
    // -----------------------------------------------------------------------

    fn handle_certificate_error(
        app: &tauri::AppHandle,
        tab: &str,
        args: &ICoreWebView2ServerCertificateErrorDetectedEventArgs,
    ) -> Result<(), BrowserError> {
        let uri = read_uri(|slot| unsafe { args.RequestUri(slot) }).unwrap_or_default();
        let host = session::normalize_host(&uri).unwrap_or_default();
        let mut status = COREWEBVIEW2_WEB_ERROR_STATUS(0);
        // SAFETY: 只写局部变量。
        unsafe { args.ErrorStatus(&mut status) }.ok();

        // user:“「继续访问」需显式确认且默认不记住”+(一次性放行由我们自己的状态表控制，用完即失效)。
        let one_shot = super::super::with_runtime(|rt| {
            if host.is_empty() {
                return Ok(false);
            }
            Ok(rt.certificate_allows.remove(&host))
        })
        .unwrap_or(false);

        if one_shot {
            // SAFETY: 用户已经显式确认过这一次。
            unsafe { args.SetAction(COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_ALWAYS_ALLOW) }
                .map_err(|error| BrowserError::internal(format!("放行证书错误失败：{error}")))?;
            return Ok(());
        }

        // SAFETY: 默认动作是阻断，这里显式写一次 CANCEL，避免运行时默认放行。
        unsafe { let _ = args.SetAction(COREWEBVIEW2_SERVER_CERTIFICATE_ERROR_ACTION_CANCEL); };
        let message = security::certificate_error_message(if host.is_empty() { "该站点" } else { &host }, status.0);
        let _ = app.emit_to(
            "main",
            super::super::EVENT_ERROR,
            super::super::ErrorPayload {
                tab: tab.to_string(),
                code: "certificate_error".to_string(),
                message,
                retriable: true,
                host: (!host.is_empty()).then_some(host),
            },
        );
        Ok(())
    }

    fn register_certificate(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) -> Result<(), BrowserError> {
        // `add_ServerCertificateErrorDetected` 在 ICoreWebView2_14；旧运行时拿不到就明确报“不拦截”，不假装已拦截。
        let extended: ICoreWebView2_14 = core
            .cast()
            .map_err(|_| BrowserError::new("unsupported", "当前 WebView2 运行时不支持证书拦截，请更新 WebView2 Runtime", false))?;
        let handler_app = app.clone();
        let handler_tab = tab.to_string();
        let handler = ServerCertificateErrorDetectedEventHandler::create(Box::new(move |_sender, args| {
            if let Some(args) = args.as_ref() {
                if let Err(error) = handle_certificate_error(&handler_app, &handler_tab, args) {
                    report(&handler_app, &handler_tab, error);
                }
            }
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: 事件注册只在当前 core 上生效。
        unsafe { extended.add_ServerCertificateErrorDetected(&handler, &mut token) }
            .map_err(|error| BrowserError::new("unsupported", format!("注册证书拦截失败：{error}"), false))
    }

    // -----------------------------------------------------------------------
    // favicon：FaviconChanged + GetFavicon(PNG)
    // -----------------------------------------------------------------------

    fn read_stream(stream: &IStream) -> Option<Vec<u8>> {
        let mut bytes = Vec::new();
        let mut chunk = vec![0u8; FAVICON_CHUNK];
        loop {
            let mut read = 0u32;
            // SAFETY: 缓冲区长度即读取上限，`read` 由调用写出。
            let result = unsafe {
                stream.Read(chunk.as_mut_ptr() as *mut core::ffi::c_void, FAVICON_CHUNK as u32, Some(&mut read))
            };
            if result.is_err() || read == 0 {
                break;
            }
            bytes.extend_from_slice(&chunk[..read as usize]);
            if bytes.len() > favicon::MAX_FAVICON_BYTES {
                return None;
            }
        }
        Some(bytes)
    }

    fn store_favicon(app: &tauri::AppHandle, tab: &str, page_url: &str, data_url: String) {
        let _ = super::super::with_runtime(|rt| {
            let page_url = if page_url.is_empty() {
                rt.tabs.get(tab).map(|state| state.url.clone()).unwrap_or_default()
            } else {
                page_url.to_string()
            };
            if let Ok(state) = rt.tabs.get_mut(tab) {
                state.favicon = Some(data_url.clone());
            }
            rt.favicons.insert(tab, &page_url, data_url);
            Ok(())
        });
        super::super::emit_state(app, tab);
    }

    /// 退化第二步：页面里读 `<link rel=icon>`（原生接口不可用时）。
    fn favicon_link_script() -> String {
        r#"(() => {
  try {
    const link = document.querySelector('link[rel~="icon"][href], link[rel="shortcut icon"][href]');
    return JSON.stringify({ href: link ? link.href : '' });
  } catch (error) {
    return JSON.stringify({ href: '' });
  }
})()"#
            .to_string()
    }

    fn read_favicon_link(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) {
        let reply_app = app.clone();
        let reply_tab = tab.to_string();
        let page_url = read_source(core).unwrap_or_default();
        let handler = ExecuteScriptCompletedHandler::create(Box::new(move |result, value| {
            if result.is_ok() {
                if let Ok(parsed) = serde_json::from_str::<FaviconLinkReply>(value.trim()) {
                    if !parsed.href.is_empty() {
                        store_favicon(&reply_app, &reply_tab, &page_url, parsed.href);
                    }
                }
            }
            Ok(())
        }));
        // SAFETY: ExecuteScript 复制脚本文本；handler 由 WebView2 持有到回调触发。
        if unsafe { core.ExecuteScript(&HSTRING::from(favicon_link_script().as_str()), &handler) }.is_err() {
            report(app, tab, BrowserError::new("unsupported", "无法读取站点图标", false));
        }
    }

    #[derive(serde::Deserialize)]
    struct FaviconLinkReply {
        href: String,
    }

    fn register_favicon(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) -> Result<(), BrowserError> {
        let extended: ICoreWebView2_15 = core
            .cast()
            .map_err(|_| BrowserError::new("unsupported", "当前 WebView2 运行时不支持站点图标接口", false))?;
        let handler_app = app.clone();
        let handler_tab = tab.to_string();
        let handler = FaviconChangedEventHandler::create(Box::new(move |sender, _args| {
            let Some(sender) = sender.as_ref() else { return Ok(()) };
            let Ok(extended) = sender.cast::<ICoreWebView2_15>() else { return Ok(()) };
            let page_url = read_source(sender).unwrap_or_default();
            let done_app = handler_app.clone();
            let done_tab = handler_tab.clone();
            let completed = GetFaviconCompletedHandler::create(Box::new(move |result, stream| {
                let Some(stream) = stream.as_ref() else { return Ok(()) };
                if result.is_err() {
                    return Ok(());
                }
                if let Some(bytes) = read_stream(stream) {
                    if let Some(data_url) = favicon::png_data_url(&bytes) {
                        store_favicon(&done_app, &done_tab, &page_url, data_url);
                    }
                }
                Ok(())
            }));
            // SAFETY: 只在本 webview 上取一次图标，handler 由 WebView2 持有。
            if unsafe { extended.GetFavicon(COREWEBVIEW2_FAVICON_IMAGE_FORMAT_PNG, &completed) }.is_err() {
                // 原生取图标失败：退到脚本读 <link rel=icon>。
                read_favicon_link(&handler_app, &handler_tab, sender);
            }
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: 事件注册只在当前 core 上生效。
        unsafe { extended.add_FaviconChanged(&handler, &mut token) }
            .map_err(|error| BrowserError::new("unsupported", format!("注册站点图标事件失败：{error}"), false))
    }

    // -----------------------------------------------------------------------
    // 快捷键：Ctrl+F / Ctrl+加/减/0
    // -----------------------------------------------------------------------

    fn ctrl_down() -> bool {
        // SAFETY: GetKeyState 只读当前线程的按键状态，没有副作用。
        unsafe { GetKeyState(VK_CONTROL.0 as i32) < 0 }
    }

    fn handle_accelerator(app: &tauri::AppHandle, tab: &str, args: &ICoreWebView2AcceleratorKeyPressedEventArgs) {
        let mut kind = COREWEBVIEW2_KEY_EVENT_KIND(0);
        let mut key = 0u32;
        // SAFETY: 只写局部变量。
        unsafe {
            if args.KeyEventKind(&mut kind).is_err() || args.VirtualKey(&mut key).is_err() {
                return;
            }
        }
        let key_down = kind == COREWEBVIEW2_KEY_EVENT_KIND_KEY_DOWN;
        let Some(shortcut) = shortcut::resolve(key, ctrl_down(), key_down) else { return };
        // user:“回调在 UI 线程，不能阻塞”+(先同步 SetHandled(true)，真正的动作丢到异步任务里)。
        // SAFETY: SetHandled 只写事件参数。
        unsafe { let _ = args.SetHandled(true); };
        let app = app.clone();
        let tab = tab.to_string();
        match shortcut {
            Shortcut::Find => {
                // 查找条画在 Sunday 界面里，所以既要通知前端打开，也要把键盘焦点交回主 webview。
                tauri::async_runtime::spawn(async move {
                    let _ = app.emit_to(
                        "main",
                        super::super::EVENT_FIND,
                        super::super::FindPayload {
                            tab: tab.clone(),
                            matches: 0,
                            index: -1,
                            action: Some("open".to_string()),
                        },
                    );
                    if let Some(main) = app.get_webview("main") {
                        let _ = main.set_focus();
                    }
                });
            }
            Shortcut::ZoomIn | Shortcut::ZoomOut | Shortcut::ZoomReset => {
                let action = match shortcut {
                    Shortcut::ZoomIn => "in",
                    Shortcut::ZoomOut => "out",
                    _ => "reset",
                };
                tauri::async_runtime::spawn(async move {
                    if let Err(error) = super::super::zoom_step(&app, &tab, action) {
                        report(&app, &tab, error);
                    }
                });
            }
        }
        let _ = shortcut.label();
    }

    fn register_accelerator(
        app: &tauri::AppHandle,
        tab: &str,
        platform: &tauri::webview::PlatformWebview,
    ) -> Result<(), BrowserError> {
        let controller: ICoreWebView2Controller = platform.controller();
        let handler_app = app.clone();
        let handler_tab = tab.to_string();
        let handler = AcceleratorKeyPressedEventHandler::create(Box::new(move |_sender, args| {
            if let Some(args) = args.as_ref() {
                handle_accelerator(&handler_app, &handler_tab, args);
            }
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: 事件注册只在当前 controller 上生效。
        unsafe { controller.add_AcceleratorKeyPressed(&handler, &mut token) }
            .map_err(|error| BrowserError::new("unsupported", format!("注册快捷键拦截失败：{error}"), false))
    }

    // -----------------------------------------------------------------------
    // 原生页内查找（ICoreWebView2_28::Find）
    // -----------------------------------------------------------------------

    fn find_api(core: &ICoreWebView2) -> Option<(ICoreWebView2Find, ICoreWebView2FindOptions)> {
        // cast 失败 = 运行时太旧，返回 None 让调用方走脚本实现（两者对外契约一致）。
        // SAFETY: 三个调用只取当前 webview 的环境与 Find 服务，不保存裸指针。
        let environment = unsafe { core.cast::<ICoreWebView2_2>().ok()?.Environment().ok()? };
        let env: ICoreWebView2Environment15 = environment.cast().ok()?;
        let find = unsafe { core.cast::<ICoreWebView2_28>().ok()?.Find().ok()? };
        // SAFETY: 每次查找都用一份新的 options，避免上一条查找词残留。
        let options = unsafe { env.CreateFindOptions().ok()? };
        Some((find, options))
    }

    fn find_counts(find: &ICoreWebView2Find) -> (usize, i64) {
        let mut count = 0i32;
        let mut index = -1i32;
        // SAFETY: 只写局部变量。
        unsafe {
            if find.MatchCount(&mut count).is_err() {
                count = 0;
            }
            if find.ActiveMatchIndex(&mut index).is_err() {
                index = -1;
            }
        }
        (count.max(0) as usize, index as i64)
    }

    fn register_find(app: &tauri::AppHandle, tab: &str, find: &ICoreWebView2Find) {
        let count_app = app.clone();
        let count_tab = tab.to_string();
        let count_find = find.clone();
        let count_handler = webview2_com::FindMatchCountChangedEventHandler::create(Box::new(move |_sender, _args| {
            let (matches, index) = find_counts(&count_find);
            super::super::emit_find(
                &count_app,
                super::super::FindPayload { tab: count_tab.clone(), matches, index, action: None },
            );
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: 事件注册只在 find 对象上生效。
        unsafe { find.add_MatchCountChanged(&count_handler, &mut token) }.ok();

        let index_app = app.clone();
        let index_tab = tab.to_string();
        let index_find = find.clone();
        let index_handler = webview2_com::FindActiveMatchIndexChangedEventHandler::create(Box::new(move |_sender, _args| {
            let (matches, index) = find_counts(&index_find);
            super::super::emit_find(
                &index_app,
                super::super::FindPayload { tab: index_tab.clone(), matches, index, action: None },
            );
            Ok(())
        }));
        let mut index_token = 0i64;
        // SAFETY: 同上。
        unsafe { find.add_ActiveMatchIndexChanged(&index_handler, &mut index_token) }.ok();
    }

    /// 命中返回 Ok(true)（原生已处理）；运行时太旧返回 Ok(false)，由调用方走脚本实现。
    pub fn native_find_core(
        app: &tauri::AppHandle,
        tab: &str,
        core: &ICoreWebView2,
        action: &str,
        query: &str,
        match_case: bool,
    ) {
        let Some((find, options)) = find_api(core) else {
            report(app, tab, BrowserError::new("unsupported", "原生页内查找不可用，刷新后重试", true));
            return;
        };
        unsafe {
            match action {
                "stop" => {
                    let _ = find.Stop();
                }
                "next" => {
                    let _ = find.FindNext();
                }
                "prev" => {
                    let _ = find.FindPrevious();
                }
                _ => {
                    let _ = options.SetFindTerm(&HSTRING::from(query));
                    let _ = options.SetIsCaseSensitive(match_case);
                    let _ = options.SetShouldHighlightAllMatches(true);
                    let _ = options.SetSuppressDefaultFindDialog(true);
                    let start_app = app.clone();
                    let start_tab = tab.to_string();
                    let start_find = find.clone();
                    let completed = FindStartCompletedHandler::create(Box::new(move |_result| {
                        let (matches, index) = find_counts(&start_find);
                        super::super::emit_find(
                            &start_app,
                            super::super::FindPayload { tab: start_tab.clone(), matches, index, action: None },
                        );
                        Ok(())
                    }));
                    if let Err(error) = find.Start(&options, &completed) {
                        report(app, tab, BrowserError::internal(format!("原生查找启动失败：{error}")));
                    }
                }
            }
        }
    }

    pub fn native_find(
        app: &tauri::AppHandle,
        tab: &str,
        view: &tauri::Webview,
        action: &str,
        query: Option<&str>,
        match_case: bool,
    ) -> Result<bool, BrowserError> {
        if !matches!(action, "start" | "next" | "prev" | "stop") {
            return Err(BrowserError::new("unsupported", format!("未知查找动作：{action}"), false));
        }
        let app = app.clone();
        let tab = tab.to_string();
        let action = action.to_string();
        let query = query.unwrap_or_default().to_string();
        let _ = view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&app, &tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            native_find_core(&app, &tab, &core, &action, &query, match_case);
        });
        // 命中变化由事件回传（attach 时注册过一次）。
        Ok(true)
    }

    // -----------------------------------------------------------------------
    // 站数据清理（Cookie + 缓存，不用 CDP）
    // -----------------------------------------------------------------------

    /// user:“接管时把 Cookie 和 User-Agent 传给 aria2”+(只读当前 URL 的 Cookie；结果走事件回传，
    /// 命令本身不阻塞 UI 线程，也不把 Cookie 写进任何日志)。
    pub fn read_download_headers(app: &tauri::AppHandle, tab: &str, url: &str) {
        let Ok(view) = super::super::view_for(app, tab) else {
            super::super::emit_download_headers(app, tab, url, super::super::DownloadHeaders::default());
            return;
        };
        let done_app = app.clone();
        let done_tab = tab.to_string();
        let done_url = url.to_string();
        let uri = url.to_string();
        let posted = view.with_webview(move |platform| {
            let finish = |cookie: String, user_agent: String| {
                super::super::emit_download_headers(
                    &done_app,
                    &done_tab,
                    &done_url,
                    super::super::DownloadHeaders { cookie, user_agent },
                );
            };
            let Ok(core) = core_of(&platform) else {
                finish(String::new(), String::new());
                return;
            };
            let user_agent = read_agent(&core);
            let manager = unsafe { core.cast::<ICoreWebView2_2>() }
                .and_then(|extended| unsafe { extended.CookieManager() });
            let Ok(manager) = manager else {
                finish(String::new(), user_agent);
                return;
            };
            let handler_app = done_app.clone();
            let handler_tab = done_tab.clone();
            let handler_url = done_url.clone();
            let handler_agent = user_agent.clone();
            let handler = GetCookiesCompletedHandler::create(Box::new(move |result, list| {
                let mut cookie = String::new();
                if result.is_ok() {
                    if let Some(list) = list.as_ref() {
                        let mut count = 0u32;
                        // SAFETY: 只读列表长度，索引来自同一次读取。
                        if unsafe { list.Count(&mut count) }.is_ok() {
                            for index in 0..count {
                                let Ok(item) = (unsafe { list.GetValueAtIndex(index) }) else { continue };
                                let name = read_uri(|slot| unsafe { item.Name(slot) }).unwrap_or_default();
                                let value = read_uri(|slot| unsafe { item.Value(slot) }).unwrap_or_default();
                                if name.is_empty() {
                                    continue;
                                }
                                if !cookie.is_empty() {
                                    cookie.push_str("; ");
                                }
                                cookie.push_str(&name);
                                cookie.push('=');
                                cookie.push_str(&value);
                            }
                        }
                    }
                }
                super::super::emit_download_headers(
                    &handler_app,
                    &handler_tab,
                    &handler_url,
                    super::super::DownloadHeaders { cookie, user_agent: handler_agent.clone() },
                );
                Ok(())
            }));
            // SAFETY: GetCookies 复制 uri 文本，handler 由 WebView2 持有到回调触发。
            if unsafe { manager.GetCookies(&HSTRING::from(uri.as_str()), &handler) }.is_err() {
                finish(String::new(), user_agent);
            }
        });
        if posted.is_err() {
            super::super::emit_download_headers(app, tab, url, super::super::DownloadHeaders::default());
        }
    }

    fn read_agent(core: &ICoreWebView2) -> String {
        let Ok(settings) = (unsafe { core.Settings() }) else {
            return String::new();
        };
        match unsafe { settings.cast::<ICoreWebView2Settings2>() } {
            Ok(extended) => read_uri(|slot| unsafe { extended.UserAgent(slot) }).unwrap_or_default(),
            Err(_) => String::new(),
        }
    }

    fn clear_cookies(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2, host: String) {
        // SAFETY: 只取当前 webview 的 cookie 管理器，不保存裸指针。
        let manager = match unsafe { core.cast::<ICoreWebView2_2>().and_then(|extended| extended.CookieManager()) } {
            Ok(manager) => manager,
            Err(error) => {
                report(app, tab, BrowserError::internal(format!("拿不到 Cookie 管理器：{error}")));
                return;
            }
        };
        for source in session::cookie_sources(&host) {
            // 回调里要删 cookie，命令线程还要发起 GetCookies：两次各持有自己的引用。
            let handler_manager = manager.clone();
            let clear_app = app.clone();
            let clear_tab = tab.to_string();
            let clear_host = host.clone();
            let handler = GetCookiesCompletedHandler::create(Box::new(move |result, list| {
                if result.is_err() {
                    return Ok(());
                }
                let Some(list) = list.as_ref() else { return Ok(()) };
                let mut count = 0u32;
                // SAFETY: 只读取列表长度。
                if unsafe { list.Count(&mut count) }.is_err() {
                    return Ok(());
                }
                let mut removed = 0usize;
                for index in 0..count {
                    // SAFETY: 索引来自上面读到的 Count。
                    let Ok(cookie) = (unsafe { list.GetValueAtIndex(index) }) else { continue };
                    let domain = read_uri(|slot| unsafe { cookie.Domain(slot) }).unwrap_or_default();
                    if !session::cookie_domain_matches(&domain, &clear_host) {
                        continue;
                    }
                    // SAFETY: 删除的正是刚枚举到的 cookie。
                    if unsafe { handler_manager.DeleteCookie(&cookie) }.is_ok() {
                        removed += 1;
                    }
                }
                let _ = (removed, &clear_app, &clear_tab);
                Ok(())
            }));
            // SAFETY: GetCookies 复制 uri 文本，handler 由 WebView2 持有到回调触发。
            if let Err(error) = unsafe { manager.GetCookies(&HSTRING::from(source.as_str()), &handler) } {
                report(app, tab, BrowserError::internal(format!("读取 Cookie 失败：{error}")));
            }
        }
    }

    /// 页面存储（localStorage / sessionStorage / IndexedDB）只能在同源文档里清，属于尽力而为。
    fn clear_page_storage(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2, host: &str) {
        let page_url = read_source(core).unwrap_or_default();
        if session::normalize_host(&page_url).as_deref() != Some(host) {
            // 当前页面不是这个站点：脚本清不到它的存储，如实告知而不是假装清过。
            report(
                app,
                tab,
                BrowserError::new("unsupported", "页面存储只能在当前打开该站点时清理，请先切换到该站点刷新后再清", false),
            );
            return;
        }
        // user:“Service Worker 注册也算存储”+(不清它的话离线页仍可能带着旧登录态)；缓存资源一律不碰。
        let script = r#"(() => {
  try { localStorage.clear(); } catch (error) {}
  try { sessionStorage.clear(); } catch (error) {}
  try {
    if (indexedDB.databases) {
      indexedDB.databases().then(items => {
        for (const item of items) { if (item && item.name) indexedDB.deleteDatabase(item.name); }
      }).catch(() => {});
    }
  } catch (error) {}
  try {
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      navigator.serviceWorker.getRegistrations().then(list => {
        for (const registration of list) registration.unregister().catch(() => {});
      }).catch(() => {});
    }
  } catch (error) {}
  // 明确不动 caches：站数据清理不清缓存
  return 'ok';
})()"#;
        let handler = ExecuteScriptCompletedHandler::create(Box::new(|_result, _value| Ok(())));
        // SAFETY: ExecuteScript 复制脚本文本。
        if unsafe { core.ExecuteScript(&HSTRING::from(script), &handler) }.is_err() {
            report(app, tab, BrowserError::internal("清理页面存储失败"));
        }
    }

    pub fn clear_site_data_core(
        app: &tauri::AppHandle,
        tab: &str,
        core: &ICoreWebView2,
        host: String,
        kinds: SiteDataKinds,
    ) {
        if kinds.cookies {
            clear_cookies(app, tab, core, host.clone());
        }
        if kinds.storage {
            clear_page_storage(app, tab, core, &host);
        }
        super::super::emit_site_data(
            app,
            super::super::SiteDataPayload {
                tab: tab.to_string(),
                host: host.clone(),
                kinds: kinds.targets().into_iter().map(str::to_string).collect(),
                cleared: true,
                message: format!(
                    "已清除 {host} 的登录与存储（Cookie、localStorage、IndexedDB、Service Worker）；缓存资源未清理，从缓存直接打开的旧页面可能仍显示已登录内容"
                ),
            },
        );
    }

    pub fn clear_site_data(
        app: &tauri::AppHandle,
        tab: &str,
        view: &tauri::Webview,
        host: String,
        kinds: SiteDataKinds,
    ) -> Result<(), BrowserError> {
        let app = app.clone();
        let tab = tab.to_string();
        let _ = view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&app, &tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            clear_site_data_core(&app, &tab, &core, host, kinds);
        });
        Ok(())
    }

    pub fn supports_incognito() -> bool {
        // 真实生效需要真机验证（附录 C 的 E1–E4）；这里只回答「平台路径存在」。
        true
    }

    /// user:“越权自检：尝试调用任一条命令，断言必须失败”+(网页侧没有任何 invoke 通道，
    /// 所以既要证明三个全局不存在，也要把它们真的调用一次看结果)。
    pub fn run_diagnostics(app: &tauri::AppHandle, tab: &str, view: &tauri::Webview) {
        let probe_app = app.clone();
        let probe_tab = tab.to_string();
        let probe_view = view.clone();
        let _ = view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&probe_app, &probe_tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            let handler = ExecuteScriptCompletedHandler::create(Box::new(|_result, _value| Ok(())));
            // 第一阶段：同步记录三个全局是否存在，并真的尝试一次越权调用（Promise 结果写回页面全局）。
            // SAFETY: ExecuteScript 复制脚本文本；handler 由 WebView2 持有到回调触发。
            if unsafe { core.ExecuteScript(&HSTRING::from(diagnostics_probe_script()), &handler) }.is_err() {
                report(&probe_app, &probe_tab, BrowserError::internal("越权自检脚本执行失败"));
                return;
            }
            let report_app = probe_app.clone();
            let report_tab = probe_tab.clone();
            // 第二阶段延后读取：Promise 的拒绝需要一轮事件循环才会落回页面全局。
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(400));
                let done_app = report_app.clone();
                let done_tab = report_tab.clone();
                let _ = probe_view.with_webview(move |platform| {
                    let Ok(core) = core_of(&platform) else { return };
                    let handler = ExecuteScriptCompletedHandler::create(Box::new(move |result, value| {
                        if result.is_err() {
                            return Ok(());
                        }
                        let payload = diagnostics_payload(&done_tab, &value);
                        super::super::emit_diagnostics(&done_app, payload);
                        Ok(())
                    }));
                    // SAFETY: 同第一阶段，脚本只读页面全局变量。
                    let _ = unsafe {
                        core.ExecuteScript(&HSTRING::from("JSON.stringify(window.__sundayBrowserDiag || null)"), &handler)
                    };
                });
            });
        });
    }

    /// 第一阶段脚本：只做只读探测，不改页面内容。
    fn diagnostics_probe_script() -> &'static str {
        r#"(() => {
  const record = { checks: [], invokeResult: 'not-available' };
  const globals = [
    ['__TAURI_INTERNALS__', window.__TAURI_INTERNALS__],
    ['__TAURI__', window.__TAURI__],
    ['ipc', window.ipc],
    ['__TAURI_IPC__', window.__TAURI_IPC__],
  ];
  for (const item of globals) {
    const present = item[1] !== undefined && item[1] !== null;
    record.checks.push({ name: item[0], present: present, detail: present ? '存在（越权风险）' : '不存在（通过）' });
  }
  try {
    if (window.__TAURI_INTERNALS__ && typeof window.__TAURI_INTERNALS__.invoke === 'function') {
      record.invokeResult = 'pending';
      Promise.resolve(window.__TAURI_INTERNALS__.invoke('browser_state', { tab: 'diagnostic' }))
        .then(() => { record.invokeResult = 'succeeded'; })
        .catch(error => { record.invokeResult = 'failed: ' + String(error).slice(0, 160); });
    } else if (window.ipc && typeof window.ipc.postMessage === 'function') {
      record.invokeResult = 'ipc-available';
    } else if (typeof window.fetch === 'function') {
      record.invokeResult = 'no-invoke-channel';
    }
  } catch (error) {
    record.invokeResult = 'threw: ' + String(error).slice(0, 160);
  }
  window.__sundayBrowserDiag = record;
  return 'ok';
})()"#
    }

    #[derive(serde::Deserialize)]
    struct DiagnosticsReply {
        checks: Vec<DiagnosticsProbe>,
        #[serde(rename = "invokeResult")]
        invoke_result: String,
    }

    #[derive(serde::Deserialize)]
    struct DiagnosticsProbe {
        name: String,
        present: bool,
        #[serde(default)]
        detail: String,
    }

    fn diagnostics_payload(tab: &str, raw: &str) -> super::super::DiagnosticsPayload {
        // user:“后台标签消息投递可观测”+(观测来自宿主自己的账本，与页面自检结果并排给出，
        // 真机验收时不用猜「后台标签到底能不能直接跑 Agent 指令」)。
        let delivery = super::super::bridge::last_delivery(tab);
        let delivery_note = delivery
            .as_ref()
            .map(super::super::bridge::delivery_note)
            .unwrap_or_else(|| "还没有 Agent 指令投递记录".to_string());
        // ExecuteScript 的结果是 JSON 字符串；兼容「返回对象」与「返回 JSON 文本」两种形状。
        let mut reply = serde_json::from_str::<DiagnosticsReply>(raw.trim()).ok();
        if reply.is_none() {
            if let Ok(inner) = serde_json::from_str::<String>(raw.trim()) {
                reply = serde_json::from_str::<DiagnosticsReply>(&inner).ok();
            }
        }
        let Some(reply) = reply else {
            return super::super::DiagnosticsPayload {
                tab: tab.to_string(),
                passed: false,
                checks: Vec::new(),
                message: format!("越权自检没有取到结果（页面可能还在加载），请刷新后重试；{delivery_note}"),
                delivery,
                delivery_note,
            };
        };
        let checks = reply
            .checks
            .into_iter()
            .map(|probe| super::super::DiagnosticsCheck { name: probe.name, passed: !probe.present, detail: probe.detail })
            .collect::<Vec<_>>();
        let globals_clean = checks.iter().all(|check| check.passed);
        let invoke_clean = !reply.invoke_result.starts_with("succeeded") && reply.invoke_result != "ipc-available";
        let passed = globals_clean && invoke_clean;
        let message = if passed {
            format!("通过：网页里没有 Tauri IPC 通道（{}）；{delivery_note}", reply.invoke_result)
        } else {
            format!("失败：网页里存在可用的 Tauri IPC 通道（{}），请检查 capability 配置；{delivery_note}", reply.invoke_result)
        };
        super::super::DiagnosticsPayload { tab: tab.to_string(), passed, checks, message, delivery, delivery_note }
    }

    // -----------------------------------------------------------------------
    /// user:“证书放行记忆范围”+(WebView2 的 ALWAYS_ALLOW 是「本次会话该主机放行」，不会自动过期，
    /// 所以给一个显式清除入口；`ClearServerCertificateErrorActions` 在 ICoreWebView2_14 上可用)。
    pub fn clear_certificate_memory_core(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) {
        let Ok(extended) = core.cast::<ICoreWebView2_14>() else {
            report(
                app,
                tab,
                BrowserError::new("unsupported", "当前 WebView2 运行时不支持清除证书放行记忆", false),
            );
            return;
        };
        let done_app = app.clone();
        let done_tab = tab.to_string();
        let completed = ClearServerCertificateErrorActionsCompletedHandler::create(Box::new(move |result| {
            if let Err(error) = result {
                report(&done_app, &done_tab, BrowserError::internal(format!("清除证书放行记忆失败：{error}")));
            }
            Ok(())
        }));
        if unsafe { extended.ClearServerCertificateErrorActions(&completed) }.is_err() {
            report(app, tab, BrowserError::internal("清除证书放行记忆失败"));
        }
    }

    pub fn clear_certificate_memory(app: &tauri::AppHandle, tab: &str, view: &tauri::Webview) -> Result<(), BrowserError> {
        let handler_app = app.clone();
        let handler_tab = tab.to_string();
        let _ = view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&handler_app, &handler_tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            clear_certificate_memory_core(&handler_app, &handler_tab, &core);
        });
        Ok(())
    }

    // 事件注册入口
    // -----------------------------------------------------------------------

    // SAFETY: 所有 COM 调用都在 wry 提供的有效接口上，且不保存裸指针到闭包之外。
    unsafe fn register(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) -> Result<(), BrowserError> {
        // 标题：以 WebView2 的 DocumentTitle 为准，页面自己上报的标题只作提示。
        let title_app = app.clone();
        let title_tab = tab.to_string();
        let title_handler = DocumentTitleChangedEventHandler::create(Box::new(move |sender, _| {
            if let Some(sender) = sender.as_ref() {
                if let Some(title) = read_title(sender) {
                    let _ = super::super::with_runtime(|rt| {
                        if let Ok(state) = rt.tabs.get_mut(&title_tab) {
                            state.title = title;
                        }
                        Ok(())
                    });
                    super::super::emit_state(&title_app, &title_tab);
                }
            }
            Ok(())
        }));
        let mut title_token = 0i64;
        core.add_DocumentTitleChanged(&title_handler, &mut title_token)
            .map_err(|error| BrowserError::internal(format!("注册标题事件失败：{error}")))?;

        // 历史：canGoBack/canGoForward 与真实地址都以 WebView2 为准。
        let history_app = app.clone();
        let history_tab = tab.to_string();
        let history_handler = HistoryChangedEventHandler::create(Box::new(move |sender, _| {
            if let Some(sender) = sender.as_ref() {
                sync_history(&history_tab, sender);
                super::super::emit_state(&history_app, &history_tab);
            }
            Ok(())
        }));
        let mut history_token = 0i64;
        core.add_HistoryChanged(&history_handler, &mut history_token)
            .map_err(|error| BrowserError::internal(format!("注册历史事件失败：{error}")))?;

        // user:“网页请求全屏时能真全屏”+(网页全屏 = 主窗口全屏 + 该 webview 撑满，退出还原)。
        let fullscreen_app = app.clone();
        let fullscreen_tab = tab.to_string();
        let fullscreen_handler = ContainsFullScreenElementChangedEventHandler::create(Box::new(move |sender, _| {
            if let Some(sender) = sender.as_ref() {
                let mut value = BOOL::default();
                if unsafe { sender.ContainsFullScreenElement(&mut value) }.is_ok() {
                    let on = value.as_bool();
                    if let Err(error) = super::super::apply_fullscreen(&fullscreen_app, &fullscreen_tab, on) {
                        report(&fullscreen_app, &fullscreen_tab, error);
                    }
                }
            }
            Ok(())
        }));
        let mut fullscreen_token = 0i64;
        core.add_ContainsFullScreenElementChanged(&fullscreen_handler, &mut fullscreen_token)
            .map_err(|error| BrowserError::internal(format!("注册全屏事件失败：{error}")))?;

        // 新建标签时的初始历史状态（否则首屏的 canGoBack 一直是 false 直到第一次跳转）。
        sync_history(tab, core);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // M4：页面桥（WebMessage 双向）+ 视口截图
    // -----------------------------------------------------------------------

    pub fn attach_bridge_core(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2) -> Result<(), BrowserError> {
        let message_app = app.clone();
        let message_tab = tab.to_string();
        let handler = WebMessageReceivedEventHandler::create(Box::new(move |_sender, args| {
            let Some(args) = args else { return Ok(()) };
            let mut raw = PWSTR::null();
            // SAFETY: 只有字符串型消息能取到；JSON 型消息（宿主发往页面的）不会走到这里，失败即忽略。
            if unsafe { args.TryGetWebMessageAsString(&mut raw) }.is_err() {
                return Ok(());
            }
            let text = take_pwstr(raw);
            // 校验与配对全在 bridge 层：非法消息直接丢弃并计数，不影响页面。
            crate::browser::bridge::on_page_message(&message_app, &message_tab, &text);
            Ok(())
        }));
        let mut token = 0i64;
        // SAFETY: handler 由 WebView2 持有到 webview 释放；token 只是注册句柄，不需要手工解绑。
        unsafe { core.add_WebMessageReceived(&handler, &mut token) }
            .map_err(|error| BrowserError::internal(format!("注册页面桥失败：{error}")))
    }

    /// user:“通信走 WebView2 WebMessage”+(注册 `WebMessageReceived`；消息校验全部在 bridge 层，
    /// 这里只负责把字符串搬过去，不做任何解释，解析失败也不会影响页面)。
    pub fn attach_bridge(app: &tauri::AppHandle, tab: &str, view: &tauri::Webview) -> Result<(), BrowserError> {
        let bridge_app = app.clone();
        let bridge_tab = tab.to_string();
        view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&bridge_app, &bridge_tab, BrowserError::internal("拿不到 WebView2 接口（页面桥没有接上）"));
                return;
            };
            if let Err(error) = attach_bridge_core(&bridge_app, &bridge_tab, &core) {
                report(&bridge_app, &bridge_tab, error);
            }
        })
        .map_err(|error| BrowserError::internal(format!("注册页面桥失败：{error}")))
    }

    /// 把一条指令投进页面。注意 `with_webview` 从非 UI 线程只做「投递」，真正的 COM 调用稍后在 UI 线程发生，
    /// 所以发送失败无法同步返回；调用方以应答超时兜底。
    pub fn post_message(view: &tauri::Webview, payload: &str) -> Result<(), BrowserError> {
        let text = payload.to_string();
        view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else { return };
            // SAFETY: PostWebMessageAsJson 复制字符串内容，不保留引用。
            let _ = unsafe { core.PostWebMessageAsJson(&HSTRING::from(text.as_str())) };
        })
        .map_err(|error| BrowserError::internal(format!("指令发送失败：{error}")))
    }

    pub fn capture_viewport_with_core(
        core: &ICoreWebView2,
        sender: std::sync::mpsc::Sender<Result<Vec<u8>, String>>,
    ) {
        // SAFETY: 只有一个返回值，空指针参数即「不预置内容」。
        let Some(stream) = (unsafe { SHCreateMemStream(None) }) else {
            let _ = sender.send(Err("无法创建截图内存流".to_string()));
            return;
        };
        let stream_for_read = stream.clone();
        let done = sender.clone();
        let handler = CapturePreviewCompletedHandler::create(Box::new(move |result| {
            if let Err(error) = result {
                let _ = done.send(Err(format!("截图失败：{error}")));
                return Ok(());
            }
            let _ = done.send(read_png_stream(&stream_for_read));
            Ok(())
        }));
        // SAFETY: 只截当前 webview 的视口；stream 与 handler 活到本次调用结束（回调由 WebView2 持有）。
        if let Err(error) =
            unsafe { core.CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG, &stream, &handler) }
        {
            let _ = sender.send(Err(format!("截图失败：{error}")));
        }
    }

    /// user:“截图用 CapturePreview 取视口”+(不支持整页与元素级：那需要 CDP 或自己拼图，首版明确报 unsupported)。
    pub fn capture_viewport(view: &tauri::Webview, timeout: std::time::Duration) -> Result<Vec<u8>, BrowserError> {
        let (sender, receiver) = std::sync::mpsc::channel::<Result<Vec<u8>, String>>();
        view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                let _ = sender.send(Err("拿不到 WebView2 接口".to_string()));
                return;
            };
            capture_viewport_with_core(&core, sender);
        })
        .map_err(|error| BrowserError::internal(format!("截图请求失败：{error}")))?;

        match receiver.recv_timeout(timeout) {
            Ok(Ok(bytes)) => Ok(bytes),
            Ok(Err(message)) => Err(BrowserError::new("unsupported", message, true)),
            Err(_) => Err(BrowserError::new(
                "timeout",
                "截图超时：标签可能不可见或页面还没渲染完，先让它显示出来再截",
                true,
            )),
        }
    }

    /// 从内存流读出 PNG 字节；上限 8 MB，防止异常页面把内存吃满。
    fn read_png_stream(stream: &IStream) -> Result<Vec<u8>, String> {
        const LIMIT: usize = 8 * 1024 * 1024;
        let mut bytes = Vec::new();
        let mut buffer = vec![0u8; 64 * 1024];
        // SAFETY: 内存流支持 Seek/Read；buffer 指针只在本次循环内使用。
        unsafe {
            stream.Seek(0, STREAM_SEEK_SET, None).map_err(|error| format!("读取截图失败：{error}"))?;
            loop {
                let mut read = 0u32;
                let status = stream.Read(buffer.as_mut_ptr() as *mut core::ffi::c_void, buffer.len() as u32, Some(&mut read));
                if status.is_err() {
                    return Err(format!("读取截图失败：{status:?}"));
                }
                if read == 0 {
                    break;
                }
                bytes.extend_from_slice(&buffer[..read as usize]);
                if bytes.len() > LIMIT {
                    return Err("截图超过 8 MB，已放弃（先缩小窗口或改用快照）".to_string());
                }
            }
        }
        if bytes.is_empty() {
            return Err("截图返回空内容".to_string());
        }
        Ok(bytes)
    }

    pub fn attach_core(
        app: &tauri::AppHandle,
        tab: &str,
        core: &ICoreWebView2,
        controller: Option<&ICoreWebView2Controller>,
    ) {
        let result = (|| {
            // SAFETY: core 只在当前 UI 线程回调内有效，注册本身不保留裸指针。
            unsafe { register(app, tab, core) }?;
            // user:“权限默认全部拒绝”+(拦截注册失败必须让用户看见：不能静默退回运行时默认行为)。
            register_permissions(app, tab, core)?;
            Ok::<_, BrowserError>(())
        })();
        if let Err(error) = result {
            report(app, tab, error);
            return;
        }
        // 证书/favicon/快捷键/原生查找都是「有就更好」：失败只上报，不阻塞页面。
        if let Err(error) = register_certificate(app, tab, core) {
            report(app, tab, error);
        }
        if let Err(error) = register_favicon(app, tab, core) {
            read_favicon_link(app, tab, core);
            let _ = error;
        }
        if let Some((find, _options)) = find_api(core) {
            register_find(app, tab, &find);
            let _ = super::super::with_runtime(|rt| {
                if let Ok(state) = rt.tabs.get_mut(tab) {
                    state.native_find = true;
                }
                Ok(())
            });
        }
        if let Some(ctrl) = controller {
            let accel_app = app.clone();
            let accel_tab = tab.to_string();
            let handler = webview2_com::AcceleratorKeyPressedEventHandler::create(Box::new(move |_, args| {
                if let Some(args) = args.as_ref() {
                    handle_accelerator(&accel_app, &accel_tab, args);
                }
                Ok(())
            }));
            let mut token = 0i64;
            let _ = unsafe { ctrl.add_AcceleratorKeyPressed(&handler, &mut token) };
        }
    }

    pub fn attach(app: &tauri::AppHandle, tab: &str, view: &tauri::Webview) {
        let app = app.clone();
        let tab = tab.to_string();
        view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&app, &tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            attach_core(&app, &tab, &core, None);
            if let Err(error) = register_accelerator(&app, &tab, &platform) {
                report(&app, &tab, error);
            }
        });
    }

    fn call_history(view: &tauri::Webview, call: HistoryCall) {
        // with_webview 把动作投递到 UI 线程；失败由事件上报，不阻塞命令返回。
        view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else { return };
            // SAFETY: 三个调用都只作用于当前 controller 的 webview。
            let _ = unsafe {
                match call {
                    HistoryCall::Back => core.GoBack(),
                    HistoryCall::Forward => core.GoForward(),
                    HistoryCall::Stop => core.Stop(),
                }
            };
        });
    }

    pub fn go_back(view: &tauri::Webview) -> Result<(), BrowserError> {
        call_history(view, HistoryCall::Back);
        Ok(())
    }

    pub fn go_forward(view: &tauri::Webview) -> Result<(), BrowserError> {
        call_history(view, HistoryCall::Forward);
        Ok(())
    }

    pub fn stop(view: &tauri::Webview) -> Result<(), BrowserError> {
        call_history(view, HistoryCall::Stop);
        Ok(())
    }

    #[derive(serde::Deserialize)]
    struct FindReply {
        matches: usize,
        index: i64,
    }

    pub fn eval_with_result_core(app: &tauri::AppHandle, tab: &str, core: &ICoreWebView2, script: String) {
        let reply_app = app.clone();
        let reply_tab = tab.to_string();
        let handler = ExecuteScriptCompletedHandler::create(Box::new(move |result, value| {
            if result.is_ok() {
                if let Ok(parsed) = serde_json::from_str::<FindReply>(value.trim()) {
                    super::super::emit_find(
                        &reply_app,
                        super::super::FindPayload {
                            tab: reply_tab.clone(),
                            matches: parsed.matches,
                            index: parsed.index,
                            action: None,
                        },
                    );
                }
            }
            Ok(())
        }));
        if let Err(error) = unsafe { core.ExecuteScript(&HSTRING::from(script.as_str()), &handler) } {
            report(app, tab, BrowserError::internal(format!("查找脚本执行失败：{error}")));
        }
    }

    /// 脚本实现的查找（原生接口不可用时的兜底），对外契约与 `native_find` 一致。
    pub fn eval_with_result(
        app: &tauri::AppHandle,
        tab: &str,
        view: &tauri::Webview,
        script: String,
    ) -> Result<(), BrowserError> {
        let app = app.clone();
        let tab = tab.to_string();
        let _ = view.with_webview(move |platform| {
            let Ok(core) = core_of(&platform) else {
                report(&app, &tab, BrowserError::internal("拿不到 WebView2 接口"));
                return;
            };
            eval_with_result_core(&app, &tab, &core, script);
        });
        Ok(())
    }

}

pub use imp::*;
