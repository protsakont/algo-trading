"""Orchestrator: composition root + strategy lifecycle with promotion gates."""

from .wiring import AppGraph, build_graph

__all__ = ["AppGraph", "build_graph"]
