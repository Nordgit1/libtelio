import asyncio
import base64
import config
import itertools
import pytest
import re
import telio
import timeouts
from collections import defaultdict
from config import DERP_SERVERS
from contextlib import AsyncExitStack, asynccontextmanager
from helpers import Environment, setup_mesh_nodes, SetupParameters
from mesh_api import Node
from telio import PathType, State
from telio_features import (
    Batching,
    TelioFeatures,
    Direct,
    Lana,
    Nurse,
    Wireguard,
    SkipUnresponsivePeers,
    FeatureEndpointProvidersOptimization,
    PersistentKeepalive,
)
from typing import Any, Dict, List, Tuple
from utils.asyncio_util import run_async_context
from utils.connection_util import Connection, ConnectionTag
from utils.ping import ping
from utils.telio_log_notifier import TelioLogNotifier

ANY_PROVIDERS = ["local", "stun"]

DOCKER_CONE_GW_1_IP = "10.0.254.1"
DOCKER_CONE_GW_2_IP = "10.0.254.2"
DOCKER_FULLCONE_GW_1_IP = "10.0.254.9"
DOCKER_FULLCONE_GW_2_IP = "10.0.254.6"
DOCKER_OPEN_INTERNET_CLIENT_1_IP = "10.0.11.2"
DOCKER_OPEN_INTERNET_CLIENT_2_IP = "10.0.11.3"
DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK_IP = "10.0.11.4"
DOCKER_SYMMETRIC_CLIENT_1_IP = "192.168.103.88"
DOCKER_SYMMETRIC_GW_1_IP = "10.0.254.3"
DOCKER_UPNP_GW_1_IP = "10.0.254.5"
DOCKER_UPNP_GW_2_IP = "10.0.254.12"


def _generate_setup_parameters(
    clients: List[Tuple[ConnectionTag, List[str], bool]],
) -> List[SetupParameters]:
    return [
        SetupParameters(
            connection_tag=conn_tag,
            adapter_type=telio.AdapterType.BoringTun,
            features=TelioFeatures(
                direct=Direct(providers=endpoint_providers),
                batching=Batching(direct_connection_threshold=5) if batching else None,
                wireguard=Wireguard(
                    persistent_keepalive=PersistentKeepalive(direct=10),
                ),
            ),
            fingerprint=f"{conn_tag}",
        )
        for conn_tag, endpoint_providers, batching in clients
    ]


def _generate_setup_parameters_with_reflexive_ips(
    clients: List[Tuple[ConnectionTag, List[str], bool, str]],
) -> Tuple[List[SetupParameters], List[str]]:
    setup_parameters = _generate_setup_parameters(
        [(ct, p, b) for ct, p, b, _ in clients]
    )
    return setup_parameters, [gw_ip for *_, gw_ip in clients]


# fmt: off
UHP_WORKING_PATHS_PARAMS = [
    [
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_1, ["stun"], True, DOCKER_FULLCONE_GW_1_IP),
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_2, ["stun"], False, DOCKER_FULLCONE_GW_2_IP),
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ["stun"], True, DOCKER_CONE_GW_1_IP),
        (ConnectionTag.DOCKER_CONE_CLIENT_2, ["stun"], False, DOCKER_CONE_GW_2_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["stun"], True, DOCKER_OPEN_INTERNET_CLIENT_1_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2, ["stun"], False, DOCKER_OPEN_INTERNET_CLIENT_2_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK, ["stun"], False, DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK_IP),
        (ConnectionTag.DOCKER_UPNP_CLIENT_1, ["upnp"], True, DOCKER_UPNP_GW_1_IP),
        (ConnectionTag.DOCKER_UPNP_CLIENT_2, ["upnp"], False, DOCKER_UPNP_GW_2_IP),
    ],
    [
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ["stun"], True, DOCKER_SYMMETRIC_GW_1_IP),
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_1, ["stun"], True, DOCKER_FULLCONE_GW_1_IP),
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_2, ["stun"], False, DOCKER_FULLCONE_GW_2_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["stun"], True, DOCKER_OPEN_INTERNET_CLIENT_1_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2, ["stun"], False, DOCKER_OPEN_INTERNET_CLIENT_2_IP),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK, ["stun"], True, DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK_IP),
    ],
    [
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["local"], True, DOCKER_OPEN_INTERNET_CLIENT_1_IP),
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ["local"], True, DOCKER_OPEN_INTERNET_CLIENT_1_IP),
    ],
    [
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ["local"], True, DOCKER_SYMMETRIC_CLIENT_1_IP),
        (ConnectionTag.DOCKER_INTERNAL_SYMMETRIC_CLIENT, ["local"], True, DOCKER_SYMMETRIC_CLIENT_1_IP),
    ],
]
# fmt: on


async def _ping_between_all_nodes(env: Environment) -> None:
    await asyncio.gather(*[
        ping(conn.connection, node.ip_addresses[0])
        for (client, conn), node in itertools.product(
            zip(env.clients, env.connections), env.nodes
        )
        if not client.is_node(node)
    ])


async def _check_if_true_direct_connection(env: Environment) -> None:
    async with AsyncExitStack() as temp_exit_stack:
        await asyncio.gather(*[
            temp_exit_stack.enter_async_context(
                client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )
            for client, server in itertools.product(env.clients, DERP_SERVERS)
        ])

        await asyncio.gather(*[
            client.wait_for_state_on_any_derp([State.Connecting, State.Disconnected])
            for client in env.clients
        ])

        await _ping_between_all_nodes(env)

    await asyncio.gather(*[
        client.wait_for_state_on_any_derp([State.Connected]) for client in env.clients
    ])


@asynccontextmanager
async def _disable_direct_connection(env: Environment, reflexive_ips: List[str]):
    async with AsyncExitStack() as temp_exit_stack:
        await asyncio.gather(*[
            temp_exit_stack.enter_async_context(
                client.get_router().disable_path(reflexive_ip)
            )
            for client, reflexive_ip in itertools.product(env.clients, reflexive_ips)
        ])

        await asyncio.gather(*[
            conn.connection.create_process(["conntrack", "-F"]).execute()
            for conn in env.connections
        ])

        yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setup_params, reflexive_ips",
    [
        pytest.param(
            *_generate_setup_parameters_with_reflexive_ips(clients),
        )
        for clients in UHP_WORKING_PATHS_PARAMS
    ],
)
async def test_direct_working_paths(
    setup_params: List[SetupParameters], reflexive_ips: List[str]
) -> None:
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params)

        print("Test direct connection")
        await _check_if_true_direct_connection(env)

        print("Test direct -> relay -> direct transitions")
        relay_events = await asyncio.gather(*[
            exit_stack.enter_async_context(
                run_async_context(
                    client.wait_for_event_peer(
                        node.public_key, [State.Connected], [PathType.Relay]
                    )
                )
            )
            for client, node in itertools.product(env.clients, env.nodes)
            if not client.is_node(node)
        ])

        direct_events = await asyncio.gather(*[
            exit_stack.enter_async_context(
                run_async_context(
                    client.wait_for_event_peer(
                        node.public_key, [State.Connected], [PathType.Direct]
                    )
                )
            )
            for client, node in itertools.product(env.clients, env.nodes)
            if not client.is_node(node)
        ])

        async with _disable_direct_connection(env, reflexive_ips):
            await asyncio.gather(*relay_events)
            await _ping_between_all_nodes(env)

        await asyncio.gather(*direct_events)
        await _check_if_true_direct_connection(env)

        print("Test direct connection on short connection loss")
        possible_relay_events: Dict[Connection, Dict[Node, Any]] = defaultdict(dict)
        for (client, conn), node in itertools.product(
            zip(env.clients, env.connections), env.nodes
        ):
            if client.is_node(node):
                continue
            possible_relay_events[conn.connection][node] = (
                await exit_stack.enter_async_context(
                    run_async_context(
                        client.wait_for_event_peer(
                            node.public_key, [State.Connected], [PathType.Relay]
                        )
                    )
                )
            )

        async with _disable_direct_connection(env, reflexive_ips):

            async def ping_timeout(connection, node):
                try:
                    await ping(connection, node.ip_addresses[0], 10)
                except asyncio.TimeoutError:
                    pass
                else:
                    # if no timeout exception happens, this means, that peers connected through relay
                    # faster than we expected, but if no relay event occurs, this means, that something
                    # else was wrong, so we asserts
                    await asyncio.wait_for(possible_relay_events[connection][node], 1)

            await asyncio.gather(*[
                ping_timeout(conn.connection, node)
                for (client, conn), node in itertools.product(
                    zip(env.clients, env.connections), env.nodes
                )
                if not client.is_node(node)
            ])

        await _ping_between_all_nodes(env)


@pytest.mark.moose
@pytest.mark.asyncio
@pytest.mark.timeout(
    timeouts.TEST_DIRECT_WORKING_PATHS_ARE_REESTABLISHED_AND_CORRECTLY_REPORTED_IN_ANALYTICS_TIMEOUT
)
async def test_direct_working_paths_are_reestablished_and_correctly_reported_in_analytics() -> (
    None
):
    setup_params = _generate_setup_parameters([
        (ConnectionTag.DOCKER_UPNP_CLIENT_1, ["upnp"], True),
        (ConnectionTag.DOCKER_CONE_CLIENT_2, ["stun"], False),
    ])
    reflexive_ip = DOCKER_CONE_GW_2_IP

    async with AsyncExitStack() as exit_stack:
        for param in setup_params:
            param.features.nurse = Nurse(
                enable_nat_traversal_conn_data=True,
                enable_nat_type_collection=True,
            )
            param.features.lana = Lana(prod=False, event_path="/event.db")
        env = await setup_mesh_nodes(exit_stack, setup_params)
        alpha, beta = env.nodes
        alpha_client, beta_client = env.clients

        def fix_provider_name(name):
            return "UPnP" if name == "upnp" else name.title()

        alpha_direct = alpha_client.get_features().direct
        # Asserts are here to silence mypy...
        assert alpha_direct is not None
        assert alpha_direct.providers is not None
        assert len(alpha_direct.providers) > 0
        alpha_provider = fix_provider_name(alpha_direct.providers[0])

        beta_direct = beta_client.get_features().direct
        # Asserts are here to silence mypy...
        assert beta_direct is not None
        assert beta_direct.providers is not None
        assert len(beta_direct.providers) > 0
        beta_provider = fix_provider_name(beta_direct.providers[0])

        alpha_connection, beta_connection = [
            conn.connection for conn in env.connections
        ]

        # We need to compare the decoded forms, not the base64 encoded strings
        if base64.b64decode(alpha.public_key) < base64.b64decode(beta.public_key):
            reporting_connection = alpha_connection
            losing_key = beta.public_key
            from_provider = alpha_provider
            to_provider = beta_provider
        else:
            reporting_connection = beta_connection
            losing_key = alpha.public_key
            from_provider = beta_provider
            to_provider = alpha_provider

        await asyncio.gather(
            alpha_client.wait_for_state_peer(
                beta.public_key, [State.Connected], [PathType.Direct]
            ),
            beta_client.wait_for_state_peer(
                alpha.public_key, [State.Connected], [PathType.Direct]
            ),
        )
        await ping(alpha_connection, beta.ip_addresses[0])

        telio_log_notifier = await exit_stack.enter_async_context(
            TelioLogNotifier(reporting_connection).run()
        )

        # Break UHP
        async with AsyncExitStack() as direct_disabled_exit_stack:
            relayed_state_reported = telio_log_notifier.notify_output(
                f'Relayed peer state change for "{losing_key[:4]}...{losing_key[-4:]}" to Connected will be reported'
            )

            await direct_disabled_exit_stack.enter_async_context(
                alpha_client.get_router().disable_path(reflexive_ip)
            )

            await asyncio.gather(
                alpha_client.wait_for_state_peer(
                    beta.public_key,
                    [State.Connected],
                    [PathType.Relay],
                ),
                beta_client.wait_for_state_peer(
                    alpha.public_key,
                    [State.Connected],
                    [PathType.Relay],
                ),
                relayed_state_reported.wait(),
            )

            await ping(alpha_connection, beta.ip_addresses[0])

            direct_state_reported = telio_log_notifier.notify_output(
                f'Direct peer state change for "{losing_key[:4]}...{losing_key[-4:]}" to Connected'
                f" ({from_provider} -> {to_provider}) will be reported",
            )

        await asyncio.gather(
            alpha_client.wait_for_state_peer(
                beta.public_key, [State.Connected], [PathType.Direct]
            ),
            beta_client.wait_for_state_peer(
                alpha.public_key, [State.Connected], [PathType.Direct]
            ),
            direct_state_reported.wait(),
        )
        await ping(alpha_connection, beta.ip_addresses[0])

        # This is expected. Clients can still receive messages from
        # the previous sessions.
        alpha_client.allow_errors(["boringtun::device.*Decapsulate error"])
        beta_client.allow_errors(["boringtun::device.*Decapsulate error"])

        # LLT-5532: To be cleaned up...
        alpha_client.allow_errors(
            ["telio_proxy::proxy.*Unable to send. WG Address not available"]
        )
        beta_client.allow_errors(
            ["telio_proxy::proxy.*Unable to send. WG Address not available"]
        )


@pytest.mark.asyncio
async def test_direct_working_paths_stun_ipv6() -> None:
    setup_params = [
        SetupParameters(
            connection_tag=conn_tag,
            adapter_type=telio.AdapterType.BoringTun,
            features=TelioFeatures(
                direct=Direct(
                    providers=["stun"],
                ),
                ipv6=True,
            ),
        )
        for conn_tag in [
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_1),
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_2),
        ]
    ]
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params)
        _, beta = env.nodes
        alpha_client, beta_client = env.clients
        alpha_connection, _ = [conn.connection for conn in env.connections]

        for server in DERP_SERVERS:
            await exit_stack.enter_async_context(
                alpha_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )
            await exit_stack.enter_async_context(
                beta_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )

        await ping(alpha_connection, beta.ip_addresses[0])

        # LLT-5532: To be cleaned up...
        alpha_client.allow_errors(
            ["telio_proxy::proxy.*Unable to send. WG Address not available"]
        )
        beta_client.allow_errors(
            ["telio_proxy::proxy.*Unable to send. WG Address not available"]
        )


@pytest.mark.asyncio
async def test_direct_working_paths_with_skip_unresponsive_peers() -> None:
    # Force shorter unresponsive peer handshake threshold
    # and adjust wireguard keepalives accordingly too
    # in order to allow for three packet drops
    setup_params = [
        SetupParameters(
            connection_tag=conn_tag,
            adapter_type=telio.AdapterType.BoringTun,
            features=TelioFeatures(
                direct=Direct(
                    providers=["stun"],
                    skip_unresponsive_peers=SkipUnresponsivePeers(
                        no_rx_threshold_secs=16
                    ),
                ),
                wireguard=Wireguard(
                    persistent_keepalive=PersistentKeepalive(proxying=5, direct=5)
                ),
            ),
        )
        for conn_tag in [
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_1),
            (ConnectionTag.DOCKER_CONE_CLIENT_1),
            (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1),
            (ConnectionTag.DOCKER_FULLCONE_CLIENT_2),
            (ConnectionTag.DOCKER_CONE_CLIENT_2),
        ]
    ]

    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params)
        api = env.api
        *_, delta, epsilon = env.nodes
        alpha_client, beta_client, gamma_client, delta_client, epsilon_client = (
            env.clients
        )

        await _ping_between_all_nodes(env)

        await delta_client.stop_device()
        await epsilon_client.stop_device()

        await asyncio.gather(*[
            running_client.wait_for_log(
                f"Skipping sending CMM to peer {stopped_node.public_key} (Unresponsive)"
            )
            for running_client, stopped_node in itertools.product(
                [alpha_client, beta_client, gamma_client], [delta, epsilon]
            )
        ])

        await delta_client.simple_start()
        await epsilon_client.simple_start()
        await delta_client.set_meshmap(api.get_meshmap(delta.id))
        await epsilon_client.set_meshmap(api.get_meshmap(epsilon.id))

        await asyncio.gather(*[
            client.wait_for_state_peer(
                node.public_key, [State.Connected], [PathType.Direct]
            )
            for client, node in itertools.product(env.clients, env.nodes)
            if not client.is_node(node)
        ])

        await _ping_between_all_nodes(env)

        # This is expected. Alpha client can still receive messages from
        # the previous session from beta after the restart.
        alpha_client.allow_errors(["boringtun::device.*Decapsulate error"])


@pytest.mark.asyncio
# Regression test for LLT-4306
async def test_direct_infinite_stun_loop() -> None:
    setup_params = _generate_setup_parameters([
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ["stun"], True),
        (ConnectionTag.DOCKER_CONE_CLIENT_2, ["stun"], False),
    ])
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params)
        alpha_client, _ = env.clients
        alpha_connection, _ = [conn.connection for conn in env.connections]

        for server in config.DERP_SERVERS:
            await exit_stack.enter_async_context(
                alpha_client.get_router().break_udp_conn_to_host(str(server["ipv4"]))
            )

        # 3478 and 3479 are STUN ports in natlab containers
        tcpdump = await exit_stack.enter_async_context(
            alpha_connection.create_process([
                "tcpdump",
                "--immediate-mode",
                "-l",
                "-i",
                "any",
                "(",
                "port",
                "3478",
                "or",
                "3479",
                ")",
            ]).run()
        )
        await asyncio.sleep(5)

        stun_requests = tcpdump.get_stdout().splitlines()
        # There seems to be some delay when getting stdout from a process
        # Without this delay, `stun_requests` is empty even if tcpdump reports traffic
        await asyncio.sleep(0.5)
        # 20 is a semi-random number that is low enough to prove the original issue is not present
        # while being high enough to prevent false-positivies.
        # The actual number of requests will be lower given the time frame that is being measured.
        assert len(stun_requests) < 20


@pytest.mark.asyncio
async def test_direct_working_paths_with_pausing_upnp_and_stun() -> None:
    setup_params = _generate_setup_parameters([
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_1, ["stun"], True),
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_2, ["stun"], False),
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ["stun"], True),
        (ConnectionTag.DOCKER_CONE_CLIENT_2, ["stun"], False),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["stun"], True),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_2, ["stun"], False),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_DUAL_STACK, ["stun"], False),
        (ConnectionTag.DOCKER_UPNP_CLIENT_1, ["upnp"], True),
        (ConnectionTag.DOCKER_UPNP_CLIENT_2, ["upnp"], False),
    ])

    async with AsyncExitStack() as exit_stack:
        providers: List[List[str]] = []
        for param in setup_params:
            assert param.features.direct is not None
            param.features.direct.endpoint_providers_optimization = (
                FeatureEndpointProvidersOptimization(
                    optimize_direct_upgrade_stun=True,
                    optimize_direct_upgrade_upnp=True,
                )
            )
            assert param.features.direct.providers is not None
            providers.append(param.features.direct.providers)

        env = await setup_mesh_nodes(exit_stack, setup_params)

        await _ping_between_all_nodes(env)

        await asyncio.gather(*[
            (
                client.wait_for_log(
                    "Skipping getting endpoint via STUN endpoint provider(ModulePaused)"
                )
                if "stun" in provider
                else client.wait_for_log(
                    "Skipping getting endpoint via UPNP endpoint provider(ModulePaused)"
                )
            )
            for client, provider in zip(env.clients, providers)
        ])

        tcpdumps = await asyncio.gather(*[
            exit_stack.enter_async_context(
                conn.connection.create_process([
                    "tcpdump",
                    "--immediate-mode",
                    "-l",
                    "-i",
                    "any",
                ]).run()
            )
            for conn in env.connections
        ])
        await asyncio.sleep(5)

        packets = itertools.chain.from_iterable(
            tcpdump.get_stdout().splitlines() for tcpdump in tcpdumps
        )

        # filter outgoing stun packets by ports 3478/3479
        # filter upnp igd request packets by ip (ssdp multicast ip)
        # use regex with a few more symbols to avoid false positives
        match_pattern = r"\.347[89]:|239\.255\.255\.250"

        stun_upnp_requests = [
            request
            for request in packets
            if re.search(match_pattern, request) is not None
        ]

        assert len(stun_upnp_requests) == 0


UHP_FAILING_PATHS_PARAMS = [
    [
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_2, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_1, ANY_PROVIDERS, False),
        (ConnectionTag.DOCKER_UDP_BLOCK_CLIENT_2, ANY_PROVIDERS, False),
    ],
    [
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["local"], False),
        (ConnectionTag.DOCKER_FULLCONE_CLIENT_1, ["local"], False),
    ],
    [
        (ConnectionTag.DOCKER_CONE_CLIENT_1, ["local"], False),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["local"], False),
    ],
    [
        (ConnectionTag.DOCKER_SYMMETRIC_CLIENT_1, ["local"], False),
        (ConnectionTag.DOCKER_OPEN_INTERNET_CLIENT_1, ["local"], False),
    ],
]

UHP_FAILING_PATHS = [
    pytest.param(
        _generate_setup_parameters(clients),
    )
    for clients in UHP_FAILING_PATHS_PARAMS
]


@pytest.mark.asyncio
@pytest.mark.long
@pytest.mark.timeout(timeouts.TEST_DIRECT_FAILING_PATHS_TIMEOUT)
@pytest.mark.parametrize("setup_params", UHP_FAILING_PATHS)
# Not sure this is needed. It will only be helpful to catch if any
# libtelio change would make any of these setup work.
async def test_direct_failing_paths(setup_params: List[SetupParameters]) -> None:
    async with AsyncExitStack() as exit_stack:
        env = await setup_mesh_nodes(exit_stack, setup_params, is_timeout_expected=True)
        _, beta = env.nodes
        alpha_client, beta_client = env.clients
        alpha_connection, _ = [conn.connection for conn in env.connections]

        for server in DERP_SERVERS:
            await exit_stack.enter_async_context(
                alpha_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )
            await exit_stack.enter_async_context(
                beta_client.get_router().break_tcp_conn_to_host(str(server["ipv4"]))
            )

        await asyncio.gather(
            alpha_client.wait_for_state_on_any_derp([State.Connecting]),
            beta_client.wait_for_state_on_any_derp([State.Connecting]),
        )

        with pytest.raises(asyncio.TimeoutError):
            await ping(alpha_connection, beta.ip_addresses[0], 15)
