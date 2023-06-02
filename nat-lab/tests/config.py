import os
import platform
from utils import stun

PROJECT_ROOT = os.path.dirname(os.path.realpath(__file__)) + "/../../../"

# Get file path relative to project root
def get_root_path(path: str) -> str:
    return os.path.normpath(PROJECT_ROOT + path)


# Same as defined in `Vagrantfile`
LINUX_VM_IP = "10.55.0.10"
WINDOWS_VM_IP = "10.55.0.11"
MAC_VM_IP = "10.55.0.12"

LINUX_VM_PRIMARY_GATEWAY = "10.55.0.10"
LINUX_VM_SECONDARY_GATEWAY = "10.66.0.10"

# Same as defined in `libtelio/nat-lab/docker-compose.yml`, 10.0.0.0/16
DOCKER_NETWORK_IP = "10.0.0.0"
DOCKER_NETWORK_MASK = "255.255.0.0"
STUN_SERVER = "10.0.1.1"

# Same as defined in `libtelio/nat-lab/provision_windows.ps1`
stun.STUN_BINARY_PATH_WINDOWS = "C:/workspace/stunserver/release/stunclient.exe"
stun.STUN_BINARY_PATH_MAC = "/Users/vagrant/stunserver/stunclient"

IPERF_BINARY_MAC = "/Users/vagrant/iperf3/iperf3"
IPERF_BINARY_WINDOWS = "C:\\workspace\\iperf3\\iperf3.exe"

# JIRA issue: LLT-1664
# The directories between host and Docker container are shared via
# Docker volumes. Mounting `libtelio-build/dist` is a nogo, since when host
# filesystem directory dist/linux/release/x86_64 is deleted during
# ./run_local.py, the volume “loses” it’s link with host file system.
#
# JIRA issue: LLT-1702
# Seems like the best solution is to mount `libtelio-build` root directory,
# since its stable unlike `libtelio-build/dist`.
#
# Libtelio binary path inside Docker containers.
LIBTELIO_BINARY_PATH_DOCKER = (
    "/libtelio-build/dist/linux/release/" + platform.uname().machine + "/"
)

# Libtelio binary path inside Windows and Mac VMs
LIBTELIO_BINARY_PATH_VM = "/workspace/binaries/"

LIBTELIO_DNS_IP = "100.64.0.2"
LIBTELIO_EXIT_DNS_IP = "100.64.0.3"

VPN_SERVER_SUBNET = "10.0.100.0/24"

DOCKER_CONE_CLIENT_1_LAN_ADDR = "192.168.101.104"
DOCKER_CONE_CLIENT_2_LAN_ADDR = "192.168.102.54"

# vpn-01
WG_SERVER = {
    "ipv4": "10.0.100.1",
    "port": 51820,
    "public_key": "N2Kuejq5Gd553kGYKY4iwtnCuk9MJjAPpg7C04FOdDw=",
}

# vpn-02
WG_SERVER_2 = {
    "ipv4": "10.0.100.2",
    "port": 51820,
    "public_key": "N2Kuejq5Gd553kGYKY4iwtnCuk9MJjAPpg7C04FOdDw=",
}

# TODO - bring here class DerpServer  from telio.py
# and replace dictionaries with objects

# DERP servers
DERP_PRIMARY = {
    "region_code": "nl",
    "name": "Natlab #0001",
    "hostname": "derp-01",
    "ipv4": "10.0.10.1",
    "relay_port": 8765,
    "stun_port": 3479,
    "stun_plaintext_port": 3478,
    "public_key": "qK/ICYOGBu45EIGnopVu+aeHDugBrkLAZDroKGTuKU0=",
    "weight": 1,
    "use_plain_text": True,
}

DERP_FAKE = {
    "region_code": "fk",
    "name": "Natlab #0002-fake",
    "hostname": "derp-00",
    "ipv4": "10.0.10.245",
    "relay_port": 8765,
    "stun_port": 3479,
    "stun_plaintext_port": 3478,
    "public_key": "aAY0rU8pW8LV3BJlY5u5WYH7nbAwS5H0mBMJppVDRGs=",
    "weight": 2,
    "use_plain_text": True,
}
# we kept it because the test on  mesh_api

DERP_SECONDARY = {
    "region_code": "de",
    "name": "Natlab #0002",
    "hostname": "derp-02",
    "ipv4": "10.0.10.2",
    "relay_port": 8765,
    "stun_port": 3479,
    "stun_plaintext_port": 3478,
    "public_key": "KmcnUJ7EfhCIF9o1S5ycShaNc3y1DmioKUlkMvEVoRI=",
    "weight": 3,
    "use_plain_text": True,
}

DERP_TERTIARY = {
    "region_code": "us",
    "name": "Natlab #0003",
    "hostname": "derp-03",
    "ipv4": "10.0.10.3",
    "relay_port": 8765,
    "stun_port": 3479,
    "stun_plaintext_port": 3478,
    "public_key": "A4ggUMw5DmMSjz1uSz3IkjM3A/CRgJxEHoGigwT0W3k=",
    "weight": 4,
    "use_plain_text": True,
}


# separating in objects
DERP_SERVERS = [DERP_PRIMARY, DERP_FAKE, DERP_SECONDARY, DERP_TERTIARY]

# node ips to use in tests
ALPHA_NODE_ADDRESS = "100.64.1.3"
BETA_NODE_ADDRESS = "100.64.1.4"
GAMMA_NODE_ADDRESS = "100.64.1.5"

# port used by libdrop file sharing
LIBDROP_PORT = 49111
