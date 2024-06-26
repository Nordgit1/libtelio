import pytest
import telio
from contextlib import AsyncExitStack
from helpers import SetupParameters, setup_mesh_nodes
from telio_features import TelioFeatures, Direct
from utils.connection_util import ConnectionTag
from utils.ping import Ping


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disable_connected_socket",
    [True, False],
)
@pytest.mark.parametrize(
    "beta_tag",
    [ConnectionTag.MAC_VM, ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2],
)
async def test_mesh_connected_socket_ping(disable_connected_socket, beta_tag) -> None:
    async with AsyncExitStack() as exit_stack:
        features_beta = TelioFeatures(
            direct=Direct(),
            disable_connected_socket=disable_connected_socket,
        )
        env = await setup_mesh_nodes(
            exit_stack,
            [
                SetupParameters(
                    connection_tag=ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1,
                    adapter_type=telio.AdapterType.BoringTun,
                    features=TelioFeatures(
                        direct=Direct(),
                    ),
                ),
                SetupParameters(
                    connection_tag=beta_tag,
                    adapter_type=telio.AdapterType.BoringTun,
                    features=features_beta,
                ),
            ],
        )
        alpha, beta = env.nodes

        connection_alpha, connection_beta = [
            conn.connection for conn in env.connections
        ]

        async with Ping(connection_alpha, beta.ip_addresses[0]).run() as ping:
            await ping.wait_for_next_ping()
        async with Ping(connection_beta, alpha.ip_addresses[0]).run() as ping:
            await ping.wait_for_next_ping()
