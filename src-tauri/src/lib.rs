use std::sync::{Arc, Mutex};

use log::info;
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::ShellExt;

mod sidecar;

use sidecar::{
    monitor_sidecar, shutdown_sidecar, spawn_sidecar, wait_for_healthy, SharedSidecarState,
    SidecarState,
};

/// Tauri IPC command: open a native folder picker dialog.
/// Called from frontend JS via: invoke('pick_folder')
/// Replaces the old tkinter subprocess approach.
#[tauri::command]
async fn pick_folder(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let folder = app
        .dialog()
        .file()
        .set_title("Select a workspace folder for Palimind")
        .blocking_pick_folder();
    Ok(folder.map(|p| p.to_string_lossy().to_string()))
}

/// Tauri IPC command: get the current sidecar port.
/// Frontend uses this to know which localhost port to talk to.
#[tauri::command]
fn get_sidecar_port(state: tauri::State<SharedSidecarState>) -> Option<u16> {
    state.lock().unwrap().port
}

/// Tauri IPC command: get the per-session localhost API auth token.
#[tauri::command]
fn get_auth_token(state: tauri::State<SharedSidecarState>) -> Option<String> {
    state.lock().unwrap().auth_token.clone()
}

/// Tauri IPC command: get app version.
#[tauri::command]
fn get_app_version(app: AppHandle) -> String {
    app.package_info().version.to_string()
}

/// Tauri IPC command: open a URL in the system browser.
#[tauri::command]
async fn open_external(app: AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_shell::ShellExt;
    app.shell().open(&url, None).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let sidecar_state: SharedSidecarState = Arc::new(Mutex::new(SidecarState::default()));
    let sidecar_state_clone = sidecar_state.clone();

    tauri::Builder::default()
        // ── Plugins ────────────────────────────────────────────────────────
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_process::init())
        // ── Shared state ───────────────────────────────────────────────────
        .manage(sidecar_state)
        // ── IPC commands ───────────────────────────────────────────────────
        .invoke_handler(tauri::generate_handler![
            pick_folder,
            get_sidecar_port,
            get_auth_token,
            get_app_version,
            open_external,
        ])
        // ── Setup: runs once before any window is shown ────────────────────
        .setup(move |app| {
            let app_handle = app.handle().clone();
            let state = sidecar_state_clone.clone();

            // Spawn the full startup sequence in a background async task
            tauri::async_runtime::spawn(async move {
                run_startup_sequence(app_handle, state).await;
            });

            Ok(())
        })
        // ── Run loop ───────────────────────────────────────────────────────
        .build(tauri::generate_context!())
        .expect("Failed to build Tauri application")
        .run(move |app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Graceful shutdown when the window is closed
                let state = app_handle.state::<SharedSidecarState>();
                let port = state.lock().unwrap().port;
                let state_clone = state.inner().clone();

                tauri::async_runtime::block_on(async move {
                    info!("App exiting — shutting down sidecar...");
                    shutdown_sidecar(&state_clone, port).await;
                });
            }
        });
}

/// Full startup sequence:
/// 1. Emit progress events to splash screen
/// 2. Spawn sidecar
/// 3. Poll health
/// 4. Check Ollama availability
/// 5. Show main window, hide splash
/// 6. Start background health monitor
async fn run_startup_sequence(app: AppHandle, state: SharedSidecarState) {
    // Stage 1: Initialising
    let _ = app.emit(
        "startup-progress",
        serde_json::json!({
            "stage": "init", "progress": 5, "message": "Starting Palimind..."
        }),
    );
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;

    // Stage 2: Spawn sidecar
    let _ = app.emit(
        "startup-progress",
        serde_json::json!({
            "stage": "spawning", "progress": 20, "message": "Starting AI engine..."
        }),
    );

    let port = match spawn_sidecar(&app, &state).await {
        Ok(p) => p,
        Err(e) => {
            let _ = app.emit(
                "startup-error",
                serde_json::json!({
                    "message": format!("Failed to start AI engine: {}", e),
                    "fatal": true
                }),
            );
            return;
        }
    };

    // Stage 3: Wait for health (up to 40 seconds)
    let _ = app.emit(
        "startup-progress",
        serde_json::json!({
            "stage": "health_checking", "progress": 25, "message": "Initializing backend..."
        }),
    );

    if let Err(e) = wait_for_healthy(&app, port, 40).await {
        let _ = app.emit(
            "startup-error",
            serde_json::json!({
                "message": e,
                "fatal": false
            }),
        );
        // Don't return — show the window anyway so user can retry
    }

    // Stage 4: Check Ollama
    let _ = app.emit(
        "startup-progress",
        serde_json::json!({
            "stage": "ollama_check", "progress": 80, "message": "Connecting to Ollama..."
        }),
    );

    let auth_token = {
        let s = state.lock().unwrap();
        s.auth_token.clone()
    };
    let ollama_ok = check_ollama(port, auth_token).await;
    let _ = app.emit("startup-progress", serde_json::json!({
        "stage": "ollama_done",
        "progress": 90,
        "message": if ollama_ok { "Ollama connected" } else { "Ollama not found (degraded mode)" },
        "ollama_available": ollama_ok
    }));

    tokio::time::sleep(std::time::Duration::from_millis(400)).await;

    // Stage 5: Ready — show main window, redirect to app
    let _ = app.emit(
        "startup-progress",
        serde_json::json!({
            "stage": "ready", "progress": 100,
            "message": "Ready",
            "port": port,
            "ollama_available": ollama_ok
        }),
    );

    tokio::time::sleep(std::time::Duration::from_millis(300)).await;

    // Navigate the main window to the actual app UI
    if let Some(window) = app.get_webview_window("main") {
        let app_url = format!("http://127.0.0.1:{}/ui/", port);
        let _ = window.navigate(app_url.parse().expect("Invalid app URL"));
        let _ = window.show();
        let _ = window.set_focus();
    }

    info!("Startup complete — Palimind running on port {}", port);

    // Stage 6: Background health monitor
    tauri::async_runtime::spawn(monitor_sidecar(app, state));
}

/// Quick check if Ollama is running by hitting the local FastAPI /api/models proxy.
async fn check_ollama(port: u16, auth_token: Option<String>) -> bool {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .unwrap();
    let mut req = client.get(format!("http://127.0.0.1:{}/api/models", port));
    if let Some(token) = auth_token {
        req = req.bearer_auth(token);
    }
    req.send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}
