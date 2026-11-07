use agent_desktop_core::AdapterError;
use zbus::Connection;
use zbus::zvariant::OwnedValue;

use super::liveness::Liveness;
use super::node_read::{COMPONENT_INTERFACE, call, deserialize, field};
use crate::tree::{AtspiElement, Extents, Field};

const ACTION_INTERFACE: &str = "org.a11y.atspi.Action";
const SCREEN_COORDINATES: u32 = 0;

/// `None` when the interface is advertised and its reads should go ahead.
/// When the interface list itself could not be read, nothing is known about
/// the interface, so the dependent field is a failure and not an absence.
pub(in crate::tree) fn skipped_without<T>(
    interfaces: &Field<Vec<String>>,
    name: &str,
) -> Option<Field<T>> {
    match interfaces {
        Field::Present(list) if list.iter().any(|entry| entry == name) => None,
        Field::Present(_) | Field::Absent => Some(Field::Absent),
        Field::Failed(detail) => Some(Field::Failed(format!(
            "interface list unavailable, {name} not checked: {detail}"
        ))),
    }
}

pub(in crate::tree) async fn read_extents(
    connection: &Connection,
    element: &AtspiElement,
    interfaces: &Field<Vec<String>>,
    liveness: Liveness,
) -> Result<Field<Extents>, AdapterError> {
    if let Some(skipped) = skipped_without(interfaces, COMPONENT_INTERFACE) {
        return Ok(skipped);
    }
    let reply = call(
        connection,
        element,
        COMPONENT_INTERFACE,
        "GetExtents",
        &(SCREEN_COORDINATES,),
    )
    .await;
    field(deserialize::<(i32, i32, i32, i32)>(reply), liveness).map(|read| {
        read.map(|(x, y, width, height)| Extents {
            x,
            y,
            width,
            height,
        })
    })
}

async fn action_count(connection: &Connection, element: &AtspiElement) -> Option<i32> {
    let reply = call(
        connection,
        element,
        "org.freedesktop.DBus.Properties",
        "Get",
        &(ACTION_INTERFACE, "NActions"),
    )
    .await;
    let value = deserialize::<OwnedValue>(reply).ok()?;
    value.downcast_ref::<i32>().ok()
}

/// `GetName(i)` is the only call that returns the machine name on every
/// toolkit: `GetActions` returns empty names on Chromium and junk on Gecko.
///
/// Palimind: we do not call `GetActions` at all. On at-spi2-core 2.44 / the
/// GTK bridges on this host, several widgets advertise the Action interface
/// while their ATK user-data is not an `AtkAction`; serializing the
/// `GetActions` reply aborts the application (measured: GTK3 zenity calendar,
/// GNOME Calculator unit combo and digit buttons). `GetName(i)` reaches the
/// same data without building that reply and is safe on every node measured,
/// so action names are probed by index until the toolkit refuses the index.
/// This is a deliberate, documented fork delta; see docs/computer-use.md.
const MAX_PROBED_ACTIONS: i32 = 8;

pub(in crate::tree) async fn read_actions(
    connection: &Connection,
    element: &AtspiElement,
    interfaces: &Field<Vec<String>>,
) -> Result<Field<Vec<String>>, AdapterError> {
    if let Some(skipped) = skipped_without(interfaces, ACTION_INTERFACE) {
        return Ok(skipped);
    }
    // `NActions` is the safe count: probing `GetName(i)` past the last action
    // aborts some GTK apps (nautilus: assertion `i < LAST_ACTION`). If the
    // property cannot be read, probe only index 0 rather than guess.
    let count = match action_count(connection, element).await {
        Some(count) => count.clamp(0, MAX_PROBED_ACTIONS),
        None => 1,
    };
    let mut names = Vec::new();
    for index in 0..count {
        let reply = call(connection, element, ACTION_INTERFACE, "GetName", &(index,)).await;
        match deserialize::<String>(reply) {
            Ok(name) if !name.is_empty() => names.push(name),
            Ok(_) => break,
            Err(error) if crate::system::is_connection_failure(&error) => {
                return Err(crate::system::classify(&error));
            }
            Err(_) => break,
        }
    }
    if names.is_empty() {
        Ok(Field::Absent)
    } else {
        Ok(Field::Present(names))
    }
}

#[cfg(test)]
#[path = "interface_reads_tests.rs"]
mod tests;
