//! State-root and command-context setup.
//!
//! The vendored engine derives its state root from `AGENT_DESKTOP_HOME` and
//! otherwise falls back to `~/.agent-desktop`. Palimind owns a different
//! directory: `~/.palimind/desktop` (overridable with `PALIMIND_DESKTOP_HOME`).
//! We set the engine's override before the first engine call so snapshots,
//! refs and sessions land in the Palimind tree, never in the upstream one.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use agent_desktop_core::{AppError, CommandContext};

pub const DEFAULT_SESSION: &str = "palimind";

pub fn desktop_home() -> PathBuf {
    if let Ok(value) = std::env::var("PALIMIND_DESKTOP_HOME")
        && !value.trim().is_empty()
    {
        return PathBuf::from(value);
    }
    if let Ok(value) = std::env::var("HOME") {
        return PathBuf::from(value).join(".palimind").join("desktop");
    }
    PathBuf::from(".palimind/desktop")
}

/// Point the engine at the Palimind state root and create it 0700.
pub fn init() -> Result<(), String> {
    let home = desktop_home();
    if std::env::var_os("AGENT_DESKTOP_HOME").is_none() {
        // SAFETY: this runs before the engine starts any thread or reads the
        // variable. Palimind is the only writer of its own process env here.
        unsafe { std::env::set_var("AGENT_DESKTOP_HOME", &home) };
    }
    for dir in [&home, &home.join("sessions"), &home.join("artifacts")] {
        fs::create_dir_all(dir)
            .map_err(|error| format!("cannot create {}: {error}", dir.display()))?;
        let _ = fs::set_permissions(dir, fs::Permissions::from_mode(0o700));
    }
    Ok(())
}

pub fn session_id(explicit: Option<&str>) -> String {
    explicit
        .map(str::to_owned)
        .or_else(|| std::env::var("PALIMIND_DESKTOP_SESSION").ok())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_SESSION.to_owned())
}

pub fn context(headed: bool, session: Option<&str>) -> Result<CommandContext, AppError> {
    let id = session_id(session);
    CommandContext::new(Some(id), None, false).map(|context| context.with_headed(headed))
}

/// Create a real, on-disk session manifest. The daemon uses this so traces and
/// a `session list` entry exist; the one-shot CLI deliberately keeps using the
/// stable session id without a manifest so refs survive between invocations.
pub fn start_session(name: &str) -> Result<String, AppError> {
    let manifest = agent_desktop_core::session::start_session(
        agent_desktop_core::session::StartSessionOptions {
            name: Some(name.to_owned()),
            trace: agent_desktop_core::session::SessionTraceMode::On,
            artifacts: agent_desktop_core::session::ArtifactsMode::Events,
        },
    )?;
    Ok(manifest.id)
}
