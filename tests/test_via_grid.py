"""
tests/test_via_grid.py
Tests for ViaGrid, ViaGridGenerator, EndTurnSpec, and EndTurnRouter.
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import MotorConfig
from pcbstatorgen.geometry.end_turn import (
    END_TURN_VIA_REGION_M,
    EndTurnRouter,
    EndTurnSide,
    EndTurnSpec,
)
from pcbstatorgen.geometry.via_grid import (
    ViaGrid,
    ViaGridGenerator,
    _CURRENT_PER_VIA_A,
    _CURRENT_SAFETY_MARGIN,
)
from pcbstatorgen.geometry.wave_winding import CoilSegment, WaveWindingGenerator
from pcbstatorgen.units import mm, mils_to_m, oz_to_m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_via_grid(rows=2, cols=3, pitch=0.6e-3, drill=0.2e-3, ring=0.1e-3):
    return ViaGrid(
        center=(0.0, 0.0),
        rows=rows,
        cols=cols,
        pitch_x=pitch,
        pitch_y=pitch,
        drill_m=drill,
        annular_ring_m=ring,
    )


# ===========================================================================
# ViaGrid
# ===========================================================================


class TestViaGrid:
    def test_count(self):
        g = _make_via_grid(rows=3, cols=4)
        assert g.count == 12

    def test_pad_diameter(self):
        g = ViaGrid(
            center=(0.0, 0.0), rows=1, cols=1,
            pitch_x=0.0, pitch_y=0.0,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        assert g.pad_diameter_m == pytest.approx(mm(0.4))

    def test_footprint_x_single_col(self):
        g = ViaGrid(
            center=(0.0, 0.0), rows=2, cols=1,
            pitch_x=0.0, pitch_y=0.6e-3,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        assert g.footprint_x_m == pytest.approx(mm(0.4))  # just one pad width

    def test_footprint_x_multi_col(self):
        g = _make_via_grid(rows=1, cols=3, pitch=0.6e-3, drill=0.2e-3, ring=0.1e-3)
        # (3-1)*0.6 + 0.4 = 1.2 + 0.4 = 1.6 mm
        assert g.footprint_x_m == pytest.approx(1.6e-3)

    def test_footprint_y_multi_row(self):
        g = _make_via_grid(rows=3, cols=1, pitch=0.6e-3, drill=0.2e-3, ring=0.1e-3)
        # (3-1)*0.6 + 0.4 = 1.6 mm
        assert g.footprint_y_m == pytest.approx(1.6e-3)

    # ------------------------------------------------------------------
    # positions()
    # ------------------------------------------------------------------

    def test_single_via_at_center(self):
        g = ViaGrid(
            center=(0.005, 0.003), rows=1, cols=1,
            pitch_x=0.0, pitch_y=0.0,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        assert g.positions() == pytest.approx([(0.005, 0.003)])

    def test_positions_count(self):
        g = _make_via_grid(rows=3, cols=4)
        assert len(g.positions()) == 12

    def test_positions_centred_on_center_2x2(self):
        pitch = 1e-3
        g = ViaGrid(
            center=(0.0, 0.0), rows=2, cols=2,
            pitch_x=pitch, pitch_y=pitch,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        pos = g.positions()
        xs = sorted({p[0] for p in pos})
        ys = sorted({p[1] for p in pos})
        assert xs == pytest.approx([-pitch / 2, pitch / 2])
        assert ys == pytest.approx([-pitch / 2, pitch / 2])

    def test_positions_centred_on_nonzero_center(self):
        cx, cy = 5e-3, 3e-3
        pitch = 1e-3
        g = ViaGrid(
            center=(cx, cy), rows=1, cols=3,
            pitch_x=pitch, pitch_y=0.0,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        pos = g.positions()
        xs = [p[0] for p in pos]
        assert xs == pytest.approx([cx - pitch, cx, cx + pitch])

    def test_positions_row_major_order(self):
        """Positions must be ordered row-by-row (bottom row first)."""
        pitch = 1e-3
        g = ViaGrid(
            center=(0.0, 0.0), rows=2, cols=2,
            pitch_x=pitch, pitch_y=pitch,
            drill_m=mm(0.2), annular_ring_m=mm(0.1),
        )
        pos = g.positions()
        # First two positions should be in row 0 (lower y)
        assert pos[0][1] < pos[2][1]  # row 0 < row 1 in Y

    # ------------------------------------------------------------------
    # Current capacity
    # ------------------------------------------------------------------

    def test_current_capacity(self):
        g = _make_via_grid(rows=2, cols=3)
        assert g.current_capacity_a() == pytest.approx(6 * _CURRENT_PER_VIA_A)

    def test_is_sufficient_for_pass(self):
        g = _make_via_grid(rows=4, cols=4)  # 16 vias × 0.5A = 8A capacity
        assert g.is_sufficient_for(current_a=1.0, margin=2.0)  # needs 2A capacity

    def test_is_sufficient_for_fail(self):
        g = _make_via_grid(rows=1, cols=1)  # 1 via × 0.5A = 0.5A < 2A needed
        assert not g.is_sufficient_for(current_a=2.0, margin=2.0)

    def test_is_sufficient_for_exact_boundary(self):
        # 4 vias × 0.5A = 2A capacity; needed = 1A × 2 margin = 2A → just passes
        g = _make_via_grid(rows=2, cols=2)
        assert g.is_sufficient_for(current_a=1.0, margin=2.0)


# ===========================================================================
# ViaGridGenerator
# ===========================================================================


class TestViaGridGenerator:
    def test_invalid_current_per_via_raises(self):
        with pytest.raises(ValueError, match="current_per_via_a must be positive"):
            ViaGridGenerator(current_per_via_a=0.0)

    def test_invalid_safety_margin_raises(self):
        with pytest.raises(ValueError, match="current_safety_margin must be ≥ 1"):
            ViaGridGenerator(current_safety_margin=0.5)

    def test_generate_returns_via_grid(self, default_config):
        gen = ViaGridGenerator()
        grid = gen.generate_for_end_turn(
            center=(mm(6), mm(20)),
            available_x_m=mm(12),
            available_y_m=mm(2),
            current_a=1.0,
            config=default_config,
        )
        assert isinstance(grid, ViaGrid)

    def test_generated_grid_has_positive_count(self, default_config):
        gen = ViaGridGenerator()
        grid = gen.generate_for_end_turn(
            center=(mm(6), mm(20)),
            available_x_m=mm(12),
            available_y_m=mm(2),
            current_a=1.0,
            config=default_config,
        )
        assert grid.count >= 1

    def test_generated_grid_fits_in_available_x(self, default_config):
        gen = ViaGridGenerator()
        avail_x = mm(12)
        grid = gen.generate_for_end_turn(
            center=(0.0, 0.0),
            available_x_m=avail_x,
            available_y_m=mm(2),
            current_a=1.0,
            config=default_config,
        )
        assert grid.footprint_x_m <= avail_x + 1e-9

    def test_generated_grid_fits_in_available_y(self, default_config):
        gen = ViaGridGenerator()
        avail_y = mm(2)
        grid = gen.generate_for_end_turn(
            center=(0.0, 0.0),
            available_x_m=mm(12),
            available_y_m=avail_y,
            current_a=1.0,
            config=default_config,
        )
        assert grid.footprint_y_m <= avail_y + 1e-9

    def test_generated_drill_matches_config(self, default_config):
        gen = ViaGridGenerator()
        grid = gen.generate_for_end_turn(
            center=(0.0, 0.0),
            available_x_m=mm(12),
            available_y_m=mm(2),
            current_a=1.0,
            config=default_config,
        )
        assert grid.drill_m == default_config.min_via_drill_m
        assert grid.annular_ring_m == default_config.min_via_annular_ring_m

    def test_too_small_available_x_raises(self, default_config):
        gen = ViaGridGenerator()
        with pytest.raises(ValueError, match="available_x_m"):
            gen.generate_for_end_turn(
                center=(0.0, 0.0),
                available_x_m=mm(0.01),  # smaller than via pad
                available_y_m=mm(2),
                current_a=1.0,
                config=default_config,
            )

    def test_too_small_available_y_raises(self, default_config):
        gen = ViaGridGenerator()
        with pytest.raises(ValueError, match="available_y_m"):
            gen.generate_for_end_turn(
                center=(0.0, 0.0),
                available_x_m=mm(12),
                available_y_m=mm(0.01),  # smaller than via pad
                current_a=1.0,
                config=default_config,
            )

    def test_larger_space_gives_more_vias(self, default_config):
        gen = ViaGridGenerator()
        g_small = gen.generate_for_end_turn(
            center=(0.0, 0.0), available_x_m=mm(3),
            available_y_m=mm(1), current_a=1.0, config=default_config,
        )
        g_large = gen.generate_for_end_turn(
            center=(0.0, 0.0), available_x_m=mm(12),
            available_y_m=mm(3), current_a=1.0, config=default_config,
        )
        assert g_large.count > g_small.count

    def test_generated_grid_sufficient_for_1A(self, default_config):
        """Default config 1A current should be met with the standard end-turn space."""
        gen = ViaGridGenerator()
        grid = gen.generate_for_end_turn(
            center=(0.0, 0.0),
            available_x_m=default_config.pole_pitch_m,  # 12 mm
            available_y_m=mm(2),
            current_a=default_config.max_current_a,
            config=default_config,
        )
        assert grid.is_sufficient_for(default_config.max_current_a)

    def test_min_via_count_for_current(self):
        gen = ViaGridGenerator(current_per_via_a=0.5, current_safety_margin=2.0)
        # 1A × 2 / 0.5A = 4 vias minimum
        assert gen.min_via_count_for_current(1.0) == 4
        # 2A × 2 / 0.5A = 8 vias
        assert gen.min_via_count_for_current(2.0) == 8

    def test_generate_for_coil_returns_list(self, default_config):
        gen = ViaGridGenerator()
        midpoints = [(mm(6), mm(20)), (mm(18), mm(20)), (mm(30), mm(20))]
        grids = gen.generate_for_coil(
            coil_end_turn_midpoints=midpoints,
            available_x_m=mm(12),
            available_y_m=mm(2),
            current_a=1.0,
            config=default_config,
        )
        assert len(grids) == 3
        for g in grids:
            assert isinstance(g, ViaGrid)


# ===========================================================================
# EndTurnRouter
# ===========================================================================


class TestEndTurnRouter:
    def test_invalid_via_region_raises(self):
        with pytest.raises(ValueError, match="via_region_width_m must be positive"):
            EndTurnRouter(via_region_width_m=0.0)

    def test_compute_specs_returns_correct_count(self, default_config):
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config)
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config)
        # Should be one spec per end-turn segment across all coils
        total_end_turns = sum(len(c.end_turn_segments) for c in coils)
        assert len(specs) == total_end_turns

    def test_specs_have_via_grids(self, default_config):
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config)
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config)
        for spec in specs:
            assert spec.via_grid is not None

    def test_specs_without_via_grids(self, default_config):
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config)
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config, attach_via_grids=False)
        for spec in specs:
            assert spec.via_grid is None

    def test_side_classification_top(self, default_config):
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config)
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config, attach_via_grids=False)
        W = default_config.board_width_m
        for spec in specs:
            if abs(spec.y_position - W) < 1e-9:
                assert spec.side == EndTurnSide.TOP
            elif abs(spec.y_position) < 1e-9:
                assert spec.side == EndTurnSide.BOTTOM

    def test_layer_conflicts_single_layer_multiphase(self, default_config):
        """All phases on the same layer → end-turn overlaps must be detected."""
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config, layer_idx=0)  # all on layer 0
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config, attach_via_grids=False)
        conflicts = router.check_layer_conflicts(specs)
        # With 3 phases all on layer 0, adjacent phases overlap → expect conflicts
        assert len(conflicts) > 0

    def test_layer_conflicts_separate_layers_no_conflict(self, default_config):
        """Each phase on its own layer → no end-turn conflicts."""
        gen = WaveWindingGenerator()
        # Manually assign each phase to a separate layer
        coils = [
            gen.generate(default_config, layer_idx=p)[p]
            for p in range(default_config.phases)
        ]
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config, attach_via_grids=False)
        conflicts = router.check_layer_conflicts(specs)
        assert len(conflicts) == 0

    def test_effective_via_region_narrow_board(self, default_config):
        """For a narrow board, via region must be clamped to board_width/4."""
        narrow = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
            magnet_count=10,
            magnet_pitch_m=mm(12),
            board_width_m=mm(6),  # narrow: 6 mm → 6/4 = 1.5 mm
        )
        router = EndTurnRouter(via_region_width_m=mm(2))  # 2mm requested
        # pylint: disable=protected-access
        effective = router._effective_via_region_width(narrow)
        assert effective == pytest.approx(mm(6) / 4.0)

    def test_effective_via_region_wide_board(self, default_config):
        """For a wide board, via region stays at the requested value."""
        router = EndTurnRouter(via_region_width_m=mm(2))
        effective = router._effective_via_region_width(default_config)  # 20 mm wide
        assert effective == pytest.approx(mm(2))

    def test_phase_idx_in_specs(self, default_config):
        gen = WaveWindingGenerator()
        coils = gen.generate(default_config)
        router = EndTurnRouter()
        specs = router.compute_end_turn_specs(coils, default_config, attach_via_grids=False)
        for spec, coil in [
            (s, next(c for c in coils if c.phase_idx == s.phase_idx))
            for s in specs
        ]:
            assert spec.phase_idx == coil.phase_idx
