use super::{ACTION_INTERFACE, skipped_without};
use crate::tree::Field;
use crate::tree::properties::node_read::COMPONENT_INTERFACE;

#[test]
fn action_name_transport_loss_ends_observation() {
    // Palimind: names are probed through `GetName(i)`; a transport failure on
    // the first probe must still surface as an error, never as an empty list.
    let connection = crate::tree::live::test_support::closed_connection();
    let element = crate::tree::AtspiElement::new(":1.1", "/button", 1);
    let interfaces = listed(&[ACTION_INTERFACE]);
    let error = zbus::block_on(super::read_actions(&connection, &element, &interfaces))
        .expect_err("transport loss must end observation");
    assert_eq!(error.code, agent_desktop_core::ErrorCode::Internal);
}

fn listed(names: &[&str]) -> Field<Vec<String>> {
    Field::Present(names.iter().map(|name| (*name).to_owned()).collect())
}

#[test]
fn an_advertised_interface_is_read() {
    let interfaces = listed(&[COMPONENT_INTERFACE]);
    assert!(skipped_without::<()>(&interfaces, COMPONENT_INTERFACE).is_none());
}

#[test]
fn an_unadvertised_interface_is_absent() {
    let interfaces = listed(&[COMPONENT_INTERFACE]);
    assert_eq!(
        skipped_without::<()>(&interfaces, ACTION_INTERFACE),
        Some(Field::Absent)
    );
}

#[test]
fn an_unreadable_interface_list_makes_the_dependent_field_a_failure() {
    let interfaces = Field::Failed("timed out".to_owned());
    let skipped = skipped_without::<()>(&interfaces, ACTION_INTERFACE);
    assert!(skipped.is_some_and(|field| field.is_failed()));
}
