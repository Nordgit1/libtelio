from utils.connection import Connection, TargetOS
from typing import Optional
import re

# For Linux, use the standard `stunclient` available on most distributions.
#
# For Windows, stun binaries are available from
# http://www.stunprotocol.org/
#
# For Mac, stun binaries are available from
# https://master.dl.sourceforge.net/project/stuntman/stunserver_osx_1_2_13.zip?viasf=1

STUN_BINARY_PATH_WINDOWS: Optional[str] = None
STUN_BINARY_PATH_MAC: Optional[str] = None


async def get(connection: Connection, stun_server: str) -> str:
    if connection.target_os == TargetOS.Linux:
        process = await connection.create_process(
            ["stun", stun_server, "1", "-v"]
        ).execute()

        # Match: 'XorMappedAddress = 10.0.254.1:24295'
        match = re.search(
            r"XorMappedAddress = (\d+\.\d+\.\d+\.\d+):(\d+)", process.get_stderr()
        )
        assert match, "stun response missing XorMappedAddress"

        return match.group(1)

    elif connection.target_os == TargetOS.Windows:
        assert STUN_BINARY_PATH_WINDOWS, "stun binary path not configured"
        process = await connection.create_process(
            [STUN_BINARY_PATH_WINDOWS, stun_server]
        ).execute()

        # Match: 'Mapped address: 10.0.0.1:53628'
        match = re.search(r"Mapped address: (\d+.\d+.\d+.\d+)", process.get_stdout())
        assert match

        return match.group(1)

    elif connection.target_os == TargetOS.Mac:
        assert STUN_BINARY_PATH_MAC, "stun binary path not configured"
        process = await connection.create_process(
            [STUN_BINARY_PATH_MAC, stun_server]
        ).execute()

        # Match: 'Mapped address: 10.0.0.1:53628'
        match = re.search(r"Mapped address: (\d+.\d+.\d+.\d+)", process.get_stdout())
        assert match

        return match.group(1)

    assert False, "unsupported os"
