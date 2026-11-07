//! Wayland pointer-targeting policy.
//!
//! `/dev/uinput` solves *delivery*, not *targeting*. On Wayland the
//! compositor does not expose a global window origin, and AT-SPI
//! `Component.GetExtents(SCREEN)` can be window-local (see the reference
//! project's measured finding L13-17). A physical pointer action therefore
//! needs a coordinate source that is actually global:
//!
//! * explicit user coordinates,
//! * a screenshot + local vision/OCR pass over the whole display,
//! * a compositor ScreenCast stream with monitor geometry,
//! * or known geometry from a maximized/fullscreen window.
//!
//! Anything else is refused before dispatch. We never guess a coordinate.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CoordinateSource {
    /// Coordinates typed/confirmed by the user.
    User,
    /// Coordinates derived from a full-display screenshot or OCR pass.
    Screenshot,
    /// Monitor/window geometry supplied by the compositor (ScreenCast).
    Compositor,
    /// Geometry read from AT-SPI. Not global on Wayland.
    Atspi,
    /// No source was declared.
    Unknown,
}

impl CoordinateSource {
    pub fn is_global_on_wayland(self) -> bool {
        matches!(self, Self::User | Self::Screenshot | Self::Compositor)
    }

    pub fn parse(value: Option<&str>) -> Self {
        match value.map(str::trim) {
            Some("user") => Self::User,
            Some("screenshot") => Self::Screenshot,
            Some("compositor") => Self::Compositor,
            Some("atspi") => Self::Atspi,
            _ => Self::Unknown,
        }
    }
}

pub fn session_is_wayland() -> bool {
    std::env::var("XDG_SESSION_TYPE")
        .map(|value| value.eq_ignore_ascii_case("wayland"))
        .unwrap_or(false)
        || (std::env::var("WAYLAND_DISPLAY").is_ok()
            && std::env::var("XDG_SESSION_TYPE")
                .map(|value| !value.eq_ignore_ascii_case("x11"))
                .unwrap_or(true))
}

/// Gate a physical pointer action before any event is emitted.
pub fn require_global_coordinates(source: CoordinateSource) -> Result<(), String> {
    if !session_is_wayland() || source.is_global_on_wayland() {
        return Ok(());
    }
    Err(format!(
        "Physical pointer input on Wayland needs a proven global coordinate source; got {source:?}. \
         Use a semantic action, or supply user coordinates, a full-display screenshot/OCR pass, or \
         compositor geometry. Palimind will not guess a window-local AT-SPI coordinate."
    ))
}

/// Map display pixels into the uinput absolute-pointer unit range.
pub fn to_device_units(x: f64, y: f64, width: u32, height: u32) -> (i32, i32) {
    let max = f64::from(crate::uinput::COORD_MAX);
    let sx = if width == 0 {
        0.0
    } else {
        (x / f64::from(width)).clamp(0.0, 1.0) * max
    };
    let sy = if height == 0 {
        0.0
    } else {
        (y / f64::from(height)).clamp(0.0, 1.0) * max
    };
    (sx.round() as i32, sy.round() as i32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn atspi_bounds_are_not_a_wayland_coordinate_source() {
        assert!(!CoordinateSource::Atspi.is_global_on_wayland());
        assert!(!CoordinateSource::Unknown.is_global_on_wayland());
        assert!(CoordinateSource::User.is_global_on_wayland());
        assert!(CoordinateSource::Screenshot.is_global_on_wayland());
        assert!(CoordinateSource::Compositor.is_global_on_wayland());
    }

    #[test]
    fn device_units_map_the_full_display() {
        assert_eq!(to_device_units(0.0, 0.0, 1920, 1080), (0, 0));
        assert_eq!(
            to_device_units(1920.0, 1080.0, 1920, 1080),
            (65_535, 65_535)
        );
        assert_eq!(to_device_units(960.0, 540.0, 1920, 1080), (32_768, 32_768));
    }
}
