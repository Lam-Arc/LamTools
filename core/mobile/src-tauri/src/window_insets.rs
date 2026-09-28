use serde::{Deserialize, Serialize};
use tauri::{plugin::PluginHandle, Runtime};

pub struct MobileWindowInsets<R: Runtime>(pub PluginHandle<R>);

#[derive(Debug, Deserialize, Serialize)]
pub struct WindowInsetsResponse {
    pub top: f64,
    /// Height of the on-screen keyboard in CSS pixels; 0 while it is closed.
    /// `default` keeps an older Android plugin (which does not report it) from
    /// failing the whole read.
    #[serde(rename = "imeBottom", default)]
    pub ime_bottom: f64,
}

#[tauri::command]
pub fn window_insets_get(
    insets: tauri::State<'_, MobileWindowInsets<tauri::Wry>>,
) -> Result<WindowInsetsResponse, String> {
    insets
        .0
        .run_mobile_plugin::<WindowInsetsResponse>("get", serde_json::json!({}))
        .map_err(|error| error.to_string())
}
