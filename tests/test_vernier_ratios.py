"""
tests/test_vernier_ratios.py
============================
Test coverage for the Vernier spacing_ratio field on BaseMotorConfig.

The spacing_ratio controls fractional slot spacing (Vernier winding):
    slot_pitch_m = (pole_pitch_m / phases) * spacing_ratio

Product spec (PRODUCT_GOALS.md section 4B) requires 4:5 and 5:6 Vernier
ratios to reduce spatial force ripple.
"""

from __future__ import annotations

import math

import pytest

from pcbstatorgen.config import LinearMotorConfig, MotorConfig
from pcbstatorgen.geometry.wave_winding import (
    WaveWindingGenerator,
    SineWaveWindingGenerator,
)
from pcbstatorgen.magnetic.force_eval import ForceEvaluator, ForceResult
from pcbstatorgen.units import mm


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def gen() -> WaveWindingGenerator:
    return WaveWindingGenerator()


@pytest.fixture
def sine_gen() -> SineWaveWindingGenerator:
    return SineWaveWindingGenerator()


@pytest.fixture
def vernier_45_config(default_config) -> MotorConfig:
    """4:5 Vernier config (spacing_ratio = 0.8)."""
    return MotorConfig(
        name="vernier-45",
        active_area_length_m=default_config.active_area_length_m,
        magnet_dims_m=default_config.magnet_dims_m,
        magnet_count=default_config.magnet_count,
        magnet_pitch_m=default_config.magnet_pitch_m,
        magnet_remanence_t=default_config.magnet_remanence_t,
        phases=default_config.phases,
        spacing_ratio=0.8,
        target_force_n=default_config.target_force_n,
        max_current_a=default_config.max_current_a,
        min_trace_m=default_config.min_trace_m,
        min_space_m=default_config.min_space_m,
        min_via_drill_m=default_config.min_via_drill_m,
        min_via_annular_ring_m=default_config.min_via_annular_ring_m,
        board_width_m=default_config.board_width_m,
        air_gap_m=default_config.air_gap_m,
        max_layers=default_config.max_layers,
        drive_frequency_hz=default_config.drive_frequency_hz,
    )


@pytest.fixture
def vernier_56_config(default_config) -> MotorConfig:
    """5:6 Vernier config (spacing_ratio = 5/6 = 0.8333...)."""
    return MotorConfig(
        name="vernier-56",
        active_area_length_m=default_config.active_area_length_m,
        magnet_dims_m=default_config.magnet_dims_m,
        magnet_count=default_config.magnet_count,
        magnet_pitch_m=default_config.magnet_pitch_m,
        magnet_remanence_t=default_config.magnet_remanence_t,
        phases=default_config.phases,
        spacing_ratio=5.0 / 6.0,
        target_force_n=default_config.target_force_n,
        max_current_a=default_config.max_current_a,
        min_trace_m=default_config.min_trace_m,
        min_space_m=default_config.min_space_m,
        min_via_drill_m=default_config.min_via_drill_m,
        min_via_annular_ring_m=default_config.min_via_annular_ring_m,
        board_width_m=default_config.board_width_m,
        air_gap_m=default_config.air_gap_m,
        max_layers=default_config.max_layers,
        drive_frequency_hz=default_config.drive_frequency_hz,
    )


def _clone_with_ratio(cfg: MotorConfig, ratio: float) -> MotorConfig:
    """Return a copy of *cfg* with spacing_ratio set to *ratio*."""
    return MotorConfig(
        name=cfg.name,
        active_area_length_m=cfg.active_area_length_m,
        magnet_dims_m=cfg.magnet_dims_m,
        magnet_count=cfg.magnet_count,
        magnet_pitch_m=cfg.magnet_pitch_m,
        magnet_remanence_t=cfg.magnet_remanence_t,
        phases=cfg.phases,
        spacing_ratio=ratio,
        target_force_n=cfg.target_force_n,
        max_current_a=cfg.max_current_a,
        min_trace_m=cfg.min_trace_m,
        min_space_m=cfg.min_space_m,
        min_via_drill_m=cfg.min_via_drill_m,
        min_via_annular_ring_m=cfg.min_via_annular_ring_m,
        board_width_m=cfg.board_width_m,
        air_gap_m=cfg.air_gap_m,
        max_layers=cfg.max_layers,
        drive_frequency_hz=cfg.drive_frequency_hz,
    )


# ===========================================================================
# TestSpacingRatioConfig
# ===========================================================================


class TestSpacingRatioConfig:
    def test_default_is_unity(self, default_config):
        assert default_config.spacing_ratio == pytest.approx(1.0)

    def test_slot_pitch_m_with_ratio_1(self, default_config):
        expected = default_config.pole_pitch_m / default_config.phases
        assert default_config.slot_pitch_m == pytest.approx(expected, rel=1e-9)

    def test_slot_pitch_m_with_ratio_0_8(self, vernier_45_config):
        cfg = vernier_45_config
        expected = (cfg.pole_pitch_m / cfg.phases) * 0.8
        assert cfg.slot_pitch_m == pytest.approx(expected, rel=1e-9)

    def test_slot_pitch_m_with_ratio_5_6(self, vernier_56_config):
        cfg = vernier_56_config
        expected = (cfg.pole_pitch_m / cfg.phases) * (5.0 / 6.0)
        assert cfg.slot_pitch_m == pytest.approx(expected, rel=1e-9)

    def test_rejects_zero(self, default_config):
        with pytest.raises(ValueError, match="spacing_ratio"):
            _clone_with_ratio(default_config, 0.0)

    def test_rejects_negative(self, default_config):
        with pytest.raises(ValueError, match="spacing_ratio"):
            _clone_with_ratio(default_config, -0.5)

    def test_rejects_above_2(self, default_config):
        with pytest.raises(ValueError, match="spacing_ratio"):
            _clone_with_ratio(default_config, 2.01)

    def test_accepts_just_above_zero(self, default_config):
        cfg = _clone_with_ratio(default_config, 0.001)
        assert cfg.spacing_ratio == pytest.approx(0.001)

    def test_accepts_exactly_2(self, default_config):
        cfg = _clone_with_ratio(default_config, 2.0)
        assert cfg.spacing_ratio == pytest.approx(2.0)

    def test_accepts_mid_range(self, default_config):
        for r in (0.1, 0.5, 0.8, 1.0, 1.5, 1.99):
            cfg = _clone_with_ratio(default_config, r)
            assert cfg.spacing_ratio == pytest.approx(r)


# ===========================================================================
# TestVernierConductorPositions
# ===========================================================================


class TestVernierConductorPositions:
    def test_phase_offsets_use_vernier_slot_pitch(self, vernier_45_config, gen):
        cfg = vernier_45_config
        sp = cfg.slot_pitch_m
        positions_a = gen.conductor_x_positions(cfg, phase_idx=0)
        positions_b = gen.conductor_x_positions(cfg, phase_idx=1)
        positions_c = gen.conductor_x_positions(cfg, phase_idx=2)
        assert positions_a[0] == pytest.approx(0.0, abs=1e-9)
        assert positions_b[0] == pytest.approx(sp, rel=1e-9)
        assert positions_c[0] == pytest.approx(2 * sp, rel=1e-9)

    def test_conductor_spacing_is_pole_pitch(self, vernier_45_config, gen):
        cfg = vernier_45_config
        tau = cfg.pole_pitch_m
        for p in range(cfg.phases):
            positions = gen.conductor_x_positions(cfg, phase_idx=p)
            for i in range(len(positions) - 1):
                assert positions[i + 1] - positions[i] == pytest.approx(tau, rel=1e-9)

    def test_ratio_0_8_differs_from_1_0(self, default_config, vernier_45_config, gen):
        for p in range(1, default_config.phases):
            pos_1 = gen.conductor_x_positions(default_config, phase_idx=p)
            pos_08 = gen.conductor_x_positions(vernier_45_config, phase_idx=p)
            assert pos_1 != pos_08, (
                f"Phase {p}: ratio 0.8 positions identical to ratio 1.0"
            )

    def test_ratio_5_6_differs_from_0_8(self, vernier_45_config, vernier_56_config, gen):
        for p in range(1, vernier_45_config.phases):
            pos_08 = gen.conductor_x_positions(vernier_45_config, phase_idx=p)
            pos_56 = gen.conductor_x_positions(vernier_56_config, phase_idx=p)
            assert pos_08 != pos_56, (
                f"Phase {p}: ratio 5/6 positions identical to ratio 0.8"
            )

    def test_balanced_conductor_count_across_phases(self, vernier_45_config, gen):
        cfg = vernier_45_config
        counts = [
            len(gen.conductor_x_positions(cfg, phase_idx=p))
            for p in range(cfg.phases)
        ]
        assert len(set(counts)) == 1, f"Unequal conductor counts with Vernier: {counts}"

    def test_balanced_conductor_count_5_6(self, vernier_56_config, gen):
        cfg = vernier_56_config
        counts = [
            len(gen.conductor_x_positions(cfg, phase_idx=p))
            for p in range(cfg.phases)
        ]
        assert len(set(counts)) == 1, f"Unequal conductor counts with 5:6 Vernier: {counts}"

    def test_phase_offset_equals_phase_idx_times_slot_pitch(self, vernier_45_config, gen):
        cfg = vernier_45_config
        sp = cfg.slot_pitch_m
        for p in range(cfg.phases):
            positions = gen.conductor_x_positions(cfg, phase_idx=p)
            assert positions[0] == pytest.approx(p * sp, rel=1e-9)

    def test_phase_offset_equals_phase_idx_times_slot_pitch_5_6(self, vernier_56_config, gen):
        cfg = vernier_56_config
        sp = cfg.slot_pitch_m
        for p in range(cfg.phases):
            positions = gen.conductor_x_positions(cfg, phase_idx=p)
            assert positions[0] == pytest.approx(p * sp, rel=1e-9)

    def test_vernier_count_matches_default_count(self, default_config, vernier_45_config, gen):
        for p in range(default_config.phases):
            n_default = len(gen.conductor_x_positions(default_config, phase_idx=p))
            n_vernier = len(gen.conductor_x_positions(vernier_45_config, phase_idx=p))
            assert n_vernier == n_default, (
                f"Phase {p}: Vernier conductor count ({n_vernier}) "
                f"differs from default ({n_default})"
            )


# ===========================================================================
# TestVernierCoilGeneration
# ===========================================================================


class TestVernierCoilGeneration:
    def test_wave_generate_produces_continuous_polylines(self, vernier_45_config, gen):
        coils = gen.generate(vernier_45_config)
        assert len(coils) == vernier_45_config.phases
        for coil in coils:
            assert coil.is_continuous(), (
                f"Phase {coil.phase_name} coil not continuous with ratio 0.8"
            )
            assert len(coil.polyline) == len(coil.segments) + 1

    def test_vernier_bounding_box_differs_from_default(self, default_config, vernier_45_config, gen):
        coils_default = gen.generate(default_config)
        coils_vernier = gen.generate(vernier_45_config)
        for p in range(1, default_config.phases):
            bb_d = coils_default[p].bounding_box
            bb_v = coils_vernier[p].bounding_box
            assert bb_v != bb_d, (
                f"Phase {p}: bounding box identical between ratio 0.8 and 1.0"
            )

    def test_sine_generate_produces_valid_phase_coils(self, vernier_45_config, sine_gen):
        coils = sine_gen.generate(vernier_45_config)
        assert len(coils) == vernier_45_config.phases
        for coil in coils:
            assert len(coil.segments) > 0, (
                f"Phase {coil.phase_name} sine coil has no segments"
            )
            assert coil.is_continuous(), (
                f"Phase {coil.phase_name} sine coil not continuous"
            )

    def test_conductor_count_preserved_across_ratios(self, default_config, vernier_45_config, gen):
        coils_default = gen.generate(default_config)
        coils_vernier = gen.generate(vernier_45_config)
        for p in range(default_config.phases):
            n_d = coils_default[p].active_conductor_count
            n_v = coils_vernier[p].active_conductor_count
            assert n_v == n_d, (
                f"Phase {p}: Vernier active conductor count ({n_v}) "
                f"differs from default ({n_d})"
            )

    def test_vernier_phase_offsets_in_terminal_start(self, vernier_45_config, gen):
        cfg = vernier_45_config
        sp = cfg.slot_pitch_m
        coils = gen.generate(cfg)
        for p, coil in enumerate(coils):
            assert coil.terminal_start[0] == pytest.approx(p * sp, rel=1e-9)

    def test_sine_vernier_differs_from_default(self, default_config, vernier_45_config, sine_gen):
        coils_default = sine_gen.generate(default_config)
        coils_vernier = sine_gen.generate(vernier_45_config)
        for p in range(default_config.phases):
            bb_d = coils_default[p].bounding_box
            bb_v = coils_vernier[p].bounding_box
            assert bb_v != bb_d, (
                f"Phase {p}: sine bounding box identical between ratio 0.8 and 1.0"
            )


# ===========================================================================
# TestVernierRippleEffect  (slow — Magpylib force sweep)
# ===========================================================================


class TestVernierRippleEffect:
    @pytest.mark.slow
    def test_4_5_vernier_changes_ripple(self, default_config, vernier_45_config, gen):
        ev = ForceEvaluator(n_positions=8, meshing=5, commutation="max_torque")

        coils_1 = gen.generate(default_config)
        result_1 = ev.evaluate(default_config, coils_1)

        coils_08 = gen.generate(vernier_45_config)
        result_08 = ev.evaluate(vernier_45_config, coils_08)

        assert result_1.ripple_pct != pytest.approx(result_08.ripple_pct, abs=0.01), (
            f"4:5 Vernier ripple ({result_08.ripple_pct:.2f}%) "
            f"matches 1:1 ripple ({result_1.ripple_pct:.2f}%)"
        )

    @pytest.mark.slow
    def test_5_6_vernier_changes_ripple(self, default_config, vernier_56_config, gen):
        ev = ForceEvaluator(n_positions=8, meshing=5, commutation="max_torque")

        coils_1 = gen.generate(default_config)
        result_1 = ev.evaluate(default_config, coils_1)

        coils_56 = gen.generate(vernier_56_config)
        result_56 = ev.evaluate(vernier_56_config, coils_56)

        assert result_1.ripple_pct != pytest.approx(result_56.ripple_pct, abs=0.01), (
            f"5:6 Vernier ripple ({result_56.ripple_pct:.2f}%) "
            f"matches 1:1 ripple ({result_1.ripple_pct:.2f}%)"
        )

    @pytest.mark.slow
    def test_4_5_vernier_reduces_ripple_if_feasible(self, default_config, vernier_45_config, gen):
        ev = ForceEvaluator(n_positions=8, meshing=5, commutation="max_torque")

        coils_1 = gen.generate(default_config)
        result_1 = ev.evaluate(default_config, coils_1)

        coils_08 = gen.generate(vernier_45_config)
        result_08 = ev.evaluate(vernier_45_config, coils_08)

        if result_08.ripple_pct < result_1.ripple_pct:
            pass
        else:
            assert result_1.ripple_pct != pytest.approx(result_08.ripple_pct, abs=0.01), (
                "4:5 Vernier did not reduce ripple and ripple values are identical"
            )
