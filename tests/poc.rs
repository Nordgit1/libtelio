use std::{str::FromStr, sync::Arc};

use rand::{self, Rng};
use telio::{
    self,
    defaults_builder::FeaturesDefaultsBuilder,
    device::{Device, DeviceConfig},
};
use telio_crypto::SecretKey;
use telio_model::{
    config::{Config, Peer, PeerBase, RelayState, Server},
    event::Event,
    mesh::ExitNode,
    PublicKey,
};
use telio_utils::Hidden;
use telio_wg::AdapterType;

fn rand_range(lower: u8, upper: u8) -> u8 {
    rand::thread_rng().gen_range(lower..=upper)
}

fn get_peer(identifier: &str) -> (SecretKey, Peer) {
    let key = SecretKey::gen();
    let ip = format!(
        "100.{}.{}.{}",
        rand_range(64, 127),
        rand_range(0, 255),
        rand_range(8, 254)
    )
    .parse()
    .unwrap();
    let peer = Peer {
        base: PeerBase {
            identifier: identifier.to_owned(),
            public_key: key.public(),
            hostname: Hidden(format!("{identifier}.nord")),
            ip_addresses: Some(vec![ip]),
            nickname: None,
        },
        is_local: false,
        allow_incoming_connections: true,
        allow_peer_send_files: false,
        allow_multicast: false,
        peer_allows_multicast: false,
    };
    (key, peer)
}

fn get_derp_servers() -> Vec<Server> {
    vec![Server {
        region_code: "nl".to_owned(),
        name: "Natlab #0001".to_owned(),
        hostname: "derp-01".to_owned(),
        ipv4: "10.0.10.1".parse().unwrap(),
        relay_port: 8765,
        stun_port: 3479,
        stun_plaintext_port: 3478,
        public_key: PublicKey::from_str("qK/ICYOGBu45EIGnopVu+aeHDugBrkLAZDroKGTuKU0=").unwrap(),
        weight: 1,
        use_plain_text: true,
        conn_state: RelayState::Disconnected,
    }]
}

#[test]
fn test_poc_meshnet() {
    let (peer1_key, peer1) = get_peer("alpha");
    let (peer2_key, peer2) = get_peer("beta");

    let event_dispatcher = move |event: Box<Event>| {
        println!("Event: {event:?}");
    };

    let features = Arc::new(FeaturesDefaultsBuilder::new());

    let mut dev1 = Device::new(
        features.clone().enable_direct().build(),
        event_dispatcher,
        None,
    )
    .unwrap();
    dev1.start(&DeviceConfig {
        private_key: peer1_key,
        adapter: AdapterType::BoringTun,
        fwmark: None,
        name: Some("tun10".to_owned()),
        tun: None,
    })
    .unwrap();

    let mut dev2 = Device::new(features.enable_direct().build(), event_dispatcher, None).unwrap();
    dev2.start(&DeviceConfig {
        private_key: peer2_key,
        adapter: AdapterType::BoringTun,
        fwmark: None,
        name: Some("tun11".to_owned()),
        tun: None,
    })
    .unwrap();

    let dev1_meshnet_config = Config {
        this: peer1.base.clone(),
        peers: Some(vec![peer2.clone()]),
        derp_servers: Some(get_derp_servers()),
        dns: None,
    };
    let dev2_meshnet_config = Config {
        this: peer2.base.clone(),
        peers: Some(vec![peer1.clone()]),
        derp_servers: Some(get_derp_servers()),
        dns: None,
    };

    dev1.set_config(&Some(dev1_meshnet_config)).unwrap();
    dev2.set_config(&Some(dev2_meshnet_config)).unwrap();

    std::thread::sleep(std::time::Duration::from_secs(20));

    // verify connection by checking events

    dev1.stop();
    dev2.stop();

    dev1.shutdown_art();
    dev2.shutdown_art();
}

#[test]
fn test_poc_vpn() {
    let event_dispatcher = move |event: Box<Event>| {
        println!("Event: {event:?}");
    };

    let mut dev = Device::new(Default::default(), event_dispatcher, None).unwrap();
    dev.start(&DeviceConfig {
        private_key: SecretKey::gen(),
        adapter: AdapterType::BoringTun,
        fwmark: None,
        name: Some("tun10".to_owned()),
        tun: None,
    })
    .unwrap();
    let node = ExitNode {
        identifier: "wgserver".to_owned(),
        public_key: SecretKey::gen().public(),
        allowed_ips: None,
        endpoint: Some("10.0.100.1:1023".parse().unwrap()),
    };
    dev.connect_exit_node(&node).unwrap();

    // verify connection by checking events
    // stun
}
