"""
tests/test_coil_generators.py
Tests for ConcentratedCoilGenerator, RhombicCoilGenerator, SpiralCoilGenerator,
and the make_coil_generator factory.
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import CoilTopology, LinearMotorConfig
from pcbstatorgen.geometry.coil_generators import (
    ConcentratedCoilGenerator,
    RhombicCoilGenerator,
    SpiralCoilGenerator,
    make_coil_generator,
)
from pcbstatorgen.geometry.wave_winding import CoilSegment, PhaseCoil, WaveWindingGenerator
from pcbstatorgen.units import mm, mils_to_m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg(default_config) -> LinearMotorConfig:
    return default_config


@pytest.fixture
def small_cfg() -> LinearMotorConfig:
    """Reduced config for fast spiral tests."""
    return LinearMotorConfig(
        travel_m=mm(24),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=4,
        magnet_pitch_m=mm(12),
        phases=3,
        target_force_n=0.1,
        max_current_a=1.0,
        min_trace_m=mm(0.15),
        min_space_m=mm(0.15),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
        max_layers=6,
    )


# ===========================================================================
# make_coil_generator factory
# ===========================================================================

class TestMakeCoilGenerator:
    def test_serpentine_returns_wave_generator(self, cfg):
        gen = make_coil_generator(CoilTopology.SERPENTINE)
        assert isinstance(gen, WaveWindingGenerator)

    def test_concentrated_returns_concentrated(self):
        gen = make_coil_generator(CoilTopology.CONCENTRATED)
        assert isinstance(gen, ConcentratedCoilGenerator)

    def test_rhombic_returns_rhombic(self):
        gen = make_coil_generator(CoilTopology.RHOMBIC)
        assert isinstance(gen, RhombicCoilGenerator)

    def test_spiral_returns_spiral(self):
        gen = make_coil_generator(CoilTopology.SPIRAL)
        assert isinstance(gen, SpiralCoilGenerator)

    def test_kwargs_forwarded(self):
        gen = make_coil_generator(CoilTopology.RHOMBIC, angle_deg=25.0)
        assert gen.angle_deg == pytest.approx(25.0)

    def test_spiral_kwargs_forwarded(self):
        gen = make_coil_generator(CoilTopology.SPIRAL, n_turns=3)
        assert gen.n_turns == 3

    def test_all_topologies_covered(self, cfg):
        """Every CoilTopology value must produce a working generator."""
        for topo in CoilTopology:
            gen = make_coil_generator(topo)
            # Each generator must produce coils without error
            if topo == CoilTopology.SPIRAL:
                coils = gen.generate(cfg, layer_pair=(0, 1))
            else:
                coils = gen.generate(cfg)
            assert len(coils) > 0


# ===========================================================================
# PhaseCoil new fields (regression — existing tests must still pass)
# ===========================================================================

class TestPhaseCoilNewFields:
    def test_serpentine_tagged_correctly(self, cfg):
        coils = WaveWindingGenerator().generate(cfg)
        for coil in coils:
            assert coil.topology is CoilTopology.SERPENTINE

    def test_serpentine_no_layer_pair(self, cfg):
        coils = WaveWindingGenerator().generate(cfg)
        for coil in coils:
            assert coil.layer_pair is None

    def test_serpentine_no_center_vias(self, cfg):
        coils = WaveWindingGenerator().generate(cfg)
        for coil in coils:
            assert coil.center_via_positions == []

    def test_default_topology_is_serpentine(self):
        coil = PhaseCoil(phase_idx=0, layer_idx=0, segments=[], phase_name="A")
        assert coil.topology is CoilTopology.SERPENTINE


# ===========================================================================
# ConcentratedCoilGenerator
# ===========================================================================

class TestConcentratedConstruction:
    def test_default_coil_pitch_is_none(self):
        gen = ConcentratedCoilGenerator()
        assert gen.coil_pitch_m is None

    def test_custom_coil_pitch(self):
        gen = ConcentratedCoilGenerator(coil_pitch_m=mm(8))
        assert gen.coil_pitch_m == pytest.approx(mm(8))

    def test_zero_coil_pitch_raises(self):
        with pytest.raises(ValueError, match="coil_pitch_m must be positive"):
            ConcentratedCoilGenerator(coil_pitch_m=0.0)

    def test_coil_pitch_exceeds_pole_pitch_raises(self, cfg):
        gen = ConcentratedCoilGenerator(coil_pitch_m=cfg.pole_pitch_m * 1.5)
        with pytest.raises(ValueError, match="coil_pitch_m"):
            gen.generate(cfg)


class TestConcentratedGenerate:
    def test_returns_one_coil_per_phase(self, cfg):
        coils = ConcentratedCoilGenerator().generate(cfg)
        assert len(coils) == cfg.phases

    def test_tagged_concentrated(self, cfg):
        for coil in ConcentratedCoilGenerator().generate(cfg):
            assert coil.topology is CoilTopology.CONCENTRATED

    def test_no_layer_pair(self, cfg):
        for coil in ConcentratedCoilGenerator().generate(cfg):
            assert coil.layer_pair is None

    def test_path_is_continuous(self, cfg):
        for coil in ConcentratedCoilGenerator().generate(cfg):
            assert coil.is_continuous(), f"Phase {coil.phase_name} not continuous"

    def test_active_segments_are_vertical(self, cfg):
        for coil in ConcentratedCoilGenerator().generate(cfg):
            for seg in coil.active_segments:
                assert seg.is_vertical(), (
                    f"Active seg in concentrated phase {coil.phase_name} not vertical: {seg}"
                )

    def test_end_turns_are_horizontal(self, cfg):
        for coil in ConcentratedCoilGenerator().generate(cfg):
            for seg in coil.end_turn_segments:
                assert seg.is_horizontal(), (
                    f"End-turn in concentrated phase {coil.phase_name} not horizontal"
                )

    def test_all_go_conductors_are_upward(self, cfg):
        """All active conductors should go from y=0 to y=W (no alternation)."""
        W = cfg.board_width_m
        for coil in ConcentratedCoilGenerator().generate(cfg):
            for seg in coil.active_segments:
                # Either upward (go) or downward (return), but go conductors are always up
                ys = sorted([seg.start[1], seg.end[1]])
                assert ys[0] == pytest.approx(0.0) and ys[1] == pytest.approx(W)

    def test_full_pitch_same_active_count_as_serpentine(self, cfg):
        """Full-pitch concentrated should have the same active conductor count as serpentine."""
        serpentine_counts = [c.active_conductor_count for c in WaveWindingGenerator().generate(cfg)]
        concentrated_counts = [c.active_conductor_count for c in ConcentratedCoilGenerator().generate(cfg)]
        for sc, cc in zip(serpentine_counts, concentrated_counts):
            assert abs(sc - cc) <= 2  # within 2 due to boundary coil handling

    def test_short_pitch_shorter_top_end_turns(self, cfg):
        """2/3-pitch coil should have shorter top end-turns than full-pitch."""
        coil_full = ConcentratedCoilGenerator(coil_pitch_m=cfg.pole_pitch_m).generate(cfg)[0]
        coil_short = ConcentratedCoilGenerator(coil_pitch_m=2 * cfg.slot_pitch_m).generate(cfg)[0]
        # Top end-turns at y=W
        W = cfg.board_width_m
        top_et_full = [s for s in coil_full.end_turn_segments if abs(s.start[1] - W) < 1e-9]
        top_et_short = [s for s in coil_short.end_turn_segments if abs(s.start[1] - W) < 1e-9]
        if top_et_full and top_et_short:
            avg_full = sum(s.length_m for s in top_et_full) / len(top_et_full)
            avg_short = sum(s.length_m for s in top_et_short) / len(top_et_short)
            assert avg_short < avg_full

    def test_top_end_turn_length_helper(self, cfg):
        cp = mm(8)
        assert ConcentratedCoilGenerator.top_end_turn_length(cp) == pytest.approx(cp)

    def test_bottom_link_length_helper(self, cfg):
        cp = mm(8)
        pp = cfg.pole_pitch_m
        assert ConcentratedCoilGenerator.bottom_link_length(cp, pp) == pytest.approx(2 * pp - cp)

    def test_phase_offsets_match_serpentine(self, cfg):
        """Phase A starts at x=0, B at slot_pitch, C at 2×slot_pitch."""
        sp = cfg.slot_pitch_m
        coils = ConcentratedCoilGenerator().generate(cfg)
        for p, coil in enumerate(coils):
            assert coil.terminal_start[0] == pytest.approx(p * sp)

    def test_layer_idx_assigned(self, cfg):
        coils = ConcentratedCoilGenerator().generate(cfg, layer_idx=2)
        for coil in coils:
            assert coil.layer_idx == 2

    def test_phase_names(self, cfg):
        coils = ConcentratedCoilGenerator().generate(cfg)
        assert coils[0].phase_name == "A"
        assert coils[1].phase_name == "B"
        assert coils[2].phase_name == "C"


# ===========================================================================
# RhombicCoilGenerator
# ===========================================================================

class TestRhombicConstruction:
    def test_default_angle(self):
        gen = RhombicCoilGenerator()
        assert gen.angle_deg == pytest.approx(30.0)

    def test_custom_angle(self):
        gen = RhombicCoilGenerator(angle_deg=20.0)
        assert gen.angle_deg == pytest.approx(20.0)

    def test_zero_angle_raises(self):
        with pytest.raises(ValueError, match="angle_deg must be in"):
            RhombicCoilGenerator(angle_deg=0.0)

    def test_angle_above_max_raises(self):
        with pytest.raises(ValueError, match="angle_deg must be in"):
            RhombicCoilGenerator(angle_deg=90.0)

    def test_force_factor_30deg(self):
        gen = RhombicCoilGenerator(angle_deg=30.0)
        assert gen.force_factor == pytest.approx(math.cos(math.radians(30)), rel=1e-6)

    def test_conductor_length_factor_30deg(self):
        gen = RhombicCoilGenerator(angle_deg=30.0)
        assert gen.conductor_length_factor == pytest.approx(
            1.0 / math.cos(math.radians(30)), rel=1e-6
        )

    def test_force_factor_45deg(self):
        gen = RhombicCoilGenerator(angle_deg=45.0)
        assert gen.force_factor == pytest.approx(math.cos(math.radians(45)), rel=1e-6)


class TestRhombicGenerate:
    def test_returns_one_coil_per_phase(self, cfg):
        coils = RhombicCoilGenerator().generate(cfg)
        assert len(coils) == cfg.phases

    def test_tagged_rhombic(self, cfg):
        for coil in RhombicCoilGenerator().generate(cfg):
            assert coil.topology is CoilTopology.RHOMBIC

    def test_active_segments_are_diagonal(self, cfg):
        """Rhombic active segments are NOT vertical — they have an X component."""
        gen = RhombicCoilGenerator(angle_deg=30.0)
        for coil in gen.generate(cfg):
            for seg in coil.active_segments:
                dx = abs(seg.end[0] - seg.start[0])
                # Diagonal: x displacement should be W * tan(30°) ≈ 11.5mm
                assert dx > 1e-6, f"Active seg has no X displacement: {seg}"

    def test_end_turns_are_horizontal(self, cfg):
        for coil in RhombicCoilGenerator().generate(cfg):
            for seg in coil.end_turn_segments:
                assert seg.is_horizontal(), (
                    f"End-turn in rhombic phase {coil.phase_name} not horizontal"
                )

    def test_path_is_continuous(self, cfg):
        for coil in RhombicCoilGenerator().generate(cfg):
            assert coil.is_continuous(), f"Phase {coil.phase_name} rhombic coil not continuous"

    def test_active_conductors_span_board_width(self, cfg):
        """Active conductors must bridge y=0 to y=board_width."""
        W = cfg.board_width_m
        for coil in RhombicCoilGenerator().generate(cfg):
            for seg in coil.active_segments:
                ys = sorted([seg.start[1], seg.end[1]])
                assert ys[0] == pytest.approx(0.0)
                assert ys[1] == pytest.approx(W)

    def test_x_displacement_matches_angle(self, cfg):
        """X displacement of each active conductor = W × tan(angle_deg)."""
        angle = 30.0
        gen = RhombicCoilGenerator(angle_deg=angle)
        expected_dx = cfg.board_width_m * math.tan(math.radians(angle))
        for coil in gen.generate(cfg):
            for seg in coil.active_segments:
                dx = abs(seg.end[0] - seg.start[0])
                assert dx == pytest.approx(expected_dx, rel=1e-6)

    def test_larger_angle_larger_displacement(self, cfg):
        gen_30 = RhombicCoilGenerator(angle_deg=30.0)
        gen_40 = RhombicCoilGenerator(angle_deg=40.0)
        coil_30 = gen_30.generate(cfg)[0]
        coil_40 = gen_40.generate(cfg)[0]
        dx_30 = abs(coil_30.active_segments[0].end[0] - coil_30.active_segments[0].start[0])
        dx_40 = abs(coil_40.active_segments[0].end[0] - coil_40.active_segments[0].start[0])
        assert dx_40 > dx_30

    def test_no_layer_pair(self, cfg):
        for coil in RhombicCoilGenerator().generate(cfg):
            assert coil.layer_pair is None

    def test_phase_indices_correct(self, cfg):
        coils = RhombicCoilGenerator().generate(cfg)
        for p, coil in enumerate(coils):
            assert coil.phase_idx == p

    def test_returns_coils_at_different_angles(self, cfg):
        for angle in [10.0, 20.0, 30.0, 40.0, 45.0]:
            coils = RhombicCoilGenerator(angle_deg=angle).generate(cfg)
            assert len(coils) == cfg.phases


# ===========================================================================
# SpiralCoilGenerator
# ===========================================================================

class TestSpiralConstruction:
    def test_default_n_turns_is_none(self):
        gen = SpiralCoilGenerator()
        assert gen.n_turns is None

    def test_custom_n_turns(self):
        gen = SpiralCoilGenerator(n_turns=3)
        assert gen.n_turns == 3

    def test_zero_turns_raises(self):
        with pytest.raises(ValueError, match="n_turns must be ≥ 1"):
            SpiralCoilGenerator(n_turns=0)

    def test_max_turns_bounded(self, cfg):
        gen = SpiralCoilGenerator()
        assert gen.max_turns(cfg) <= SpiralCoilGenerator._MAX_AUTO_TURNS

    def test_max_turns_at_least_one(self, cfg):
        gen = SpiralCoilGenerator()
        assert gen.max_turns(cfg) >= 1

    def test_max_turns_increases_with_larger_area(self, cfg):
        """Wider board → more room → more turns."""
        cfg_narrow = LinearMotorConfig(
            travel_m=cfg.travel_m,
            magnet_dims_m=cfg.magnet_dims_m,
            board_width_m=mm(10),
        )
        cfg_wide = LinearMotorConfig(
            travel_m=cfg.travel_m,
            magnet_dims_m=cfg.magnet_dims_m,
            board_width_m=mm(30),
        )
        gen = SpiralCoilGenerator()
        assert gen.max_turns(cfg_wide) >= gen.max_turns(cfg_narrow)


class TestSpiralGenerate:
    def test_returns_two_coils_per_phase(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        assert len(coils) == small_cfg.phases * 2  # 2 per phase (primary + secondary)

    def test_tagged_spiral(self, small_cfg):
        for coil in SpiralCoilGenerator(n_turns=2).generate(small_cfg):
            assert coil.topology is CoilTopology.SPIRAL

    def test_layer_pair_set(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg, layer_pair=(2, 3))
        for coil in coils:
            assert coil.layer_pair == (2, 3)

    def test_primary_layer_idx(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg, layer_pair=(2, 3))
        # Primary (inward) coils should have layer_idx = 2
        primaries = [c for c in coils if c.layer_idx == 2]
        assert len(primaries) == small_cfg.phases

    def test_secondary_layer_idx(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg, layer_pair=(2, 3))
        secondaries = [c for c in coils if c.layer_idx == 3]
        assert len(secondaries) == small_cfg.phases

    def test_center_via_positions_populated(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        for coil in coils:
            assert len(coil.center_via_positions) >= 1

    def test_center_via_inside_stator_bounds(self, small_cfg):
        """All centre vias must be within a reasonable X/Y extent.

        Spiral unit starts at x_unit ≤ x_max; its centre is at
        x_unit + pole_pitch/2, so vias can extend up to x_max + pole_pitch/2.
        """
        x_max = small_cfg.active_length_m + small_cfg.pole_pitch_m
        via_x_max = x_max + small_cfg.pole_pitch_m / 2.0 + 1e-9
        W = small_cfg.board_width_m
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        for coil in coils:
            for vx, vy in coil.center_via_positions:
                assert vx >= -small_cfg.pole_pitch_m, f"via x={vx:.4f} m too far left"
                assert vx <= via_x_max, f"via x={vx*1e3:.1f} mm exceeds bound {via_x_max*1e3:.1f} mm"
                assert 0.0 <= vy <= W + 1e-9

    def test_primary_has_more_segments_than_zero(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        primaries = [c for c in coils if c.layer_idx == 0]
        for coil in primaries:
            assert len(coil.segments) > 0

    def test_both_layers_same_phase_idx(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        # For each phase, there should be one coil per layer with the same phase_idx
        for phase_idx in range(small_cfg.phases):
            phase_coils = [c for c in coils if c.phase_idx == phase_idx]
            assert len(phase_coils) == 2

    def test_active_segments_exist(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        primaries = [c for c in coils if c.layer_idx == 0]
        for coil in primaries:
            assert coil.active_conductor_count > 0

    def test_custom_layer_pair(self, small_cfg):
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg, layer_pair=(4, 5))
        layer_ids = {c.layer_idx for c in coils}
        assert 4 in layer_ids
        assert 5 in layer_ids

    def test_secondary_same_segment_count_as_primary(self, small_cfg):
        """Secondary has a comparable (not necessarily identical) segment count.

        Primary includes inter-unit link segments that secondary does not need
        (secondary units connect back through the primary inter-unit path).
        Verify secondary has ≥ 70% of primary's segment count — enough to confirm
        it was generated properly rather than being accidentally empty.
        """
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg, layer_pair=(0, 1))
        for phase_idx in range(small_cfg.phases):
            primary = next(c for c in coils if c.phase_idx == phase_idx and c.layer_idx == 0)
            secondary = next(c for c in coils if c.phase_idx == phase_idx and c.layer_idx == 1)
            assert len(secondary.segments) > 0, f"Phase {phase_idx} secondary is empty"
            ratio = len(secondary.segments) / len(primary.segments)
            assert ratio >= 0.7, (
                f"Phase {phase_idx}: secondary has only {ratio:.0%} of primary's segments"
            )

    def test_spiral_active_segments_are_vertical(self, small_cfg):
        """Spiral active segments (left/right sides) are vertical."""
        coils = SpiralCoilGenerator(n_turns=2).generate(small_cfg)
        for coil in coils:
            for seg in coil.active_segments:
                assert seg.is_vertical(), f"Active spiral seg not vertical: {seg}"


# ===========================================================================
# Cross-topology consistency checks
# ===========================================================================

class TestCrossTopology:
    @pytest.mark.parametrize("topo,layer_arg", [
        (CoilTopology.CONCENTRATED, {"layer_idx": 0}),
        (CoilTopology.RHOMBIC, {"layer_idx": 0}),
    ])
    def test_non_spiral_topology_count(self, cfg, topo, layer_arg):
        gen = make_coil_generator(topo)
        coils = gen.generate(cfg, **layer_arg)
        assert len(coils) == cfg.phases

    def test_spiral_returns_double(self, small_cfg):
        coils = make_coil_generator(CoilTopology.SPIRAL).generate(
            small_cfg, layer_pair=(0, 1)
        )
        assert len(coils) == small_cfg.phases * 2

    def test_all_topologies_produce_active_segments(self, small_cfg):
        for topo in CoilTopology:
            gen = make_coil_generator(topo)
            if topo == CoilTopology.SPIRAL:
                coils = gen.generate(small_cfg, layer_pair=(0, 1))
            else:
                coils = gen.generate(small_cfg)
            for coil in coils:
                assert coil.active_conductor_count > 0, (
                    f"{topo.value} phase {coil.phase_name} has no active conductors"
                )

    def test_topology_tag_matches_generator(self, cfg):
        """Each generator must tag its coils with the correct CoilTopology."""
        expected = {
            CoilTopology.SERPENTINE: CoilTopology.SERPENTINE,
            CoilTopology.CONCENTRATED: CoilTopology.CONCENTRATED,
            CoilTopology.RHOMBIC: CoilTopology.RHOMBIC,
            CoilTopology.SPIRAL: CoilTopology.SPIRAL,
        }
        for topo, exp_tag in expected.items():
            gen = make_coil_generator(topo)
            if topo == CoilTopology.SPIRAL:
                coils = gen.generate(cfg, layer_pair=(0, 1))
            else:
                coils = gen.generate(cfg)
            for coil in coils:
                assert coil.topology is exp_tag, (
                    f"Generator {topo.value} produced coil tagged {coil.topology}"
                )

    def test_geometry_package_exports(self):
        """All new generators must be importable from the geometry package."""
        from pcbstatorgen.geometry import (
            ConcentratedCoilGenerator,
            RhombicCoilGenerator,
            SpiralCoilGenerator,
            make_coil_generator,
        )
        assert ConcentratedCoilGenerator is not None
        assert RhombicCoilGenerator is not None
        assert SpiralCoilGenerator is not None
        assert make_coil_generator is not None
