//! `palimind-desktop` — Linux desktop control for Palimind.
//!
//! One binary, two modes:
//!
//! * one-shot CLI (`status`, `apps`, `snapshot`, `find`, `wait`, `act`,
//!   `screenshot`, `launch`) for debugging and for the Python client's
//!   fallback path;
//! * `serve`, a newline-delimited JSON-RPC daemon over stdio that the Python
//!   backend supervises.
//!
//! Both modes share the same dispatcher, policy and audit log. Observation is
//! AT-SPI2; screenshots are on demand only; physical input is XTEST (X11),
//! Mutter RemoteDesktop (Wayland) or the opt-in `/dev/uinput` kernel backend.

mod commands;
mod daemon;
mod envelope;
mod policy;
mod state;
mod targeting;
mod uinput;

use std::process::ExitCode;

use agent_desktop_core::{CommandContext, Direction, PlatformAdapter};
use clap::{Parser, Subcommand};
use serde_json::Value;

use commands::{ActAction, ActArgs, AppsKind, Dispatcher};
use envelope::Envelope;
use policy::Policy;
use targeting::CoordinateSource;

#[derive(Debug, Parser)]
#[command(
    name = "palimind-desktop",
    version,
    about = "Palimind Linux desktop control (AT-SPI2 observation + kernel-level input)"
)]
struct Cli {
    /// Allow physical input to activate/focus the target (default: headless).
    #[arg(long, global = true)]
    headed: bool,
    /// Session id whose snapshot refs are used. Defaults to PALIMIND_DESKTOP_SESSION or "palimind".
    #[arg(long, global = true)]
    session: Option<String>,
    /// Pretty-print the JSON envelope.
    #[arg(long, global = true)]
    pretty: bool,
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Platform, accessibility, input and policy status.
    Status,
    /// List applications, windows or displays.
    Apps {
        #[arg(value_enum, default_value = "apps")]
        kind: AppsKind,
        #[arg(long)]
        app: Option<String>,
    },
    /// Capture a compact accessibility snapshot (no screenshot).
    Snapshot {
        #[arg(long)]
        app: Option<String>,
        #[arg(long = "window-id")]
        window_id: Option<String>,
        /// Interactive elements and labelled containers only.
        #[arg(short = 'i', long = "interactive-only")]
        interactive_only: bool,
        /// Explicit escape hatch: full tree, compact off.
        #[arg(long)]
        full: bool,
        #[arg(long = "max-depth", default_value_t = 12)]
        max_depth: u8,
        #[arg(long = "max-nodes", default_value_t = 300)]
        max_nodes: usize,
        /// Snapshot deadline in milliseconds (large Chromium windows need more).
        #[arg(long = "timeout-ms")]
        timeout_ms: Option<u64>,
    },
    /// Search the live accessibility tree.
    Find {
        #[arg(long)]
        app: Option<String>,
        #[arg(long = "window-id")]
        window_id: Option<String>,
        #[arg(long)]
        role: Option<String>,
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        text: Option<String>,
        #[arg(long, default_value_t = 20)]
        limit: usize,
        #[arg(long = "timeout-ms")]
        timeout_ms: Option<u64>,
    },
    /// Wait for an element, text, window or a fixed delay.
    Wait {
        #[arg(long)]
        app: Option<String>,
        #[arg(long = "window-id")]
        window_id: Option<String>,
        #[arg(long)]
        ms: Option<u64>,
        #[arg(long)]
        element: Option<String>,
        #[arg(long)]
        window: Option<String>,
        #[arg(long)]
        text: Option<String>,
        #[arg(long = "timeout-ms", default_value_t = 5_000)]
        timeout_ms: u64,
    },
    /// One semantic action on a ref, or a physical fallback.
    Act {
        #[arg(value_enum)]
        action: ActAction,
        #[arg(long = "ref")]
        reference: Option<String>,
        #[arg(long)]
        text: Option<String>,
        #[arg(long)]
        value: Option<String>,
        #[arg(long)]
        key: Option<String>,
        #[arg(long, value_enum, default_value = "down")]
        direction: DirectionArg,
        #[arg(long, default_value_t = 3)]
        amount: u32,
        #[arg(long, allow_hyphen_values = true)]
        x: Option<f64>,
        #[arg(long, allow_hyphen_values = true)]
        y: Option<f64>,
        #[arg(long = "to-ref")]
        to_ref: Option<String>,
        #[arg(long = "to-x", allow_hyphen_values = true)]
        to_x: Option<f64>,
        #[arg(long = "to-y", allow_hyphen_values = true)]
        to_y: Option<f64>,
        #[arg(long)]
        app: Option<String>,
        #[arg(long = "window-id")]
        window_id: Option<String>,
        /// Where physical coordinates came from: user, screenshot, compositor, atspi.
        #[arg(long = "coords-source", default_value = "unknown")]
        coords_source: String,
        /// Use the /dev/uinput kernel backend for global keys/typing/pointer.
        #[arg(long)]
        kernel: bool,
        #[arg(long = "timeout-ms")]
        timeout_ms: Option<u64>,
        /// Acknowledge that the action looks destructive.
        #[arg(long = "confirm-destructive")]
        confirm_destructive: bool,
    },
    /// Capture a screenshot on demand.
    Screenshot {
        #[arg(long)]
        app: Option<String>,
        #[arg(long = "window-id")]
        window_id: Option<String>,
        #[arg(long)]
        screen: Option<usize>,
    },
    /// Launch an application.
    Launch {
        #[arg(long)]
        app: String,
    },
    /// Run the stdio JSON-RPC daemon used by the Python backend.
    Serve {
        #[arg(long, default_value = "palimind-daemon")]
        name: String,
    },
}

#[derive(Debug, Clone, Copy, clap::ValueEnum)]
enum DirectionArg {
    Up,
    Down,
    Left,
    Right,
}

impl From<DirectionArg> for Direction {
    fn from(value: DirectionArg) -> Self {
        match value {
            DirectionArg::Up => Self::Up,
            DirectionArg::Down => Self::Down,
            DirectionArg::Left => Self::Left,
            DirectionArg::Right => Self::Right,
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct WaitArgs {
    pub ms: Option<u64>,
    pub element: Option<String>,
    pub window: Option<String>,
    pub text: Option<String>,
    pub window_id: Option<String>,
    pub app: Option<String>,
    pub timeout_ms: u64,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    if let Err(error) = state::init() {
        let envelope = Envelope::err("init", agent_desktop_core::AppError::Internal(error));
        print_envelope(&envelope, cli.pretty);
        return ExitCode::FAILURE;
    }
    let policy = Policy::from_env();
    if let Err(error) = policy.prepare_dirs() {
        let envelope = Envelope::err("init", agent_desktop_core::AppError::Io(error));
        print_envelope(&envelope, cli.pretty);
        return ExitCode::FAILURE;
    }
    policy.prune_artifacts();
    agent_desktop_linux::release_input_on_signals();

    if let Command::Serve { name } = &cli.command {
        return serve(&policy, &cli, name);
    }

    let context = match state::context(cli.headed, cli.session.as_deref()) {
        Ok(context) => context,
        Err(error) => {
            print_envelope(&Envelope::err("init", error), cli.pretty);
            return ExitCode::FAILURE;
        }
    };
    let adapter = agent_desktop_linux::LinuxAdapter::new();
    let envelope = dispatch(&policy, &adapter, &context, cli.command);
    let ok = envelope.ok;
    print_envelope(&envelope, cli.pretty);
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn serve(policy: &Policy, cli: &Cli, name: &str) -> ExitCode {
    let session = if std::env::var("PALIMIND_DESKTOP_SESSION")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .is_some()
        || cli.session.is_some()
    {
        cli.session.clone()
    } else {
        match state::start_session(name) {
            Ok(id) => Some(id),
            Err(error) => {
                print_envelope(&Envelope::err("serve", error), cli.pretty);
                return ExitCode::FAILURE;
            }
        }
    };
    let context = match state::context(cli.headed, session.as_deref()) {
        Ok(context) => context,
        Err(error) => {
            print_envelope(&Envelope::err("serve", error), cli.pretty);
            return ExitCode::FAILURE;
        }
    };
    let adapter = agent_desktop_linux::LinuxAdapter::new();
    let code = daemon::serve(&adapter, policy, &context);
    ExitCode::from(code as u8)
}

fn dispatch(
    policy: &Policy,
    adapter: &dyn PlatformAdapter,
    context: &CommandContext,
    command: Command,
) -> Envelope {
    let dispatcher = Dispatcher {
        policy,
        adapter,
        context,
    };
    match command {
        Command::Status => dispatcher.status(),
        Command::Apps { kind, app } => dispatcher.apps(kind, app.as_deref()),
        Command::Snapshot {
            app,
            window_id,
            interactive_only,
            full,
            max_depth,
            max_nodes,
            timeout_ms,
        } => dispatcher.snapshot(
            app.as_deref(),
            window_id.as_deref(),
            interactive_only,
            full,
            max_depth,
            max_nodes,
            timeout_ms,
        ),
        Command::Find {
            app,
            window_id,
            role,
            name,
            text,
            limit,
            timeout_ms,
        } => dispatcher.find(
            app.as_deref(),
            window_id.as_deref(),
            role.as_deref(),
            name.as_deref(),
            text.as_deref(),
            limit,
            timeout_ms,
        ),
        Command::Wait {
            app,
            window_id,
            ms,
            element,
            window,
            text,
            timeout_ms,
        } => dispatcher.wait(WaitArgs {
            ms,
            element,
            window,
            text,
            window_id,
            app,
            timeout_ms,
        }),
        Command::Act {
            action,
            reference,
            text,
            value,
            key,
            direction,
            amount,
            x,
            y,
            to_ref,
            to_x,
            to_y,
            app,
            window_id,
            coords_source,
            kernel,
            timeout_ms,
            confirm_destructive,
        } => {
            let args = ActArgs {
                action,
                reference,
                text,
                value,
                key,
                direction: direction.into(),
                amount,
                x,
                y,
                to_ref,
                to_x,
                to_y,
                app,
                window_id,
                coords_source: CoordinateSource::parse(Some(coords_source.as_str())),
                kernel,
                confirm_destructive,
                timeout_ms,
            };
            dispatcher.act(args)
        }
        Command::Screenshot {
            app,
            window_id,
            screen,
        } => dispatcher.screenshot(app.as_deref(), window_id.as_deref(), screen),
        Command::Launch { app } => dispatcher.act(ActArgs {
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
            coords_source: CoordinateSource::Unknown,
            kernel: false,
            confirm_destructive: false,
            timeout_ms: None,
        }),
        Command::Serve { .. } => Envelope::err(
            "serve",
            agent_desktop_core::AppError::Internal("serve is handled before dispatch".into()),
        ),
    }
}

fn print_envelope(envelope: &Envelope, pretty: bool) {
    let result = if pretty {
        serde_json::to_string_pretty(envelope)
            .map_err(std::io::Error::other)
            .and_then(|text| {
                use std::io::Write;
                let stdout = std::io::stdout();
                let mut out = stdout.lock();
                writeln!(out, "{text}")?;
                out.flush()
            })
    } else {
        envelope::emit(envelope)
    };
    if let Err(error) = result {
        eprintln!("palimind-desktop: failed to write response: {error}");
    }
}

/// Re-exported for the daemon's parameter parsing.
pub fn json_string(value: &Value, key: &str) -> Option<String> {
    value.get(key).and_then(Value::as_str).map(str::to_owned)
}
