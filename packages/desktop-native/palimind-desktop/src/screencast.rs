//! Persistent Wayland screen capture through the xdg-desktop-portal
//! `ScreenCast` interface.
//!
//! The `Screenshot` portal prompts on every call and cannot capture a single
//! window on Wayland. `ScreenCast` returns a PipeWire stream and a
//! `restore_token`: after the one-time source-selection dialog, the token lets
//! later captures reuse the same monitor without prompting. Frame extraction
//! is delegated to `gst-launch-1.0` + `pipewiresrc` (both part of the standard
//! PipeWire/GStreamer packages), so this module adds no browser runtime and no
//! new system service.
//!
//! Palimind never records: the pipeline stops after a handful of frames and
//! the PNG is stored under the same 0700 artifact directory as every other
//! screenshot.

use std::collections::HashMap;
use std::future::Future;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use agent_desktop_core::{AdapterError, Deadline, DeliverySemantics, ErrorCode};
use futures_util::StreamExt;
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Value};
use zbus::{Connection, Proxy};

const PORTAL_SERVICE: &str = "org.freedesktop.portal.Desktop";
const DESKTOP_PATH: &str = "/org/freedesktop/portal/desktop";
const SCREENCAST: &str = "org.freedesktop.portal.ScreenCast";
const REQUEST: &str = "org.freedesktop.portal.Request";
const TOKEN_FILE: &str = "screencast-token";

/// A captured frame. The image is the whole monitor; callers that need a
/// window crop must have a proven global origin (AT-SPI bounds are
/// window-local on Wayland).
pub struct Capture {
    pub path: PathBuf,
    pub width: u32,
    pub height: u32,
    pub node_id: u32,
    pub restore_token_saved: bool,
}

fn timeout_error(message: &str) -> AdapterError {
    AdapterError::new(ErrorCode::Timeout, message)
        .with_suggestion(
            "A person must approve the desktop's ScreenCast source dialog. Approve it once; \
             the restore token makes later captures prompt-free. Do not retry automatically.",
        )
        .with_details(serde_json::json!({
            "kind": "screencast_consent_timeout",
            "retryable": false,
            "dialog_may_be_open": true,
        }))
        .with_disposition(DeliverySemantics::uncertain())
}

fn portal_error(error: &zbus::Error) -> AdapterError {
    let missing = matches!(
        error,
        zbus::Error::MethodError(name, _, _)
            if name.as_str() == "org.freedesktop.DBus.Error.ServiceUnknown"
                || name.as_str() == "org.freedesktop.DBus.Error.NameHasNoOwner"
    );
    if missing {
        return AdapterError::new(
            ErrorCode::PlatformNotSupported,
            "The xdg-desktop-portal ScreenCast service is not running in this session",
        )
        .with_suggestion("Install and start xdg-desktop-portal and its desktop backend");
    }
    AdapterError::new(ErrorCode::ActionFailed, "The ScreenCast portal call failed")
        .with_platform_detail(error.to_string())
}

fn deserialize_error(error: impl std::fmt::Display) -> AdapterError {
    AdapterError::new(
        ErrorCode::ActionFailed,
        "The ScreenCast portal returned an unreadable response",
    )
    .with_platform_detail(error.to_string())
}

fn refused(code: u32) -> AdapterError {
    AdapterError::new(
        ErrorCode::PermDenied,
        format!("The desktop portal refused ScreenCast (response {code})"),
    )
    .with_suggestion(
        "Approve the source-selection dialog the next time it appears. If a Deny was \
         remembered, reset screen-sharing permission in the desktop's privacy settings.",
    )
    .with_disposition(DeliverySemantics::not_delivered())
}

/// Run `future` until it completes or the deadline expires. zbus futures are
/// dropped on timeout; the portal keeps its dialog open until the user answers
/// or its own 25 s limit closes it.
fn within<T>(
    deadline: Deadline,
    future: impl Future<Output = Result<T, AdapterError>>,
) -> Result<T, AdapterError> {
    let remaining = deadline.remaining();
    if remaining.is_zero() {
        return Err(timeout_error("The ScreenCast portal did not answer in time"));
    }
    let result = futures_lite::future::block_on(futures_lite::future::or(
        async { Some(future.await) },
        async {
            async_io::Timer::after(remaining).await;
            None
        },
    ));
    result.unwrap_or_else(|| Err(timeout_error("The ScreenCast portal did not answer in time")))
}

fn token(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_nanos());
    format!("pl{prefix}{}x{nanos}", std::process::id())
}

fn request_path(unique_name: &str, handle_token: &str) -> String {
    let sender = unique_name.trim_start_matches(':').replace('.', "_");
    format!("/org/freedesktop/portal/desktop/request/{sender}/{handle_token}")
}

async fn call_request<B>(
    connection: &Connection,
    interface: &str,
    method: &str,
    body: &B,
    handle_token: &str,
) -> Result<HashMap<String, OwnedValue>, AdapterError>
where
    B: serde::Serialize + zbus::zvariant::DynamicType,
{
    let unique = connection
        .unique_name()
        .map(|name| name.to_string())
        .unwrap_or_default();
    let expected = request_path(&unique, handle_token);
    // Subscribe before the call: CreateSession can answer immediately.
    let request_proxy = Proxy::new(connection, PORTAL_SERVICE, expected.clone(), REQUEST)
        .await
        .map_err(|error| portal_error(&error))?;
    let mut stream = request_proxy
        .receive_signal("Response")
        .await
        .map_err(|error| portal_error(&error))?;
    let proxy = Proxy::new(connection, PORTAL_SERVICE, DESKTOP_PATH, interface)
        .await
        .map_err(|error| portal_error(&error))?;
    let reply = proxy
        .call_method(method, body)
        .await
        .map_err(|error| portal_error(&error))?;
    let handle: OwnedObjectPath = reply
        .body()
        .deserialize()
        .map_err(deserialize_error)?;
    if handle.as_str() != expected {
        return Err(AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal answered on a request this call did not subscribe to",
        )
        .with_platform_detail(handle.to_string()));
    }
    let message = stream.next().await.ok_or_else(|| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast request ended with no answer",
        )
    })?;
    let (code, results): (u32, HashMap<String, OwnedValue>) = message
        .body()
        .deserialize()
        .map_err(deserialize_error)?;
    if code != 0 {
        return Err(refused(code));
    }
    Ok(results)
}

fn read_token(root: &Path) -> Option<String> {
    std::fs::read_to_string(root.join(TOKEN_FILE))
        .ok()
        .map(|value| value.trim().to_owned())
        .filter(|value| !value.is_empty())
}

fn write_token(root: &Path, value: &str) -> bool {
    if std::fs::create_dir_all(root).is_err() {
        return false;
    }
    let path = root.join(TOKEN_FILE);
    let written = std::fs::OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .mode(0o600)
        .open(&path)
        .and_then(|mut file| file.write_all(value.as_bytes()))
        .is_ok();
    if written {
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }
    written
}

fn session_handle(results: &HashMap<String, OwnedValue>) -> Result<OwnedObjectPath, AdapterError> {
    let value = results.get("session_handle").cloned().ok_or_else(|| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal did not return a session handle",
        )
    })?;
    if let Ok(path) = OwnedObjectPath::try_from(value.clone()) {
        return Ok(path);
    }
    // Some portal versions return the handle as a string (`s`) rather than an
    // object path (`o`).
    let text = String::try_from(value).map_err(|error| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal returned an invalid session handle",
        )
        .with_platform_detail(error.to_string())
    })?;
    let path = zbus::zvariant::ObjectPath::try_from(text.as_str()).map_err(|error| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal returned an invalid session handle",
        )
        .with_platform_detail(error.to_string())
    })?;
    Ok(OwnedObjectPath::from(path.to_owned()))
}

fn stream_node(results: &HashMap<String, OwnedValue>) -> Result<u32, AdapterError> {
    let value = results.get("streams").cloned().ok_or_else(|| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal returned no streams",
        )
    })?;
    let streams: Vec<(u32, HashMap<String, OwnedValue>)> = value.try_into().map_err(|error| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal returned an unreadable stream list",
        )
        .with_platform_detail(format!("{error:?}"))
    })?;
    streams.first().map(|(node, _)| *node).ok_or_else(|| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast portal returned an empty stream list",
        )
    })
}

fn gst_command(node_id: u32, fd: Option<i32>, output: &Path) -> Vec<String> {
    let mut args = vec![
        "-q".to_owned(),
        "pipewiresrc".to_owned(),
    ];
    if let Some(fd) = fd {
        args.push(format!("fd={fd}"));
    }
    args.extend([
        format!("path={node_id}"),
        "num-buffers=30".to_owned(),
        "!".to_owned(),
        "videoconvert".to_owned(),
        "!".to_owned(),
        "pngenc".to_owned(),
        "!".to_owned(),
        "filesink".to_owned(),
        format!("location={}", output.display()),
    ]);
    args
}

fn spawn_capture(node_id: u32, fd: Option<i32>, output: &Path, deadline: Instant) -> Result<(), AdapterError> {
    let mut child = std::process::Command::new("gst-launch-1.0")
        .args(gst_command(node_id, fd, output))
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|error| {
            let code = if error.kind() == std::io::ErrorKind::NotFound {
                ErrorCode::PlatformNotSupported
            } else {
                ErrorCode::ActionFailed
            };
            AdapterError::new(code, format!("Could not start gst-launch-1.0: {error}"))
                .with_suggestion(
                    "Install gstreamer1.0-tools and gstreamer1.0-pipewire, then retry",
                )
                .with_disposition(DeliverySemantics::not_delivered())
        })?;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(status)) => {
                let mut stderr = String::new();
                if let Some(mut pipe) = child.stderr.take() {
                    use std::io::Read;
                    let _ = pipe.read_to_string(&mut stderr);
                }
                return Err(AdapterError::new(
                    ErrorCode::ActionFailed,
                    "The PipeWire frame capture failed",
                )
                .with_platform_detail(format!("gst-launch exited {status}: {}", stderr.trim()))
                .with_disposition(DeliverySemantics::not_delivered()));
            }
            Ok(None) if Instant::now() >= deadline => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(timeout_error(
                    "The PipeWire stream produced no frame before the capture deadline",
                ));
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(error) => {
                let _ = child.kill();
                return Err(AdapterError::new(
                    ErrorCode::ActionFailed,
                    format!("Could not wait for gst-launch: {error}"),
                ));
            }
        }
    }
}

fn capture_frames(
    node_id: u32,
    fd: &zbus::zvariant::OwnedFd,
    output: &Path,
    timeout: Duration,
) -> Result<(), AdapterError> {
    let deadline = Instant::now() + timeout;
    // gst-launch is a child process, so the portal fd must survive exec. zbus
    // creates it close-on-exec; clear that bit for this one descriptor.
    let raw = fd.as_raw_fd();
    // SAFETY: fcntl on a valid owned descriptor; failure only means the fd
    // stays close-on-exec and the retry without fd is used.
    unsafe {
        libc::fcntl(raw, libc::F_SETFD, 0);
    }
    match spawn_capture(node_id, Some(raw), output, deadline) {
        Ok(()) => Ok(()),
        Err(first) => {
            // Some PipeWire versions publish the portal node in the default
            // daemon; retrying without the fd is a cheap fallback.
            let _ = std::fs::remove_file(output);
            match spawn_capture(node_id, None, output, deadline) {
                Ok(()) => Ok(()),
                Err(_) => Err(first),
            }
        }
    }
}

/// Capture one frame from the portal's ScreenCast stream.
///
/// `state_root` is the 0700 artifact/state directory (`~/.palimind/desktop`).
/// `consent_timeout` covers the first-use source dialog; `capture_timeout`
/// covers PipeWire/GStreamer frame extraction.
pub fn capture_screen(
    state_root: &Path,
    output: &Path,
    consent_timeout: Duration,
    capture_timeout: Duration,
) -> Result<Capture, AdapterError> {
    let deadline = Deadline::detached_after(
        u64::try_from(consent_timeout.as_millis()).unwrap_or(30_000),
    )?;
    let restore_token = read_token(state_root);
    let connection = within(deadline, async {
        Connection::session()
            .await
            .map_err(|error| portal_error(&error))
    })?;

    let create_handle = token("c");
    let session_token = token("s");
    let mut create_options: HashMap<&str, Value<'_>> = HashMap::new();
    create_options.insert("handle_token", Value::from(create_handle.as_str()));
    create_options.insert("session_handle_token", Value::from(session_token.as_str()));
    let created = within(
        deadline,
        call_request(
            &connection,
            SCREENCAST,
            "CreateSession",
            &(create_options,),
            &create_handle,
        ),
    )?;
    let session = session_handle(&created)?;

    let source_handle = token("src");
    let mut source_options: HashMap<&str, Value<'_>> = HashMap::new();
    source_options.insert("handle_token", Value::from(source_handle.as_str()));
    // types: 1 = monitor, 2 = window. A monitor is the vision fallback: it
    // works for canvas/web content without needing a proven window origin.
    source_options.insert("types", Value::from(1u32));
    source_options.insert("multiple", Value::from(false));
    source_options.insert("persist_mode", Value::from(2u32));
    if let Some(token) = restore_token.as_deref() {
        source_options.insert("restore_token", Value::from(token));
    }
    within(
        deadline,
        call_request(
            &connection,
            SCREENCAST,
            "SelectSources",
            &(&session, source_options),
            &source_handle,
        ),
    )?;

    let start_handle = token("st");
    let mut start_options: HashMap<&str, Value<'_>> = HashMap::new();
    start_options.insert("handle_token", Value::from(start_handle.as_str()));
    let started = within(
        deadline,
        call_request(
            &connection,
            SCREENCAST,
            "Start",
            &(&session, "", start_options),
            &start_handle,
        ),
    )?;
    let node_id = stream_node(&started)?;
    let new_token = started
        .get("restore_token")
        .cloned()
        .and_then(|value| String::try_from(value).ok());
    let restore_token_saved = new_token
        .as_deref()
        .map(|value| write_token(state_root, value))
        .unwrap_or(false);

    // Consent is over; give the PipeWire hand-off its own budget. A slow
    // source dialog must not consume the time needed to read the stream.
    let pipewire_deadline = Deadline::detached_after(15_000)?;
    let open_proxy = within(pipewire_deadline, async {
        Proxy::new(&connection, PORTAL_SERVICE, DESKTOP_PATH, SCREENCAST)
            .await
            .map_err(|error| portal_error(&error))
    })?;
    let mut open_options: HashMap<&str, Value<'_>> = HashMap::new();
    let open_handle = token("pw");
    open_options.insert("handle_token", Value::from(open_handle.as_str()));
    let fd_reply = within(pipewire_deadline, async {
        open_proxy
            .call_method("OpenPipeWireRemote", &(&session, open_options))
            .await
            .map_err(|error| portal_error(&error))
    })?;
    let fd: zbus::zvariant::OwnedFd = fd_reply
        .body()
        .deserialize()
        .map_err(deserialize_error)?;

    capture_frames(node_id, &fd, output, capture_timeout)?;
    let bytes = std::fs::read(output).map_err(|error| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            format!("The ScreenCast frame was not written: {error}"),
        )
    })?;
    let (width, height) = agent_desktop_core::parse_png_dimensions(&bytes).ok_or_else(|| {
        AdapterError::new(
            ErrorCode::ActionFailed,
            "The ScreenCast frame is not a PNG this tool can use",
        )
    })?;
    Ok(Capture {
        path: output.to_path_buf(),
        width,
        height,
        node_id,
        restore_token_saved,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_path_uses_the_portal_sender_and_token_layout() {
        assert_eq!(
            request_path(":1.42", "tok123"),
            "/org/freedesktop/portal/desktop/request/1_42/tok123"
        );
    }

    #[test]
    fn gst_command_carries_the_portal_fd_and_node() {
        let args = gst_command(77, Some(9), Path::new("/tmp/out.png"));
        assert!(args.iter().any(|arg| arg == "fd=9"));
        assert!(args.iter().any(|arg| arg == "path=77"));
        assert!(args.iter().any(|arg| arg == "location=/tmp/out.png"));
        assert!(args.iter().any(|arg| arg == "pipewiresrc"));
        assert!(args.iter().any(|arg| arg == "pngenc"));
    }

    #[test]
    fn gst_command_can_retry_without_fd() {
        let args = gst_command(5, None, Path::new("/tmp/out.png"));
        assert!(!args.iter().any(|arg| arg.starts_with("fd=")));
        assert!(args.iter().any(|arg| arg == "path=5"));
    }

    #[test]
    fn session_handle_accepts_a_string_or_an_object_path() {
        let path = "/org/freedesktop/portal/desktop/session/1_1/tok";
        let mut string_map = HashMap::new();
        string_map.insert(
            "session_handle".to_owned(),
            OwnedValue::try_from(Value::from(path)).expect("string value"),
        );
        assert_eq!(session_handle(&string_map).unwrap().as_str(), path);

        let object = zbus::zvariant::ObjectPath::try_from(path).expect("object path");
        let mut object_map = HashMap::new();
        object_map.insert(
            "session_handle".to_owned(),
            OwnedValue::try_from(Value::from(object)).expect("object value"),
        );
        assert_eq!(session_handle(&object_map).unwrap().as_str(), path);
    }
}
