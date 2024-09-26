import asyncio
import pytest
from contextlib import AsyncExitStack
from helpers import setup_mesh_nodes, SetupParameters
from telio import AdapterType
from typing import List, Tuple
from utils.bindings import default_features
from utils.connection_util import ConnectionTag, Connection, TargetOS
from utils.multicast import MulticastClient, MulticastServer


def generate_setup_parameter_pair(
    cfg: List[Tuple[ConnectionTag, AdapterType]],
) -> List[SetupParameters]:
    return [
        SetupParameters(
            connection_tag=conn_tag,
            adapter_type=adapter_type,
            features=default_features(enable_multicast=True),
        )
        for conn_tag, adapter_type in cfg
    ]


MUILTICAST_TEST_PARAMS = [
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_2, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
        ]),
        "ssdp",
    ),
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_2, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
        ]),
        "mdns",
    ),
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.WINDOWS_VM_1, AdapterType.WireguardGo),
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_2, AdapterType.BoringTun),
        ]),
        "ssdp",
    ),
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.WINDOWS_VM_1, AdapterType.WindowsNativeWg),
            (ConnectionTag.DOCKER_CONE_CLIENT_2, AdapterType.BoringTun),
        ]),
        "mdns",
    ),
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.MAC_VM, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_2, AdapterType.BoringTun),
        ]),
        "ssdp",
        marks=pytest.mark.mac,
    ),
    pytest.param(
        generate_setup_parameter_pair([
            (ConnectionTag.DOCKER_CONE_CLIENT_1, AdapterType.BoringTun),
            (ConnectionTag.MAC_VM, AdapterType.BoringTun),
            (ConnectionTag.DOCKER_CONE_CLIENT_2, AdapterType.BoringTun),
        ]),
        "mdns",
        marks=pytest.mark.mac,
    ),
]


async def add_multicast_route(connection: Connection) -> None:
    if connection.target_os == TargetOS.Linux:
        ipconf = connection.create_process(
            ["ip", "route", "add", "224.0.0.0/4", "dev", "tun10"]
        )
        await ipconf.execute()
    elif connection.target_os == TargetOS.Mac:
        ipconf = await connection.create_process(
            ["route", "delete", "224.0.0.0/4"]
        ).execute()
        ipconf = await connection.create_process(
            ["route", "add", "-net", "224.0.0.0/4", "-interface", "utun10"]
        ).execute()


@pytest.mark.asyncio
@pytest.mark.parametrize("setup_params, protocol", MUILTICAST_TEST_PARAMS)
async def test_multicast(setup_params: List[SetupParameters], protocol: str) -> None:
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params)
        client_alpha, client_beta, _ = env.clients
        alpha, beta, gamma = env.nodes

        mesh_configs = [
            env.api.get_meshnet_config(alpha.id),
            env.api.get_meshnet_config(beta.id),
        ]
        # Only setting allow_multicast to False, because peer_allow_multicast flag is
        # tested by a unit test in Libtelio.
        for mesh_config in mesh_configs:
            if mesh_config.peers is not None:
                for peer in mesh_config.peers:
                    if peer.base.hostname == gamma.hostname:
                        peer.allow_multicast = False
        await client_alpha.set_meshnet_config(mesh_configs[0])
        await client_beta.set_meshnet_config(mesh_configs[1])

        alpha_connection, beta_connection, gamma_connection = [
            conn.connection for conn in env.connections
        ]

        await add_multicast_route(alpha_connection)
        await add_multicast_route(beta_connection)
        await add_multicast_route(gamma_connection)

        async with MulticastServer(beta_connection, protocol).run() as server:
            await server.wait_till_ready()
            await MulticastClient(alpha_connection, protocol).execute()
        async with MulticastServer(gamma_connection, protocol).run() as server:
            await server.wait_till_ready()
            with pytest.raises(asyncio.TimeoutError):
                await MulticastClient(alpha_connection, protocol).execute()
