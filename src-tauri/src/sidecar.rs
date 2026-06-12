use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use log::{error, info, warn};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Shared sidecar state, wrapped in Arc<Mutex> for thread-safe access.
#[derive(Default)]
pub struct SidecarState {
    pub port: Option<u16>,
    pub child: Option<CommandChild>,
    pub restart_count: u32,
    pub auth_token: Option<String>,
    pub dev_mode: bool,
}

pub type SharedSidecarState = Arc<Mutex<SidecarState>>;

/// Find a free TCP port in the range 8000–8099.
/// Returns the first available port, or 8000 if none found.
pub fn find_free_port() -> u16 {
    for port in 8000u16..8100 {
        if TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return port;
        }
    }
    8000
}

/// Generate a high-entropy token for localhost API calls.
pub fn generate_auth_token() -> String {
    format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    )
}

/// Kill any process that is already listening on the given port.
/// Uses `netstat` on Windows to find and terminate the stale process.
pub fn kill_stale_on_port(port: u16) {
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;

        // Find PID using netstat
        let output = Command::new("cmd")
            .args([
                "/C",
                &format!(
                    "for /f \"tokens=5\" %a in ('netstat -aon ^| findstr :{} ^| findstr LISTENING') do @echo %a",
                    port
                ),
            ])
            .output();

        if let Ok(out) = output {
            let pid_str = String::from_utf8_lossy(&out.stdout).trim().to_string();
            if let Ok(pid) = pid_str.parse::<u32>() {
                if pid > 0 {
                    info!("Killing stale process {} on port {}", pid, port);
                    let _ = Command::new("taskkill")
                        .args(["/PID", &pid.to_string(), "/F"])
                        .output();
                    std::thread::sleep(Duration::from_millis(500));
                }
            }
        }
    }
}

/// Spawn the Palimind FastAPI sidecar process.
///
/// The sidecar binary is named `palimind-server` and must exist at
/// `src-tauri/binaries/palimind-server-<target-triple>.exe`.
///
/// Returns the port the sidecar is listening on.
pub async fn spawn_sidecar(app: &AppHandle, state: &SharedSidecarState) -> Result<u16, String> {
    if let Ok(dev_port) = std::env::var("PALIMIND_DEV_PORT") {
        let port = dev_port
            .parse::<u16>()
            .map_err(|e| format!("Invalid PALIMIND_DEV_PORT '{}': {}", dev_port, e))?;
        attach_to_dev_server(state, port);
        return Ok(port);
    }

    #[cfg(debug_assertions)]
    {
        const DEFAULT_DEV_PORT: u16 = 8000;
        if is_dev_server_alive(DEFAULT_DEV_PORT).await {
            attach_to_dev_server(state, DEFAULT_DEV_PORT);
            return Ok(DEFAULT_DEV_PORT);
        }
    }

    let port = find_free_port();
    info!("Starting Palimind sidecar on port {}", port);

    // Kill anything stale before we try to bind
    kill_stale_on_port(port);

    // Determine log file path in AppData
    let log_path = app
        .path()
        .app_log_dir()
        .map(|p| p.join("palimind-server.log"))
        .ok();

    let auth_token = {
        let mut s = state.lock().unwrap();
        match &s.auth_token {
            Some(token) => token.clone(),
            None => {
                let token = generate_auth_token();
                s.auth_token = Some(token.clone());
                token
            }
        }
    };

    let mut cmd = app
        .shell()
        .sidecar("palimind-server")
        .map_err(|e| format!("Failed to find sidecar binary: {}", e))?
        .args(["--port", &port.to_string()]);

    if let Some(ref log_file) = log_path {
        cmd = cmd.args(["--log-file", &log_file.to_string_lossy()]);
    }

    // Set environment variables for UTF-8 output and local API auth.
    cmd = cmd
        .env("PYTHONUTF8", "1")
        .env("PALIMIND_AUTH_TOKEN", auth_token);

    let (_rx, child) = cmd
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar: {}", e))?;

    {
        let mut s = state.lock().unwrap();
        s.port = Some(port);
        s.child = Some(child);
        s.dev_mode = false;
    }

    info!("Sidecar spawned on port {}", port);
    Ok(port)
}

fn attach_to_dev_server(state: &SharedSidecarState, port: u16) {
    info!("Using existing Palimind dev server on port {}", port);
    let mut s = state.lock().unwrap();
    s.port = Some(port);
    s.child = None;
    s.dev_mode = true;
}

async fn is_dev_server_alive(port: u16) -> bool {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(client) => client,
        Err(_) => return false,
    };

    client
        .get(format!("http://127.0.0.1:{}/health", port))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

/// Wait until the sidecar's /health endpoint responds with 200 OK.
///
/// Polls every 1 second for up to `max_attempts` seconds.
/// Emits "startup-progress" events to the frontend during the wait.
pub async fn wait_for_healthy(app: &AppHandle, port: u16, max_attempts: u32) -> Result<(), String> {
    let health_url = format!("http://127.0.0.1:{}/health", port);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;

    for attempt in 1..=max_attempts {
        tokio::time::sleep(Duration::from_secs(1)).await;

        match client.get(&health_url).send().await {
            Ok(resp) if resp.status().is_success() => {
                info!("Sidecar is healthy after {} attempts", attempt);
                let _ = app.emit(
                    "startup-progress",
                    serde_json::json!({
                        "stage": "backend_ready",
                        "progress": 70,
                        "message": "AI engine ready"
                    }),
                );
                return Ok(());
            }
            _ => {
                let progress = 25 + (attempt * 45 / max_attempts);
                let _ = app.emit(
                    "startup-progress",
                    serde_json::json!({
                        "stage": "health_checking",
                        "progress": progress,
                        "message": format!("Starting AI engine... ({}/{})", attempt, max_attempts),
                        "attempt": attempt
                    }),
                );
            }
        }
    }

    Err(format!(
        "Sidecar did not become healthy after {} seconds. Check logs at AppData/Palimind/logs/",
        max_attempts
    ))
}

/// Gracefully shut down the sidecar.
///
/// Attempts a POST /shutdown first, then force-kills after 5 seconds.
pub async fn shutdown_sidecar(state: &SharedSidecarState, port: Option<u16>) {
    let dev_mode = {
        let s = state.lock().unwrap();
        s.dev_mode
    };
    if dev_mode {
        info!("Leaving manually-started dev server running");
        return;
    }

    // Try graceful shutdown via HTTP
    if let Some(port) = port {
        let client = reqwest::Client::new();
        let url = format!("http://127.0.0.1:{}/shutdown", port);
        let auth_token = {
            let s = state.lock().unwrap();
            s.auth_token.clone()
        };
        let mut req = client.post(&url);
        if let Some(token) = auth_token {
            req = req.bearer_auth(token);
        }
        let _ = tokio::time::timeout(Duration::from_secs(3), req.send()).await;
    }

    // Force kill if still running
    let child = {
        let mut s = state.lock().unwrap();
        s.child.take()
    };

    if let Some(mut child) = child {
        std::thread::sleep(Duration::from_secs(2));
        if let Err(e) = child.kill() {
            warn!("Failed to kill sidecar (may have already exited): {}", e);
        } else {
            info!("Sidecar process terminated");
        }
    }
}

/// Background health monitor — polls every 10 seconds.
///
/// If the sidecar stops responding, attempts to restart it (max 3 times per minute).
/// Emits "sidecar-status" events to the frontend.
pub async fn monitor_sidecar(app: AppHandle, state: SharedSidecarState) {
    const POLL_INTERVAL_SECS: u64 = 10;
    const MAX_RESTARTS_PER_CYCLE: u32 = 3;

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .expect("Failed to build reqwest client");

    loop {
        tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;

        let port = {
            let s = state.lock().unwrap();
            s.port
        };

        let Some(port) = port else {
            continue; // Not yet started
        };

        let health_url = format!("http://127.0.0.1:{}/health", port);
        let is_healthy = client
            .get(&health_url)
            .send()
            .await
            .map(|r| r.status().is_success())
            .unwrap_or(false);

        if is_healthy {
            // All good — nothing to do
            continue;
        }

        // Sidecar is down
        warn!(
            "Sidecar health check failed on port {}. Attempting restart...",
            port
        );
        let _ = app.emit(
            "sidecar-status",
            serde_json::json!({
                "status": "down",
                "message": "Reconnecting to AI engine..."
            }),
        );

        // Check restart count
        let restart_count = {
            let s = state.lock().unwrap();
            if s.dev_mode {
                let _ = app.emit(
                    "sidecar-status",
                    serde_json::json!({
                        "status": "fatal",
                        "message": "The dev backend stopped. Restart scripts/dev.ps1."
                    }),
                );
                break;
            }
            s.restart_count
        };

        if restart_count >= MAX_RESTARTS_PER_CYCLE {
            error!(
                "Sidecar crashed {} times. Giving up auto-restart.",
                restart_count
            );
            let _ = app.emit(
                "sidecar-status",
                serde_json::json!({
                    "status": "fatal",
                    "message": "AI engine failed to restart. Please restart Palimind."
                }),
            );
            break;
        }

        // Increment restart counter
        {
            let mut s = state.lock().unwrap();
            s.restart_count += 1;
        }

        // Attempt restart
        match spawn_sidecar(&app, &state).await {
            Ok(new_port) => match wait_for_healthy(&app, new_port, 20).await {
                Ok(()) => {
                    info!("Sidecar successfully restarted on port {}", new_port);
                    let _ = app.emit(
                        "sidecar-status",
                        serde_json::json!({
                            "status": "restored",
                            "port": new_port,
                            "message": "AI engine reconnected"
                        }),
                    );
                }
                Err(e) => {
                    error!("Restarted sidecar failed health check: {}", e);
                }
            },
            Err(e) => {
                error!("Failed to restart sidecar: {}", e);
            }
        }
    }
}
