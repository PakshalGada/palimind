//! `palimind-desktop serve`: newline-delimited JSON-RPC over stdio.
//!
//! The Python backend spawns this as a child process. Being a same-user child
//! means the daemon inherits the graphical session environment (D-Bus, X11,
//! Wayland) and needs no port, bearer token or desktop bridge.
//!
//! Protocol (one JSON object per line, request and response):
//!
//! ```json
//! {"id": 1, "method": "snapshot", "params": {"app": "gnome-calculator"}}
//! {"id": 1, "ok": true, "command": "snapshot", "data": {"snapshot": {}}}
//! ```
//!
//! `method` is one of `status`, `apps`, `snapshot`, `find`, `wait`, `act`,
//! `screenshot`, `stop`, `resume`, `audit`, `ping`. Errors use the same
//! envelope as the CLI.

use std::io::{BufRead, Write};
use std::sync::Arc;

use agent_desktop_core::Direction;
use agent_desktop_core::PlatformAdapter;
use serde::Deserialize;
use serde_json::{Value, json};

use crate::commands::{ActAction, ActArgs, AppsKind, Dispatcher};
use crate::envelope::Envelope;
use crate::policy::{Policy, RateLimiter, clear_stop, is_stopped, request_stop};

#[derive(Debug, Deserialize)]
struct Request {
    #[serde(default)]
    id: Option<Value>,
    method: String,
    #[serde(default)]
    params: Value,
}

pub fn serve(
    adapter: &dyn PlatformAdapter,
    policy: &Policy,
    context: &agent_desktop_core::CommandContext,
) -> i32 {
    let limiter = Arc::new(RateLimiter::new(policy.rate_limit()));
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out = std::io::BufWriter::new(stdout.lock());
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let request: Request = match serde_json::from_str(&line) {
            Ok(request) => request,
            Err(error) => {
                let _ = write_response(
                    &mut out,
                    None,
                    &Envelope::err(
                        "parse",
                        agent_desktop_core::AppError::invalid_input(format!(
                            "Invalid JSON request: {error}"
                        )),
                    ),
                );
                continue;
            }
        };
        let id = request.id.clone();
        let dispatcher = Dispatcher {
            policy,
            adapter,
            context,
        };
        let envelope = dispatch(&dispatcher, &limiter, &request);
        if write_response(&mut out, id, &envelope).is_err() {
            return 1;
        }
    }
    0
}

fn dispatch(dispatcher: &Dispatcher<'_>, limiter: &RateLimiter, request: &Request) -> Envelope {
    let params = &request.params;
    match request.method.as_str() {
        "ping" => Envelope::ok("ping", json!({ "pong": true, "pid": std::process::id() })),
        "status" => dispatcher.status(),
        "apps" => {
            let kind = match string_param(params, "kind").as_deref() {
                Some("windows") => AppsKind::Windows,
                Some("displays") => AppsKind::Displays,
                _ => AppsKind::Apps,
            };
            dispatcher.apps(kind, string_param(params, "app").as_deref())
        }
        "snapshot" => {
            if is_stopped() {
                return stopped("snapshot");
            }
            dispatcher.snapshot(
                string_param(params, "app").as_deref(),
                string_param(params, "window_id").as_deref(),
                bool_param(params, "interactive_only").unwrap_or(false),
                bool_param(params, "full").unwrap_or(false),
                number_param(params, "max_depth").unwrap_or(12) as u8,
                number_param(params, "max_nodes").unwrap_or(300) as usize,
                number_param(params, "timeout_ms"),
            )
        }
        "find" => {
            if is_stopped() {
                return stopped("find");
            }
            dispatcher.find(
                string_param(params, "app").as_deref(),
                string_param(params, "window_id").as_deref(),
                string_param(params, "role").as_deref(),
                string_param(params, "name").as_deref(),
                string_param(params, "text").as_deref(),
                number_param(params, "limit").unwrap_or(20) as usize,
                number_param(params, "timeout_ms"),
            )
        }
        "wait" => {
            if is_stopped() {
                return stopped("wait");
            }
            dispatcher.wait(crate::WaitArgs {
                ms: number_param(params, "ms"),
                element: string_param(params, "element"),
                window: string_param(params, "window"),
                text: string_param(params, "text"),
                window_id: string_param(params, "window_id"),
                app: string_param(params, "app"),
                timeout_ms: number_param(params, "timeout_ms").unwrap_or(5_000),
            })
        }
        "act" => {
            if is_stopped() {
                return stopped("act");
            }
            let Some(action) =
                string_param(params, "action").and_then(|value| ActAction::parse(&value))
            else {
                return Envelope::err(
                    "act",
                    agent_desktop_core::AppError::invalid_input(
                        "act requires a known action (click, type, set_value, press_key, …)",
                    ),
                );
            };
            let args = ActArgs {
                action,
                reference: string_param(params, "ref"),
                text: string_param(params, "text"),
                value: string_param(params, "value"),
                key: string_param(params, "key"),
                direction: match string_param(params, "direction").as_deref() {
                    Some("up") => Direction::Up,
                    Some("left") => Direction::Left,
                    Some("right") => Direction::Right,
                    _ => Direction::Down,
                },
                amount: number_param(params, "amount").unwrap_or(3) as u32,
                x: float_param(params, "x"),
                y: float_param(params, "y"),
                to_ref: string_param(params, "to_ref"),
                to_x: float_param(params, "to_x"),
                to_y: float_param(params, "to_y"),
                app: string_param(params, "app"),
                window_id: string_param(params, "window_id"),
                coords_source: parse_source(string_param(params, "coords_source").as_deref()),
                kernel: bool_param(params, "kernel").unwrap_or(false),
                confirm_destructive: bool_param(params, "confirm_destructive").unwrap_or(false),
                timeout_ms: number_param(params, "timeout_ms"),
            };
            if args.action.is_mutating() {
                if let Err(error) = limiter.check() {
                    return Envelope::err(
                        "act",
                        agent_desktop_core::AppError::invalid_input(error),
                    );
                }
            }
            dispatcher.act(args)
        }
        "screenshot" => {
            if is_stopped() {
                return stopped("screenshot");
            }
            dispatcher.screenshot(
                string_param(params, "app").as_deref(),
                string_param(params, "window_id").as_deref(),
                number_param(params, "screen").map(|value| value as usize),
            )
        }
        "launch" => {
            if is_stopped() {
                return stopped("launch");
            }
            let Some(app) = string_param(params, "app") else {
                return Envelope::err(
                    "launch",
                    agent_desktop_core::AppError::invalid_input("launch requires app"),
                );
            };
            dispatcher.act(ActArgs {
                action: ActAction::Launch,
                reference: None,
                text: None,
                value: None,
                key: None,
                direction: Direction::Down,
                amount: 1,
                x: None,
                y: None,
                to_ref: None,
                to_x: None,
                to_y: None,
                app: Some(app),
                window_id: None,
                coords_source: crate::targeting::CoordinateSource::Unknown,
                kernel: false,
                confirm_destructive: false,
                timeout_ms: None,
            })
        }
        "stop" => {
            request_stop();
            agent_desktop_linux::end_input_session();
            Envelope::ok(
                "stop",
                json!({
                    "stopped": true,
                    "released": ["keys", "buttons", "remote_desktop_session"],
                    "note": "Held input was released and the session is disabled until resume.",
                }),
            )
        }
        "resume" => {
            clear_stop();
            Envelope::ok("resume", json!({ "stopped": false }))
        }
        "audit" => {
            let limit = number_param(params, "limit").unwrap_or(50) as usize;
            Envelope::ok("audit", audit_tail(dispatcher.policy, limit))
        }
        other => Envelope::err(
            other,
            agent_desktop_core::AppError::invalid_input(format!("Unknown method '{other}'")),
        ),
    }
}

fn audit_tail(policy: &Policy, limit: usize) -> Value {
    let path = policy.audit_path();
    let Ok(text) = std::fs::read_to_string(path) else {
        return json!({ "entries": [], "path": path.to_string_lossy() });
    };
    let entries: Vec<Value> = text
        .lines()
        .rev()
        .take(limit)
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .collect();
    json!({ "entries": entries, "path": path.to_string_lossy() })
}

fn stopped(command: &str) -> Envelope {
    Envelope::err(
        command,
        agent_desktop_core::AppError::Adapter(
            agent_desktop_core::AdapterError::new(
                agent_desktop_core::ErrorCode::PolicyDenied,
                "The desktop session is stopped. Press resume or start a new run.",
            )
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
        ),
    )
}

fn write_response(
    out: &mut impl Write,
    id: Option<Value>,
    envelope: &Envelope,
) -> std::io::Result<()> {
    let mut value = serde_json::to_value(envelope).map_err(std::io::Error::other)?;
    if let Some(object) = value.as_object_mut() {
        object.insert("id".into(), id.unwrap_or(Value::Null));
    }
    serde_json::to_writer(&mut *out, &value)?;
    out.write_all(b"\n")?;
    out.flush()
}

fn parse_source(value: Option<&str>) -> crate::targeting::CoordinateSource {
    use crate::targeting::CoordinateSource;
    match value {
        Some("user") => CoordinateSource::User,
        Some("screenshot") => CoordinateSource::Screenshot,
        Some("compositor") => CoordinateSource::Compositor,
        Some("atspi") => CoordinateSource::Atspi,
        _ => CoordinateSource::Unknown,
    }
}

fn string_param(params: &Value, key: &str) -> Option<String> {
    params.get(key).and_then(Value::as_str).map(str::to_owned)
}

fn bool_param(params: &Value, key: &str) -> Option<bool> {
    params.get(key).and_then(Value::as_bool)
}

fn number_param(params: &Value, key: &str) -> Option<u64> {
    params.get(key).and_then(Value::as_u64)
}

fn float_param(params: &Value, key: &str) -> Option<f64> {
    params.get(key).and_then(Value::as_f64)
}
