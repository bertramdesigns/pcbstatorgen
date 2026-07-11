"""
tests/conftest.py — shared pytest fixtures
==========================================
Fixtures available to all tests without explicit import.
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import MotorConfig, StackupResult
from pcbstatorgen.units import mm, mils_to_m, oz_to_m


# ---------------------------------------------------------------------------
# MotorConfig fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> MotorConfig:
    """Minimal valid MotorConfig with realistic flying-fader parameters."""
    return MotorConfig(
        name="test-config",
        travel_m=mm(75),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=10,
        magnet_pitch_m=mm(12),
        magnet_remanence_t=1.35,
        phases=3,
        target_force_n=0.5,
        max_current_a=1.0,
        min_trace_m=mils_to_m(5),
        min_space_m=mils_to_m(5),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
        max_layers=12,
        drive_frequency_hz=500.0,
    )


@pytest.fixture
def minimal_config() -> MotorConfig:
    """Smallest valid MotorConfig — 2 magnets, coarser design rules."""
    return MotorConfig(
        travel_m=mm(60),
        magnet_dims_m=(mm(8), mm(8), mm(3)),
        magnet_count=2,
        magnet_pitch_m=mm(9),
        phases=1,
        target_force_n=0.1,
        max_current_a=0.5,
        min_trace_m=mm(0.2),
        min_space_m=mm(0.2),
        min_via_drill_m=mm(0.3),
        min_via_annular_ring_m=mm(0.15),
        board_width_m=mm(15),
        air_gap_m=mm(1.0),
        max_layers=4,
    )


# ---------------------------------------------------------------------------
# StackupResult fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def four_layer_stackup() -> StackupResult:
    """Minimal valid 4-layer StackupResult."""
    return StackupResult(
        layer_count=4,
        trace_widths_m=(mm(0.15), mm(0.25), mm(0.25), mm(0.15)),
        cu_thickness_m=(oz_to_m(1.0), oz_to_m(2.0), oz_to_m(2.0), oz_to_m(1.0)),
        via_drill_m=mm(0.2),
        via_annular_ring_m=mm(0.1),
        via_grid_rows=2,
        via_grid_cols=3,
        estimated_force_n=0.42,
        estimated_dc_resistance_ohm=3.1,
        notes=["4-layer stackup chosen by test fixture"],
    )


@pytest.fixture
def eight_layer_stackup() -> StackupResult:
    """8-layer StackupResult with pyramid trace widths."""
    return StackupResult(
        layer_count=8,
        trace_widths_m=(
            mm(0.13), mm(0.18), mm(0.22), mm(0.25),
            mm(0.25), mm(0.22), mm(0.18), mm(0.13),
        ),
        cu_thickness_m=(
            oz_to_m(1.0), oz_to_m(2.0), oz_to_m(2.0), oz_to_m(2.0),
            oz_to_m(2.0), oz_to_m(2.0), oz_to_m(2.0), oz_to_m(1.0),
        ),
        via_drill_m=mm(0.2),
        via_annular_ring_m=mm(0.1),
        via_grid_rows=3,
        via_grid_cols=4,
        estimated_force_n=0.81,
        estimated_dc_resistance_ohm=1.8,
        notes=["8-layer stackup chosen by test fixture"],
    )
