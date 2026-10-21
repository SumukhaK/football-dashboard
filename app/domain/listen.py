"""Where a server is listening, and whether an address is this computer's own.

The fixture demonstration may serve only the loopback interface. Addresses are
judged as IP literals: a host name such as ``localhost`` resolves through
configuration this console does not control, so it is not proof of loopback.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass


def is_loopback(host: str | None) -> bool:
    """Whether ``host`` is a loopback IP literal (127.0.0.0/8 or ::1)."""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ListenAddress:
    """The address a launcher actually bound its listening socket to."""

    host: str
    port: int

    @property
    def loopback(self) -> bool:
        """Whether only this computer can reach the socket."""
        return is_loopback(self.host)
