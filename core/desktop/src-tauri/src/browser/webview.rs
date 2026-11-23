// user:“多标签 = 多个子 webview”+(创建、矩形、可见性、导航收敛在这层；bounds 由前端布局算，这里只执行)。
use tauri::{AppHandle, Manager};
#[cfg(not(windows))]
use tauri::Emitter;

use crate::browser::session::BrowserProfile;
#[cfg(not(windows))]
use crate::browser::tabs::label_for;
#[cfg(not(windows))]
use crate::browser::url_policy::allowed_navigation;
use crate::browser::BrowserError;
#[cfg(not(windows))]
use crate::browser::EVENT_PENDING_TAB;

/// user:“网页跑到分屏外面”+(坐标空间约定，写死在 browser 模块：
/// **前端一律传「物理像素」= CSS px × `window.devicePixelRatio`（在 native.ts 的 boundsArgs
/// 这一个入口换算）；Rust 一律用 `PhysicalPosition/PhysicalSize`，内部不再乘任何 DPI 系数。**
/// 原来的写法是前端传 CSS px、Rust 当 Logical 交给 tauri，一旦页面缩放（实测 dpr=1.85 而
/// 窗口 scale=1.25）两套比例就打架：网页会被放到 597×1.25=746 而不是 597×1.85=1104 的位置上，
/// 表现就是「不在分屏里、跑到别处、还偏小」)。
const OFFSCREEN_Y: f64 = -19000.0;
const MAX_EDGE: f64 = 20000.0;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Bounds {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub visible: bool,
}

impl Bounds {
    /// 新建标签的初始状态：1×1 离屏且不可见，等前端下发真实矩形。
    pub fn hidden() -> Self {
        Self { x: 0.0, y: OFFSCREEN_Y, width: 1.0, height: 1.0, visible: false }
    }

    // user:“网页不能跑到屏幕角落”+(允许负坐标用于离屏，但拒绝 NaN/无穷与离谱尺寸)。
    pub fn validated(x: f64, y: f64, width: f64, height: f64, visible: bool) -> Result<Self, BrowserError> {
        let values = [x, y, width, height];
        if !values.iter().all(|value| value.is_finite()) {
            return Err(BrowserError::invalid_bounds());
        }
        if width <= 0.0 || height <= 0.0 || width > MAX_EDGE || height > MAX_EDGE || x.abs() > MAX_EDGE || y.abs() > MAX_EDGE {
            return Err(BrowserError::invalid_bounds());
        }
        Ok(Self { x, y, width, height, visible })
    }
}

// user:“一个新模块，不要两套浏览器”+(子 webview 的 label 只能由 Rust 拼，前端传不进来)。
pub async fn create(
    app: &AppHandle,
    window: &tauri::Window,
    tab: &str,
    url: &url::Url,
    bounds: Bounds,
    profile: &BrowserProfile,
) -> Result<(), BrowserError> {
    #[cfg(windows)]
    {
        let bounds = Bounds::validated(bounds.x, bounds.y, bounds.width, bounds.height, bounds.visible)?;
        let app_data = app
            .path()
            .app_data_dir()
            .map_err(|error| BrowserError::internal(format!("无法定位应用数据目录：{error}")))?;
        let environment = profile.resolve(&app_data)?;
        let hwnd_raw = window
            .hwnd()
            .map_err(|error| BrowserError::internal(format!("拿不到主窗口句柄：{error}")))?
            .0 as isize;
        return crate::browser::compositor::create_tab(app, hwnd_raw, tab, url, bounds, environment).await;
    }
    #[cfg(not(windows))]
    {
        let _ = create_legacy(app, window, tab, url, bounds, profile)?;
        Ok(())
    }
}

#[cfg(not(windows))]
fn create_legacy(
    app: &AppHandle,
    window: &tauri::Window,
    tab: &str,
    url: &url::Url,
    bounds: Bounds,
    profile: &BrowserProfile,
) -> Result<tauri::Webview, BrowserError> {
    let label = label_for(tab).ok_or_else(BrowserError::tab_not_found)?;
    if app.get_webview(&label).is_some() {
        return Err(BrowserError::new("tab_exists", "这个浏览器标签已经打开", false));
    }
    let bounds = Bounds::validated(bounds.x, bounds.y, bounds.width, bounds.height, bounds.visible)?;
    // user:“失败后的降级方案需要重新批准，不自动接受 C”+(临时会话必须真隔离：normal/incognito/自定义目录三态先留好接缝，
    // M2 才实现；不得用创建后再改 profile 的方式，controller 创建后无法回填)。
    // user:“内置浏览器不能和主界面共用 profile”+(三态都要先算出目录：normal 走 `<app data>/webview2/browser`，
    // 临时会话走 InPrivate，自定义目录按参数落盘；一律在创建 controller 之前决定，创建之后无法回填)。
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| BrowserError::internal(format!("无法定位应用数据目录：{error}")))?;
    let environment = profile.resolve(&app_data)?;
    let load_app = app.clone();
    let load_tab = tab.to_string();
    let popup_app = app.clone();
    let popup_tab = tab.to_string();
    let nav_app = app.clone();
    let nav_tab = tab.to_string();
    let builder = tauri::WebviewBuilder::new(label, tauri::WebviewUrl::External(url.clone()))
        // user:“网页是不可信输入”+(顶层导航只放 http/https；其余协议在导航前挡掉并给出明确错误码)。
        .on_navigation(move |url| {
            if allowed_navigation(url) {
                return true;
            }
            // user:“tauri:// / asset:// / file:// 必须被拦截，且失败有明确错误码”+(不能静默白屏)。
            let _ = nav_app.emit_to(
                "main",
                super::EVENT_ERROR,
                super::ErrorPayload {
                    tab: nav_tab.clone(),
                    code: "blocked_scheme".to_string(),
                    message: format!("已阻止网页跳转到 {}: 链接", url.scheme()),
                    retriable: false,
                    host: Some(url.scheme().to_string()),
                },
            );
            false
        })
        .on_page_load(move |view, payload| {
            let loading = matches!(payload.event(), tauri::webview::PageLoadEvent::Started);
            let current = view.url().map(|url| url.to_string()).unwrap_or_default();
            let update = super::with_runtime(|rt| {
                if let Ok(state) = rt.tabs.get_mut(&load_tab) {
                    state.loading = loading;
                    if !current.is_empty() {
                        state.url = current.clone();
                    }
                    state.crashed = false;
                }
                Ok(())
            });
            if update.is_ok() {
                super::emit_state(&load_app, &load_tab);
            }
        })
        // user:“target=_blank 打开的是新标签而不是丢失”+(先拦下再决策：交给前端在同一个分屏开新标签)。
        .on_new_window(move |url, _features| {
            let payload = super::PendingTabPayload {
                tab: popup_tab.clone(),
                url: url.to_string(),
                opener: Some(popup_tab.clone()),
                // 用户发起的弹窗才算；页面脚本自动弹的也先拦下来，由前端决定是否打开。
                user_initiated: false,
            };
            let _ = popup_app.emit_to("main", EVENT_PENDING_TAB, payload);
            tauri::webview::NewWindowResponse::Deny
        });
    // user:“临时会话/自定义目录先留接缝”+(profile 只能在创建 controller 之前生效；创建之后的 controller 无法回填)。
    let builder = if let Some(dir) = environment.data_directory {
        builder.data_directory(dir)
    } else {
        builder
    };
    let builder = if environment.incognito { builder.incognito(true) } else { builder };
    // user:“注入一份固定的、可审计的桥脚本”+(每个新文档执行一次；脚本只做读结构/派发合成事件/滚动/
    // 上报真实输入，不含任意脚本执行能力。静态断言 tests/browser_security_assert.rs 会扫这份源码)。
    let builder = builder.initialization_script(crate::browser::bridge::BRIDGE_SCRIPT);
    // user:“下载唯一通道是 tauri 的 on_download”+(wry 默认已注册 DownloadStarting，这里替换而不是叠加；
    // 落盘路径必须在 Requested 阶段就定好，晚一步文件已经写到默认目录)。
    let download_app = app.clone();
    let download_tab = tab.to_string();
    let builder = builder.on_download(move |_webview, event| {
        match event {
            tauri::webview::DownloadEvent::Requested { url, destination } => {
                let Some(dir) = crate::browser::download_dir(&download_app) else {
                    return false;
                };
                let suggested = crate::browser::download::suggested_filename(url.as_str());
                let target = crate::browser::download::download_target(&dir, &suggested, |path| path.exists());
                *destination = target.clone();
                let now = crate::browser::security::iso_from_unix(
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|elapsed| elapsed.as_secs())
                        .unwrap_or(0),
                );
                crate::browser::record_download_started(&download_app, &download_tab, url.as_str(), &target, &now);
                true
            }
            tauri::webview::DownloadEvent::Finished { url, path, success } => {
                crate::browser::record_download_finished(&download_app, &download_tab, url.as_str(), path.as_deref(), success);
                true
            }
            _ => true,
        }
    });
    let view = window
        .add_child(
            builder,
            tauri::PhysicalPosition::new(bounds.x, bounds.y),
            tauri::PhysicalSize::new(bounds.width, bounds.height),
        )
        .map_err(|error| BrowserError::internal(format!("创建网页失败：{error}")))?;
    if !bounds.visible {
        let _ = view.hide();
    }
    // 平台事件（标题/历史/网页全屏）只在 Windows 上挂；失败不阻塞页面显示。
    crate::browser::platform_win::attach(app, tab, &view);
    // user:“唯一通道是注入桥 + WebMessage”+(注册 WebMessageReceived；失败只上报，页面照常可用，
    // 只是 Agent 指令会以 timeout 结束，不会静默降级成「看起来能操作」)。
    if let Err(error) = crate::browser::platform_win::attach_bridge(app, tab, &view) {
        let _ = app.emit_to(
            "main",
            super::EVENT_ERROR,
            super::ErrorPayload {
                tab: tab.to_string(),
                code: error.code.clone(),
                message: error.message.clone(),
                retriable: false,
                host: None,
            },
        );
    }
    Ok(view)
}

pub fn set_bounds(view: &tauri::Webview, bounds: Bounds) -> Result<(), BrowserError> {
    let bounds = Bounds::validated(bounds.x, bounds.y, bounds.width, bounds.height, bounds.visible)?;
    // user:“网页跑到分屏外面”+(坐标空间约定：进来的 x/y/width/height 已经是**物理像素**，
    // 这里直接用 Physical*，绝不再乘窗口 scale_factor)。
    view.set_position(tauri::PhysicalPosition::new(bounds.x, bounds.y))
        .map_err(|error| BrowserError::internal(format!("移动网页失败：{error}")))?;
    view.set_size(tauri::PhysicalSize::new(bounds.width, bounds.height))
        .map_err(|error| BrowserError::internal(format!("调整网页尺寸失败：{error}")))?;
    // user:“切换标签时先 show 新页再 hide 旧页”+(顺序由调用方保证，这里只做单次可见性切换)。
    if bounds.visible {
        view.show()
    } else {
        view.hide()
    }
    .map_err(|error| BrowserError::internal(format!("切换网页可见性失败：{error}")))
}

/// 非活动标签：隐藏并挪出可视区，防止「隐藏失败仍可见」时盖住活动页。
///
/// user:“未确认期间采取保守策略”+(P2 待验证项：后台标签的 rAF / setInterval / 后台视频 / TrySuspend /
/// 隐藏页 ExecuteScript 的真实行为都还没证实，所以这里**不启用 TrySuspend**（wry 0.55.1 全 crate 也无此调用），
/// 也不把「后台计时器继续跑」当作任何实现前提；未来 Agent 操作后台标签一律「临时显示该标签 → 操作 → 切回」)。
pub fn hide_offscreen(view: &tauri::Webview) -> Result<(), BrowserError> {
    let _ = view.hide();
    view.set_position(tauri::PhysicalPosition::new(0.0, OFFSCREEN_Y))
        .map_err(|error| BrowserError::internal(format!("移动后台网页失败：{error}")))
}

pub fn navigate(view: &tauri::Webview, url: &url::Url) -> Result<(), BrowserError> {
    view.navigate(url.clone())
        .map_err(|error| BrowserError::internal(format!("打开网页失败：{error}")))
}

pub fn reload(view: &tauri::Webview) -> Result<(), BrowserError> {
    view.reload()
        .map_err(|error| BrowserError::internal(format!("刷新失败：{error}")))
}

// user:“Ctrl+F 能高亮”+(首版用注入脚本实现：Highlight API 高亮、命中计数、上下跳转；接口固定，后续可换原生实现)。
pub fn find_script(action: &str, query: Option<&str>, match_case: bool) -> Result<String, BrowserError> {
    if !matches!(action, "start" | "next" | "prev" | "stop") {
        return Err(BrowserError::new("unsupported", format!("未知查找动作：{action}"), false));
    }
    let query = serde_json::to_string(query.unwrap_or_default())
        .map_err(|error| BrowserError::internal(format!("查找词无法序列化：{error}")))?;
    let action = serde_json::to_string(action)
        .map_err(|error| BrowserError::internal(format!("查找动作无法序列化：{error}")))?;
    Ok(format!(
        r#"(() => {{
  const KEY = '__sundayFind';
  const action = {action};
  const query = {query};
  const matchCase = {match_case};
  let state = window[KEY];
  const reply = () => JSON.stringify({{ matches: state ? state.ranges.length : 0, index: state ? state.index : -1 }});
  if (action === 'stop') {{
    if (state) {{ try {{ CSS.highlights.delete('sunday-find'); }} catch (e) {{}} window[KEY] = null; }}
    return JSON.stringify({{ matches: 0, index: -1 }});
  }}
  if (!state || state.query !== query || state.matchCase !== matchCase) {{
    const ranges = [];
    if (query) {{
      const root = document.body || document.documentElement;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const needle = matchCase ? query : query.toLowerCase();
      let node;
      while ((node = walker.nextNode())) {{
        const parent = node.parentElement;
        if (!parent || parent.closest('script,style,noscript,textarea')) continue;
        const text = matchCase ? (node.textContent || '') : (node.textContent || '').toLowerCase();
        let from = 0, at;
        while ((at = text.indexOf(needle, from)) >= 0) {{
          const range = document.createRange();
          range.setStart(node, at);
          range.setEnd(node, at + needle.length);
          ranges.push(range);
          from = at + Math.max(1, needle.length);
        }}
      }}
    }}
    state = window[KEY] = {{ ranges, index: -1, query, matchCase }};
  }}
  if (!state.ranges.length) return reply();
  if (action === 'start') state.index = 0;
  else if (action === 'next') state.index = (state.index + 1) % state.ranges.length;
  else if (action === 'prev') state.index = (state.index - 1 + state.ranges.length) % state.ranges.length;
  try {{
    if (!document.getElementById('sunday-find-style')) {{
      const style = document.createElement('style');
      style.id = 'sunday-find-style';
      style.textContent = '::highlight(sunday-find){{background-color:rgba(255,214,10,.85);color:#111}}';
      (document.head || document.documentElement).appendChild(style);
    }}
    CSS.highlights.set('sunday-find', new Highlight(...state.ranges));
    const current = state.ranges[state.index];
    const rect = current.getBoundingClientRect();
    if (rect && (rect.top < 0 || rect.bottom > window.innerHeight)) {{
      window.scrollBy(0, rect.top - window.innerHeight / 3);
    }}
  }} catch (e) {{}}
  return reply();
}})()"#
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 一块典型屏幕：逻辑左上角 + 逻辑宽高。
    struct Screen {
        x: f64,
        y: f64,
        width: f64,
        height: f64,
    }

    /// user:“网页区域无效”+(用主流双屏布局当判定基准：1080p 在原点，1440p 接在它右边)。
    fn typical_screens() -> Vec<Screen> {
        vec![
            Screen { x: 0.0, y: 0.0, width: 1920.0, height: 1080.0 },
            Screen { x: 1920.0, y: 0.0, width: 2560.0, height: 1440.0 },
        ]
    }

    fn intersects(bounds: &Bounds, screen: &Screen) -> bool {
        let right = bounds.x + bounds.width;
        let bottom = bounds.y + bounds.height;
        let screen_right = screen.x + screen.width;
        let screen_bottom = screen.y + screen.height;
        bounds.x < screen_right && right > screen.x && bounds.y < screen_bottom && bottom > screen.y
    }

    /// user:“网页根本建不出来”+(创建标签第一件事就是把 hidden 交给 validated，
    /// 这条断言就是「每次开网页都失败」的直接守卫：两个常量一旦打架立刻红)。
    #[test]
    fn hidden_bounds_pass_validation() {
        let hidden = Bounds::hidden();
        let validated = Bounds::validated(hidden.x, hidden.y, hidden.width, hidden.height, hidden.visible);
        assert!(
            validated.is_ok(),
            "Bounds::hidden() 必须能通过 validated()，否则 browser_open 必失败；当前 y={}，MAX_EDGE={}",
            hidden.y,
            MAX_EDGE
        );
        assert!(
            OFFSCREEN_Y.abs() <= MAX_EDGE,
            "OFFSCREEN_Y({}) 必须落在 ±MAX_EDGE({}) 之内，两个常量不得互相打架",
            OFFSCREEN_Y,
            MAX_EDGE
        );
    }

    /// user:“隐藏标签挪出屏幕”+(把网页移到所有常规屏幕之外，是为了 IsVisible=false 失效时也不叠在活动页上)。
    #[test]
    fn hidden_bounds_stay_off_every_screen() {
        let hidden = Bounds::hidden();
        for screen in typical_screens() {
            assert!(
                !intersects(&hidden, &screen),
                "隐藏矩形不能与屏幕相交：hidden=({}, {}, {}×{})，screen=({}, {}, {}×{})",
                hidden.x,
                hidden.y,
                hidden.width,
                hidden.height,
                screen.x,
                screen.y,
                screen.width,
                screen.height
            );
        }
    }

    /// user:“不改产品行为语义，except 这个常量本身”+(放宽 OFFSCREEN_Y 不能顺手削弱对前端乱值的拦截)。
    #[test]
    fn out_of_range_bounds_are_still_rejected() {
        let error = Bounds::validated(0.0, -30000.0, 1.0, 1.0, false)
            .expect_err("y=-30000 仍然必须被拒，拦截能力不能被削弱");
        assert_eq!(error.code, "invalid_bounds");
        assert_eq!(
            Bounds::validated(0.0, 0.0, MAX_EDGE + 1.0, 100.0, true).expect_err("超大宽度必须被拒").code,
            "invalid_bounds"
        );
        assert_eq!(
            Bounds::validated(0.0, 0.0, 0.0, 100.0, true).expect_err("零宽度必须被拒").code,
            "invalid_bounds"
        );
        assert_eq!(
            Bounds::validated(f64::NAN, 0.0, 10.0, 10.0, true).expect_err("NaN 必须被拒").code,
            "invalid_bounds"
        );
    }
}
