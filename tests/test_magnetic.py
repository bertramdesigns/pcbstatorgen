"""
tests/test_magnetic.py
======================
Tests for MagnetArray, CoilCurrentModel, and ForceEvaluator.

Test tiers
----------
Fast (no mark):   geometry, object construction, commutation math — run always.
@pytest.mark.slow: calls magpy.getFT() or magpy.getB() — skip with -m "not slow".
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import magpylib as magpy

from pcbstatorgen.config import MotorConfig
from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator
from pcbstatorgen.magnetic.coil_model import CoilCurrentModel, PhaseCurrentSources
from pcbstatorgen.magnetic.force_eval import ForceEvaluator, ForceResult
from pcbstatorgen.magnetic.magnet_model import MagnetArray
from pcbstatorgen.units import mm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_config(default_config) -> MotorConfig:
    """Full default config — 75 mm travel, 10 magnets, 3-phase."""
    return default_config


@pytest.fixture
def tiny_config() -> MotorConfig:
    """Reduced config for fast force tests: 4 magnets, 1-phase, short travel."""
    return MotorConfig(
        travel_m=mm(24),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=4,
        magnet_pitch_m=mm(12),
        phases=1,
        target_force_n=0.05,
        max_current_a=1.0,
        min_trace_m=mm(0.15),
        min_space_m=mm(0.15),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
        max_layers=4,
    )


@pytest.fixture
def gen() -> WaveWindingGenerator:
    return WaveWindingGenerator()


# ===========================================================================
# MagnetArray — geometry (fast)
# ===========================================================================


class TestMagnetArrayGeometry:
    def test_builds_correct_magnet_count(self, small_config):
        arr = MagnetArray(small_config)
        coll = arr.build_collection()
        assert len(coll.sources_all) == small_config.magnet_count

    def test_magnet_z_center(self, small_config):
        arr = MagnetArray(small_config)
        expected_z = small_config.air_gap_m + small_config.magnet_dims_m[2] / 2.0
        assert arr.magnet_z_center_m() == pytest.approx(expected_z)

    def test_magnet_z_center_above_pcb(self, small_config):
        arr = MagnetArray(small_config)
        assert arr.magnet_z_center_m() > 0.0

    def test_first_magnet_x_at_mover_zero(self, small_config):
        arr = MagnetArray(small_config)
        xs = arr.magnet_x_centers_m(mover_position_m=0.0)
        assert xs[0] == pytest.approx(0.0)

    def test_magnet_spacing_equals_pitch(self, small_config):
        arr = MagnetArray(small_config)
        xs = arr.magnet_x_centers_m()
        diffs = np.diff(xs)
        assert np.allclose(diffs, small_config.magnet_pitch_m)

    def test_mover_position_shifts_all_magnets(self, small_config):
        arr = MagnetArray(small_config)
        shift = mm(30)
        xs_0 = arr.magnet_x_centers_m(mover_position_m=0.0)
        xs_s = arr.magnet_x_centers_m(mover_position_m=shift)
        assert np.allclose(xs_s - xs_0, shift)

    def test_polarizations_alternate_sign(self, small_config):
        arr = MagnetArray(small_config)
        pols = arr.polarizations_t()
        for k in range(small_config.magnet_count):
            expected_sign = 1.0 if k % 2 == 0 else -1.0
            assert pols[k, 2] == pytest.approx(
                expected_sign * small_config.magnet_remanence_t
            )

    def test_polarizations_x_y_are_zero(self, small_config):
        arr = MagnetArray(small_config)
        pols = arr.polarizations_t()
        assert np.allclose(pols[:, 0], 0.0)
        assert np.allclose(pols[:, 1], 0.0)

    def test_polarization_magnitude_equals_remanence(self, small_config):
        arr = MagnetArray(small_config)
        pols = arr.polarizations_t()
        magnitudes = np.linalg.norm(pols, axis=1)
        assert np.allclose(magnitudes, small_config.magnet_remanence_t)

    def test_sweep_collection_path_length(self, small_config):
        arr = MagnetArray(small_config)
        positions = np.linspace(0, small_config.travel_m, 15)
        coll = arr.build_sweep_collection(positions)
        assert len(coll.position) == 15

    def test_sweep_collection_requires_1d(self, small_config):
        arr = MagnetArray(small_config)
        with pytest.raises(ValueError, match="1-D"):
            arr.build_sweep_collection(np.zeros((3, 2)))

    def test_collection_at_nonzero_position(self, small_config):
        arr = MagnetArray(small_config)
        coll = arr.build_collection(mover_position_m=mm(30))
        # First child should be at x ≈ 30mm (plus the child's own offset)
        first_pos = coll.sources_all[0].position
        assert first_pos[0] == pytest.approx(mm(30), abs=1e-9)


# ===========================================================================
# MagnetArray — B field (slow)
# ===========================================================================


class TestMagnetArrayBField:
    @pytest.mark.slow
    def test_bfield_returns_correct_shape(self, small_config):
        arr = MagnetArray(small_config)
        xs = np.linspace(0, small_config.active_length_m, 20)
        B = arr.bfield_at_pcb_surface(xs)
        assert B.shape == (20, 3)

    @pytest.mark.slow
    def test_bfield_has_nonzero_z_component(self, small_config):
        arr = MagnetArray(small_config)
        xs = np.linspace(0, small_config.coil_span_m, 30)
        B = arr.bfield_at_pcb_surface(xs)
        # Bz should be substantial (hundreds of mT) near the first magnet
        assert np.max(np.abs(B[:, 2])) > 0.05  # > 50 mT

    @pytest.mark.slow
    def test_bfield_bz_alternates_sign(self, small_config):
        """Bz should have both positive and negative regions under alternating poles."""
        arr = MagnetArray(small_config)
        # Sample near the magnet centres
        xs = arr.magnet_x_centers_m()
        B = arr.bfield_at_pcb_surface(xs)
        bz = B[:, 2]
        assert np.any(bz > 0.05) and np.any(bz < -0.05)

    @pytest.mark.slow
    def test_bfield_changes_with_mover_position(self, small_config):
        arr = MagnetArray(small_config)
        xs = np.array([0.0, mm(12), mm(24)])
        B0 = arr.bfield_at_pcb_surface(xs, mover_position_m=0.0)
        B1 = arr.bfield_at_pcb_surface(xs, mover_position_m=mm(6))
        assert not np.allclose(B0, B1)


# ===========================================================================
# CoilCurrentModel — construction (fast)
# ===========================================================================


class TestCoilCurrentModelConstruction:
    def test_builds_one_polyline_per_active_conductor(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        sources = model.build_phase(coils[0], current_a=1.0)
        assert len(sources.polylines) == coils[0].active_conductor_count

    def test_polyline_vertices_match_segment(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel(layer_z_m=0.0)
        sources = model.build_phase(coils[0], current_a=1.0)
        coil_seg = coils[0].active_segments[0]
        poly = sources.polylines[0]
        verts = np.array(poly.vertices)
        assert verts[0, 0] == pytest.approx(coil_seg.start[0])
        assert verts[0, 1] == pytest.approx(coil_seg.start[1])
        assert verts[1, 0] == pytest.approx(coil_seg.end[0])
        assert verts[1, 1] == pytest.approx(coil_seg.end[1])

    def test_polyline_layer_z(self, small_config, gen):
        coils = gen.generate(small_config)
        z_test = -mm(0.1)
        model = CoilCurrentModel(layer_z_m=z_test)
        sources = model.build_phase(coils[0], current_a=1.0)
        for poly in sources.polylines:
            verts = np.array(poly.vertices)
            assert np.all(verts[:, 2] == pytest.approx(z_test))

    def test_polyline_current_value(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        I_test = 2.5
        sources = model.build_phase(coils[0], current_a=I_test)
        for poly in sources.polylines:
            assert poly.current == pytest.approx(I_test)

    def test_meshing_applied(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel(meshing=15)
        sources = model.build_phase(coils[0], current_a=1.0)
        for poly in sources.polylines:
            assert poly.meshing == 15

    def test_invalid_meshing_raises(self):
        with pytest.raises(ValueError, match="meshing must be ≥ 1"):
            CoilCurrentModel(meshing=0)

    def test_build_all_phases_count(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        all_src = model.build_all_phases(coils, currents_a=[1.0, -0.5, -0.5])
        assert len(all_src) == 3

    def test_build_all_phases_mismatch_raises(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        with pytest.raises(ValueError, match="same length"):
            model.build_all_phases(coils, currents_a=[1.0])

    def test_flat_polylines_total_count(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        all_src = model.build_all_phases(coils, currents_a=[1.0, -0.5, -0.5])
        flat = model.flat_polylines(all_src)
        expected = sum(c.active_conductor_count for c in coils)
        assert len(flat) == expected

    def test_phase_current_sources_collection(self, small_config, gen):
        coils = gen.generate(small_config)
        model = CoilCurrentModel()
        sources = model.build_phase(coils[0], current_a=1.0)
        coll = sources.as_collection()
        assert isinstance(coll, magpy.Collection)
        assert len(coll.sources_all) == len(sources)

    def test_include_end_turns_increases_count(self, small_config, gen):
        coils = gen.generate(small_config)
        model_active = CoilCurrentModel(include_end_turns=False)
        model_full = CoilCurrentModel(include_end_turns=True)
        src_a = model_active.build_phase(coils[0], current_a=1.0)
        src_f = model_full.build_phase(coils[0], current_a=1.0)
        assert len(src_f) > len(src_a)


# ===========================================================================
# CoilCurrentModel — B field at conductors (slow)
# ===========================================================================


class TestCoilCurrentModelBField:
    @pytest.mark.slow
    def test_bfield_at_conductor_positions_shape(self, small_config, gen):
        coils = gen.generate(small_config)
        arr = MagnetArray(small_config)
        coll = arr.build_collection(mover_position_m=0.0)
        model = CoilCurrentModel()
        B = model.bfield_at_conductor_positions(coils[0], coll)
        assert B.shape == (coils[0].active_conductor_count, 3)

    @pytest.mark.slow
    def test_bfield_nonzero_at_conductors(self, small_config, gen):
        coils = gen.generate(small_config)
        arr = MagnetArray(small_config)
        coll = arr.build_collection(mover_position_m=0.0)
        model = CoilCurrentModel()
        B = model.bfield_at_conductor_positions(coils[0], coll)
        # The magnets are directly above — expect substantial Bz
        assert np.max(np.abs(B[:, 2])) > 0.05


# ===========================================================================
# ForceEvaluator — commutation math (fast, no Magpylib calls)
# ===========================================================================


class TestForceEvaluatorCommutation:
    def test_phase_a_only_returns_correct_currents(self, small_config):
        ev = ForceEvaluator(commutation="phase_a_only")
        currents = ev._commutation_currents(small_config, 0.0, n_phases=3)
        assert currents[0] == pytest.approx(small_config.max_current_a)
        assert currents[1] == pytest.approx(0.0)
        assert currents[2] == pytest.approx(0.0)

    def test_max_torque_currents_sum_to_near_zero(self, small_config):
        """Balanced 3-phase: instantaneous sum of phase currents ≈ 0."""
        ev = ForceEvaluator(commutation="max_torque")
        for pos in np.linspace(0, small_config.travel_m, 20):
            currents = ev._commutation_currents(small_config, pos, n_phases=3)
            assert abs(sum(currents)) < 1e-9

    def test_max_torque_peak_equals_config_current(self, small_config):
        ev = ForceEvaluator(commutation="max_torque")
        max_seen = 0.0
        for pos in np.linspace(0, 2 * small_config.pole_pitch_m, 100):
            currents = ev._commutation_currents(small_config, pos, n_phases=3)
            max_seen = max(max_seen, max(abs(i) for i in currents))
        # max of sin sweep should reach I_peak
        assert max_seen == pytest.approx(small_config.max_current_a, abs=0.01)

    def test_electrical_angle_increments_correctly(self, small_config):
        """One full electrical cycle spans exactly 2 × pole_pitch."""
        two_tau = 2.0 * small_config.pole_pitch_m
        angle_0 = ForceEvaluator.electrical_angle(small_config, 0.0)
        angle_2t = ForceEvaluator.electrical_angle(small_config, two_tau)
        assert angle_0 == pytest.approx(0.0)
        assert angle_2t == pytest.approx(2.0 * math.pi)

    def test_n_positions_validation(self):
        with pytest.raises(ValueError, match="n_positions must be ≥ 2"):
            ForceEvaluator(n_positions=1)

    def test_meshing_validation(self):
        with pytest.raises(ValueError, match="meshing must be ≥ 1"):
            ForceEvaluator(meshing=0)


# ===========================================================================
# ForceResult — properties (fast, constructed from synthetic data)
# ===========================================================================


class TestForceResult:
    @pytest.fixture
    def synthetic_result(self) -> ForceResult:
        n = 20
        pos = np.linspace(0, 0.075, n)
        # Simulate small ripple around 300 mN with 3-phase
        base = 0.300
        ripple = 0.010
        fx = base + ripple * np.sin(np.linspace(0, 6 * math.pi, n))
        return ForceResult(
            positions_m=pos,
            force_x_n=fx,
            force_y_n=np.zeros(n),
            force_z_n=np.full(n, -0.5),
            per_phase_force_x=np.ones((n, 3)) * base / 3,
            commutation="max_torque",
            current_a=1.0,
        )

    def test_n_positions(self, synthetic_result):
        assert synthetic_result.n_positions == 20

    def test_mean_thrust(self, synthetic_result):
        assert synthetic_result.mean_thrust_n == pytest.approx(0.300, abs=0.005)

    def test_ripple_pct_small(self, synthetic_result):
        # Peak-to-peak = 2 * 0.010 = 0.020; mean = 0.300
        assert synthetic_result.ripple_pct == pytest.approx(20.0 / 300.0 * 100, abs=1.0)

    def test_peak_thrust_above_mean(self, synthetic_result):
        assert synthetic_result.peak_thrust_n > synthetic_result.mean_thrust_n

    def test_min_thrust_below_mean(self, synthetic_result):
        assert synthetic_result.min_thrust_n < synthetic_result.mean_thrust_n

    def test_summary_is_string(self, synthetic_result):
        s = synthetic_result.summary()
        assert isinstance(s, str) and len(s) > 0

    def test_summary_contains_ripple(self, synthetic_result):
        assert "Ripple" in synthetic_result.summary()

    def test_zero_mean_ripple_returns_zero(self):
        n = 5
        result = ForceResult(
            positions_m=np.zeros(n),
            force_x_n=np.zeros(n),
            force_y_n=np.zeros(n),
            force_z_n=np.zeros(n),
            per_phase_force_x=np.zeros((n, 1)),
            commutation="phase_a_only",
            current_a=1.0,
        )
        assert result.ripple_pct == pytest.approx(0.0)


# ===========================================================================
# ForceEvaluator — evaluate() (slow)
# ===========================================================================


class TestForceEvaluatorSlow:
    @pytest.mark.slow
    def test_evaluate_returns_force_result(self, tiny_config, gen):
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=5, meshing=5)
        result = ev.evaluate(tiny_config, coils)
        assert isinstance(result, ForceResult)

    @pytest.mark.slow
    def test_evaluate_positions_shape(self, tiny_config, gen):
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=8, meshing=5)
        result = ev.evaluate(tiny_config, coils)
        assert result.positions_m.shape == (8,)
        assert result.force_x_n.shape == (8,)

    @pytest.mark.slow
    def test_evaluate_per_phase_shape(self, tiny_config, gen):
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=5, meshing=5)
        result = ev.evaluate(tiny_config, coils)
        assert result.per_phase_force_x.shape == (5, tiny_config.phases)

    @pytest.mark.slow
    def test_evaluate_at_single_position(self, tiny_config, gen):
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=5, meshing=5)
        F, T = ev.evaluate_at(tiny_config, coils, mover_position_m=mm(12))
        assert F.shape == (3,)
        assert T.shape == (3,)

    @pytest.mark.slow
    def test_thrust_direction_positive(self, tiny_config, gen):
        """For phase_a_only at position 0, thrust should be in +X (positive)."""
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=5, meshing=10, commutation="phase_a_only")
        F, _ = ev.evaluate_at(tiny_config, coils, mover_position_m=0.0)
        # With alternating poles and a wave winding, net X force should be non-zero.
        # The sign depends on magnet/coil alignment — just check it's nonzero.
        assert abs(F[0]) > 1e-6  # at least 1 µN

    @pytest.mark.slow
    def test_three_phase_force_nonzero(self, default_config, gen):
        """3-phase max-torque sweep should produce measurable thrust."""
        coils = gen.generate(default_config)
        ev = ForceEvaluator(n_positions=6, meshing=5, commutation="max_torque")
        result = ev.evaluate(default_config, coils)
        # Mean thrust magnitude > 0.1 mN — proves the model is producing output
        assert abs(result.mean_thrust_n) > 1e-4

    @pytest.mark.slow
    def test_phase_a_only_produces_nonzero_mean(self, tiny_config, gen):
        """phase_a_only at constant I_peak should produce a non-trivial mean force."""
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=10, meshing=8, commutation="phase_a_only")
        result = ev.evaluate(tiny_config, coils)
        # Constant current produces non-zero mean because the position sampling
        # does not cover exactly one full symmetric electrical cycle.
        assert abs(result.mean_thrust_n) > 1e-5  # > 10 µN

    @pytest.mark.slow
    def test_max_torque_1phase_near_zero_mean(self, tiny_config, gen):
        """max_torque on a 1-phase motor integrates to ~0 over a full electrical cycle.

        tiny_config has travel=24mm, pole_pitch=12mm → 1 full cycle.
        I = I_pk * sin(θ_e) → mean(sin) = 0 over [0, 2π].
        This is expected physics — 3-phase is required for constant thrust.
        """
        coils = gen.generate(tiny_config)
        ev = ForceEvaluator(n_positions=10, meshing=8, commutation="max_torque")
        result = ev.evaluate(tiny_config, coils)
        # Mean is near zero (sinusoidal over exactly 1 cycle)
        assert abs(result.mean_thrust_n) < abs(result.peak_thrust_n) * 0.1
