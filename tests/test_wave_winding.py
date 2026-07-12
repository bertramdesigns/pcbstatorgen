"""
tests/test_wave_winding.py
Tests for WaveWindingGenerator, PhaseCoil, and CoilSegment.
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import MotorConfig
from pcbstatorgen.geometry.wave_winding import (
    CoilSegment,
    PhaseCoil,
    WaveWindingGenerator,
    PHASE_NAMES,
)
from pcbstatorgen.units import mm, mils_to_m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gen() -> WaveWindingGenerator:
    return WaveWindingGenerator()


@pytest.fixture
def tiny_config() -> MotorConfig:
    """2-magnet, 1-phase, minimal config for easy hand-calculation."""
    return MotorConfig(
        active_area_length_m=mm(48),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=2,
        magnet_pitch_m=mm(12),
        phases=1,
        target_force_n=0.1,
        max_current_a=1.0,
        min_trace_m=mils_to_m(5),
        min_space_m=mils_to_m(5),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
        max_layers=4,
    )


@pytest.fixture
def three_phase_config(default_config) -> MotorConfig:
    """Default 3-phase config (75 mm travel, 12 mm pole pitch, 20 mm width)."""
    return default_config


# ===========================================================================
# CoilSegment
# ===========================================================================


class TestCoilSegment:
    def test_length_vertical(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.0, 0.02), is_active=True)
        assert seg.length_m == pytest.approx(0.02)

    def test_length_horizontal(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.012, 0.0), is_active=False)
        assert seg.length_m == pytest.approx(0.012)

    def test_length_diagonal(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.003, 0.004), is_active=True)
        assert seg.length_m == pytest.approx(0.005)

    def test_midpoint_vertical(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.0, 0.02), is_active=True)
        assert seg.midpoint == pytest.approx((0.0, 0.01))

    def test_midpoint_horizontal(self):
        seg = CoilSegment(start=(0.0, 0.02), end=(0.012, 0.02), is_active=False)
        assert seg.midpoint == pytest.approx((0.006, 0.02))

    def test_is_vertical_true(self):
        seg = CoilSegment(start=(0.005, 0.0), end=(0.005, 0.02), is_active=True)
        assert seg.is_vertical()

    def test_is_vertical_false(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.012, 0.0), is_active=False)
        assert not seg.is_vertical()

    def test_is_horizontal_true(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.012, 0.0), is_active=False)
        assert seg.is_horizontal()

    def test_is_horizontal_false(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.0, 0.02), is_active=True)
        assert not seg.is_horizontal()

    def test_frozen(self):
        seg = CoilSegment(start=(0.0, 0.0), end=(0.0, 0.02), is_active=True)
        with pytest.raises((AttributeError, TypeError)):
            seg.is_active = False  # type: ignore


# ===========================================================================
# WaveWindingGenerator — conductor positions
# ===========================================================================


class TestConductorPositions:
    def test_phase_a_starts_at_zero(self, three_phase_config, gen):
        positions = gen.conductor_x_positions(three_phase_config, phase_idx=0)
        assert positions[0] == pytest.approx(0.0)

    def test_phase_b_starts_at_slot_pitch(self, three_phase_config, gen):
        positions = gen.conductor_x_positions(three_phase_config, phase_idx=1)
        assert positions[0] == pytest.approx(three_phase_config.slot_pitch_m)

    def test_phase_c_starts_at_two_slot_pitches(self, three_phase_config, gen):
        positions = gen.conductor_x_positions(three_phase_config, phase_idx=2)
        assert positions[0] == pytest.approx(2 * three_phase_config.slot_pitch_m)

    def test_conductor_spacing_equals_pole_pitch(self, three_phase_config, gen):
        positions = gen.conductor_x_positions(three_phase_config, phase_idx=0)
        diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        for d in diffs:
            assert d == pytest.approx(three_phase_config.pole_pitch_m)

    def test_all_phases_equal_conductor_count(self, three_phase_config, gen):
        counts = [
            len(gen.conductor_x_positions(three_phase_config, p))
            for p in range(three_phase_config.phases)
        ]
        assert len(set(counts)) == 1, f"Unequal conductor counts: {counts}"

    def test_single_phase_one_conductor_minimum(self, tiny_config, gen):
        """Even a very short coil gets at least one conductor."""
        positions = gen.conductor_x_positions(tiny_config, 0)
        assert len(positions) >= 1

    def test_last_conductor_within_extended_active_length(self, three_phase_config, gen):
        """Last conductor must not exceed active_length + (phases-1)*slot_pitch."""
        x_max = (
            three_phase_config.active_length_m
            + (three_phase_config.phases - 1) * three_phase_config.slot_pitch_m
        )
        for p in range(three_phase_config.phases):
            positions = gen.conductor_x_positions(three_phase_config, p)
            assert positions[-1] <= x_max + 1e-9


# ===========================================================================
# WaveWindingGenerator — generate() single layer
# ===========================================================================


class TestGenerateSingleLayer:
    def test_returns_one_coil_per_phase(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        assert len(coils) == three_phase_config.phases

    def test_phase_indices_correct(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        for p, coil in enumerate(coils):
            assert coil.phase_idx == p

    def test_phase_names_correct(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        assert coils[0].phase_name == "A"
        assert coils[1].phase_name == "B"
        assert coils[2].phase_name == "C"

    def test_layer_idx_assigned(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config, layer_idx=3)
        for coil in coils:
            assert coil.layer_idx == 3

    def test_default_layer_idx_zero(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        for coil in coils:
            assert coil.layer_idx == 0

    def test_all_phases_same_conductor_count(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        counts = [c.active_conductor_count for c in coils]
        assert len(set(counts)) == 1, f"Unequal active conductor counts: {counts}"

    def test_coil_is_continuous(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            assert coil.is_continuous(), f"Phase {coil.phase_name} coil is not continuous"

    def test_active_segments_are_vertical(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            for seg in coil.active_segments:
                assert seg.is_vertical(), (
                    f"Active segment in phase {coil.phase_name} is not vertical: {seg}"
                )

    def test_end_turns_are_horizontal(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            for seg in coil.end_turn_segments:
                assert seg.is_horizontal(), (
                    f"End-turn in phase {coil.phase_name} is not horizontal: {seg}"
                )

    def test_end_turn_count_is_active_count_minus_one(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            assert coil.active_conductor_count - 1 == len(coil.end_turn_segments), (
                f"Phase {coil.phase_name}: expected {coil.active_conductor_count - 1} "
                f"end-turns, got {len(coil.end_turn_segments)}"
            )

    def test_active_conductors_span_board_width(self, three_phase_config, gen):
        W = three_phase_config.board_width_m
        for coil in gen.generate(three_phase_config):
            for seg in coil.active_segments:
                ys = sorted([seg.start[1], seg.end[1]])
                assert ys[0] == pytest.approx(0.0)
                assert ys[1] == pytest.approx(W)

    def test_end_turns_at_board_edges(self, three_phase_config, gen):
        W = three_phase_config.board_width_m
        for coil in gen.generate(three_phase_config):
            for seg in coil.end_turn_segments:
                y = seg.start[1]
                assert y == pytest.approx(0.0) or y == pytest.approx(W), (
                    f"End-turn at unexpected Y={y * 1e3:.3f} mm in phase {coil.phase_name}"
                )

    def test_active_conductors_advance_in_x(self, three_phase_config, gen):
        """Consecutive active conductors must be separated by exactly pole_pitch."""
        tau = three_phase_config.pole_pitch_m
        for coil in gen.generate(three_phase_config):
            xs = coil.active_conductor_x_positions()
            for i in range(len(xs) - 1):
                assert xs[i + 1] - xs[i] == pytest.approx(tau), (
                    f"Phase {coil.phase_name} conductor spacing is "
                    f"{(xs[i+1]-xs[i])*1e3:.3f} mm, expected {tau*1e3:.3f} mm"
                )

    def test_alternating_direction(self, three_phase_config, gen):
        """Active conductors must alternate direction: first goes up, second goes down, …"""
        for coil in gen.generate(three_phase_config):
            for k, seg in enumerate(coil.active_segments):
                if k % 2 == 0:  # even → going up (y: 0 → W)
                    assert seg.start[1] == pytest.approx(0.0)
                    assert seg.end[1] == pytest.approx(three_phase_config.board_width_m)
                else:  # odd → going down (y: W → 0)
                    assert seg.start[1] == pytest.approx(three_phase_config.board_width_m)
                    assert seg.end[1] == pytest.approx(0.0)

    def test_phase_offsets_slot_pitch(self, three_phase_config, gen):
        """Phase B must start slot_pitch later than A; phase C two slot pitches later."""
        sp = three_phase_config.slot_pitch_m
        coils = gen.generate(three_phase_config)
        assert coils[0].terminal_start[0] == pytest.approx(0.0)
        assert coils[1].terminal_start[0] == pytest.approx(sp)
        assert coils[2].terminal_start[0] == pytest.approx(2 * sp)

    def test_segments_alternate_active_endturn(self, three_phase_config, gen):
        """Segments must strictly alternate: active, end-turn, active, end-turn, ..., active."""
        for coil in gen.generate(three_phase_config):
            for i, seg in enumerate(coil.segments):
                if i % 2 == 0:
                    assert seg.is_active, f"Segment {i} of phase {coil.phase_name} should be active"
                else:
                    assert not seg.is_active, f"Segment {i} of phase {coil.phase_name} should be end-turn"

    def test_large_pole_pitch_few_conductors(self, gen):
        """A very large pole pitch relative to travel produces a small conductor count.

        With magnet_count=2 and pole_pitch=PP:
          active_length = travel + 2*PP
        Conductors land at x = 0, PP, 2*PP (count = 3).
        This verifies the generator handles sparse windings correctly.
        """
        cfg = MotorConfig(
            active_area_length_m=mm(101),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
            magnet_count=2,
            magnet_pitch_m=mm(50),  # large → active_length = 101 mm
            phases=1,
            target_force_n=0.1,
            max_current_a=1.0,
            min_trace_m=mils_to_m(5),
            min_space_m=mils_to_m(5),
            min_via_drill_m=mm(0.2),
            min_via_annular_ring_m=mm(0.1),
            board_width_m=mm(20),
            air_gap_m=mm(0.5),
            max_layers=4,
        )
        coil = gen.generate(cfg)[0]
        # active_length = 101 mm, pole_pitch = 50 mm → conductors at 0, 50, 100 mm
        assert coil.active_conductor_count == 3
        assert len(coil.end_turn_segments) == 2
        assert coil.is_continuous()


# ===========================================================================
# PhaseCoil properties
# ===========================================================================


class TestPhaseCoilProperties:
    def test_polyline_length_equals_segments_plus_one(self, three_phase_config, gen):
        coil = gen.generate(three_phase_config)[0]
        assert len(coil.polyline) == len(coil.segments) + 1

    def test_polyline_starts_at_terminal_start(self, three_phase_config, gen):
        coil = gen.generate(three_phase_config)[0]
        assert coil.polyline[0] == coil.terminal_start

    def test_polyline_ends_at_terminal_end(self, three_phase_config, gen):
        coil = gen.generate(three_phase_config)[0]
        assert coil.polyline[-1] == coil.terminal_end

    def test_bounding_box_x_min_is_phase_offset(self, three_phase_config, gen):
        coils = gen.generate(three_phase_config)
        sp = three_phase_config.slot_pitch_m
        for p, coil in enumerate(coils):
            bb = coil.bounding_box
            assert bb[0] == pytest.approx(p * sp)  # min_x

    def test_bounding_box_y_range_is_board_width(self, three_phase_config, gen):
        W = three_phase_config.board_width_m
        for coil in gen.generate(three_phase_config):
            bb = coil.bounding_box
            assert bb[1] == pytest.approx(0.0)   # min_y
            assert bb[3] == pytest.approx(W)      # max_y

    def test_total_length_greater_than_active_length(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            # Active segments alone span the full board width × N conductors
            # Total length must include end-turns as well
            assert coil.total_length_m > coil.active_length_m

    def test_end_turn_midpoints_top_on_top_edge(self, three_phase_config, gen):
        W = three_phase_config.board_width_m
        for coil in gen.generate(three_phase_config):
            for pt in coil.end_turn_midpoints_top:
                assert pt[1] == pytest.approx(W)

    def test_end_turn_midpoints_bottom_on_bottom_edge(self, three_phase_config, gen):
        for coil in gen.generate(three_phase_config):
            for pt in coil.end_turn_midpoints_bottom:
                assert pt[1] == pytest.approx(0.0)

    def test_top_bottom_midpoint_counts_differ_by_at_most_one(self, three_phase_config, gen):
        """Top and bottom end-turns should be approximately balanced."""
        for coil in gen.generate(three_phase_config):
            top = len(coil.end_turn_midpoints_top)
            bot = len(coil.end_turn_midpoints_bottom)
            assert abs(top - bot) <= 1

    def test_empty_coil_polyline(self, gen):
        coil = PhaseCoil(phase_idx=0, layer_idx=0, segments=[], phase_name="A")
        assert coil.polyline == []
        assert coil.terminal_start == (0.0, 0.0)
        assert coil.terminal_end == (0.0, 0.0)

    def test_empty_coil_bounding_box(self, gen):
        coil = PhaseCoil(phase_idx=0, layer_idx=0, segments=[], phase_name="A")
        assert coil.bounding_box == (0.0, 0.0, 0.0, 0.0)

    def test_total_length_sanity(self, three_phase_config, gen):
        """Active length should be n_conductors × board_width."""
        W = three_phase_config.board_width_m
        for coil in gen.generate(three_phase_config):
            expected_active = coil.active_conductor_count * W
            assert coil.active_length_m == pytest.approx(expected_active)


# ===========================================================================
# generate_all_layers
# ===========================================================================


class TestGenerateAllLayers:
    def test_returns_correct_total_coil_count(self, three_phase_config, gen):
        coils = gen.generate_all_layers(three_phase_config, layer_count=6)
        assert len(coils) == 6  # one coil per layer

    def test_eight_layer_count(self, three_phase_config, gen):
        coils = gen.generate_all_layers(three_phase_config, layer_count=8)
        assert len(coils) == 8

    def test_sorted_by_layer_then_phase(self, three_phase_config, gen):
        coils = gen.generate_all_layers(three_phase_config, layer_count=6)
        for i in range(len(coils) - 1):
            a, b = coils[i], coils[i + 1]
            assert (a.layer_idx, a.phase_idx) <= (b.layer_idx, b.phase_idx)

    def test_all_layers_represented(self, three_phase_config, gen):
        layer_count = 6
        coils = gen.generate_all_layers(three_phase_config, layer_count=layer_count)
        layer_ids = {c.layer_idx for c in coils}
        assert layer_ids == set(range(layer_count))

    def test_odd_layer_count_raises(self, three_phase_config, gen):
        with pytest.raises(ValueError, match="layer_count must be even"):
            gen.generate_all_layers(three_phase_config, layer_count=5)

    def test_fewer_layers_than_phases_raises(self, three_phase_config, gen):
        with pytest.raises(ValueError, match="layer_count.*must be ≥ phases"):
            gen.generate_all_layers(three_phase_config, layer_count=2)

    def test_custom_phase_layer_map(self, three_phase_config, gen):
        custom_map = {0: [0, 1], 1: [2, 3], 2: [4, 5]}
        coils = gen.generate_all_layers(
            three_phase_config,
            layer_count=6,
            phase_layer_map=custom_map,
        )
        for coil in coils:
            if coil.phase_idx == 0:
                assert coil.layer_idx in [0, 1]
            elif coil.phase_idx == 1:
                assert coil.layer_idx in [2, 3]
            else:
                assert coil.layer_idx in [4, 5]


# ===========================================================================
# default_phase_layer_map
# ===========================================================================


class TestDefaultPhaseLayerMap:
    def test_6_layers_3_phases(self):
        m = WaveWindingGenerator.default_phase_layer_map(3, 6)
        assert m == {0: [0, 3], 1: [1, 4], 2: [2, 5]}

    def test_8_layers_3_phases(self):
        m = WaveWindingGenerator.default_phase_layer_map(3, 8)
        # Phase 0 gets layers 0, 3, 6; phase 1 gets 1, 4, 7; phase 2 gets 2, 5
        assert 0 in m[0] and 3 in m[0] and 6 in m[0]
        assert 1 in m[1] and 4 in m[1] and 7 in m[1]
        assert 2 in m[2] and 5 in m[2]

    def test_all_layers_covered(self):
        m = WaveWindingGenerator.default_phase_layer_map(3, 6)
        all_layers = sorted(layer for layers in m.values() for layer in layers)
        assert all_layers == list(range(6))

    def test_4_layers_2_phases(self):
        m = WaveWindingGenerator.default_phase_layer_map(2, 4)
        assert m == {0: [0, 2], 1: [1, 3]}
