//! 独立最小实验：验证 WebView2 CompositionController + DirectComposition 统一视觉合成方案。
//!
//! user:“嗯，可行就直接实现”+(不碰现有 Browser 业务代码，先用最小独立可执行示例验证 4 项核心机制：
//!  1. 网页实时动画/视频播放时，透明合成的 UI 菜单直接盖在上方不闪烁；
//!  2. Browser 浮窗视觉节点实时拖动/缩放，不依赖截图冻结；
//!  3. 鼠标点击、滚轮、焦点在 UI 浮层与 Browser 网页之间正确路由；
//!  4. DPI 与窗口尺寸变化下精确定位。)
//!
//! 运行方式：在 `core/desktop/src-tauri` 下执行 `cargo run --example composition_lab`。

#![cfg(windows)]

use std::cell::RefCell;
use std::rc::Rc;
use webview2_com::Microsoft::Web::WebView2::Win32::{
    CreateCoreWebView2EnvironmentWithOptions, ICoreWebView2, ICoreWebView2CompositionController,
    ICoreWebView2Controller, ICoreWebView2Controller2, ICoreWebView2Environment3,
    COREWEBVIEW2_COLOR, COREWEBVIEW2_MOUSE_EVENT_KIND, COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS,
    COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC,
};
use webview2_com::{
    CreateCoreWebView2CompositionControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler, WebMessageReceivedEventHandler,
};
use windows::core::{w, Interface, PCWSTR, PWSTR};
use windows::Win32::Foundation::{HMODULE, HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::Graphics::Direct3D::D3D_DRIVER_TYPE_HARDWARE;
use windows::Win32::Graphics::Direct3D11::{
    D3D11CreateDevice, D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_SDK_VERSION,
};
use windows::Win32::Graphics::DirectComposition::{
    DCompositionCreateDevice, IDCompositionDevice, IDCompositionTarget, IDCompositionVisual,
};
use windows::Win32::Graphics::Dxgi::IDXGIDevice;
use windows::Win32::System::Com::{CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetClientRect, GetMessageW,
    GetWindowLongPtrW, LoadCursorW, PostQuitMessage, RegisterClassExW, SetWindowLongPtrW,
    SetWindowPos, ShowWindow, TranslateMessage, CREATESTRUCTW, CS_HREDRAW, CS_VREDRAW,
    GWLP_USERDATA, IDC_ARROW, MSG, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOZORDER, SW_SHOW, WM_CREATE,
    WM_DESTROY, WM_DPICHANGED, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP,
    WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_SIZE, WNDCLASSEXW,
    WS_EX_NOREDIRECTIONBITMAP, WS_OVERLAPPEDWINDOW,
};

#[derive(Clone, Copy)]
struct RectPx {
    x: i32,
    y: i32,
    w: i32,
    h: i32,
}

impl RectPx {
    fn contains(&self, px: i32, py: i32) -> bool {
        px >= self.x && px < self.x + self.w && py >= self.y && py < self.y + self.h
    }
}

struct HostedWebView {
    controller: ICoreWebView2Controller,
    comp: ICoreWebView2CompositionController,
    webview: ICoreWebView2,
    visual: IDCompositionVisual,
}

struct LabState {
    hwnd: HWND,
    dcomp: IDCompositionDevice,
    _target: IDCompositionTarget,
    root_visual: IDCompositionVisual,
    browser: Option<HostedWebView>,
    ui: Option<HostedWebView>,
    browser_rect: RectPx,
    /// 模拟 UI 菜单/浮层盖在网页上的矩形（当菜单打开时扩大命中区到 UI 层）。
    ui_overlay_rect: RectPx,
    ui_menu_open: bool,
    dragging_browser: bool,
    drag_start_pt: POINT,
    drag_start_rect: RectPx,
}

impl LabState {
    fn update_browser_geometry(&self) {
        if let Some(b) = &self.browser {
            unsafe {
                let _ = b.visual.SetOffsetX2(self.browser_rect.x as f32);
                let _ = b.visual.SetOffsetY2(self.browser_rect.y as f32);
                let _ = b.controller.SetBounds(RECT {
                    left: 0,
                    top: 0,
                    right: self.browser_rect.w.max(100),
                    bottom: self.browser_rect.h.max(100),
                });
                let _ = self.dcomp.Commit();
            }
        }
    }

    fn update_ui_geometry(&self, client_w: i32, client_h: i32) {
        if let Some(u) = &self.ui {
            unsafe {
                let _ = u.controller.SetBounds(RECT {
                    left: 0,
                    top: 0,
                    right: client_w.max(1),
                    bottom: client_h.max(1),
                });
                let _ = self.dcomp.Commit();
            }
        }
    }

    fn route_mouse(
        &mut self,
        kind: COREWEBVIEW2_MOUSE_EVENT_KIND,
        wparam: WPARAM,
        x: i32,
        y: i32,
        wheel_delta: u32,
    ) {
        let vkeys = virtual_keys_from_wparam(wparam);
        // 先检查是否正在拖动 Browser 视觉节点（按住 Alt + 左键拖动浏览器框，验证无冻结实时跟随）
        if self.dragging_browser {
            if kind == COREWEBVIEW2_MOUSE_EVENT_KIND(0x0200) {
                // WM_MOUSEMOVE
                let dx = x - self.drag_start_pt.x;
                let dy = y - self.drag_start_pt.y;
                self.browser_rect.x = self.drag_start_rect.x + dx;
                self.browser_rect.y = self.drag_start_rect.y + dy;
                self.update_browser_geometry();
                return;
            }
            if kind == COREWEBVIEW2_MOUSE_EVENT_KIND(0x0202) {
                // WM_LBUTTONUP
                self.dragging_browser = false;
                return;
            }
        }

        // Alt + 左键按下浏览器区域：直接拖动 Browser DirectComposition Visual（零冻结）
        let alt_down = (wparam.0 & 0x20) != 0;
        if alt_down
            && kind == COREWEBVIEW2_MOUSE_EVENT_KIND(0x0201)
            && self.browser_rect.contains(x, y)
        {
            self.dragging_browser = true;
            self.drag_start_pt = POINT { x, y };
            self.drag_start_rect = self.browser_rect;
            return;
        }

        // 命中判定：顶部栏 (y < 48) 或打开的菜单/浮层区域由 UI 层接管，其余穿透给下方的 Browser！
        let hits_ui = y < 48 || (self.ui_menu_open && self.ui_overlay_rect.contains(x, y));
        if hits_ui {
            if let Some(u) = &self.ui {
                if kind == COREWEBVIEW2_MOUSE_EVENT_KIND(0x0201) {
                    unsafe {
                        let _ = u
                            .controller
                            .MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
                    }
                }
                unsafe {
                    let _ = u.comp.SendMouseInput(
                        kind,
                        vkeys,
                        wheel_delta,
                        POINT { x, y },
                    );
                }
            }
            return;
        }

        if self.browser_rect.contains(x, y) {
            if let Some(b) = &self.browser {
                if kind == COREWEBVIEW2_MOUSE_EVENT_KIND(0x0201) {
                    unsafe {
                        let _ = b
                            .controller
                            .MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
                    }
                }
                let local = POINT {
                    x: x - self.browser_rect.x,
                    y: y - self.browser_rect.y,
                };
                unsafe {
                    let _ = b.comp.SendMouseInput(kind, vkeys, wheel_delta, local);
                }
            }
        }
    }
}

fn virtual_keys_from_wparam(wparam: WPARAM) -> COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS {
    let flags = (wparam.0 as u32) & (0x0001 | 0x0002 | 0x0004 | 0x0008 | 0x0010);
    COREWEBVIEW2_MOUSE_EVENT_VIRTUAL_KEYS(flags as i32)
}

fn create_dcomp(hwnd: HWND) -> windows::core::Result<(IDCompositionDevice, IDCompositionTarget, IDCompositionVisual)> {
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
        )?;
        let d3d_device = d3d_device.unwrap();
        let dxgi: IDXGIDevice = d3d_device.cast()?;
        let dcomp: IDCompositionDevice = DCompositionCreateDevice(&dxgi)?;
        let target = dcomp.CreateTargetForHwnd(hwnd, true)?;
        let root = dcomp.CreateVisual()?;
        target.SetRoot(&root)?;
        dcomp.Commit()?;
        Ok((dcomp, target, root))
    }
}

const BROWSER_HTML: &str = r#"<!doctype html>
<html><body style="margin:0;background:#10141d;color:#e8eefc;font-family:system-ui;padding:16px;">
  <h2 style="margin:0 0 8px">Browser Visual (底层实时渲染)</h2>
  <p style="opacity:.75;font-size:13px;margin:0 0 12px">动画持续运行，可滚动、可点击计数（Alt+左键可直接拖动整块网页）</p>
  <canvas id="c" width="520" height="160" style="border-radius:10px;display:block;margin-bottom:12px;background:#182032;"></canvas>
  <button id="btn" style="padding:8px 14px;border-radius:8px;border:0;background:#3b82f6;color:#fff;cursor:pointer;">点击测试: 0</button>
  <div style="margin-top:16px;height:600px;background:linear-gradient(180deg,#182032,#0f172a);border-radius:10px;padding:12px;">
    向下滚动测试区域（CompositionController SendMouseInput WM_MOUSEWHEEL）
  </div>
  <script>
    let n = 0;
    document.getElementById('btn').onclick = () => {
      n += 1;
      document.getElementById('btn').textContent = '点击测试: ' + n;
    };
    const ctx = document.getElementById('c').getContext('2d');
    let t = 0;
    function frame() {
      t += 0.04;
      ctx.fillStyle = '#182032';
      ctx.fillRect(0, 0, 520, 160);
      for (let i = 0; i < 6; i++) {
        const x = 60 + i * 80;
        const y = 80 + Math.sin(t + i * 0.7) * 42;
        ctx.fillStyle = `hsl(${(i * 50 + t * 40) % 360}, 80%, 62%)`;
        ctx.beginPath();
        ctx.arc(x, y, 20, 0, Math.PI * 2);
        ctx.fill();
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  </script>
</body></html>"#;

const UI_HTML: &str = r#"<!doctype html>
<html><body style="margin:0;background:transparent;color:#f3f4f6;font-family:system-ui;user-select:none;">
  <div style="height:48px;display:flex;align-items:center;gap:10px;padding:0 16px;background:rgba(20,22,28,0.92);border-bottom:1px solid rgba(255,255,255,0.1);">
    <strong>Sunday Composition Lab</strong>
    <button id="menuBtn" style="padding:6px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.18);background:#272a34;color:#fff;cursor:pointer;">更多菜单（实时覆盖网页）</button>
    <button id="moveBtn" style="padding:6px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.18);background:#272a34;color:#fff;cursor:pointer;">移动 Browser</button>
  </div>
  <div id="menu" style="display:none;position:absolute;left:180px;top:54px;width:280px;padding:12px;border-radius:12px;background:rgba(30,33,42,0.86);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.18);box-shadow:0 18px 40px rgba(0,0,0,0.45);">
    <div style="font-weight:600;margin-bottom:6px">统一合成菜单</div>
    <div style="font-size:12px;opacity:.8;margin-bottom:10px">下方网页动画仍在实时播放，无需截图冻结</div>
    <button id="closeBtn" style="padding:6px 10px;border-radius:6px;border:0;background:#3b82f6;color:#fff;cursor:pointer;">关闭菜单</button>
  </div>
  <script>
    const menu = document.getElementById('menu');
    const post = (msg) => window.chrome.webview.postMessage(JSON.stringify(msg));
    document.getElementById('menuBtn').onclick = () => {
      const open = menu.style.display === 'none';
      menu.style.display = open ? 'block' : 'none';
      post({ type: 'menu', open });
    };
    document.getElementById('closeBtn').onclick = () => {
      menu.style.display = 'none';
      post({ type: 'menu', open: false });
    };
    document.getElementById('moveBtn').onclick = () => post({ type: 'nudge' });
  </script>
</body></html>"#;

fn init_webview2(state_rc: Rc<RefCell<LabState>>) {
    let hwnd = state_rc.borrow().hwnd;
    let state_for_env = state_rc.clone();
    let handler = CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(move |res, env| {
        if res.is_err() {
            return Ok(());
        }
        let Some(env) = env else { return Ok(()) };
        let env3: ICoreWebView2Environment3 = env.cast()?;

        // 1) 创建底层 Browser CompositionController
        let state_b = state_for_env.clone();
        let b_handler = CreateCoreWebView2CompositionControllerCompletedHandler::create(Box::new(
            move |res, comp| {
                if res.is_err() {
                    return Ok(());
                }
                let Some(comp) = comp else { return Ok(()) };
                let controller: ICoreWebView2Controller = comp.cast()?;
                let webview = unsafe { controller.CoreWebView2()? };
                let mut st = state_b.borrow_mut();
                let visual = unsafe { st.dcomp.CreateVisual()? };
                unsafe {
                    comp.SetRootVisualTarget(&visual)?;
                    st.root_visual.AddVisual(&visual, false, None)?;
                    let _ = controller.SetIsVisible(true);
                    let _ = webview.NavigateToString(PCWSTR(
                        BROWSER_HTML.encode_utf16().chain(Some(0)).collect::<Vec<_>>().as_ptr(),
                    ));
                }
                st.browser = Some(HostedWebView {
                    controller,
                    comp,
                    webview,
                    visual,
                });
                st.update_browser_geometry();
                Ok(())
            },
        ));
        unsafe {
            let _ = env3.CreateCoreWebView2CompositionController(hwnd, &b_handler);
        }

        // 2) 创建顶层透明 UI CompositionController
        let state_u = state_for_env.clone();
        let u_handler = CreateCoreWebView2CompositionControllerCompletedHandler::create(Box::new(
            move |res, comp| {
                if res.is_err() {
                    return Ok(());
                }
                let Some(comp) = comp else { return Ok(()) };
                let controller: ICoreWebView2Controller = comp.cast()?;
                if let Ok(c2) = controller.cast::<ICoreWebView2Controller2>() {
                    unsafe {
                        let _ = c2.SetDefaultBackgroundColor(COREWEBVIEW2_COLOR {
                            A: 0,
                            R: 0,
                            G: 0,
                            B: 0,
                        });
                    }
                }
                let webview = unsafe { controller.CoreWebView2()? };
                let state_msg = state_u.clone();
                let msg_handler = WebMessageReceivedEventHandler::create(Box::new(move |_, args| {
                    if let Some(args) = args {
                        let mut raw = PWSTR::null();
                        unsafe {
                            let _ = args.TryGetWebMessageAsString(&mut raw);
                            if !raw.is_null() {
                                let s = raw.to_string().unwrap_or_default();
                                if s.contains("\"menu\"") {
                                    state_msg.borrow_mut().ui_menu_open = s.contains("true");
                                } else if s.contains("\"nudge\"") {
                                    let mut st = state_msg.borrow_mut();
                                    st.browser_rect.x = if st.browser_rect.x > 120 { 40 } else { 180 };
                                    st.browser_rect.y = if st.browser_rect.y > 100 { 64 } else { 120 };
                                    st.update_browser_geometry();
                                }
                            }
                        }
                    }
                    Ok(())
                }));
                let mut token = 0i64;
                unsafe {
                    let _ = webview.add_WebMessageReceived(&msg_handler, &mut token);
                }

                let mut rect = RECT::default();
                unsafe {
                    let _ = GetClientRect(hwnd, &mut rect);
                }
                let mut st = state_u.borrow_mut();
                let visual = unsafe { st.dcomp.CreateVisual()? };
                unsafe {
                    comp.SetRootVisualTarget(&visual)?;
                    // AddVisual(..., true, browser_visual) 把 UI 放在 Browser 之上
                    let ref_vis = st.browser.as_ref().map(|b| &b.visual);
                    st.root_visual.AddVisual(&visual, true, ref_vis)?;
                    let _ = controller.SetIsVisible(true);
                    let _ = webview.NavigateToString(PCWSTR(
                        UI_HTML.encode_utf16().chain(Some(0)).collect::<Vec<_>>().as_ptr(),
                    ));
                }
                st.ui = Some(HostedWebView {
                    controller,
                    comp,
                    webview,
                    visual,
                });
                st.update_ui_geometry(rect.right - rect.left, rect.bottom - rect.top);
                Ok(())
            },
        ));
        unsafe {
            let _ = env3.CreateCoreWebView2CompositionController(hwnd, &u_handler);
        }
        Ok(())
    }));

    unsafe {
        let _ = CreateCoreWebView2EnvironmentWithOptions(None, None, None, &handler);
    }
}

unsafe extern "system" fn wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if msg == WM_CREATE {
        let cs = &*(lparam.0 as *const CREATESTRUCTW);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, cs.lpCreateParams as isize);
        return LRESULT(0);
    }
    let ptr = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const RefCell<LabState>;
    if !ptr.is_null() {
        let state = &*ptr;
        let x = (lparam.0 & 0xFFFF) as i16 as i32;
        let y = ((lparam.0 >> 16) & 0xFFFF) as i16 as i32;
        match msg {
            WM_SIZE => {
                let mut rect = RECT::default();
                let _ = GetClientRect(hwnd, &mut rect);
                state
                    .borrow()
                    .update_ui_geometry(rect.right - rect.left, rect.bottom - rect.top);
                return LRESULT(0);
            }
            WM_DPICHANGED => {
                let suggested = &*(lparam.0 as *const RECT);
                let _ = SetWindowPos(
                    hwnd,
                    None,
                    suggested.left,
                    suggested.top,
                    suggested.right - suggested.left,
                    suggested.bottom - suggested.top,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                );
                return LRESULT(0);
            }
            WM_MOUSEMOVE => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0200), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_LBUTTONDOWN => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0201), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_LBUTTONUP => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0202), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_RBUTTONDOWN => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0204), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_RBUTTONUP => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0205), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_MBUTTONDOWN => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0207), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_MBUTTONUP => {
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x0208), wparam, x, y, 0);
                return LRESULT(0);
            }
            WM_MOUSEWHEEL => {
                let delta = ((wparam.0 >> 16) & 0xFFFF) as i16 as i32 as u32;
                state
                    .borrow_mut()
                    .route_mouse(COREWEBVIEW2_MOUSE_EVENT_KIND(0x020A), wparam, x, y, delta);
                return LRESULT(0);
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                return LRESULT(0);
            }
            _ => {}
        }
    }
    DefWindowProcW(hwnd, msg, wparam, lparam)
}

fn main() -> windows::core::Result<()> {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let hinstance = GetModuleHandleW(None)?;
        let class_name = w!("SundayCompositionLabWindow");
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(wnd_proc),
            hInstance: hinstance.into(),
            hCursor: LoadCursorW(None, IDC_ARROW)?,
            lpszClassName: class_name,
            ..Default::default()
        };
        RegisterClassExW(&wc);

        let hwnd = CreateWindowExW(
            WS_EX_NOREDIRECTIONBITMAP,
            class_name,
            w!("Sunday WebView2 Composition Lab"),
            WS_OVERLAPPEDWINDOW,
            120,
            80,
            1060,
            720,
            None,
            None,
            Some(hinstance.into()),
            None,
        )?;

        let (dcomp, target, root_visual) = create_dcomp(hwnd)?;
        let state = Rc::new(RefCell::new(LabState {
            hwnd,
            dcomp,
            _target: target,
            root_visual,
            browser: None,
            ui: None,
            browser_rect: RectPx {
                x: 40,
                y: 64,
                w: 840,
                h: 560,
            },
            ui_overlay_rect: RectPx {
                x: 180,
                y: 54,
                w: 280,
                h: 160,
            },
            ui_menu_open: false,
            dragging_browser: false,
            drag_start_pt: POINT::default(),
            drag_start_rect: RectPx {
                x: 0,
                y: 0,
                w: 0,
                h: 0,
            },
        }));

        let raw_ptr = Rc::into_raw(state.clone());
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, raw_ptr as isize);
        let _ = ShowWindow(hwnd, SW_SHOW);
        let _ = SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE_DUMMY);

        init_webview2(state);

        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).into() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        let _ = Rc::from_raw(raw_ptr);
        CoUninitialize();
    }
    Ok(())
}

const SWP_NOSIZE_DUMMY: windows::Win32::UI::WindowsAndMessaging::SET_WINDOW_POS_FLAGS =
    windows::Win32::UI::WindowsAndMessaging::SWP_NOSIZE;
