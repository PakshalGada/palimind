#![cfg_attr(not(test), deny(clippy::unwrap_used, clippy::expect_used))]

mod actions;
mod adapter;
mod input;
mod notifications;
mod system;
mod tree;

pub use adapter::LinuxAdapter;
pub use input::clipboard::owner::owner_entry::run_from_env as clipboard_owner_from_env;
pub use input::wayland::kept_session::end as end_input_session;
pub use input::x11::signal_release::enable as release_input_on_signals;

// Palimind: the following two helpers are product deltas over upstream
// agent-desktop v1.1.0. They expose the existing Mutter RemoteDesktop pointer
// and clipboard machinery to the Palimind wrapper without changing the
// upstream command/action modules.

/// Deliver one absolute pointer click through Mutter's RemoteDesktop session.
///
/// This is the Wayland pointer fallback that does not need `/dev/uinput`: the
/// compositor owns the coordinate space and performs the move/click. The
/// caller must have proven that `point` is global screen coordinates; the
/// function refuses anything else through the same display mapping the engine
/// uses for physical input.
pub fn send_absolute_pointer_click(
    point: (f64, f64),
    button: agent_desktop_core::MouseButton,
    count: u32,
    deadline: agent_desktop_core::Deadline,
) -> Result<(), agent_desktop_core::AdapterError> {
    let displays = system::list_displays(deadline)?;
    let event = agent_desktop_core::MouseEvent {
        point: agent_desktop_core::Point {
            x: point.0,
            y: point.1,
        },
        button,
        kind: agent_desktop_core::MouseEventKind::Click { count },
        modifiers: Vec::new(),
    };
    // The caller already proved the coordinate source. There is no AT-SPI
    // element to re-validate here, so the gate is a no-op.
    let mut gate = || Ok(());
    input::wayland::pointer_send::send(&event, &displays, &mut gate, deadline)
}

/// Type arbitrary Unicode text through the compositor by putting it on the
/// clipboard and sending Ctrl+V, then restoring the previous text clipboard.
/// Used when the kernel keymap (US ASCII only) cannot represent the text.
///
/// `wl-copy` is preferred; `xclip` is the fallback because GNOME's XWayland
/// bridge makes the X11 clipboard visible to Wayland applications. Both are
/// plain processes, so no desktop-runtime dependency is added.
pub fn type_text_via_clipboard(
    text: &str,
    deadline: agent_desktop_core::Deadline,
) -> Result<bool, agent_desktop_core::AdapterError> {
    use agent_desktop_core::{
        Action, ActionOps, ActionRequest, InteractionLease, KeyCombo, Modifier, NativeHandle,
        SystemOps,
    };
    use std::io::Write;
    use std::process::{Command, Stdio};

    fn tool_available(name: &str) -> bool {
        Command::new(name)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok()
    }

    fn run(
        program: &str,
        args: &[&str],
        input: Option<&str>,
        capture: bool,
    ) -> Result<Vec<u8>, std::io::Error> {
        let mut command = Command::new(program);
        command.args(args).stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        });
        if capture {
            command.stdout(Stdio::piped()).stderr(Stdio::piped());
        } else {
            // Clipboard owners (notably xclip) fork a child that can outlive
            // the parent. A piped stdout would then stay open and make
            // wait_with_output block forever, so a write must not capture it.
            command.stdout(Stdio::null()).stderr(Stdio::null());
        }
        let mut child = command.spawn()?;
        if let Some(input) = input {
            if let Some(mut stdin) = child.stdin.take() {
                stdin.write_all(input.as_bytes())?;
            }
        }
        let output = child.wait_with_output()?;
        if !output.status.success() && capture {
            return Err(std::io::Error::other(
                String::from_utf8_lossy(&output.stderr).trim().to_owned(),
            ));
        }
        Ok(output.stdout)
    }

    let wl = tool_available("wl-copy") && tool_available("wl-paste");
    let xclip = !wl && tool_available("xclip");
    if !wl && !xclip {
        return Err(agent_desktop_core::AdapterError::new(
            agent_desktop_core::ErrorCode::ActionFailed,
            "Unicode typing needs a clipboard tool (`wl-copy` from wl-clipboard, or `xclip`)",
        )
        .with_suggestion(
            "Install wl-clipboard (recommended on Wayland) or xclip, then retry type_text",
        )
        .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered()));
    }
    let read = || -> Option<String> {
        let bytes = if wl {
            run("wl-paste", &["--no-newline"], None, true).ok()?
        } else {
            run("xclip", &["-selection", "clipboard", "-o"], None, true).ok()?
        };
        String::from_utf8(bytes).ok()
    };
    let write = |value: &str| -> Result<(), std::io::Error> {
        if wl {
            run("wl-copy", &[], Some(value), false).map(|_| ())
        } else {
            run("xclip", &["-selection", "clipboard"], Some(value), false).map(|_| ())
        }
    };
    let clear = || -> Result<(), std::io::Error> {
        if wl {
            run("wl-copy", &["--clear"], None, false).map(|_| ())
        } else {
            run("xclip", &["-selection", "clipboard"], Some(""), false).map(|_| ())
        }
    };

    let previous = read();
    write(text).map_err(|error| {
        agent_desktop_core::AdapterError::new(
            agent_desktop_core::ErrorCode::ActionFailed,
            format!("The clipboard could not be set for typing: {error}"),
        )
        .with_disposition(agent_desktop_core::DeliverySemantics::not_delivered())
    })?;

    let adapter = LinuxAdapter::new();
    let lease: InteractionLease = adapter.acquire_interaction_lease(deadline)?;
    let combo = KeyCombo {
        key: "v".to_owned(),
        modifiers: vec![Modifier::Ctrl],
    };
    let request = ActionRequest::headless(Action::PressKey(combo));
    let result = adapter.execute_action(&NativeHandle::null(), request, &lease);
    // Give the focused application a moment to read the clipboard before the
    // previous owner is restored.
    std::thread::sleep(std::time::Duration::from_millis(400));
    let restored = match previous {
        Some(value) => write(&value).is_ok(),
        None => clear().is_ok(),
    };
    result?;
    Ok(restored)
}
