"""Proven, tuned engine libraries — do not rewrite.

These modules are the byte-for-byte MAME-parity readers, the evolved FSM, and
the clearance planner that took the memory bot to wave 138. The orchestration
layer (perception / control / harness / brain) wraps them; it never reimplements
their logic. Imports between these modules are relative, so the package is fully
self-contained.
"""
