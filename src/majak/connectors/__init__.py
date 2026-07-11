"""Connectors: pull raw inputs from external systems with delta-sync cursors."""

from majak.connectors.base import Connector, RawInput, registry

__all__ = ["Connector", "RawInput", "registry"]
