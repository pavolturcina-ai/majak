"""Connector interface + registry.

A connector pulls new inputs since a cursor and returns them as RawInput plus a
new cursor. The pipeline is the same for every connector, so a connector's only
job is to fetch + shape payloads. Idempotency is guaranteed downstream by
sources.unique(connector, external_id); the cursor just bounds the fetch window.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from majak.models.schemas import RawInput

__all__ = ["Connector", "RawInput", "registry", "register"]


@runtime_checkable
class Connector(Protocol):
    name: str

    @property
    def configured(self) -> bool:
        """True when the required tokens/env are present."""
        ...

    async def fetch_since(self, cursor: str | None) -> tuple[list[RawInput], str | None]:
        """Return (new inputs, new cursor). Empty list when nothing new."""
        ...


registry: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    registry[connector.name] = connector
    return connector


def load_default_connectors() -> dict[str, Connector]:
    """Instantiate and register the v1 connectors (idempotent)."""
    if registry:
        return registry
    # Imported here to avoid import cycles at module load.
    from majak.connectors.fathom import FathomConnector
    from majak.connectors.gcal import GoogleCalendarConnector
    from majak.connectors.gmail import GmailConnector
    from majak.connectors.slack import SlackConnector

    for conn in (GmailConnector(), SlackConnector(), FathomConnector(), GoogleCalendarConnector()):
        register(conn)
    return registry
