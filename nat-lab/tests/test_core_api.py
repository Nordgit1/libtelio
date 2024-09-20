import base64
import json
import os as rng
import pytest
from contextlib import AsyncExitStack
from dataclasses import dataclass, fields
from typing import List
from utils.connection_util import ConnectionTag, new_connection_by_tag
from uuid import UUID


@dataclass
class MachineData:
    public_key: str
    hardware_identifier: str
    os: str
    os_version: str


@dataclass
class Peer:
    identifier: str
    public_key: str
    hostname: str
    os: str
    os_version: str
    device_type: str
    nickname: str
    ip_addresses: List[str]
    is_local: bool
    allow_incoming_connections: bool


class DerpServer:
    region_code: str
    name: str
    hostname: str
    ipv4: str
    relay_port: int
    stun_port: int
    stun_plaintext_port: int
    public_key: str
    weight: int


def generate_wireguard_like_public_key():
    random_bytes = rng.urandom(32)
    public_key_base64 = base64.b64encode(random_bytes).decode("utf-8")
    return public_key_base64


def generate_hardware_identifier():
    return rng.urandom(16).hex()


def validate_dataclass(dataclass_instance, data_to_validate):
    for field in fields(dataclass_instance):
        field_name = field.name
        field_type = field.type

        assert field_name in data_to_validate, f"Missing field: {field_name}"
        assert isinstance(
            data_to_validate[field_name], field_type
        ), f"Field '{field_name}' should be of type {field_type}, but got {type(data_to_validate[field_name])}"


def verify_uuid(uuid_to_test, version=4):
    try:
        uuid_obj = UUID(uuid_to_test, version=version)
    except ValueError:
        assert False, "Not a valid UUID"
    assert str(uuid_obj) == uuid_to_test, "Not a valid UUID"


def create_machine_data(public_key, hardware_identifier, os, os_version):
    return MachineData(
        public_key=public_key,
        hardware_identifier=hardware_identifier,
        os=os,
        os_version=os_version,
    )


async def send_http_request(
    connection, endpoint, method, data=None, expect_response=True
):
    curl_command = [
        "curl",
        "-X",
        method,
        endpoint,
        "-H",
        "Content-Type: application/json",
    ]

    if data:
        curl_command.extend(["-d", json.dumps(data)])

    process = await connection.create_process(curl_command).execute()
    response = process.get_stdout()
    if expect_response:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            assert False, f"Expected JSON response but got: {response}"
    return None


async def clean_up_machines(connection, server_host):
    machines = await send_http_request(
        connection, f"{server_host}/v1/meshnet/machines", method="GET"
    )

    for machine in machines:
        await send_http_request(
            connection,
            f"{server_host}/v1/meshnet/machines/{machine['identifier']}",
            method="DELETE",
            expect_response=False,
        )


@pytest.fixture(name="machine_data")
def fixture_machine_data(request):
    return request.param


@pytest.fixture(name="server_host")
def fixture_server_host():
    return "http://10.0.80.86:8080"


@pytest.fixture(name="registered_machines")
async def fixture_register_machine(server_host, machine_data):
    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )

        await clean_up_machines(connection, server_host)

        registered_machines = []

        for data in machine_data:
            payload = json.dumps(data.__dict__)

            response_data = await send_http_request(
                connection,
                f"{server_host}/v1/meshnet/machines",
                method="POST",
                data=payload,
            )
            registered_machines.append(response_data)

        return registered_machines


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_data",
    [[
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "linux",
            "Ubuntu 22.04; kernel=5.15.0-78-generic",
        ),
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "windows",
            "Windows 11; kernel=10.0.22621.2283",
        ),
    ]],
    indirect=True,
)
async def test_register_multiple_machines(registered_machines, machine_data):
    assert len(registered_machines) == 2
    for machine, data in zip(registered_machines, machine_data):
        verify_uuid(machine["identifier"])
        assert machine["public_key"] == data.public_key
        assert machine["os"] == data.os
        assert machine["os_version"] == data.os_version
        assert "hostname" in machine
        assert "device_type" in machine
        assert "nickname" in machine
        assert "ip_addresses" in machine
        assert "discovery_key" in machine
        assert "relay_address" in machine
        assert not machine["traffic_routing_supported"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_data",
    [[
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "linux",
            "Ubuntu 22.04; kernel=5.15.0-78-generic",
        ),
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "windows",
            "Windows 11; kernel=10.0.22621.2283",
        ),
    ]],
    indirect=True,
)
async def test_get_all_machines(server_host, registered_machines, machine_data):
    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )

        response_data = await send_http_request(
            connection, f"{server_host}/v1/meshnet/machines", "GET"
        )

        assert isinstance(response_data, list)
        assert len(response_data) == 2

        for machine, data in zip(registered_machines, machine_data):
            verify_uuid(machine["identifier"])
            assert machine["public_key"] == data.public_key
            assert machine["os"] == data.os
            assert machine["os_version"] == data.os_version


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_data",
    [[
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "linux",
            "Ubuntu 22.04; kernel=5.15.0-78-generic",
        )
    ]],
    indirect=True,
)
async def test_update_registered_machine_data(
    server_host, registered_machines, machine_data
):
    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )

        original_data = machine_data[0]

        machine_data_to_update = {
            "nickname": "Updated Machine",
            "os_version": "5.12",
        }

        payload = json.dumps(machine_data_to_update)

        for machine in registered_machines:

            response_data = await send_http_request(
                connection,
                f"{server_host}/v1/meshnet/machines/{machine['identifier']}",
                "PATCH",
                data=payload,
            )

            assert response_data["nickname"] == machine_data_to_update["nickname"]
            assert response_data["os_version"] == machine_data_to_update["os_version"]

            assert response_data["public_key"] == original_data.public_key
            assert response_data["os"] == original_data.os


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_data",
    [[
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "linux",
            "Ubuntu 22.04; kernel=5.15.0-78-generic",
        )
    ]],
    indirect=True,
)
# pylint: disable=unused-argument
async def test_delete_registered_machine(
    server_host, registered_machines, machine_data
):
    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )

        machine = registered_machines[0]

        await send_http_request(
            connection,
            f"{server_host}/v1/meshnet/machines/{machine['identifier']}",
            "DELETE",
            expect_response=False,
        )

        get_response_data = await send_http_request(
            connection, f"{server_host}/v1/meshnet/machines", "GET"
        )

        assert len(get_response_data) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "machine_data",
    [[
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "linux",
            "Ubuntu 22.04; kernel=5.15.0-78-generic",
        ),
        create_machine_data(
            generate_wireguard_like_public_key(),
            generate_hardware_identifier(),
            "windows",
            "Windows 11; kernel=10.0.22621.2283",
        ),
    ]],
    indirect=True,
)
# pylint: disable=unused-argument
async def test_get_mesh_map(server_host, registered_machines, machine_data):
    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )

        for machine in registered_machines:

            response_data = await send_http_request(
                connection,
                f"{server_host}/v1/meshnet/machines/{machine['identifier']}/map",
                "GET",
            )

            assert isinstance(response_data["peers"], list)
            assert len(response_data["peers"]) == 1
            for peer in response_data["peers"]:
                validate_dataclass(Peer, peer)

            assert isinstance(response_data["derp_servers"], list)
            for derp_server in response_data["derp_servers"]:
                validate_dataclass(DerpServer, derp_server)


async def not_able_to_register_same_machine_twice(server_host):
    machine_data = MachineData(
        public_key=generate_wireguard_like_public_key(),
        hardware_identifier=generate_hardware_identifier(),
        os="linux",
        os_version="Ubuntu 22.04; kernel=5.15.0-78-generic",
    )

    async with AsyncExitStack() as exit_stack:
        connection = await exit_stack.enter_async_context(
            new_connection_by_tag(ConnectionTag.DOCKER_CONE_CLIENT_1)
        )
        await clean_up_machines(connection, server_host)

        payload = json.dumps(machine_data.__dict__)

        await send_http_request(
            connection,
            f"{server_host}/v1/meshnet/machines",
            method="POST",
            data=payload,
            expect_response=False,
        )

        response_data = await send_http_request(
            connection,
            f"{server_host}/v1/meshnet/machines",
            method="POST",
            data=payload,
        )

        assert response_data["errors"]["code"] == 101117
        assert (
            response_data["errors"]["message"]
            == "Machine with this public key already exists"
        )
