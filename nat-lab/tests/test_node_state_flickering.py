import asyncio
import itertools
import pytest
import timeouts
from contextlib import AsyncExitStack
from helpers import SetupParameters, setup_mesh_nodes
from typing import Tuple
from utils.bindings import (
    features_with_endpoint_providers,
    EndpointProvider,
    TelioAdapterType,
    NodeState,
    RelayState,
    PathType,
)
from utils.connection import TargetOS
from utils.connection_tracker import ConnectionLimits
from utils.connection_util import generate_connection_tracker_config, ConnectionTag


@pytest.mark.asyncio
@pytest.mark.timeout(timeouts.TEST_NODE_STATE_FLICKERING_RELAY_TIMEOUT)
@pytest.mark.long
@pytest.mark.parametrize(
    "alpha_setup_params",
    [
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.DOCKER_CONE_CLIENT_1,
                adapter_type=TelioAdapterType.BORING_TUN,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.DOCKER_CONE_CLIENT_1,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            )
        ),
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.DOCKER_CONE_CLIENT_1,
                adapter_type=TelioAdapterType.LINUX_NATIVE_TUN,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.DOCKER_CONE_CLIENT_1,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            ),
            marks=pytest.mark.linux_native,
        ),
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.WINDOWS_VM_1,
                adapter_type=TelioAdapterType.WINDOWS_NATIVE_TUN,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.WINDOWS_VM_1,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            ),
            marks=pytest.mark.windows,
        ),
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.WINDOWS_VM_1,
                adapter_type=TelioAdapterType.WIREGUARD_GO_TUN,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.WINDOWS_VM_1,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            ),
            marks=pytest.mark.windows,
        ),
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.MAC_VM,
                adapter_type=TelioAdapterType.BORING_TUN,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.MAC_VM,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            ),
            marks=pytest.mark.mac,
        ),
    ],
)
@pytest.mark.parametrize(
    "beta_setup_params",
    [
        pytest.param(
            SetupParameters(
                connection_tag=ConnectionTag.DOCKER_CONE_CLIENT_2,
                connection_tracker_config=generate_connection_tracker_config(
                    ConnectionTag.DOCKER_CONE_CLIENT_2,
                    derp_1_limits=ConnectionLimits(1, 1),
                ),
            )
        )
    ],
)
async def test_node_state_flickering_relay(
    alpha_setup_params: SetupParameters, beta_setup_params: SetupParameters
) -> None:
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(
            exit_stack, [alpha_setup_params, beta_setup_params]
        )
        alpha, beta = env.nodes
        client_alpha, client_beta = env.clients

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.gather(
                client_alpha.wait_for_event_peer(
                    beta.public_key, list(NodeState), timeout=120
                ),
                client_beta.wait_for_event_peer(
                    alpha.public_key, list(NodeState), timeout=120
                ),
                client_alpha.wait_for_event_on_any_derp(list(RelayState), timeout=120),
                client_beta.wait_for_event_on_any_derp(list(RelayState), timeout=120),
            )


CFG = [
    (TargetOS.Windows, TelioAdapterType.WINDOWS_NATIVE_TUN),
    (TargetOS.Windows, TelioAdapterType.WIREGUARD_GO_TUN),
    (TargetOS.Linux, TelioAdapterType.BORING_TUN),
    (TargetOS.Linux, TelioAdapterType.LINUX_NATIVE_TUN),
]


@pytest.mark.long
@pytest.mark.timeout(timeouts.TEST_NODE_STATE_FLICKERING_DIRECT_TIMEOUT)
@pytest.mark.parametrize(
    "alpha_cfg, beta_cfg", itertools.combinations_with_replacement(CFG, 2)
)
async def test_node_state_flickering_direct(
    alpha_cfg: Tuple[TargetOS, TelioAdapterType],
    beta_cfg: Tuple[TargetOS, TelioAdapterType],
) -> None:
    async with AsyncExitStack() as exit_stack:
        (alpha_target_os, alpha_adapter_type) = alpha_cfg
        (beta_target_os, beta_adapter_type) = beta_cfg
        alpha_conn_tag = (
            ConnectionTag.WINDOWS_VM_1
            if alpha_target_os == TargetOS.Windows
            else ConnectionTag.DOCKER_CONE_CLIENT_1
        )
        beta_conn_tag = (
            ConnectionTag.WINDOWS_VM_2
            if beta_target_os == TargetOS.Windows
            else ConnectionTag.DOCKER_CONE_CLIENT_2
        )

        env = await setup_mesh_nodes(
            exit_stack,
            [
                SetupParameters(
                    connection_tag=alpha_conn_tag,
                    adapter_type=alpha_adapter_type,
                    features=features_with_endpoint_providers([
                        EndpointProvider.STUN,
                        EndpointProvider.LOCAL,
                        EndpointProvider.UPNP,
                    ]),
                ),
                SetupParameters(
                    connection_tag=beta_conn_tag,
                    adapter_type=beta_adapter_type,
                    features=features_with_endpoint_providers([
                        EndpointProvider.STUN,
                        EndpointProvider.LOCAL,
                        EndpointProvider.UPNP,
                    ]),
                ),
            ],
        )
        alpha, beta = env.nodes
        client_alpha, client_beta = env.clients

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.gather(
                client_alpha.wait_for_event_peer(
                    beta.public_key,
                    list(NodeState),
                    list(PathType),
                    timeout=120,
                ),
                client_beta.wait_for_event_peer(
                    alpha.public_key,
                    list(NodeState),
                    list(PathType),
                    timeout=120,
                ),
                client_alpha.wait_for_event_on_any_derp(list(RelayState), timeout=120),
                client_beta.wait_for_event_on_any_derp(list(RelayState), timeout=120),
            )
