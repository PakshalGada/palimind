// lib.rs — placeholder for future Tauri command handlers.
// Commands are registered in main.rs via .invoke_handler().

/// Returns a greeting — used for IPC health testing.
pub fn ping() -> &'static str {
    "pong"
}
