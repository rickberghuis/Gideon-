"""Builds the default tool registry by collecting every capability's tools.

Adding a new capability = write a tools module with build_tools() and add one line here.
"""

from __future__ import annotations

from ..memory import Memory
from . import draft_message, memory_tools, notes, reminders, websearch
from .base import Registry


def build_registry(memory: Memory | None = None) -> Registry:
    registry = Registry()
    for tool in reminders.build_tools():
        registry.register(tool)
    for tool in notes.build_tools():
        registry.register(tool)
    for tool in draft_message.build_tools():
        registry.register(tool)
    for tool in websearch.build_tools():
        registry.register(tool)
    if memory is not None:
        for tool in memory_tools.build_tools(memory):
            registry.register(tool)
    return registry
