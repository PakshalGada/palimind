//! Palimind policy enforced at the native boundary.
//!
//! The engine (vendored agent-desktop) already refuses protected processes and
//! redacts secure fields. This module adds the product policy the plan calls
//! for and keeps it *outside* the prompt: an app allow/block list, a hard
//! protected-app set, an append-only audit log that never stores typed text,
//! an action rate limit, artifact retention, and one machine-wide stop flag.

use std::collections::VecDeque;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use serde_json::{Value, json};

/// Processes Palimind must never observe or control, even when the user names
/// them in an allowlist. These are the desktop shell, session managers, auth
/// agents, keyrings and lock screens named in the plan (section 8).
pub const PROTECTED_APPS: &[&str] = &[
    "gnome-shell",
    "org.gnome.shell",
    // GNOME Shell's own UI process is exposed on the accessibility bus as
    // gjs-console. Treat it as the shell, not as a user application.
    "gjs-console",
    "plasmashell",
    "plasma-desktop",
    "kwin",
    "kwin_wayland",
    "kwin_x11",
    "mutter",
    "gnome-settings-daemon",
    "gsd-",
    "gnome-session",
    "gnome-session-binary",
    "systemd",
    "polkit",
    "polkit-gnome",
    "gnome-keyring",
    "gnome-keyring-daemon",
    "kwallet",
    "kwalletd",
    "kwalletd5",
    "kwalletd6",
    "gnome-screensaver",
    "xscreensaver",
    "swaylock",
    "hyprlock",
    "palimind",
    "palimind-desktop",
];

/// Reasons the plan requires per-action confirmation even in Act mode.
const DESTRUCTIVE_VERBS: &[&str] = &[
    "delete",
    "remove",
    "erase",
    "send",
    "submit",
    "purchase",
    "buy",
    "pay",
    "close",
    "quit",
    "uninstall",
    "shutdown",
    "reboot",
    "format",
];

#[derive(Debug, Clone)]
pub struct Policy {
    allowed: Vec<String>,
    blocked: Vec<String>,
    allow_all: bool,
    desktop_dir: PathBuf,
    audit_path: PathBuf,
    artifacts_dir: PathBuf,
    rate_limit: u32,
    retention: Duration,
}

impl Policy {
    pub fn from_env() -> Self {
        let desktop_dir = desktop_home();
        let allowed = split_list(std::env::var("PALIMIND_DESKTOP_ALLOWED_APPS").ok());
        let mut blocked = split_list(std::env::var("PALIMIND_DESKTOP_BLOCKED_APPS").ok());
        blocked.extend(PROTECTED_APPS.iter().map(|s| (*s).to_owned()));
        let allow_all = env_bool("PALIMIND_DESKTOP_ALLOW_ALL", false);
        let rate_limit = std::env::var("PALIMIND_DESKTOP_ACTION_RATE")
            .ok()
            .and_then(|v| v.trim().trim_end_matches("/min").parse::<u32>().ok())
            .filter(|v| *v > 0)
            .unwrap_or(30);
        let retention_hours = std::env::var("PALIMIND_DESKTOP_ARTIFACT_RETENTION_H")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(24);
        Self {
            allowed,
            blocked,
            allow_all,
            audit_path: desktop_dir.join("audit.jsonl"),
            artifacts_dir: desktop_dir.join("artifacts"),
            desktop_dir,
            rate_limit,
            retention: Duration::from_secs(retention_hours * 3600),
        }
    }

    pub fn desktop_dir(&self) -> &Path {
        &self.desktop_dir
    }

    pub fn artifacts_dir(&self) -> &Path {
        &self.artifacts_dir
    }

    pub fn rate_limit(&self) -> u32 {
        self.rate_limit
    }

    /// A hard denial: the app is protected by name, or blocked. Otherwise the
    /// app is allowed — Palimind works with any app on the desktop by default.
    /// A non-empty `PALIMIND_DESKTOP_ALLOWED_APPS` narrows that to just those
    /// apps; an empty list is not deny-all anymore. The protected-process set
    /// and the blocked list always win, regardless of the allowlist.
    pub fn check_app(&self, app: &str) -> Result<(), String> {
        if app.trim().is_empty() {
            return Err("Refusing to operate on an unnamed application".into());
        }
        if self.is_protected(app) {
            return Err(format!(
                "'{app}' is a protected system or Palimind process and cannot be controlled"
            ));
        }
        if self.blocked.iter().any(|pattern| app_matches(pattern, app)) {
            return Err(format!("'{app}' is in the blocked-app list"));
        }
        if self.allowed.is_empty() || self.allow_all {
            return Ok(());
        }
        if self.allowed.iter().any(|pattern| app_matches(pattern, app)) {
            return Ok(());
        }
        Err(format!("'{app}' is not in the app allowlist"))
    }

    pub fn is_protected(&self, app: &str) -> bool {
        PROTECTED_APPS
            .iter()
            .any(|pattern| app_matches(pattern, app))
    }

    /// Destructive-sounding labels require a fresh confirmation even when the
    /// agent holds `desktop_control`.
    pub fn looks_destructive(&self, text: &str) -> bool {
        let lowered = text.to_ascii_lowercase();
        DESTRUCTIVE_VERBS.iter().any(|verb| {
            lowered
                .split(|c: char| !c.is_alphanumeric())
                .any(|word| word == *verb)
        })
    }

    pub fn prepare_dirs(&self) -> std::io::Result<()> {
        for dir in [&self.desktop_dir, &self.artifacts_dir] {
            fs::create_dir_all(dir)?;
            fs::set_permissions(dir, fs::Permissions::from_mode(0o700))?;
        }
        Ok(())
    }

    pub fn audit_path(&self) -> &Path {
        &self.audit_path
    }

    pub fn append_audit(&self, record: &AuditRecord) -> std::io::Result<()> {
        if let Some(parent) = self.audit_path.parent() {
            fs::create_dir_all(parent)?;
        }
        let line = serde_json::to_string(record).map_err(std::io::Error::other)?;
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .mode(0o600)
            .open(&self.audit_path)?;
        // Restrict an existing file as well: mode() only applies on create.
        let _ = fs::set_permissions(&self.audit_path, fs::Permissions::from_mode(0o600));
        file.write_all(line.as_bytes())?;
        file.write_all(b"\n")
    }

    /// Delete artifacts older than the retention window. Called once at
    /// daemon/CLI start; never during an action.
    pub fn prune_artifacts(&self) {
        let Ok(entries) = fs::read_dir(&self.artifacts_dir) else {
            return;
        };
        let now = SystemTime::now();
        for entry in entries.flatten() {
            let Ok(meta) = entry.metadata() else { continue };
            let Ok(modified) = meta.modified() else {
                continue;
            };
            if now.duration_since(modified).unwrap_or_default() > self.retention {
                let _ = fs::remove_file(entry.path());
            }
        }
    }
}

#[derive(Debug, Serialize, Clone)]
pub struct AuditRecord {
    pub ts_ms: u128,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    pub command: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub app: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub action: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_ref: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_role: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub coordinates: Option<[i64; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value_len: Option<usize>,
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    pub duration_ms: u128,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub delivery: Option<Value>,
}

impl AuditRecord {
    pub fn new(command: &str) -> Self {
        Self {
            ts_ms: now_ms(),
            run_id: std::env::var("PALIMIND_DESKTOP_RUN_ID").ok(),
            agent_id: std::env::var("PALIMIND_DESKTOP_AGENT_ID").ok(),
            command: command.to_owned(),
            app: None,
            window_id: None,
            action: None,
            target_ref: None,
            target_role: None,
            target_name: None,
            coordinates: None,
            value_hash: None,
            value_len: None,
            ok: true,
            code: None,
            duration_ms: 0,
            delivery: None,
        }
    }

    /// Record a typed payload without keeping it. A per-process salt makes the
    /// digest a correlation fingerprint, not a reversible encoding.
    pub fn with_secret(&mut self, text: &str) {
        self.value_len = Some(text.chars().count());
        self.value_hash = Some(hash_secret(text));
    }
}

fn hash_secret(text: &str) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    static SALT: std::sync::OnceLock<u64> = std::sync::OnceLock::new();
    let salt = *SALT.get_or_init(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0x9E37_79B9_7F4A_7C15)
            ^ (std::process::id() as u64)
    });
    let mut hasher = DefaultHasher::new();
    salt.hash(&mut hasher);
    text.hash(&mut hasher);
    format!("siphash13:{:016x}", hasher.finish())
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn split_list(raw: Option<String>) -> Vec<String> {
    raw.unwrap_or_default()
        .split([',', ':', ';'])
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| s.to_ascii_lowercase())
        .collect()
}

fn env_bool(name: &str, default: bool) -> bool {
    match std::env::var(name) {
        Ok(raw) => matches!(
            raw.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
        Err(_) => default,
    }
}

/// Normalize an app name or desktop id and compare by whole token or suffix.
/// `org.gnome.Calculator`, `gnome-calculator` and `Calculator` all match the
/// pattern `calculator`; `gnome-shell` matches `org.gnome.Shell`.
fn app_matches(pattern: &str, app: &str) -> bool {
    let pattern = normalize_app(pattern);
    let app = normalize_app(app);
    if pattern.is_empty() || app.is_empty() {
        return false;
    }
    app == pattern || app.ends_with(&format!("-{pattern}")) || pattern.ends_with(&format!("-{app}"))
}

fn normalize_app(value: &str) -> String {
    let lowered = value.trim().to_ascii_lowercase();
    let stem = lowered
        .rsplit('/')
        .next()
        .unwrap_or(&lowered)
        .trim_end_matches(".desktop");
    stem.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .trim_matches('-')
        .to_owned()
}

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

pub struct RateLimiter {
    limit_per_minute: u32,
    seen: Mutex<VecDeque<Instant>>,
}

impl RateLimiter {
    pub fn new(limit_per_minute: u32) -> Self {
        Self {
            limit_per_minute,
            seen: Mutex::new(VecDeque::new()),
        }
    }

    pub fn check(&self) -> Result<(), String> {
        let mut seen = self.seen.lock().unwrap_or_else(|e| e.into_inner());
        let cutoff = Instant::now() - Duration::from_secs(60);
        while seen.front().is_some_and(|instant| *instant < cutoff) {
            seen.pop_front();
        }
        if seen.len() as u32 >= self.limit_per_minute {
            return Err(format!(
                "Action rate limit reached ({} per minute)",
                self.limit_per_minute
            ));
        }
        seen.push_back(Instant::now());
        Ok(())
    }
}

/// Machine-wide panic stop. A request sets it; the daemon checks it before
/// dispatching and releases held input.
pub static STOP: AtomicBool = AtomicBool::new(false);

pub fn request_stop() {
    STOP.store(true, Ordering::SeqCst);
}

pub fn clear_stop() {
    STOP.store(false, Ordering::SeqCst);
}

pub fn is_stopped() -> bool {
    STOP.load(Ordering::SeqCst)
}

/// The master switch, enforced natively as well as in the Python tool layer.
pub fn enabled() -> bool {
    env_bool("PALIMIND_DESKTOP_ENABLE", true)
}

pub fn status_json(policy: &Policy) -> Value {
    json!({
        "enabled": env_bool("PALIMIND_DESKTOP_ENABLE", true),
        "session_type": std::env::var("XDG_SESSION_TYPE").unwrap_or_else(|_| "unknown".into()),
        "desktop_dir": policy.desktop_dir().to_string_lossy(),
        "allow_all": policy.allow_all,
        "default_allow": policy.allowed.is_empty() || policy.allow_all,
        "allowed_apps": policy.allowed,
        "blocked_apps": policy.blocked,
        "rate_limit_per_min": policy.rate_limit,
        "audit": policy.audit_path().to_string_lossy(),
        "stopped": is_stopped(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn protected_apps_match_desktop_ids_and_exec_names() {
        let policy = Policy::from_env();
        assert!(policy.is_protected("org.gnome.Shell"));
        assert!(policy.is_protected("gnome-shell"));
        assert!(policy.is_protected("plasmashell"));
        assert!(policy.is_protected("Palimind"));
        assert!(!policy.is_protected("gnome-calculator"));
    }

    #[test]
    fn empty_allowlist_allows_any_unprotected_app() {
        let mut policy = Policy::from_env();
        policy.allowed.clear();
        policy.allow_all = false;
        assert!(policy.check_app("gnome-calculator").is_ok());
        assert!(policy.check_app("gnome-text-editor").is_ok());
        // The hard exclusions still win with no allowlist at all.
        assert!(policy.check_app("gnome-shell").is_err());
    }

    #[test]
    fn a_non_empty_allowlist_still_narrows_the_default() {
        let mut policy = Policy::from_env();
        policy.allowed = vec!["calculator".into()];
        policy.allow_all = false;
        assert!(policy.check_app("gnome-calculator").is_ok());
        assert!(policy.check_app("firefox").is_err());
    }

    #[test]
    fn allowlist_matches_suffix_tokens() {
        let mut policy = Policy::from_env();
        policy.allowed = vec!["calculator".into()];
        policy.allow_all = false;
        assert!(policy.check_app("gnome-calculator").is_ok());
        assert!(policy.check_app("org.gnome.Calculator").is_ok());
        assert!(policy.check_app("firefox").is_err());
    }

    #[test]
    fn protected_wins_even_when_allowlisted() {
        let mut policy = Policy::from_env();
        policy.allowed = vec!["gnome-shell".into()];
        policy.allow_all = true;
        assert!(policy.check_app("gnome-shell").is_err());
    }

    #[test]
    fn destructive_labels_are_detected() {
        let policy = Policy::from_env();
        assert!(policy.looks_destructive("Delete file"));
        assert!(policy.looks_destructive("Send message"));
        assert!(!policy.looks_destructive("Save draft"));
    }

    #[test]
    fn secret_digest_is_not_plaintext() {
        let record = AuditRecord::new("act");
        let mut record = record;
        record.with_secret("hunter2");
        assert!(!record.value_hash.as_deref().unwrap().contains("hunter2"));
        assert_eq!(record.value_len, Some(7));
    }
}
