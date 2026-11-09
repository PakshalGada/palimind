//! Command implementations over the vendored engine.
//!
//! The engine exposes typed command modules (`agent_desktop_core::commands::*`).
//! Palimind wraps them with policy preflight, a compact observation projection,
//! and audit records. No upstream module is modified for the wrapper.

use agent_desktop_core::commands::close_app::CloseAppArgs;
use agent_desktop_core::commands::drag::{DragArgs, DragEndpoint, WaitForScope};
use agent_desktop_core::commands::find;
use agent_desktop_core::commands::find::{FindArgs, FindFilterArgs, FindSelectionArgs};
use agent_desktop_core::commands::focus_window::FocusWindowArgs;
use agent_desktop_core::commands::helpers::RefArgs;
use agent_desktop_core::commands::hover::HoverArgs;
use agent_desktop_core::commands::launch::LaunchArgs;
use agent_desktop_core::commands::press::PressArgs;
use agent_desktop_core::commands::screenshot::ScreenshotArgs;
use agent_desktop_core::commands::scroll::ScrollArgs;
use agent_desktop_core::commands::scroll_to;
use agent_desktop_core::commands::select::SelectArgs;
use agent_desktop_core::commands::set_value::SetValueArgs;
use agent_desktop_core::commands::snapshot::SnapshotArgs;
use agent_desktop_core::commands::type_text::TypeArgs;
use agent_desktop_core::commands::wait::{WaitArgs, WaitModeArgs, WaitPredicateArgs};
use agent_desktop_core::commands::{
    check, clear, click, close_app, double_click, drag, focus, focus_window, hover, launch,
    list_apps, list_displays, list_windows, press, right_click, screenshot, scroll, select,
    set_value, snapshot, toggle, type_text, uncheck, wait,
};
use agent_desktop_core::system::launch_options::LaunchOptions;
use agent_desktop_core::{
    AppError, AppInventoryQuery, CommandContext, Direction, ErrorCode, MouseButton, PlatformAdapter,
    ProcessId, SnapshotSurface, WindowFilter, WindowInfo,
};
use serde_json::{Value, json};
use std::time::Instant;

use crate::envelope::{Envelope, untrusted_provenance};
use crate::policy::{AuditRecord, Policy};
use crate::targeting::{self, CoordinateSource};
use crate::uinput;

pub struct Dispatcher<'a> {
    pub policy: &'a Policy,
    pub adapter: &'a dyn PlatformAdapter,
    pub context: &'a CommandContext,
}

pub struct ActArgs {
    pub action: ActAction,
    pub reference: Option<String>,
    pub text: Option<String>,
    pub value: Option<String>,
    pub key: Option<String>,
    pub direction: Direction,
    pub amount: u32,
    pub x: Option<f64>,
    pub y: Option<f64>,
    pub to_ref: Option<String>,
    pub to_x: Option<f64>,
    pub to_y: Option<f64>,
    pub app: Option<String>,
    pub window_id: Option<String>,
    pub coords_source: CoordinateSource,
    pub kernel: bool,
    pub confirm_destructive: bool,
    pub timeout_ms: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum ActAction {
    Click,
    DoubleClick,
    RightClick,
    Hover,
    Focus,
    Type,
    SetValue,
    Clear,
    Select,
    Toggle,
    Check,
    Uncheck,
    Scroll,
    ScrollTo,
    Drag,
    PressKey,
    TypeText,
    Launch,
    Close,
    FocusWindow,
}

impl ActAction {
    pub fn is_mutating(self) -> bool {
        !matches!(self, Self::Focus | Self::FocusWindow)
    }

    pub fn parse(value: &str) -> Option<Self> {
        Some(
            match value.trim().to_ascii_lowercase().replace('-', "_").as_str() {
                "click" => Self::Click,
                "double_click" => Self::DoubleClick,
                "right_click" => Self::RightClick,
                "hover" => Self::Hover,
                "focus" => Self::Focus,
                "type" => Self::Type,
                "set_value" => Self::SetValue,
                "clear" => Self::Clear,
                "select" => Self::Select,
                "toggle" => Self::Toggle,
                "check" => Self::Check,
                "uncheck" => Self::Uncheck,
                "scroll" => Self::Scroll,
                "scroll_to" => Self::ScrollTo,
                "drag" => Self::Drag,
                "press_key" | "press" => Self::PressKey,
                "type_text" => Self::TypeText,
                "launch" => Self::Launch,
                "close" => Self::Close,
                "focus_window" => Self::FocusWindow,
                _ => return None,
            },
        )
    }
}

impl Dispatcher<'_> {
    fn require_enabled(&self) -> Result<(), AppError> {
        if crate::policy::enabled() {
            return Ok(());
        }
        Err(AppError::Adapter(
            agent_desktop_core::AdapterError::new(
                ErrorCode::PolicyDenied,
                "Computer use is disabled (PALIMIND_DESKTOP_ENABLE is not 1)",
            )
            .with_suggestion("Enable it in Settings > Computer use, then restart the backend.")
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
        ))
    }

    #[allow(clippy::too_many_lines)]
    fn finish(
        &self,
        command: &str,
        mut record: AuditRecord,
        started: Instant,
        result: Result<Value, AppError>,
    ) -> Envelope {
        record.duration_ms = started.elapsed().as_millis();
        let envelope = match result {
            Ok(data) => {
                record.ok = true;
                record.delivery = data.get("disposition").cloned();
                Envelope::ok(command, data)
            }
            Err(error) => {
                record.ok = false;
                record.code = Some(error.code().to_owned());
                if let AppError::Adapter(adapter) = &error {
                    record.delivery = serde_json::to_value(adapter.disposition).ok();
                }
                Envelope::err(command, error)
            }
        };
        if let Err(error) = self.policy.append_audit(&record) {
            eprintln!("palimind-desktop: audit write failed: {error}");
        }
        envelope
    }

    // ---- Observation -----------------------------------------------------

    pub fn status(&self) -> Envelope {
        let started = Instant::now();
        let record = AuditRecord::new("status");
        let result = agent_desktop_core::commands::status::execute_with_report_with_context(
            self.adapter,
            &agent_desktop_core::PermissionReport::default(),
            self.context,
        );
        let result = result.map(|mut value| {
            let kernel = uinput::probe();
            value["platform"] = json!("linux");
            value["session_type"] =
                json!(std::env::var("XDG_SESSION_TYPE").unwrap_or_else(|_| "unknown".into()));
            value["capabilities"] = json!({
                "accessibility": true,
                "semantic_actions": true,
                "physical_input": true,
                "kernel_input": kernel.accessible,
                "screenshot": true,
                "wayland_pointer_targeting": if targeting::session_is_wayland() {
                    "requires_proven_global_coordinates"
                } else {
                    "screen_coordinates_available"
                },
            });
            value["kernel_input"] = serde_json::to_value(&kernel).unwrap_or(json!({}));
            value["input_backend"] = json!(
                std::env::var("PALIMIND_DESKTOP_INPUT_BACKEND").unwrap_or_else(|_| "auto".into())
            );
            value["screencast_token"] = json!(
                self.policy
                    .desktop_dir()
                    .join("screencast-token")
                    .is_file()
            );
            value["policy"] = crate::policy::status_json(self.policy);
            // Linux has no macOS-style accessibility permission prompt: the
            // real probe is whether the AT-SPI registry answers a bounded
            // inventory read. Report that answer instead of "unknown".
            let accessibility = match agent_desktop_core::Deadline::after(2_000) {
                Ok(deadline) => self
                    .adapter
                    .query_app_inventory(AppInventoryQuery::All, deadline)
                    .map_or("unavailable", |_| "granted"),
                Err(_) => "unavailable",
            };
            value["permissions"]["accessibility"] = json!({ "state": accessibility });
            value
        });
        self.finish("status", record, started, result)
    }

    pub fn apps(&self, kind: AppsKind, app: Option<&str>) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("apps");
        if let Err(error) = self.require_enabled() {
            return self.finish("apps", record, started, Err(error));
        }
        record.app = app.map(str::to_owned);
        let result = match kind {
            AppsKind::Apps => list_apps::execute(
                list_apps::ListAppsArgs {
                    app: app.map(str::to_owned),
                    timeout_ms: None,
                },
                self.adapter,
            ),
            AppsKind::Windows => list_windows::execute(
                list_windows::ListWindowsArgs {
                    app: app.map(str::to_owned),
                    timeout_ms: None,
                },
                self.adapter,
            )
            .map(filter_dead_windows)
            .and_then(|value| match (app, value) {
                // A launcher name can differ from the AT-SPI name (Flatpak
                // exposes the sandbox proxy). If the exact filter found
                // nothing, try the same alias resolution observation uses.
                (Some(app), Value::Array(windows)) if windows.is_empty() => {
                    alias_window(&self.windows_for_aliases(), app)
                        .map(|window| json!([window]))
                        .ok_or_else(|| {
                            AppError::Adapter(
                                agent_desktop_core::AdapterError::new(
                                    ErrorCode::AppNotFound,
                                    format!("No window matched application '{app}'"),
                                )
                                .with_suggestion(
                                    "Run 'apps windows' without --app and pick a window id, or use the desktop id.",
                                )
                                .with_disposition(
                                    agent_desktop_core::DeliverySemantics::not_delivered(),
                                ),
                            )
                        })
                }
                (_, value) => Ok(value),
            }),
            AppsKind::Displays => list_displays::execute(self.adapter),
        };
        self.finish("apps", record, started, result.map(|data| {
            json!({ "kind": kind.as_str(), "result": data, "provenance": untrusted_provenance("at-spi2") })
        }))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn snapshot(
        &self,
        app: Option<&str>,
        window_id: Option<&str>,
        interactive_only: bool,
        full: bool,
        max_depth: u8,
        max_nodes: usize,
        timeout_ms: Option<u64>,
    ) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("snapshot");
        if let Err(error) = self.require_enabled() {
            return self.finish("snapshot", record, started, Err(error));
        }
        record.app = app.map(str::to_owned);
        record.window_id = window_id.map(str::to_owned);

        let target = match self.resolve_target(app, window_id) {
            Ok(target) => target,
            Err(error) => return self.finish("snapshot", record, started, Err(error)),
        };
        // A stale AT-SPI entry can leave two "Calculator" windows for one
        // process. When we already resolved the live target, address it by id
        // so the engine does not answer AMBIGUOUS_TARGET for a dead twin.
        let resolved_window = target.window.as_ref().map(|window| window.id.clone());
        let effective_window = window_id.map(str::to_owned).or(resolved_window);
        if let Some(name) = target.app.as_deref()
            && let Err(reason) = self.policy.check_app(name)
        {
            return self.finish("snapshot", record, started, Err(policy_error(reason)));
        }

        let result = snapshot::execute(
            SnapshotArgs {
                app: target.app.clone(),
                window_id: effective_window.clone(),
                max_depth,
                include_bounds: true,
                interactive_only,
                // The Palimind projection is the compaction step: it drops
                // offscreen subtrees and caps the node count. The engine's own
                // `compact` mode also drops static text, which hides read-only
                // values such as a calculator display, so keep it off.
                compact: false,
                surface: SnapshotSurface::Window,
                skeleton: false,
                root_ref: None,
                timeout_ms,
                force_electron_a11y: false,
            },
            self.adapter,
            self.context,
        );
        let result = result.map(|value| project_snapshot(value, &target, max_nodes, full));
        self.finish(
            "snapshot",
            record,
            started,
            result.map(
                |data| json!({ "snapshot": data, "provenance": untrusted_provenance("at-spi2") }),
            ),
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn find(
        &self,
        app: Option<&str>,
        window_id: Option<&str>,
        role: Option<&str>,
        name: Option<&str>,
        text: Option<&str>,
        limit: usize,
        timeout_ms: Option<u64>,
    ) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("find");
        if let Err(error) = self.require_enabled() {
            return self.finish("find", record, started, Err(error));
        }
        record.app = app.map(str::to_owned);
        record.window_id = window_id.map(str::to_owned);
        let target = match self.resolve_target(app, window_id) {
            Ok(target) => target,
            Err(error) => return self.finish("find", record, started, Err(error)),
        };
        if let Some(app_name) = target.app.as_deref() {
            if let Err(reason) = self.policy.check_app(app_name) {
                return self.finish("find", record, started, Err(policy_error(reason)));
            }
            record.target_name = name.map(str::to_owned);
        }
        let effective_window = target
            .window
            .as_ref()
            .map(|window| window.id.clone())
            .or_else(|| window_id.map(str::to_owned));
        let result = find::execute(
            FindArgs {
                app: target.app.clone(),
                window_id: effective_window,
                root: None,
                surface: SnapshotSurface::Window,
                filter: FindFilterArgs {
                    role: role.map(str::to_owned),
                    name: name.map(str::to_owned),
                    description: None,
                    native_id: None,
                    value: None,
                    text: text.map(str::to_owned),
                    exact: false,
                },
                states: Vec::new(),
                selection: FindSelectionArgs {
                    count: false,
                    first: false,
                    last: false,
                    nth: None,
                    limit: Some(limit),
                },
                timeout_ms,
            },
            self.adapter,
            self.context,
        );
        // Large Chromium/web-content trees can make the locator's authoritative
        // traversal run out (or refuse incomplete evidence) while it has
        // already seen matches. Do not discard them: run a bounded snapshot
        // search and return best-effort candidates, clearly marked partial.
        let result = match result {
            Err(error) if incomplete_locator(&error) => {
                match self.fallback_find(
                    app,
                    window_id,
                    role,
                    name,
                    text,
                    limit,
                ) {
                    Ok(value)
                        if value
                            .get("matches")
                            .and_then(Value::as_array)
                            .is_some_and(|matches| !matches.is_empty()) =>
                    {
                        Ok(value)
                    }
                    _ => Err(error),
                }
            }
            other => other,
        };
        self.finish(
            "find",
            record,
            started,
            result.map(
                |data| json!({ "matches": data, "provenance": untrusted_provenance("at-spi2") }),
            ),
        )
    }

    /// A bounded snapshot search used only when the authoritative locator
    /// cannot finish. The refs are real snapshot-qualified refs, but the
    /// result is marked `partial` because the tree may have been cut short.
    fn fallback_find(
        &self,
        app: Option<&str>,
        window_id: Option<&str>,
        role: Option<&str>,
        name: Option<&str>,
        text: Option<&str>,
        limit: usize,
    ) -> Result<Value, AppError> {
        let target = self.resolve_target(app, window_id)?;
        let value = snapshot::execute(
            SnapshotArgs {
                app: target.app.clone(),
                window_id: target
                    .window
                    .as_ref()
                    .map(|window| window.id.clone())
                    .or_else(|| window_id.map(str::to_owned)),
                max_depth: 40,
                include_bounds: true,
                interactive_only: false,
                compact: false,
                surface: SnapshotSurface::Window,
                skeleton: false,
                root_ref: None,
                timeout_ms: Some(15_000),
                force_electron_a11y: false,
            },
            self.adapter,
            self.context,
        )?;
        let projected = project_snapshot(value, &target, 1_000, false);
        let nodes = projected
            .get("nodes")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let matches = filter_projected_matches(nodes, role, name, text, limit);
        let total = matches.len();
        Ok(json!({
            "matches": matches,
            "total_matches": total,
            "truncated": false,
            "partial": true,
            "note": "The authoritative find timed out on a large tree. These matches come from a bounded snapshot search and may be incomplete; retry with a narrower role/name, or pass timeout_ms and a window_id.",
        }))
    }

    pub fn wait(&self, args: crate::WaitArgs) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("wait");
        if let Err(error) = self.require_enabled() {
            return self.finish("wait", record, started, Err(error));
        }
        record.app = args.app.clone();
        if let Some(app) = args.app.as_deref()
            && let Err(reason) = self.policy.check_app(app)
        {
            return self.finish("wait", record, started, Err(policy_error(reason)));
        }
        let timeout_ms = args.timeout_ms;
        let result = wait::execute(
            WaitArgs {
                mode: WaitModeArgs {
                    ms: args.ms,
                    element: args.element,
                    window: args.window,
                    text: args.text,
                    surface: None,
                    event: None,
                    window_id: args.window_id,
                },
                predicate: WaitPredicateArgs {
                    predicate: None,
                    value: None,
                    action: None,
                    count: None,
                },
                timeout_ms,
                app: args.app,
            },
            self.adapter,
            self.context,
        );
        self.finish("wait", record, started, result)
    }

    // ---- Actions ---------------------------------------------------------

    pub fn act(&self, args: ActArgs) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("act");
        if let Err(error) = self.require_enabled() {
            return self.finish("act", record, started, Err(error));
        }
        record.action = Some(format!("{:?}", args.action).to_ascii_lowercase());
        record.app = args.app.clone();
        record.window_id = args.window_id.clone();
        record.target_ref = args.reference.clone();

        if let Some(app) = args.app.as_deref()
            && let Err(reason) = self.policy.check_app(app)
        {
            return self.finish("act", record, started, Err(policy_error(reason)));
        }
        if let Some(text) = args.text.as_deref() {
            record.with_secret(text);
        }
        if let Some(value) = args.value.as_deref() {
            record.with_secret(value);
        }
        if let (Some(x), Some(y)) = (args.x, args.y) {
            record.coordinates = Some([x.round() as i64, y.round() as i64]);
        }
        if let Some(reason) = self.destructive_reason(&args) {
            return self.finish("act", record, started, Err(reason));
        }

        // Kernel-input path: only for explicit physical actions with a proven
        // global coordinate source (or global keys).
        if args.kernel {
            let result = self.kernel_act(&args);
            return self.finish("act", record, started, result);
        }

        let result = self.semantic_act(&args);
        self.finish("act", record, started, result)
    }

    fn semantic_act(&self, args: &ActArgs) -> Result<Value, AppError> {
        let timeout = args.timeout_ms;
        let reference = args.reference.as_deref();
        match args.action {
            ActAction::Click => {
                let reference = require_ref(reference, "click")?;
                click::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::DoubleClick => {
                let reference = require_ref(reference, "double_click")?;
                double_click::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::RightClick => {
                let reference = require_ref(reference, "right_click")?;
                right_click::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Hover => {
                if args.x.is_some() || args.y.is_some() {
                    targeting::require_global_coordinates(args.coords_source).map_err(|reason| {
                        AppError::Adapter(
                            agent_desktop_core::AdapterError::new(ErrorCode::PlatformNotSupported, reason)
                                .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
                        )
                    })?;
                }
                hover::execute(
                    HoverArgs {
                        ref_id: reference.map(str::to_owned),
                        xy: match (args.x, args.y) {
                            (Some(x), Some(y)) => Some((x, y)),
                            _ => None,
                        },
                        duration_ms: None,
                        timeout_ms: timeout,
                    },
                    self.adapter,
                    self.context,
                )
            }
            ActAction::Focus => {
                let reference = require_ref(reference, "focus")?;
                focus::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Type => {
                let reference = require_ref(reference, "type")?;
                let text = args.text.clone().ok_or_else(|| invalid("type requires --text"))?;
                type_text::execute(
                    TypeArgs { ref_id: reference.to_owned(), text, timeout_ms: timeout, interval_ms: None },
                    self.adapter,
                    self.context,
                )
            }
            ActAction::SetValue => {
                let reference = require_ref(reference, "set_value")?;
                let value = args.value.clone().ok_or_else(|| invalid("set_value requires --value"))?;
                set_value::execute(SetValueArgs { ref_id: reference.to_owned(), value, timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Clear => {
                let reference = require_ref(reference, "clear")?;
                clear::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Select => {
                let reference = require_ref(reference, "select")?;
                let value = args.value.clone().ok_or_else(|| invalid("select requires --value"))?;
                select::execute(SelectArgs { ref_id: reference.to_owned(), value, timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Toggle => {
                let reference = require_ref(reference, "toggle")?;
                toggle::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Check => {
                let reference = require_ref(reference, "check")?;
                check::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Uncheck => {
                let reference = require_ref(reference, "uncheck")?;
                uncheck::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Scroll => {
                let reference = require_ref(reference, "scroll")?;
                scroll::execute(
                    ScrollArgs { ref_id: reference.to_owned(), direction: args.direction.clone(), amount: args.amount.max(1), timeout_ms: timeout },
                    self.adapter,
                    self.context,
                )
            }
            ActAction::ScrollTo => {
                let reference = require_ref(reference, "scroll_to")?;
                scroll_to::execute(RefArgs { ref_id: reference.to_owned(), timeout_ms: timeout }, self.adapter, self.context)
            }
            ActAction::Drag => {
                drag::execute(
                    DragArgs {
                        from: endpoint(reference, args.x, args.y, "drag needs --ref or --x/--y")?,
                        to: endpoint(args.to_ref.as_deref(), args.to_x, args.to_y, "drag needs --to-ref or --to-x/--to-y")?,
                        duration_ms: None,
                        drop_delay_ms: None,
                        timeout_ms: timeout,
                        wait_for_scope: WaitForScope::To,
                    },
                    self.adapter,
                    self.context,
                )
            }
            ActAction::PressKey => {
                let combo = args.key.clone().ok_or_else(|| invalid("press_key requires --key, e.g. ctrl+s"))?;
                press::execute(
                    PressArgs { combo, app: args.app.clone(), window_id: args.window_id.clone(), force: false },
                    self.adapter,
                    self.context,
                )
            }
            ActAction::TypeText => {
                let text = args
                    .text
                    .clone()
                    .ok_or_else(|| invalid("type_text requires --text"))?;
                if !targeting::session_is_wayland() {
                    return Err(AppError::Adapter(
                        agent_desktop_core::AdapterError::new(
                            ErrorCode::ActionNotSupported,
                            "Global typing needs the kernel input backend on X11",
                        )
                        .with_suggestion(
                            "Call act with action=type and a ref, or install the uinput rule.",
                        )
                        .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
                    ));
                }
                let deadline = agent_desktop_core::Deadline::after(
                    args.timeout_ms.unwrap_or(20_000),
                )
                .map_err(AppError::from)?;
                let restored =
                    agent_desktop_linux::type_text_via_clipboard(&text, deadline)
                        .map_err(AppError::from)?;
                Ok(json!({
                    "action": "type_text",
                    "mechanism": "clipboard-paste",
                    "characters": text.chars().count(),
                    "clipboard_restored": restored,
                    "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                }))
            }
            ActAction::Launch => {
                let app = args.app.clone().ok_or_else(|| invalid("launch requires --app"))?;
                if let Err(reason) = self.policy.check_app(&app) {
                    return Err(policy_error(reason));
                }
                launch::execute(LaunchArgs { app, options: LaunchOptions::default() }, self.adapter)
            }
            ActAction::Close => {
                let app = args.app.clone().ok_or_else(|| invalid("close requires --app"))?;
                if let Err(reason) = self.policy.check_app(&app) {
                    return Err(policy_error(reason));
                }
                close_app::execute(CloseAppArgs { app, force: false }, self.adapter)
            }
            ActAction::FocusWindow => focus_window::execute(
                FocusWindowArgs {
                    window_id: args.window_id.clone(),
                    app: args.app.clone(),
                    title: None,
                },
                self.adapter,
            ),
        }
    }

    fn kernel_act(&self, args: &ActArgs) -> Result<Value, AppError> {
        match args.action {
            ActAction::PressKey => {
                let combo = args
                    .key
                    .clone()
                    .ok_or_else(|| invalid("press_key requires --key"))?;
                let mut device = uinput::VirtualInput::open().map_err(kernel_error)?;
                device.chord(&combo).map_err(|e| kernel_error(e.into()))?;
                Ok(json!({
                    "action": "press_key",
                    "mechanism": "uinput",
                    "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                }))
            }
            ActAction::TypeText | ActAction::Type => {
                let text = args
                    .text
                    .clone()
                    .ok_or_else(|| invalid("type_text requires --text"))?;
                let mut clipboard_error: Option<agent_desktop_core::AdapterError> = None;
                if targeting::session_is_wayland() {
                    let deadline = agent_desktop_core::Deadline::after(
                        args.timeout_ms.unwrap_or(20_000),
                    )
                    .map_err(AppError::from)?;
                    match agent_desktop_linux::type_text_via_clipboard(&text, deadline) {
                        Ok(restored) => {
                            return Ok(json!({
                                "action": "type_text",
                                "mechanism": "clipboard-paste",
                                "characters": text.chars().count(),
                                "clipboard_restored": restored,
                                "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                            }));
                        }
                        Err(error) => clipboard_error = Some(error),
                    }
                }
                let mut device = match uinput::VirtualInput::open() {
                    Ok(device) => device,
                    Err(error) => {
                        if let Some(clipboard_error) = clipboard_error {
                            return Err(AppError::from(clipboard_error));
                        }
                        return Err(kernel_error(error));
                    }
                };
                device
                    .type_text(&text)
                    .map_err(|e| kernel_error(e.into()))?;
                Ok(json!({
                    "action": "type_text",
                    "mechanism": "uinput",
                    "characters": text.chars().count(),
                    "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                }))
            }
            ActAction::Click | ActAction::DoubleClick | ActAction::RightClick => {
                let (x, y) = match (args.x, args.y) {
                    (Some(x), Some(y)) => (x, y),
                    _ => {
                        return Err(AppError::Adapter(
                            agent_desktop_core::AdapterError::new(
                                ErrorCode::InvalidArgs,
                                "Kernel pointer input needs --x and --y",
                            )
                            .with_suggestion("Prefer a semantic action on a ref; use coordinates only for canvas-style UI.")
                            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
                        ));
                    }
                };
                targeting::require_global_coordinates(args.coords_source)
                    .map_err(unproven_coordinates)?;
                let button = if args.action == ActAction::RightClick {
                    uinput::BUTTON_RIGHT
                } else {
                    uinput::BUTTON_LEFT
                };
                let count = if args.action == ActAction::DoubleClick {
                    2
                } else {
                    1
                };
                let backend = std::env::var("PALIMIND_DESKTOP_INPUT_BACKEND")
                    .unwrap_or_else(|_| "auto".to_owned())
                    .to_ascii_lowercase();
                let mut mutter_error: Option<agent_desktop_core::AdapterError> = None;
                if targeting::session_is_wayland() && backend != "uinput" {
                    let core_button = if args.action == ActAction::RightClick {
                        MouseButton::Right
                    } else {
                        MouseButton::Left
                    };
                    let deadline = agent_desktop_core::Deadline::after(
                        args.timeout_ms.unwrap_or(15_000),
                    )
                    .map_err(AppError::from)?;
                    match agent_desktop_linux::send_absolute_pointer_click(
                        (x, y),
                        core_button,
                        count,
                        deadline,
                    ) {
                        Ok(()) => {
                            return Ok(json!({
                                "action": format!("{:?}", args.action),
                                "mechanism": "mutter-remote-desktop",
                                "coordinates": [x, y],
                                "coordinate_source": args.coords_source,
                                "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                            }));
                        }
                        Err(error) => {
                            if backend == "mutter" {
                                return Err(AppError::from(error));
                            }
                            mutter_error = Some(error);
                        }
                    }
                }
                let displays = self
                    .adapter
                    .list_displays(agent_desktop_core::Deadline::standard()?)
                    .map_err(AppError::from)?;
                let display = displays
                    .iter()
                    .find(|display| display.is_primary)
                    .or_else(|| displays.first())
                    .ok_or_else(|| {
                        invalid("No display is available for absolute pointer mapping")
                    })?;
                let (dx, dy) = targeting::to_device_units(
                    x - display.bounds.x,
                    y - display.bounds.y,
                    display.bounds.width as u32,
                    display.bounds.height as u32,
                );
                let mut device = match uinput::VirtualInput::open() {
                    Ok(device) => device,
                    Err(error) => {
                        if let Some(mutter_error) = mutter_error {
                            return Err(AppError::from(mutter_error));
                        }
                        return Err(kernel_error(error));
                    }
                };
                device
                    .move_abs(dx, dy)
                    .map_err(|e| kernel_error(e.into()))?;
                device
                    .click(button, count)
                    .map_err(|e| kernel_error(e.into()))?;
                Ok(json!({
                    "action": format!("{:?}", args.action),
                    "mechanism": "uinput",
                    "coordinates": [x, y],
                    "coordinate_source": args.coords_source,
                    "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"},
                }))
            }
            _ => Err(AppError::Adapter(
                agent_desktop_core::AdapterError::new(
                    ErrorCode::ActionNotSupported,
                    format!("Kernel input does not implement {:?}", args.action),
                )
                .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
            )),
        }
    }

    // ---- Capture ---------------------------------------------------------

    pub fn screenshot(
        &self,
        app: Option<&str>,
        window_id: Option<&str>,
        screen: Option<usize>,
    ) -> Envelope {
        let started = Instant::now();
        let mut record = AuditRecord::new("screenshot");
        if let Err(error) = self.require_enabled() {
            return self.finish("screenshot", record, started, Err(error));
        }
        record.app = app.map(str::to_owned);
        record.window_id = window_id.map(str::to_owned);
        if let Some(app) = app
            && let Err(reason) = self.policy.check_app(app)
        {
            return self.finish("screenshot", record, started, Err(policy_error(reason)));
        }
        if std::env::var("PALIMIND_DESKTOP_SCREENSHOT")
            .map(|value| value.eq_ignore_ascii_case("off"))
            .unwrap_or(false)
        {
            return self.finish(
                "screenshot",
                record,
                started,
                Err(policy_error_typed(
                    "POLICY_DENIED",
                    "Screenshots are disabled by PALIMIND_DESKTOP_SCREENSHOT=off",
                )),
            );
        }

        let id = format!(
            "shot-{}-{}",
            std::process::id(),
            started.elapsed().as_nanos()
        );
        let path = self.policy.artifacts_dir().join(format!("{id}.png"));
        if let Err(error) = self.policy.prepare_dirs() {
            return self.finish("screenshot", record, started, Err(AppError::Io(error)));
        }
        let wants_full_screen = screen.is_none() && app.is_none() && window_id.is_none();
        let token_present = self
            .policy
            .desktop_dir()
            .join("screencast-token")
            .is_file();
        // A restore token means the ScreenCast source was approved once, so it
        // is both prompt-free and the only working full-screen route when the
        // Screenshot portal has been denied. Try it before the per-call
        // Screenshot dialog.
        if targeting::session_is_wayland() && wants_full_screen && token_present {
            if let Ok(capture) = crate::screencast::capture_screen(
                self.policy.desktop_dir(),
                &path,
                screencast_duration("PALIMIND_DESKTOP_SCREENCAST_CONSENT_MS", 20_000),
                screencast_duration("PALIMIND_DESKTOP_SCREENCAST_CAPTURE_MS", 10_000),
            ) {
                let data = json!({
                    "path": capture.path.to_string_lossy(),
                    "format": "png",
                    "width": capture.width,
                    "height": capture.height,
                    "scale_factor": 1.0,
                    "capture": "screencast",
                    "scope": "screen",
                    "node_id": capture.node_id,
                    "restore_token_saved": capture.restore_token_saved,
                    "screenshot_id": id,
                    "note": "Wayland ScreenCast capture; the image is the whole monitor.",
                });
                return self.finish("screenshot", record, started, Ok(data));
            }
        }
        let result = screenshot::execute(
            ScreenshotArgs {
                app: app.map(str::to_owned),
                window_id: window_id.map(str::to_owned),
                screen,
                output_path: Some(path.clone()),
            },
            self.adapter,
        );
        // A single window cannot be captured on Wayland, and the Screenshot
        // portal may refuse or be denied. Fall back to the persistent
        // ScreenCast stream, which is also the vision route for canvas apps.
        let result = match result {
            Err(AppError::Adapter(error))
                if targeting::session_is_wayland()
                    && matches!(
                        error.code,
                        ErrorCode::PlatformNotSupported | ErrorCode::PermDenied
                    ) =>
            {
                match crate::screencast::capture_screen(
                    self.policy.desktop_dir(),
                    &path,
                    screencast_duration("PALIMIND_DESKTOP_SCREENCAST_CONSENT_MS", 30_000),
                    screencast_duration("PALIMIND_DESKTOP_SCREENCAST_CAPTURE_MS", 10_000),
                ) {
                    Ok(capture) => Ok(json!({
                        "path": capture.path.to_string_lossy(),
                        "format": "png",
                        "width": capture.width,
                        "height": capture.height,
                        "scale_factor": 1.0,
                        "capture": "screencast",
                        "scope": "screen",
                        "node_id": capture.node_id,
                        "restore_token_saved": capture.restore_token_saved,
                        "note": "Wayland ScreenCast fallback: the image is the whole monitor; OCR boxes are screen coordinates. Approve the source dialog once and later captures reuse the restore token.",
                    })),
                    Err(screencast_error) => Err(AppError::Adapter(
                        screencast_error.with_suggestion(
                            "The portal screenshot failed and the ScreenCast fallback did not complete. Approve the ScreenCast source dialog when it appears, or retry with screen=0.",
                        ),
                    )),
                }
            }
            other => other,
        };
        let result = result.map(|mut data| {
            data["screenshot_id"] = json!(id);
            data["note"] = data
                .get("note")
                .cloned()
                .unwrap_or_else(|| json!("Screenshot is local only and never uploaded."));
            data
        });
        self.finish("screenshot", record, started, result)
    }

    /// A destructive label on the live target (or on the typed payload) needs
    /// an explicit user confirmation. Reading the stored ref's captured name
    /// closes the case a bare `@s1:e7` would otherwise hide.
    fn destructive_reason(&self, args: &ActArgs) -> Option<AppError> {
        if !args.action.is_mutating() || args.confirm_destructive {
            return None;
        }
        let mut labels: Vec<String> = Vec::new();
        if let Some(text) = args.text.as_deref() {
            labels.push(text.to_owned());
        }
        if let Some(value) = args.value.as_deref() {
            labels.push(value.to_owned());
        }
        if let Some(reference) = args.reference.as_deref()
            && let Ok(store) = agent_desktop_core::RefStore::for_session(self.context.session_id())
            && let Ok(entry) = store.load_ref(reference)
        {
            labels.extend(
                [
                    entry.identity.name,
                    entry.identity.description,
                    entry.identity.value,
                ]
                .into_iter()
                .flatten(),
            );
        }
        if labels
            .iter()
            .any(|label| self.policy.looks_destructive(label))
        {
            return Some(AppError::Adapter(
                agent_desktop_core::AdapterError::new(
                    ErrorCode::PolicyDenied,
                    "This action looks destructive and needs an explicit user confirmation",
                )
                .with_suggestion(
                    "Ask the user to confirm the destructive action, then retry with confirm_destructive=true.",
                )
                .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
            ));
        }
        None
    }

    fn resolve_target(
        &self,
        app: Option<&str>,
        window_id: Option<&str>,
    ) -> Result<Target, AppError> {
        // Resolve an app alias to a real window when the accessibility name
        // differs from the name the user/model used. Flatpak and snap apps are
        // often exposed under their sandbox proxy (for example
        // "xdg-dbus-proxy"), and a launcher name such as "zen" never matches
        // the AT-SPI app name. Resolving here also fills the pid, which the
        // snapshot projection reports to the caller.
        if let Some(app) = app {
            // Never use an alias to sidestep policy: a protected or
            // disallowed name must fail as itself, not be remapped to a
            // different window that happens to be allowed.
            if self.policy.check_app(app).is_err() {
                return Ok(Target {
                    app: Some(app.to_owned()),
                    pid: None,
                    window: None,
                });
            }
            let windows = self.windows_for_aliases();
            let exact: Vec<&WindowInfo> = windows
                .iter()
                .filter(|window| {
                    window.app.eq_ignore_ascii_case(app) && pid_is_alive(window.pid)
                })
                .collect();
            if !exact.is_empty() {
                let chosen = exact
                    .iter()
                    .find(|window| window.state.is_focused)
                    .copied()
                    .unwrap_or(exact[0]);
                return Ok(Target {
                    app: Some(chosen.app.clone()),
                    pid: Some(chosen.pid),
                    // One window: address it by id so a stale twin cannot
                    // produce AMBIGUOUS_TARGET. Several windows: leave it to
                    // the engine's focused-window choice.
                    window: (exact.len() == 1).then(|| chosen.clone()),
                });
            }
            if let Some(window) = alias_window(&windows, app) {
                // The resolved window is also subject to policy: never alias
                // onto a protected or blocked process.
                if self.policy.check_app(&window.app).is_ok() {
                    return Ok(Target {
                        app: Some(window.app.clone()),
                        pid: Some(window.pid),
                        window: Some(window),
                    });
                }
            }
            return Ok(Target {
                app: Some(app.to_owned()),
                pid: None,
                window: None,
            });
        }
        if let Some(window_id) = window_id {
            let windows = self.adapter.list_windows(
                &WindowFilter {
                    focused_only: false,
                    app: None,
                },
                agent_desktop_core::Deadline::standard()?,
            )?;
            if let Some(window) = windows
                .iter()
                .find(|window| window.id == window_id && pid_is_alive(window.pid))
            {
                return Ok(Target {
                    app: Some(window.app.clone()),
                    pid: Some(window.pid),
                    window: Some(window.clone()),
                });
            }
        }
        Ok(Target {
            app: None,
            pid: None,
            window: None,
        })
    }

    /// Best-effort inventory used only for alias resolution. A failure here
    /// must not fail the observation: the engine still gets the original name
    /// and returns its own APP_NOT_FOUND hint.
    fn windows_for_aliases(&self) -> Vec<WindowInfo> {
        let Ok(deadline) = agent_desktop_core::Deadline::standard() else {
            return Vec::new();
        };
        self.adapter
            .list_windows(
                &WindowFilter {
                    focused_only: false,
                    app: None,
                },
                deadline,
            )
            .unwrap_or_default()
            .into_iter()
            .filter(|window| pid_is_alive(window.pid))
            .collect()
    }
}

/// Normalize a name for alias comparison: lowercase, and drop punctuation so
/// "org.gnome.Calculator", "gnome-calculator" and "Gnome Calculator" meet.
fn alias_key(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn proc_field(pid: ProcessId, file: &str) -> Option<String> {
    std::fs::read_to_string(format!("/proc/{}/{file}", pid.get())).ok()
}

/// Pick a unique window for an alias the accessibility name did not match.
/// Strong evidence (process name, executable, cgroup) beats a title match.
/// A title match is only accepted when it is unique and the alias is long
/// enough not to be a generic word.
fn alias_window(windows: &[WindowInfo], app: &str) -> Option<WindowInfo> {
    let raw = app.trim().to_lowercase();
    let needle = alias_key(&raw);
    if needle.is_empty() {
        return None;
    }
    // Reverse-DNS ids such as org.gnome.Calculator also answer to their last
    // segment.
    let tail = raw
        .rsplit('.')
        .next()
        .map(alias_key)
        .filter(|value| !value.is_empty());
    let keys: Vec<String> = [needle.clone(), tail.unwrap_or_default()]
        .into_iter()
        .filter(|value| !value.is_empty())
        .collect();

    let strong: Vec<WindowInfo> = windows
        .iter()
        .filter(|window| {
            let mut evidence = vec![alias_key(&window.app)];
            if let Some(comm) = proc_field(window.pid, "comm") {
                evidence.push(alias_key(&comm));
            }
            if let Some(exe) = proc_field(window.pid, "exe") {
                evidence.push(alias_key(&exe));
            }
            if let Some(cgroup) = proc_field(window.pid, "cgroup") {
                evidence.push(alias_key(&cgroup));
            }
            let evidence = evidence.join(" ");
            keys.iter().any(|key| evidence.contains(key))
        })
        .cloned()
        .collect();
    if strong.len() == 1 {
        return strong.into_iter().next();
    }
    if !strong.is_empty() {
        return None;
    }
    if needle.len() < 3 {
        return None;
    }
    let weak: Vec<WindowInfo> = windows
        .iter()
        .filter(|window| {
            let title = alias_key(&window.title);
            keys.iter().any(|key| title.contains(key))
        })
        .cloned()
        .collect();
    (weak.len() == 1).then(|| weak.into_iter().next()).flatten()
}

fn pid_is_alive(pid: ProcessId) -> bool {
    // SAFETY: signal 0 performs only an existence/permission check.
    let result = unsafe { libc::kill(pid.get() as libc::pid_t, 0) };
    result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

fn filter_dead_windows(value: Value) -> Value {
    let Some(windows) = value.as_array() else {
        return value;
    };
    Value::Array(
        windows
            .iter()
            .filter(|window| {
                window.get("pid").and_then(Value::as_u64).is_none_or(|pid| {
                    pid_is_alive(ProcessId::new(u32::try_from(pid).unwrap_or(u32::MAX)))
                })
            })
            .cloned()
            .collect(),
    )
}

pub struct Target {
    pub app: Option<String>,
    pub pid: Option<ProcessId>,
    pub window: Option<WindowInfo>,
}

#[derive(Debug, Clone, Copy, clap::ValueEnum)]
pub enum AppsKind {
    Apps,
    Windows,
    Displays,
}

impl AppsKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Apps => "apps",
            Self::Windows => "windows",
            Self::Displays => "displays",
        }
    }
}


fn screencast_duration(name: &str, default_ms: u64) -> std::time::Duration {
    let ms = std::env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(default_ms);
    std::time::Duration::from_millis(ms)
}

pub fn project_snapshot(value: Value, target: &Target, max_nodes: usize, full: bool) -> Value {
    let snapshot_id = value.get("snapshot_id").cloned().unwrap_or(Value::Null);
    let complete = value
        .get("complete")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let tree = value.get("tree").cloned().unwrap_or(Value::Null);
    let bounds_space = if targeting::session_is_wayland() {
        "window"
    } else {
        "screen"
    };
    let mut nodes = Vec::new();
    flatten(&tree, &mut nodes, bounds_space, false, full);
    let observed = nodes.len();
    let truncated = observed > max_nodes;
    nodes.truncate(max_nodes);
    let window = value
        .get("window")
        .cloned()
        .filter(|value| !value.is_null())
        .unwrap_or_else(|| {
            target
                .window
                .as_ref()
                .and_then(|window| serde_json::to_value(window).ok())
                .unwrap_or(Value::Null)
        });
    let app_name = value
        .get("app")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| target.app.clone());
    let mut output = json!({
        "snapshot_id": snapshot_id,
        "app": {
            "name": app_name,
            "pid": target.pid.map(ProcessId::get),
            "desktop_id": Value::Null,
        },
        "window": window,
        "complete": complete && !truncated,
        "truncated": truncated || !complete,
        "node_count": nodes.len(),
        "bounds_space": bounds_space,
        "nodes": nodes,
        "identity_unproven": value.get("identity_unproven").cloned().unwrap_or(Value::Null),
        "nodes_observed": value.get("nodes_observed").cloned().unwrap_or(Value::Null),
    });
    if full {
        output["tree"] = tree;
    }
    output
}

fn flatten(
    node: &Value,
    out: &mut Vec<Value>,
    bounds_space: &str,
    redact: bool,
    include_offscreen: bool,
) {
    let Some(object) = node.as_object() else {
        return;
    };
    let role = object
        .get("role")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let states: Vec<String> = object
        .get("states")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    // Compact snapshots describe what is on screen. Offscreen and defunct
    // nodes are still reachable through find/wait, but including thousands of
    // closed menu items in every snapshot is pure token cost.
    if !include_offscreen
        && states
            .iter()
            .any(|state| matches!(state.as_str(), "offscreen" | "defunct"))
    {
        return;
    }
    let secure = redact
        || role.to_ascii_lowercase().contains("password")
        || states
            .iter()
            .any(|state| matches!(state.as_str(), "secure" | "protected" | "password"));
    let name = if secure {
        Some("[redacted]".to_owned())
    } else {
        object
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_owned)
    };
    let bounds = object.get("bounds").and_then(|bounds| {
        let x = bounds.get("x")?.as_f64()?;
        let y = bounds.get("y")?.as_f64()?;
        let width = bounds.get("width")?.as_f64()?;
        let height = bounds.get("height")?.as_f64()?;
        Some(json!([x, y, width, height]))
    });
    let actions = object
        .get("available_actions")
        .cloned()
        .unwrap_or_else(|| json!([]));
    out.push(json!({
        "ref": object.get("ref_id").cloned().unwrap_or(Value::Null),
        "role": role,
        "name": name,
        "value": if secure { Value::Null } else { object.get("value").cloned().unwrap_or(Value::Null) },
        "description": if secure { Value::Null } else { object.get("description").cloned().unwrap_or(Value::Null) },
        "native_id": object.get("native_id").cloned().unwrap_or(Value::Null),
        "bounds": bounds,
        "bounds_space": bounds_space,
        "states": states,
        "actions": actions,
        "redacted": secure,
    }));
    if let Some(children) = object.get("children").and_then(Value::as_array) {
        for child in children {
            flatten(child, out, bounds_space, secure, include_offscreen);
        }
    }
}

fn incomplete_locator(error: &AppError) -> bool {
    let AppError::Adapter(adapter_error) = error else {
        return false;
    };
    if adapter_error.code != ErrorCode::Timeout {
        return false;
    }
    adapter_error
        .details
        .as_ref()
        .and_then(|details| details.get("kind"))
        .and_then(Value::as_str)
        .is_some_and(|kind| kind.starts_with("locator_"))
}

/// Filter already-projected snapshot nodes with the same broad semantics as
/// `find`: case-insensitive substring matches on role, name and text.
fn filter_projected_matches(
    nodes: Vec<Value>,
    role: Option<&str>,
    name: Option<&str>,
    text: Option<&str>,
    limit: usize,
) -> Vec<Value> {
    let role = role.map(str::to_lowercase);
    let name = name.map(str::to_lowercase);
    let text = text.map(str::to_lowercase);
    let field = |node: &Value, key: &str| {
        node.get(key)
            .and_then(Value::as_str)
            .map(str::to_lowercase)
            .unwrap_or_default()
    };
    nodes
        .into_iter()
        .filter(|node| {
            if node.get("ref").is_none_or(Value::is_null) {
                return false;
            }
            if role
                .as_ref()
                .is_some_and(|wanted| !field(node, "role").contains(wanted))
            {
                return false;
            }
            if name
                .as_ref()
                .is_some_and(|wanted| !field(node, "name").contains(wanted))
            {
                return false;
            }
            if text.as_ref().is_some_and(|wanted| {
                !["name", "value", "description"]
                    .iter()
                    .any(|key| field(node, key).contains(wanted))
            }) {
                return false;
            }
            true
        })
        .take(limit)
        .map(|node| {
            json!({
                "ref": node.get("ref").cloned().unwrap_or(Value::Null),
                "role": node.get("role").cloned().unwrap_or(Value::Null),
                "name": node.get("name").cloned().unwrap_or(Value::Null),
                "value": node.get("value").cloned().unwrap_or(Value::Null),
                "description": node.get("description").cloned().unwrap_or(Value::Null),
                "states": node.get("states").cloned().unwrap_or_else(|| json!([])),
                "bounds": node.get("bounds").cloned().unwrap_or(Value::Null),
                "interactive": node
                    .get("actions")
                    .and_then(Value::as_array)
                    .is_some_and(|actions| !actions.is_empty()),
            })
        })
        .collect()
}

fn endpoint(
    reference: Option<&str>,
    x: Option<f64>,
    y: Option<f64>,
    missing: &str,
) -> Result<DragEndpoint, AppError> {
    match (reference, x, y) {
        (Some(reference), _, _) => Ok(DragEndpoint {
            ref_id: Some(reference.to_owned()),
            xy: None,
        }),
        (None, Some(x), Some(y)) => Ok(DragEndpoint {
            ref_id: None,
            xy: Some((x, y)),
        }),
        _ => Err(invalid(missing)),
    }
}

fn require_ref<'a>(reference: Option<&'a str>, action: &str) -> Result<&'a str, AppError> {
    reference.ok_or_else(|| invalid(format!("{action} requires --ref")))
}

fn invalid(message: impl Into<String>) -> AppError {
    AppError::Adapter(
        agent_desktop_core::AdapterError::new(ErrorCode::InvalidArgs, message)
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
    )
}

fn policy_error(reason: String) -> AppError {
    policy_error_typed("POLICY_DENIED", reason)
}

fn policy_error_typed(code: &str, reason: impl Into<String>) -> AppError {
    let code = match code {
        "POLICY_DENIED" => ErrorCode::PolicyDenied,
        "PLATFORM_NOT_SUPPORTED" => ErrorCode::PlatformNotSupported,
        _ => ErrorCode::PolicyDenied,
    };
    AppError::Adapter(
        agent_desktop_core::AdapterError::new(code, reason)
            .with_suggestion(
                "Adjust the desktop app policy in Settings, or ask the user to allow this app.",
            )
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
    )
}

fn unproven_coordinates(reason: String) -> AppError {
    AppError::Adapter(
        agent_desktop_core::AdapterError::new(ErrorCode::PlatformNotSupported, reason)
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
    )
}

fn kernel_error(error: uinput::KernelInputError) -> AppError {
    let code = match &error {
        uinput::KernelInputError::PermissionDenied(_) => ErrorCode::PermDenied,
        uinput::KernelInputError::Io(io) if io.kind() == std::io::ErrorKind::InvalidInput => {
            ErrorCode::InvalidArgs
        }
        uinput::KernelInputError::Io(io) if io.kind() == std::io::ErrorKind::WouldBlock => {
            ErrorCode::Internal
        }
        uinput::KernelInputError::Io(_) => ErrorCode::ActionFailed,
    };
    AppError::Adapter(
        agent_desktop_core::AdapterError::new(code, error.to_string())
            .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()),
    )
}

#[cfg(test)]
mod projection_tests {
    use super::*;

    fn target() -> Target {
        Target {
            app: Some("demo".to_owned()),
            pid: Some(ProcessId::new(1)),
            window: None,
        }
    }

    #[test]
    fn projection_drops_offscreen_subtrees_and_redacts_secure_fields() {
        let tree = json!({
            "role": "window",
            "name": "Calculator",
            "ref_id": null,
            "children": [
                {
                    "role": "button",
                    "name": "7",
                    "ref_id": "@s1:e7",
                    "bounds": {"x": 1.0, "y": 2.0, "width": 3.0, "height": 4.0},
                    "states": [],
                    "available_actions": ["Click"],
                    "children": []
                },
                {
                    "role": "menu",
                    "name": "Closed menu",
                    "states": ["offscreen"],
                    "children": [
                        {"role": "menuitem", "name": "Delete everything", "children": []}
                    ]
                },
                {
                    "role": "password text",
                    "name": "Password",
                    "value": "hunter2",
                    "states": ["secure"],
                    "children": []
                }
            ]
        });
        let out = project_snapshot(
            json!({"snapshot_id": "s1", "app": "demo", "complete": true, "tree": tree}),
            &target(),
            300,
            false,
        );
        assert_eq!(out["node_count"], 3);
        let nodes = out["nodes"].as_array().unwrap();
        assert!(nodes.iter().any(|node| node["name"] == "7"));
        assert!(!nodes.iter().any(|node| node["name"] == "Delete everything"));
        let secure = nodes
            .iter()
            .find(|node| node["redacted"] == true)
            .expect("secure node");
        assert_eq!(secure["name"], "[redacted]");
        assert!(secure["value"].is_null());
        assert!(!out.to_string().contains("hunter2"));
    }

    #[test]
    fn projection_caps_the_node_budget_and_marks_truncation() {
        let children: Vec<Value> = (0..10)
            .map(|index| {
                json!({
                    "role": "button",
                    "name": format!("b{index}"),
                    "ref_id": format!("@s1:e{index}"),
                    "children": []
                })
            })
            .collect();
        let tree = json!({"role": "window", "children": children, "ref_id": null});
        let out = project_snapshot(
            json!({"snapshot_id": "s1", "app": "demo", "complete": true, "tree": tree}),
            &target(),
            4,
            false,
        );
        assert_eq!(out["nodes"].as_array().unwrap().len(), 4);
        assert_eq!(out["truncated"], true);
        assert_eq!(out["complete"], false);
    }

    #[test]
    fn fallback_match_filter_is_case_insensitive_and_keeps_refs() {
        let nodes = vec![
            json!({
                "ref": "@s1:e1",
                "role": "link",
                "name": "Sign in",
                "value": null,
                "description": null,
                "states": [],
                "bounds": [1.0, 2.0, 3.0, 4.0],
                "actions": ["Click"]
            }),
            json!({
                "ref": null,
                "role": "group",
                "name": "Sign in wrapper",
                "value": null,
                "description": null,
                "states": [],
                "bounds": null,
                "actions": []
            }),
            json!({
                "ref": "@s1:e2",
                "role": "button",
                "name": "Delete",
                "value": null,
                "description": null,
                "states": [],
                "bounds": [5.0, 6.0, 7.0, 8.0],
                "actions": ["Click"]
            }),
        ];
        let matches = filter_projected_matches(nodes, Some("LINK"), Some("sign"), None, 20);
        assert_eq!(matches.len(), 1, "only referenced nodes are matches");
        assert_eq!(matches[0]["ref"], "@s1:e1");
        assert_eq!(matches[0]["interactive"], true);

        let text_matches = filter_projected_matches(
            vec![json!({
                "ref": "@s1:e3",
                "role": "statictext",
                "name": "Saved",
                "value": "Saved",
                "description": null,
                "states": [],
                "bounds": null,
                "actions": []
            })],
            None,
            None,
            Some("saved"),
            20,
        );
        assert_eq!(text_matches.len(), 1);
    }

    #[test]
    fn alias_keys_ignore_punctuation_and_reverse_dns() {
        assert_eq!(alias_key("org.gnome.Calculator"), "orggnomecalculator");
        assert_eq!(alias_key("gnome-calculator"), "gnomecalculator");
        assert_eq!(alias_key("Visual Studio Code"), "visualstudiocode");
    }
}
