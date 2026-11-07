// Palimind: runtime windows for computer use.
//
// The popup and the region overlay are created at runtime (not statically in
// tauri.conf.json) so they point at the actual backend port chosen by the
// launcher and so the overlay can be created only while selecting a region.
//
// Linux-only product surface: no Windows/macOS branches here.

use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use tauri::{
    AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder,
};

/// The backend base URL, installed as managed state at startup.
pub struct ApiBase(pub String);

const POPUP_LABEL: &str = "computer-use";
const OVERLAY_LABEL: &str = "region-overlay";
const GHOST_LABEL: &str = "cursor-ghost";

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct GhostCursor {
    pub x: f64,
    pub y: f64,
    #[serde(default)]
    pub width: Option<f64>,
    #[serde(default)]
    pub height: Option<f64>,
    #[serde(default)]
    pub label: Option<String>,
}

fn ghost_url(api_base: &str, cursor: &GhostCursor) -> Result<WebviewUrl, String> {
    let mut raw = format!(
        "{api_base}/ui?window=cursor-ghost&x={}&y={}",
        cursor.x, cursor.y
    );
    if let Some(width) = cursor.width {
        raw.push_str(&format!("&w={width}"));
    }
    if let Some(height) = cursor.height {
        raw.push_str(&format!("&h={height}"));
    }
    if let Some(label) = &cursor.label {
        raw.push_str("&label=");
        raw.push_str(&url_encode(label));
    }
    raw.parse::<tauri::Url>()
        .map(WebviewUrl::External)
        .map_err(|error| format!("invalid ghost-cursor URL {raw}: {error}"))
}

fn url_encode(value: &str) -> String {
    let mut out = String::new();
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

/// Show a click-through highlight/crosshair at a target point or rectangle.
/// This never moves the real pointer; it is a visual hint for the user while
/// the agent acts (or after a region selection).
#[tauri::command]
pub fn show_ghost_cursor(
    app: AppHandle,
    base: State<'_, ApiBase>,
    cursor: GhostCursor,
) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(GHOST_LABEL) {
        let _ = app.emit_to(GHOST_LABEL, "palimind:ghost-cursor", &cursor);
        let _ = window.show();
        return Ok(());
    }
    let url = ghost_url(&base.0, &cursor)?;
    let window = WebviewWindowBuilder::new(&app, GHOST_LABEL, url)
        .title("Palimind cursor hint")
        .fullscreen(true)
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .visible(true)
        .build()
        .map_err(|error| error.to_string())?;
    // The hint must never intercept a real click intended for the app.
    if let Err(error) = window.set_ignore_cursor_events(true) {
        eprintln!("[Palimind] ghost cursor cannot ignore pointer events: {error}");
    }
    let _ = app.emit_to(GHOST_LABEL, "palimind:ghost-cursor", &cursor);
    Ok(())
}

#[tauri::command]
pub fn hide_ghost_cursor(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(GHOST_LABEL) {
        window.close().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn webview_url(api_base: &str, window: &str) -> Result<WebviewUrl, String> {
    let raw = format!("{api_base}/ui?window={window}");
    raw.parse::<tauri::Url>()
        .map(WebviewUrl::External)
        .map_err(|error| format!("invalid computer-use URL {raw}: {error}"))
}

pub fn open_popup(app: &AppHandle, api_base: &str) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(POPUP_LABEL) {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    let url = webview_url(api_base, "computer-use")?;
    let builder = WebviewWindowBuilder::new(app, POPUP_LABEL, url)
        .title("Computer Use")
        .inner_size(470.0, 720.0)
        .min_inner_size(390.0, 560.0)
        .resizable(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .visible(true);

    // Bottom-right of the primary monitor when the compositor exposes one.
    // Always-on-top is a request: some Wayland compositors ignore it, in which
    // case the tray item and hotkey remain the fallback.
    let builder = if let Ok(Some(monitor)) = app.primary_monitor() {
        let size = monitor.size().to_logical::<f64>(monitor.scale_factor());
        let position = monitor.position().to_logical::<f64>(monitor.scale_factor());
        builder.position(position.x + size.width - 490.0, position.y + 40.0)
    } else {
        builder
    };
    builder
        .build()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub fn open_computer_use(app: AppHandle, base: State<'_, ApiBase>) -> Result<(), String> {
    open_popup(&app, &base.0)
}

#[tauri::command]
pub fn hide_computer_use(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(POPUP_LABEL) {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn show_region_overlay(app: AppHandle, base: State<'_, ApiBase>) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }
    let url = webview_url(&base.0, "region-overlay")?;
    WebviewWindowBuilder::new(&app, OVERLAY_LABEL, url)
        .title("Select screen area")
        .fullscreen(true)
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(true)
        .visible(true)
        .build()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub fn hide_region_overlay(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_LABEL) {
        window.close().map_err(|error| error.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn focus_main_window(app: AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Read the per-install API token so the Stop hotkey works without the popup
/// being open. The token is the same 0600 file the backend uses.
fn api_token() -> Option<String> {
    let home = std::env::var("PALIMIND_HOME")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var("HOME")
                .ok()
                .map(|home| PathBuf::from(home).join(".palimind"))
        })?;
    fs::read_to_string(home.join("api_token"))
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

/// Panic stop for computer use: ask the backend to stop and release input.
/// Emits an event so every open UI surface can update its banner.
pub fn stop_desktop_control(app: &AppHandle, api_base: &str) {
    let mut request =
        ureq::post(&format!("{api_base}/api/desktop/stop")).timeout(Duration::from_secs(3));
    if let Some(token) = api_token() {
        request = request.set("Authorization", &format!("Bearer {token}"));
    }
    match request.send_string("{}") {
        Ok(_) => {
            let _ = app.emit("palimind:desktop-stop", ());
        }
        Err(error) => {
            eprintln!("[Palimind] desktop stop request failed: {error}");
        }
    }
}

#[tauri::command]
pub fn stop_computer_use(app: AppHandle, base: State<'_, ApiBase>) -> Result<(), String> {
    stop_desktop_control(&app, &base.0);
    Ok(())
}


pub fn hotkey_stop(app: &AppHandle) {
    let base = app.state::<ApiBase>().0.clone();
    stop_desktop_control(app, &base);
}
