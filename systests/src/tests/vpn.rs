use std::panic::AssertUnwindSafe;

use telio_crypto::SecretKey;
use telio_model::{features::PathType, mesh::ExitNode};

use crate::utils::{interface_helper::InterfaceHelper, test_client::TestClient};

pub fn test_vpn_poc() {
    let mut ifc_helper = InterfaceHelper::new();
    let test_result = std::panic::catch_unwind(AssertUnwindSafe(|| {
        let mut clients =
            TestClient::generate_clients(vec!["alpha"], &mut ifc_helper, Default::default());
        let mut alpha = clients.remove("alpha").unwrap();

        alpha.start();

        if !alpha.ifc_configured {
            InterfaceHelper::configure_ifc(&alpha.ifc_name, alpha.ip);
            InterfaceHelper::create_vpn_route(&alpha.ifc_name);
            alpha.ifc_configured = true;
        }

        let vpn_key = SecretKey::gen().public();
        let node = ExitNode {
            identifier: "wgserver".to_owned(),
            public_key: vpn_key,
            allowed_ips: None,
            endpoint: Some("10.0.100.1:1023".parse().expect("Should be valid")),
        };
        alpha.connect_to_exit_node(&node);

        alpha
            .wait_for_connection_peer(vpn_key, &[PathType::Relay, PathType::Direct])
            .unwrap();

        // stun should return VPN IP

        alpha.stop();
        alpha.shutdown();
    }));
    ifc_helper.cleanup_interfaces();
    match test_result {
        Ok(()) => println!("test_meshnet_poc passed\n\n"),
        Err(e) => println!("test_meshnet_poc failed with error {e:?}\n\n"),
    };
}
