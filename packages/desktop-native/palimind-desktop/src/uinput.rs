//! Linux kernel-input backend via `/dev/uinput`.
//!
//! This is the "kernel level" input path in the plan: we do not ship a kernel
//! module; the in-tree `uinput` module lets an unprivileged-but-authorized
//! process create a virtual HID device. The compositor and applications see
//! ordinary kernel input events, which is what makes delivery reliable on
//! Wayland.
//!
//! Things this module deliberately does *not* solve:
//!
//! * **Targeting.** Absolute device coordinates are screen coordinates only
//!   when the device is calibrated to the seat. The caller still has to prove
//!   where a target is; see `wayland_targeting`.
//! * **Keyboard layout.** v1 uses a US layout for the synthetic keyboard.
//!   Arbitrary Unicode should go through clipboard paste with restore.
//! * **Privilege escalation.** `/dev/uinput` is root-only by default. The
//!   installer adds a udev rule for the `input` group; Palimind never ships a
//!   setuid helper.

use std::fs::{File, OpenOptions};
use std::io;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::io::AsRawFd;
use std::path::Path;

const EV_SYN: u16 = 0x00;
const EV_KEY: u16 = 0x01;
const EV_ABS: u16 = 0x03;
const SYN_REPORT: u16 = 0;

const ABS_X: u16 = 0x00;
const ABS_Y: u16 = 0x01;

const BTN_LEFT: u16 = 0x110;
const BTN_RIGHT: u16 = 0x111;
const BTN_MIDDLE: u16 = 0x112;

/// Public button codes for callers that drive `VirtualInput::click`.
pub const BUTTON_LEFT: u16 = BTN_LEFT;
pub const BUTTON_RIGHT: u16 = BTN_RIGHT;

const BUS_VIRTUAL: u16 = 0x06;

const UI_DEV_CREATE: libc::c_ulong = 0x5501;
const UI_DEV_DESTROY: libc::c_ulong = 0x5502;
const UI_DEV_SETUP: libc::c_ulong = 0x405c_5503;
const UI_ABS_SETUP: libc::c_ulong = 0x401c_5504;
const UI_SET_EVBIT: libc::c_ulong = 0x4004_5564;
const UI_SET_KEYBIT: libc::c_ulong = 0x4004_5565;
const UI_SET_ABSBIT: libc::c_ulong = 0x4004_5567;

/// The virtual device spans this many device units. Coordinates are mapped
/// from the caller's pixel space into `0..=COORD_MAX` before emission.
pub const COORD_MAX: i32 = 65_535;

#[repr(C)]
#[derive(Clone, Copy)]
struct InputId {
    bustype: u16,
    vendor: u16,
    product: u16,
    version: u16,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct UinputSetup {
    id: InputId,
    name: [u8; 80],
    ff_effects_max: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct InputAbsInfo {
    value: i32,
    minimum: i32,
    maximum: i32,
    fuzz: i32,
    flat: i32,
    resolution: i32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct UinputAbsSetup {
    code: u16,
    _pad: u16,
    absinfo: InputAbsInfo,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct InputEvent {
    time: libc::timeval,
    type_: u16,
    code: u16,
    value: i32,
}

#[derive(Debug)]
pub enum KernelInputError {
    PermissionDenied(String),
    Io(io::Error),
}

impl std::fmt::Display for KernelInputError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::PermissionDenied(msg) => f.write_str(msg),
            Self::Io(err) => write!(f, "{err}"),
        }
    }
}

impl From<io::Error> for KernelInputError {
    fn from(value: io::Error) -> Self {
        if value.kind() == io::ErrorKind::PermissionDenied {
            Self::PermissionDenied(permission_hint())
        } else {
            Self::Io(value)
        }
    }
}

pub fn permission_hint() -> String {
    "Cannot open /dev/uinput. Kernel input is opt-in: load the uinput module, install the udev \
     rule (scripts/install-uinput-udev.sh) and add your user to the 'input' group, then log back \
     in. Ask/Find and semantic actions keep working without it."
        .into()
}

/// Cheap probe used by `status`: can this process open the device at all?
pub fn probe() -> KernelInputStatus {
    let path = Path::new("/dev/uinput");
    if !path.exists() {
        return KernelInputStatus {
            device: false,
            accessible: false,
            detail: Some(" /dev/uinput is missing; the kernel module is not loaded".into()),
        };
    }
    match OpenOptions::new().write(true).open(path) {
        Ok(_) => KernelInputStatus {
            device: true,
            accessible: true,
            detail: None,
        },
        Err(error) if error.kind() == io::ErrorKind::PermissionDenied => KernelInputStatus {
            device: true,
            accessible: false,
            detail: Some("available-but-not-permitted".into()),
        },
        Err(error) => KernelInputStatus {
            device: true,
            accessible: false,
            detail: Some(error.to_string()),
        },
    }
}

#[derive(Debug, serde::Serialize)]
pub struct KernelInputStatus {
    pub device: bool,
    pub accessible: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

/// A live virtual keyboard + absolute pointer. Drop destroys the device and
/// releases any key or button still held, so a panic or `?` cannot leave a
/// stuck modifier behind.
pub struct VirtualInput {
    file: File,
    held_keys: Vec<u16>,
    held_buttons: Vec<u16>,
    destroyed: bool,
}

impl VirtualInput {
    pub fn open() -> Result<Self, KernelInputError> {
        let file = OpenOptions::new()
            .write(true)
            .custom_flags(libc::O_CLOEXEC)
            .open("/dev/uinput")?;
        let mut device = Self {
            file,
            held_keys: Vec::new(),
            held_buttons: Vec::new(),
            destroyed: false,
        };
        device.configure()?;
        Ok(device)
    }

    fn configure(&mut self) -> Result<(), KernelInputError> {
        ioctl_u32(self.file.as_raw_fd(), UI_SET_EVBIT, u64::from(EV_KEY))?;
        ioctl_u32(self.file.as_raw_fd(), UI_SET_EVBIT, u64::from(EV_ABS))?;
        ioctl_u32(self.file.as_raw_fd(), UI_SET_EVBIT, u64::from(EV_SYN))?;

        for code in all_keycodes() {
            ioctl_u32(self.file.as_raw_fd(), UI_SET_KEYBIT, u64::from(code))?;
        }
        for axis in [ABS_X, ABS_Y] {
            ioctl_u32(self.file.as_raw_fd(), UI_SET_ABSBIT, u64::from(axis))?;
            let setup = UinputAbsSetup {
                code: axis,
                _pad: 0,
                absinfo: InputAbsInfo {
                    value: 0,
                    minimum: 0,
                    maximum: COORD_MAX,
                    fuzz: 0,
                    flat: 0,
                    resolution: 0,
                },
            };
            ioctl_ptr(self.file.as_raw_fd(), UI_ABS_SETUP, &setup)?;
        }

        let mut name = [0u8; 80];
        let label = b"Palimind Virtual Input";
        name[..label.len()].copy_from_slice(label);
        let setup = UinputSetup {
            id: InputId {
                bustype: BUS_VIRTUAL,
                vendor: 0x1d6b,
                product: 0x0104,
                version: 1,
            },
            name,
            ff_effects_max: 0,
        };
        ioctl_ptr(self.file.as_raw_fd(), UI_DEV_SETUP, &setup)?;
        ioctl(self.file.as_raw_fd(), UI_DEV_CREATE, 0)?;
        Ok(())
    }

    fn emit(&mut self, type_: u16, code: u16, value: i32) -> io::Result<()> {
        let event = InputEvent {
            time: libc::timeval {
                tv_sec: 0,
                tv_usec: 0,
            },
            type_,
            code,
            value,
        };
        write_struct(&mut self.file, &event)
    }

    fn sync(&mut self) -> io::Result<()> {
        self.emit(EV_SYN, SYN_REPORT, 0)
    }

    pub fn key(&mut self, code: u16, down: bool) -> io::Result<()> {
        self.emit(EV_KEY, code, i32::from(down))?;
        if down {
            if !self.held_keys.contains(&code) {
                self.held_keys.push(code);
            }
        } else {
            self.held_keys.retain(|held| *held != code);
        }
        self.sync()
    }

    pub fn tap(&mut self, code: u16) -> io::Result<()> {
        self.key(code, true)?;
        self.key(code, false)
    }

    pub fn button(&mut self, button: u16, down: bool) -> io::Result<()> {
        self.emit(EV_KEY, button, i32::from(down))?;
        if down {
            if !self.held_buttons.contains(&button) {
                self.held_buttons.push(button);
            }
        } else {
            self.held_buttons.retain(|held| *held != button);
        }
        self.sync()
    }

    /// Move the absolute pointer. `x`/`y` are in `0..=COORD_MAX` device units.
    pub fn move_abs(&mut self, x: i32, y: i32) -> io::Result<()> {
        self.emit(EV_ABS, ABS_X, x.clamp(0, COORD_MAX))?;
        self.emit(EV_ABS, ABS_Y, y.clamp(0, COORD_MAX))?;
        self.sync()
    }

    pub fn click(&mut self, button: u16, count: u32) -> io::Result<()> {
        for _ in 0..count.max(1) {
            self.button(button, true)?;
            self.button(button, false)?;
        }
        Ok(())
    }

    /// Emit a US-layout key chord such as `ctrl+s`. Returns an error when a
    /// token is not in the small, explicit keymap.
    pub fn chord(&mut self, chord: &str) -> io::Result<()> {
        let (modifiers, key) = parse_chord(chord).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("Unsupported key chord '{chord}'"),
            )
        })?;
        for modifier in &modifiers {
            self.key(*modifier, true)?;
        }
        self.tap(key)?;
        for modifier in modifiers.iter().rev() {
            self.key(*modifier, false)?;
        }
        Ok(())
    }

    /// Types printable US-ASCII (and `\n`/`\t`). Non-ASCII is refused so a
    /// caller falls back to clipboard paste rather than typing a wrong glyph.
    pub fn type_text(&mut self, text: &str) -> io::Result<()> {
        for character in text.chars() {
            if !character.is_ascii() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "Kernel typing supports ASCII only; use clipboard paste for Unicode",
                ));
            }
            let (code, shift) = ascii_key(character).ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("No US keymap entry for {character:?}"),
                )
            })?;
            if shift {
                self.key(KEY_LEFTSHIFT, true)?;
            }
            self.tap(code)?;
            if shift {
                self.key(KEY_LEFTSHIFT, false)?;
            }
        }
        Ok(())
    }

    pub fn release_all(&mut self) -> io::Result<()> {
        let keys = std::mem::take(&mut self.held_keys);
        for code in keys {
            self.emit(EV_KEY, code, 0)?;
        }
        let buttons = std::mem::take(&mut self.held_buttons);
        for code in buttons {
            self.emit(EV_KEY, code, 0)?;
        }
        self.sync()
    }
}

impl Drop for VirtualInput {
    fn drop(&mut self) {
        let _ = self.release_all();
        if !self.destroyed {
            let _ = ioctl(self.file.as_raw_fd(), UI_DEV_DESTROY, 0);
            self.destroyed = true;
        }
    }
}

fn write_struct<T>(file: &mut File, value: &T) -> io::Result<()> {
    use std::io::Write;
    let bytes = unsafe {
        std::slice::from_raw_parts((value as *const T).cast::<u8>(), std::mem::size_of::<T>())
    };
    file.write_all(bytes)
}

fn ioctl(fd: i32, request: libc::c_ulong, argument: libc::c_ulong) -> io::Result<()> {
    // SAFETY: fd is an open uinput device for the lifetime of the caller; the
    // request constants and argument are the documented uinput ioctls.
    let result = unsafe { libc::ioctl(fd, request, argument) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn ioctl_u32(fd: i32, request: libc::c_ulong, value: u64) -> io::Result<()> {
    // uinput expects the bit number as the ioctl argument, not a pointer.
    ioctl(fd, request, value as libc::c_ulong)
}

fn ioctl_ptr<T>(fd: i32, request: libc::c_ulong, value: &T) -> io::Result<()> {
    // SAFETY: `value` is a live, correctly sized struct for this ioctl.
    let result = unsafe { libc::ioctl(fd, request, value as *const T) };
    if result < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

const KEY_LEFTSHIFT: u16 = 42;
const KEY_TAB: u16 = 15;
const KEY_ENTER: u16 = 28;
const KEY_ESC: u16 = 1;
const KEY_BACKSPACE: u16 = 14;
const KEY_LEFTCTRL: u16 = 29;
const KEY_LEFTALT: u16 = 56;
const KEY_LEFTMETA: u16 = 125;
const KEY_UP: u16 = 103;
const KEY_LEFT: u16 = 105;
const KEY_RIGHT: u16 = 106;
const KEY_DOWN: u16 = 108;

fn all_keycodes() -> Vec<u16> {
    let mut codes: Vec<u16> = vec![
        KEY_LEFTSHIFT,
        KEY_TAB,
        KEY_ENTER,
        KEY_ESC,
        KEY_BACKSPACE,
        KEY_LEFTCTRL,
        KEY_LEFTALT,
        KEY_LEFTMETA,
        KEY_UP,
        KEY_LEFT,
        KEY_RIGHT,
        KEY_DOWN,
        BTN_LEFT,
        BTN_RIGHT,
        BTN_MIDDLE,
    ];
    for byte in 0x20u8..=0x7e {
        if let Some((code, _)) = ascii_key(byte as char)
            && !codes.contains(&code)
        {
            codes.push(code);
        }
    }
    codes
}

/// US layout scan codes (linux/input-event-codes.h), without the 8 offset that
/// X11 keycodes use.
fn ascii_key(character: char) -> Option<(u16, bool)> {
    let value = match character.to_ascii_lowercase() {
        'q' => 16,
        'w' => 17,
        'e' => 18,
        'r' => 19,
        't' => 20,
        'y' => 21,
        'u' => 22,
        'i' => 23,
        'o' => 24,
        'p' => 25,
        'a' => 30,
        's' => 31,
        'd' => 32,
        'f' => 33,
        'g' => 34,
        'h' => 35,
        'j' => 36,
        'k' => 37,
        'l' => 38,
        'z' => 44,
        'x' => 45,
        'c' => 46,
        'v' => 47,
        'b' => 48,
        'n' => 49,
        'm' => 50,
        '1'..='9' => (character as u16 - '1' as u16) + 2,
        '0' => 11,
        '\n' => KEY_ENTER,
        '\t' => KEY_TAB,
        ' ' => 57,
        '-' => 12,
        '=' => 13,
        '[' => 26,
        ']' => 27,
        '\\' => 43,
        ';' => 39,
        '\'' => 40,
        '`' => 41,
        ',' => 51,
        '.' => 52,
        '/' => 53,
        _ => {
            let shifted = match character {
                '!' => '1',
                '@' => '2',
                '#' => '3',
                '$' => '4',
                '%' => '5',
                '^' => '6',
                '&' => '7',
                '*' => '8',
                '(' => '9',
                ')' => '0',
                '_' => '-',
                '+' => '=',
                '{' => '[',
                '}' => ']',
                '|' => '\\',
                ':' => ';',
                '"' => '\'',
                '~' => '`',
                '<' => ',',
                '>' => '.',
                '?' => '/',
                ' ' => ' ',
                _ => return None,
            };
            let (code, _) = ascii_key(shifted)?;
            return Some((code, true));
        }
    };
    let shift = character.is_ascii_uppercase();
    Some((value, shift))
}

fn parse_chord(chord: &str) -> Option<(Vec<u16>, u16)> {
    let mut modifiers = Vec::new();
    let mut key = None;
    for token in chord.split('+') {
        match token.trim().to_ascii_lowercase().as_str() {
            "ctrl" | "control" => modifiers.push(KEY_LEFTCTRL),
            "alt" => modifiers.push(KEY_LEFTALT),
            "shift" => modifiers.push(KEY_LEFTSHIFT),
            "super" | "meta" | "win" => modifiers.push(KEY_LEFTMETA),
            other => {
                if other.is_empty() {
                    return None;
                }
                key = Some(match other {
                    "enter" | "return" => KEY_ENTER,
                    "tab" => KEY_TAB,
                    "esc" | "escape" => KEY_ESC,
                    "backspace" => KEY_BACKSPACE,
                    "up" => KEY_UP,
                    "down" => KEY_DOWN,
                    "left" => KEY_LEFT,
                    "right" => KEY_RIGHT,
                    single if single.chars().count() == 1 => ascii_key(single.chars().next()?)?.0,
                    _ => return None,
                });
            }
        }
    }
    Some((modifiers, key?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ascii_map_covers_letters_digits_and_shifted_punctuation() {
        assert_eq!(ascii_key('a'), Some((30, false)));
        assert_eq!(ascii_key('A'), Some((30, true)));
        assert_eq!(ascii_key('1'), Some((2, false)));
        assert_eq!(ascii_key('!'), Some((2, true)));
        assert_eq!(ascii_key('\n'), Some((KEY_ENTER, false)));
        assert_eq!(ascii_key('é'), None);
    }

    #[test]
    fn chords_parse_modifiers_and_keys() {
        let (modifiers, key) = parse_chord("ctrl+shift+s").unwrap();
        assert_eq!(modifiers, vec![KEY_LEFTCTRL, KEY_LEFTSHIFT]);
        assert_eq!(key, 31);
    }

    #[test]
    fn status_probe_reports_permission_state_without_panicking() {
        let status = probe();
        assert!(status.device || status.detail.is_some());
    }
}
