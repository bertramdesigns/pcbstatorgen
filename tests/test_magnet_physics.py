"""
tests/test_magnet_physics.py
Tests for PR #3:
  - MagnetArray (all four MagnetArrangement values)
  - ForceEvaluator electrical angle (arrangement-invariant)
  - FrictionEstimator + BearingType
  - PowerEstimator
  - HeightStackCalculator

Slow tests (Magpylib getB / getFT calls) are marked @pytest.mark.slow.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from pcbstatorgen.config import (
    FrictionBudget,
    HeightStackResult,
    LinearMotorConfig,
    MagnetArrangement,
    PowerBudget,
    StackupResult,
)
from pcbstatorgen.magnetic.force_eval import ForceEvaluator
from pcbstatorgen.magnetic.magnet_model import MagnetArray, _K_IRON
from pcbstatorgen.stackup.friction import BearingType, FrictionEstimator
from pcbstatorgen.stackup.height_stack import HeightStackCalculator
from pcbstatorgen.stackup.power import PowerEstimator
from pcbstatorgen.units import mm, oz_to_m


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def alt_config(default_config) -> LinearMotorConfig:
    """Default config — ALTERNATING arrangement."""
    return default_config


@pytest.fixture
def halbach_config(default_config) -> LinearMotorConfig:
    return LinearMotorConfig(
        active_area_length_m=default_config.active_area_length_m,
        magnet_dims_m=default_config.magnet_dims_m,
        magnet_count=default_config.magnet_count,
        magnet_pitch_m=default_config.magnet_pitch_m,
        magnet_arrangement=MagnetArrangement.HALBACH,
    )


@pytest.fixture
def back_iron_config(default_config) -> LinearMotorConfig:
    return LinearMotorConfig(
        active_area_length_m=default_config.active_area_length_m,
        magnet_dims_m=default_config.magnet_dims_m,
        magnet_count=default_config.magnet_count,
        magnet_pitch_m=default_config.magnet_pitch_m,
        magnet_arrangement=MagnetArrangement.ALTERNATING_BACK_IRON,
        back_iron_thickness_m=mm(1),
    )


@pytest.fixture
def halbach_back_iron_config(default_config) -> LinearMotorConfig:
    return LinearMotorConfig(
        active_area_length_m=default_config.active_area_length_m,
        magnet_dims_m=default_config.magnet_dims_m,
        magnet_count=default_config.magnet_count,
        magnet_pitch_m=default_config.magnet_pitch_m,
        magnet_arrangement=MagnetArrangement.HALBACH_BACK_IRON,
        back_iron_thickness_m=mm(1),
    )


# ===========================================================================
# MagnetArray — construction (fast)
# ===========================================================================

class TestMagnetArrayConstruction:
    def test_alternating_collection_count(self, alt_config):
        arr = MagnetArray(alt_config)
        coll = arr.build_collection()
        assert len(coll.sources_all) == alt_config.magnet_count

    def test_halbach_more_magnets_than_alternating(self, halbach_config, alt_config):
        """Halbach adds interleave magnets → more total magnets."""
        arr_h = MagnetArray(halbach_config)
        arr_a = MagnetArray(alt_config)
        n_h = len(arr_h.build_collection().sources_all)
        n_a = len(arr_a.build_collection().sources_all)
        # Halbach has n_main + n_interleave = n + (n-1) = 2n-1
        assert n_h == 2 * alt_config.magnet_count - 1

    def test_back_iron_doubles_magnets(self, back_iron_config, alt_config):
        """ALTERNATING_BACK_IRON = main + images → 2 × main count."""
        arr = MagnetArray(back_iron_config)
        n = len(arr.build_collection().sources_all)
        assert n == alt_config.magnet_count * 2

    def test_halbach_back_iron_count(self, halbach_back_iron_config, alt_config):
        """HALBACH_BACK_IRON = (main + interleave) + images = 2×(2n-1)."""
        arr = MagnetArray(halbach_back_iron_config)
        n = len(arr.build_collection().sources_all)
        expected = 2 * (2 * alt_config.magnet_count - 1)
        assert n == expected

    def test_interleave_x_centers_alternating_empty(self, alt_config):
        arr = MagnetArray(alt_config)
        assert len(arr.interleave_x_centers_m()) == 0

    def test_interleave_x_centers_halbach_count(self, halbach_config):
        arr = MagnetArray(halbach_config)
        xs = arr.interleave_x_centers_m()
        assert len(xs) == halbach_config.magnet_count - 1

    def test_interleave_x_midpoints(self, halbach_config):
        """Interleave magnets are centred between main magnets."""
        arr = MagnetArray(halbach_config)
        main_xs = arr.magnet_x_centers_m()
        interleave_xs = arr.interleave_x_centers_m()
        for k, ix in enumerate(interleave_xs):
            expected = (main_xs[k] + main_xs[k + 1]) / 2.0
            assert ix == pytest.approx(expected, abs=1e-9)

    def test_image_z_center_above_original(self, back_iron_config):
        arr = MagnetArray(back_iron_config)
        assert arr.image_z_center_m() > arr.magnet_z_center_m()

    def test_image_z_center_formula(self, back_iron_config):
        cfg = back_iron_config
        arr = MagnetArray(cfg)
        z_mirror = cfg.air_gap_m + cfg.magnet_dims_m[2]
        z_original = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
        expected = 2 * z_mirror - z_original
        assert arr.image_z_center_m() == pytest.approx(expected)

    def test_sweep_collection_path_length(self, alt_config):
        arr = MagnetArray(alt_config)
        positions = np.linspace(0, alt_config.travel_m, 15)
        coll = arr.build_sweep_collection(positions)
        assert len(coll.position) == 15

    def test_sweep_requires_1d(self, alt_config):
        arr = MagnetArray(alt_config)
        with pytest.raises(ValueError, match="1-D"):
            arr.build_sweep_collection(np.zeros((3, 2)))


# ===========================================================================
# MagnetArray — field comparison (slow)
# ===========================================================================

class TestMagnetArrayFieldComparison:
    @pytest.mark.slow
    def test_halbach_higher_bz_than_alternating(self, alt_config, halbach_config):
        """Halbach should produce ≥ ALTERNATING field at the PCB surface."""
        xs = np.linspace(0, alt_config.coil_span_m, 30)
        B_alt    = MagnetArray(alt_config).bfield_at_pcb_surface(xs)
        B_halbach = MagnetArray(halbach_config).bfield_at_pcb_surface(xs)
        # Mean |Bz| should be higher for Halbach
        assert np.abs(B_halbach[:, 2]).mean() >= np.abs(B_alt[:, 2]).mean() * 0.99

    @pytest.mark.slow
    def test_back_iron_higher_bz_than_alternating(self, alt_config, back_iron_config):
        """Back-iron should boost field at PCB surface."""
        xs = np.linspace(0, alt_config.coil_span_m, 30)
        B_alt = MagnetArray(alt_config).bfield_at_pcb_surface(xs)
        B_bi  = MagnetArray(back_iron_config).bfield_at_pcb_surface(xs)
        assert np.abs(B_bi[:, 2]).mean() > np.abs(B_alt[:, 2]).mean() * 1.0

    @pytest.mark.slow
    def test_halbach_back_iron_highest_field(
        self, alt_config, halbach_config, back_iron_config, halbach_back_iron_config
    ):
        """HALBACH_BACK_IRON should give the highest mean |Bz|."""
        xs = np.linspace(0, alt_config.coil_span_m, 30)
        results = {}
        for cfg in [alt_config, halbach_config, back_iron_config, halbach_back_iron_config]:
            B = MagnetArray(cfg).bfield_at_pcb_surface(xs)
            results[cfg.magnet_arrangement] = np.abs(B[:, 2]).mean()
        assert results[MagnetArrangement.HALBACH_BACK_IRON] >= results[MagnetArrangement.ALTERNATING]

    @pytest.mark.slow
    def test_image_magnets_k_iron_applied(self, back_iron_config):
        """Image magnets should have polarization scaled by K_IRON."""
        import magpylib as magpy
        arr = MagnetArray(back_iron_config)
        coll = arr.build_collection()
        magnets = coll.sources_all
        br = back_iron_config.magnet_remanence_t
        # Image magnets are the second half — their |Bz| polarization should be br * K_IRON
        n_main = back_iron_config.magnet_count
        for mag in magnets[n_main:]:
            pol_z = abs(mag.polarization[2])
            assert pol_z == pytest.approx(br * _K_IRON, rel=1e-6)


# ===========================================================================
# ForceEvaluator — electrical angle (fast)
# ===========================================================================

class TestElectricalAngle:
    def test_angle_at_zero_position(self, alt_config):
        assert ForceEvaluator.electrical_angle(alt_config, 0.0) == pytest.approx(0.0)

    def test_angle_at_two_pole_pitches(self, alt_config):
        pos = 2.0 * alt_config.pole_pitch_m
        assert ForceEvaluator.electrical_angle(alt_config, pos) == pytest.approx(2 * math.pi)

    def test_electrical_angle_same_for_halbach(self, alt_config, halbach_config):
        """The electrical period is 2τ for both ALTERNATING and HALBACH."""
        pos = alt_config.travel_m / 2.0
        theta_alt    = ForceEvaluator.electrical_angle(alt_config, pos)
        theta_halbach = ForceEvaluator.electrical_angle(halbach_config, pos)
        assert theta_alt == pytest.approx(theta_halbach)

    def test_electrical_angle_same_for_back_iron(self, alt_config, back_iron_config):
        pos = alt_config.travel_m / 2.0
        assert ForceEvaluator.electrical_angle(alt_config, pos) == pytest.approx(
            ForceEvaluator.electrical_angle(back_iron_config, pos)
        )


# ===========================================================================
# FrictionEstimator
# ===========================================================================

class TestBearingType:
    def test_all_three_values_exist(self):
        assert BearingType.PLASTIC_CHANNEL
        assert BearingType.PTFE_LINED
        assert BearingType.BALL_BEARING

    def test_ball_bearing_lowest_friction(self, alt_config):
        """Ball bearing should produce lower friction than plastic channel."""
        est_plastic = FrictionEstimator(BearingType.PLASTIC_CHANNEL, normal_force_n=10.0)
        est_ball    = FrictionEstimator(BearingType.BALL_BEARING,    normal_force_n=10.0)
        b_p = est_plastic.estimate()
        b_b = est_ball.estimate()
        assert b_b.bearing_friction_n < b_p.bearing_friction_n


class TestFrictionEstimator:
    def test_constructs(self):
        est = FrictionEstimator()
        assert est is not None

    def test_estimate_returns_budget(self):
        est = FrictionEstimator()
        budget = est.estimate()
        assert isinstance(budget, FrictionBudget)

    def test_zero_normal_force_zero_bearing(self):
        est = FrictionEstimator(BearingType.PLASTIC_CHANNEL, normal_force_n=0.0)
        budget = est.estimate()
        assert budget.bearing_friction_n == pytest.approx(0.0)

    def test_nonzero_normal_force_nonzero_bearing(self):
        est = FrictionEstimator(BearingType.PTFE_LINED, normal_force_n=5.0)
        budget = est.estimate()
        assert budget.bearing_friction_n > 0

    def test_ffc_drag_scales_with_conductor_count(self):
        est_26 = FrictionEstimator(ffc_conductor_count=26)
        est_52 = FrictionEstimator(ffc_conductor_count=52)
        b26 = est_26.estimate()
        b52 = est_52.estimate()
        assert b52.cable_drag_n == pytest.approx(b26.cable_drag_n * 2.0)

    def test_zero_ffc_zero_cable_drag(self):
        est = FrictionEstimator(ffc_conductor_count=0)
        assert est.estimate().cable_drag_n == pytest.approx(0.0)

    def test_wiper_contact_adds_friction(self):
        est_no_wiper  = FrictionEstimator(has_wiper_contact=False)
        est_with_wiper = FrictionEstimator(has_wiper_contact=True)
        assert est_with_wiper.estimate().wiper_contact_n > 0
        assert est_no_wiper.estimate().wiper_contact_n == pytest.approx(0.0)

    def test_negative_normal_force_raises(self):
        with pytest.raises(ValueError, match="normal_force_n"):
            FrictionEstimator(normal_force_n=-1.0)

    def test_negative_ffc_raises(self):
        with pytest.raises(ValueError, match="ffc_conductor_count"):
            FrictionEstimator(ffc_conductor_count=-1)

    def test_from_config_no_back_iron_zero_normal(self, alt_config):
        est = FrictionEstimator.from_config(alt_config)
        assert est.normal_force_n == pytest.approx(0.0)

    def test_from_config_back_iron_nonzero_normal(self, back_iron_config):
        est = FrictionEstimator.from_config(back_iron_config)
        assert est.normal_force_n > 0.0

    def test_estimate_for_config_total_matches(self, alt_config):
        alt_config_with_friction = LinearMotorConfig(
            active_area_length_m=alt_config.active_area_length_m,
            magnet_dims_m=alt_config.magnet_dims_m,
            friction_n=0.1,
        )
        est = FrictionEstimator(BearingType.PTFE_LINED)
        budget = est.estimate_for_config(alt_config_with_friction)
        assert budget.total_n == pytest.approx(0.1, rel=0.01)

    def test_estimate_for_config_zero_friction(self, alt_config):
        cfg_zero = LinearMotorConfig(
            active_area_length_m=alt_config.active_area_length_m,
            magnet_dims_m=alt_config.magnet_dims_m,
            friction_n=0.0,
        )
        est = FrictionEstimator()
        budget = est.estimate_for_config(cfg_zero)
        assert budget.total_n == pytest.approx(0.0)


# ===========================================================================
# PowerEstimator
# ===========================================================================

class TestPowerEstimator:
    def test_constructs(self):
        assert PowerEstimator() is not None

    def test_invalid_layers_per_phase_raises(self):
        with pytest.raises(ValueError, match="layers_per_phase"):
            PowerEstimator(layers_per_phase=0)

    def test_estimate_returns_budget(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert isinstance(budget, PowerBudget)

    def test_resistance_positive(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert budget.phase_resistance_ohm > 0

    def test_continuous_power_positive(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert budget.continuous_power_w > 0

    def test_burst_power_ge_continuous(self, alt_config):
        """Burst current ≥ continuous current → burst power ≥ continuous."""
        budget = PowerEstimator().estimate(alt_config)
        assert budget.burst_power_w >= budget.continuous_power_w * 0.99

    def test_temperature_rise_positive(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert budget.temperature_rise_c > 0

    def test_capacitor_positive(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert budget.capacitor_required_uf > 0

    def test_efficiency_in_range(self, alt_config):
        budget = PowerEstimator().estimate(alt_config)
        assert 0.0 <= budget.efficiency_pct <= 100.0

    def test_higher_current_higher_power(self, alt_config):
        cfg_high = LinearMotorConfig(
            active_area_length_m=alt_config.active_area_length_m,
            magnet_dims_m=alt_config.magnet_dims_m,
            max_current_a=2.0,
        )
        budget_low  = PowerEstimator().estimate(alt_config)
        budget_high = PowerEstimator().estimate(cfg_high)
        assert budget_high.continuous_power_w > budget_low.continuous_power_w

    def test_with_stackup_result(self, alt_config, four_layer_stackup):
        budget = PowerEstimator().estimate(alt_config, stackup_result=four_layer_stackup)
        assert budget.phase_resistance_ohm > 0

    def test_custom_layers_per_phase(self, alt_config):
        b2 = PowerEstimator(layers_per_phase=2).estimate(alt_config)
        b4 = PowerEstimator(layers_per_phase=4).estimate(alt_config)
        # More layers per phase → longer total trace → higher resistance
        assert b4.phase_resistance_ohm > b2.phase_resistance_ohm


# ===========================================================================
# HeightStackCalculator
# ===========================================================================

class TestHeightStackCalculator:
    def test_constructs(self):
        assert HeightStackCalculator() is not None

    def test_invalid_copper_raises(self):
        with pytest.raises(ValueError, match="outer_copper_oz"):
            HeightStackCalculator(outer_copper_oz=0.0)

    def test_invalid_tolerance_raises(self):
        with pytest.raises(ValueError, match="tolerance_m"):
            HeightStackCalculator(tolerance_m=-0.001)

    def test_calculate_returns_result(self, alt_config):
        result = HeightStackCalculator().calculate(alt_config)
        assert isinstance(result, HeightStackResult)

    def test_total_height_is_sum(self, alt_config):
        calc = HeightStackCalculator()
        result = calc.calculate(alt_config)
        parts = (
            result.pcb_thickness_m
            + result.cu_protrusion_m
            + result.solder_mask_m
            + result.air_gap_m
            + result.magnet_height_m
            + result.back_iron_thickness_m
            + result.tolerance_m
        )
        assert result.total_height_m == pytest.approx(parts)

    def test_pcb_thickness_from_config(self, alt_config):
        result = HeightStackCalculator().calculate(alt_config)
        assert result.pcb_thickness_m == pytest.approx(alt_config.pcb_thickness_m)

    def test_air_gap_from_config(self, alt_config):
        result = HeightStackCalculator().calculate(alt_config)
        assert result.air_gap_m == pytest.approx(alt_config.air_gap_m)

    def test_magnet_height_from_config(self, alt_config):
        result = HeightStackCalculator().calculate(alt_config)
        assert result.magnet_height_m == pytest.approx(alt_config.magnet_dims_m[2])

    def test_back_iron_zero_when_no_back_iron(self, alt_config):
        result = HeightStackCalculator().calculate(alt_config)
        assert result.back_iron_thickness_m == pytest.approx(0.0)

    def test_back_iron_nonzero_when_configured(self, back_iron_config):
        result = HeightStackCalculator().calculate(back_iron_config)
        assert result.back_iron_thickness_m > 0

    def test_fits_in_budget_pass(self, alt_config):
        assert HeightStackCalculator().fits_in_budget(alt_config, mm(20))

    def test_fits_in_budget_fail(self, alt_config):
        assert not HeightStackCalculator().fits_in_budget(alt_config, mm(1))

    def test_headroom_positive_in_large_budget(self, alt_config):
        assert HeightStackCalculator().headroom_m(alt_config, mm(20)) > 0

    def test_headroom_negative_in_small_budget(self, alt_config):
        assert HeightStackCalculator().headroom_m(alt_config, mm(1)) < 0

    def test_max_air_gap_for_budget(self, alt_config):
        budget = mm(8)
        max_gap = HeightStackCalculator().max_air_gap_for_budget(alt_config, budget)
        assert max_gap >= 0.0

    def test_max_air_gap_consistent_with_fits(self, alt_config):
        """Config with air_gap = max_air_gap should just fit in the budget."""
        calc = HeightStackCalculator()
        budget = mm(8)
        max_gap = calc.max_air_gap_for_budget(alt_config, budget)
        cfg_at_limit = LinearMotorConfig(
            active_area_length_m=alt_config.active_area_length_m,
            magnet_dims_m=alt_config.magnet_dims_m,
            air_gap_m=max_gap,
        )
        assert calc.fits_in_budget(cfg_at_limit, budget)

    def test_field_sensitivity_negative(self, alt_config):
        """Field decreases with increasing air gap → negative sensitivity."""
        s = HeightStackCalculator.field_sensitivity_per_mm(alt_config)
        assert s < 0

    def test_field_sensitivity_magnitude(self, alt_config):
        """For τ=12mm: sensitivity ≈ -π/12 per mm ≈ -0.26/mm."""
        s = HeightStackCalculator.field_sensitivity_per_mm(alt_config)
        expected = -(math.pi / alt_config.pole_pitch_m) * 1e-3
        assert s == pytest.approx(expected)

    def test_field_at_gap_decreases_with_larger_gap(self, alt_config):
        bz_small = HeightStackCalculator.field_at_gap(alt_config, mm(0.3))
        bz_large = HeightStackCalculator.field_at_gap(alt_config, mm(1.5))
        assert bz_small > bz_large

    def test_field_at_gap_positive(self, alt_config):
        assert HeightStackCalculator.field_at_gap(alt_config, mm(0.5)) > 0

    def test_2oz_copper_thicker_protrusion(self, alt_config):
        calc_1oz = HeightStackCalculator(outer_copper_oz=1.0)
        calc_2oz = HeightStackCalculator(outer_copper_oz=2.0)
        r1 = calc_1oz.calculate(alt_config)
        r2 = calc_2oz.calculate(alt_config)
        assert r2.cu_protrusion_m > r1.cu_protrusion_m
        assert r2.total_height_m > r1.total_height_m

    def test_stackup_exports_importable(self):
        from pcbstatorgen.stackup import (
            BearingType, FrictionEstimator, HeightStackCalculator, PowerEstimator
        )
        assert HeightStackCalculator is not None
