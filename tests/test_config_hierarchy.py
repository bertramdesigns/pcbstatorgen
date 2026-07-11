"""
tests/test_config_hierarchy.py
Tests for Phase A additions:
  - MagnetArrangement and CoilTopology enums
  - BaseMotorConfig / LinearMotorConfig class hierarchy
  - AxialMotorConfig stub (NotImplementedError)
  - New LinearMotorConfig fields: peak_force_n, friction_n, supply_voltage_v, etc.
  - HeightStackResult, FrictionBudget, PowerBudget dataclasses
  - New validation rules (assembly gap, peak >= continuous, supply_voltage > 0)
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import (
    AxialMotorConfig,
    BaseMotorConfig,
    CoilTopology,
    FrictionBudget,
    HeightStackResult,
    LinearMotorConfig,
    MagnetArrangement,
    MotorConfig,
    PowerBudget,
)
from pcbstatorgen.units import mm, mils_to_m, oz_to_m


# ===========================================================================
# MagnetArrangement enum
# ===========================================================================


class TestMagnetArrangement:
    def test_all_four_values_exist(self):
        assert MagnetArrangement.ALTERNATING
        assert MagnetArrangement.ALTERNATING_BACK_IRON
        assert MagnetArrangement.HALBACH
        assert MagnetArrangement.HALBACH_BACK_IRON

    def test_default_is_alternating(self, default_config):
        assert default_config.magnet_arrangement is MagnetArrangement.ALTERNATING

    def test_can_set_halbach(self):
        cfg = LinearMotorConfig(
            travel_m=mm(75),
            magnet_arrangement=MagnetArrangement.HALBACH,
        )
        assert cfg.magnet_arrangement is MagnetArrangement.HALBACH

    def test_can_set_halbach_back_iron(self):
        cfg = LinearMotorConfig(
            travel_m=mm(75),
            magnet_arrangement=MagnetArrangement.HALBACH_BACK_IRON,
            back_iron_thickness_m=mm(1),
        )
        assert cfg.magnet_arrangement is MagnetArrangement.HALBACH_BACK_IRON

    def test_summary_shows_arrangement(self):
        for arr, expected_text in [
            (MagnetArrangement.ALTERNATING, "alternating poles"),
            (MagnetArrangement.HALBACH, "Halbach array"),
            (MagnetArrangement.ALTERNATING_BACK_IRON, "back-iron"),
            (MagnetArrangement.HALBACH_BACK_IRON, "Halbach"),
        ]:
            cfg = LinearMotorConfig(travel_m=mm(75), magnet_arrangement=arr)
            assert expected_text in cfg.summary()


# ===========================================================================
# CoilTopology enum
# ===========================================================================


class TestCoilTopology:
    def test_all_four_values_exist(self):
        assert CoilTopology.SERPENTINE
        assert CoilTopology.CONCENTRATED
        assert CoilTopology.RHOMBIC
        assert CoilTopology.SPIRAL

    def test_string_values(self):
        assert CoilTopology.SERPENTINE.value == "serpentine"
        assert CoilTopology.CONCENTRATED.value == "concentrated"
        assert CoilTopology.RHOMBIC.value == "rhombic"
        assert CoilTopology.SPIRAL.value == "spiral"

    def test_default_is_serpentine(self, default_config):
        assert default_config.coil_topology is CoilTopology.SERPENTINE

    def test_can_set_concentrated(self):
        cfg = LinearMotorConfig(travel_m=mm(75), coil_topology=CoilTopology.CONCENTRATED)
        assert cfg.coil_topology is CoilTopology.CONCENTRATED

    def test_can_set_rhombic(self):
        cfg = LinearMotorConfig(travel_m=mm(75), coil_topology=CoilTopology.RHOMBIC)
        assert cfg.coil_topology is CoilTopology.RHOMBIC

    def test_can_set_spiral(self):
        cfg = LinearMotorConfig(travel_m=mm(75), coil_topology=CoilTopology.SPIRAL)
        assert cfg.coil_topology is CoilTopology.SPIRAL

    def test_summary_shows_topology(self):
        for topo in CoilTopology:
            cfg = LinearMotorConfig(travel_m=mm(75), coil_topology=topo)
            assert topo.value in cfg.summary()


# ===========================================================================
# Class hierarchy and alias
# ===========================================================================


class TestClassHierarchy:
    def test_linear_is_subclass_of_base(self):
        assert issubclass(LinearMotorConfig, BaseMotorConfig)

    def test_axial_is_subclass_of_base(self):
        assert issubclass(AxialMotorConfig, BaseMotorConfig)

    def test_motor_config_alias_is_linear(self):
        assert MotorConfig is LinearMotorConfig

    def test_existing_construction_via_alias(self, default_config):
        """All existing code using MotorConfig(...) must continue to work."""
        assert isinstance(default_config, LinearMotorConfig)
        assert isinstance(default_config, BaseMotorConfig)

    def test_linear_config_is_instance_of_base(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert isinstance(cfg, BaseMotorConfig)


# ===========================================================================
# LinearMotorConfig — new fields
# ===========================================================================


class TestLinearMotorConfigNewFields:
    def test_peak_force_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.peak_force_n == pytest.approx(1.0)

    def test_friction_n_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.friction_n == pytest.approx(0.05)

    def test_supply_voltage_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.supply_voltage_v == pytest.approx(5.0)

    def test_pcb_thickness_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.pcb_thickness_m == pytest.approx(0.0016)

    def test_carriage_mass_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.carriage_mass_kg == pytest.approx(0.015)

    def test_max_accel_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.max_accel_m_s2 == pytest.approx(2.0)

    def test_capacitor_bank_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.capacitor_bank_uf == pytest.approx(1000.0)

    def test_max_temperature_rise_default(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.max_temperature_rise_c == pytest.approx(20.0)

    def test_back_iron_thickness_default_zero(self):
        cfg = LinearMotorConfig(travel_m=mm(75))
        assert cfg.back_iron_thickness_m == pytest.approx(0.0)

    def test_custom_peak_force(self):
        cfg = LinearMotorConfig(travel_m=mm(75), target_force_n=0.3, peak_force_n=0.8)
        assert cfg.peak_force_n == pytest.approx(0.8)

    def test_custom_friction(self):
        cfg = LinearMotorConfig(travel_m=mm(75), friction_n=0.12)
        assert cfg.friction_n == pytest.approx(0.12)

    def test_custom_supply_voltage(self):
        cfg = LinearMotorConfig(travel_m=mm(75), supply_voltage_v=12.0)
        assert cfg.supply_voltage_v == pytest.approx(12.0)


# ===========================================================================
# LinearMotorConfig — derived properties (new)
# ===========================================================================


class TestLinearMotorConfigDerivedNew:
    def test_acceleration_force(self):
        cfg = LinearMotorConfig(
            travel_m=mm(75), carriage_mass_kg=0.015, max_accel_m_s2=2.0
        )
        assert cfg.acceleration_force_n == pytest.approx(0.030)

    def test_minimum_drive_force_is_friction_times_margin(self):
        cfg = LinearMotorConfig(travel_m=mm(75), friction_n=0.1)
        assert cfg.minimum_drive_force_n == pytest.approx(0.1 * 1.3)

    def test_minimum_drive_force_zero_friction(self):
        cfg = LinearMotorConfig(travel_m=mm(75), friction_n=0.0)
        assert cfg.minimum_drive_force_n == pytest.approx(0.0)

    def test_coil_span(self, default_config):
        expected = default_config.magnet_count * default_config.magnet_pitch_m
        assert default_config.coil_span_m == pytest.approx(expected)

    def test_active_length(self, default_config):
        expected = default_config.travel_m + default_config.coil_span_m
        assert default_config.active_length_m == pytest.approx(expected)


# ===========================================================================
# LinearMotorConfig — new validation
# ===========================================================================


class TestLinearMotorConfigNewValidation:
    def test_peak_force_less_than_continuous_raises(self):
        with pytest.raises(ValueError, match="peak_force_n"):
            LinearMotorConfig(
                travel_m=mm(75),
                target_force_n=0.5,
                peak_force_n=0.3,  # less than continuous
            )

    def test_peak_force_equal_to_continuous_allowed(self):
        cfg = LinearMotorConfig(
            travel_m=mm(75), target_force_n=0.5, peak_force_n=0.5
        )
        assert cfg.peak_force_n == pytest.approx(0.5)

    def test_zero_supply_voltage_raises(self):
        with pytest.raises(ValueError, match="supply_voltage_v"):
            LinearMotorConfig(travel_m=mm(75), supply_voltage_v=0.0)

    def test_negative_friction_raises(self):
        with pytest.raises(ValueError, match="friction_n"):
            LinearMotorConfig(travel_m=mm(75), friction_n=-0.01)

    def test_negative_back_iron_raises(self):
        with pytest.raises(ValueError, match="back_iron_thickness_m"):
            LinearMotorConfig(travel_m=mm(75), back_iron_thickness_m=-mm(1))

    def test_assembly_gap_negative_raises(self):
        """magnet_pitch < magnet_width → magnets overlap → should raise."""
        with pytest.raises(ValueError, match="magnet_pitch_m"):
            LinearMotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(13), mm(10), mm(4)),  # width > pitch → overlap
                magnet_pitch_m=mm(12),
            )

    def test_assembly_gap_zero_allowed(self):
        """Gap = 0 mm (edge-to-edge) is physically valid and must be accepted."""
        cfg = LinearMotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(12), mm(10), mm(4)),
            magnet_pitch_m=mm(12),   # width == pitch → gap = 0
        )
        assert cfg.magnet_pitch_m - cfg.magnet_dims_m[0] == pytest.approx(0.0, abs=1e-9)

    def test_small_positive_gap_allowed(self):
        """Any gap ≥ 0 should be accepted, including sub-mm values."""
        cfg = LinearMotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(11.9), mm(10), mm(4)),
            magnet_pitch_m=mm(12),   # gap = 0.1 mm
        )
        assert cfg.magnet_pitch_m - cfg.magnet_dims_m[0] == pytest.approx(mm(0.1), abs=1e-9)

    def test_zero_travel_raises(self):
        with pytest.raises(ValueError, match="travel_m"):
            LinearMotorConfig(travel_m=0.0)

    def test_negative_pcb_thickness_raises(self):
        with pytest.raises(ValueError, match="pcb_thickness_m"):
            LinearMotorConfig(travel_m=mm(75), pcb_thickness_m=-0.001)


# ===========================================================================
# AxialMotorConfig stub
# ===========================================================================


class TestAxialMotorConfigStub:
    def test_instantiation_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            AxialMotorConfig(stator_OD_m=mm(80))

    def test_error_message_mentions_issue(self):
        with pytest.raises(NotImplementedError, match="GitHub Issue"):
            AxialMotorConfig()

    def test_is_subclass_of_base(self):
        assert issubclass(AxialMotorConfig, BaseMotorConfig)


# ===========================================================================
# HeightStackResult
# ===========================================================================


class TestHeightStackResult:
    @pytest.fixture
    def typical_stack(self) -> HeightStackResult:
        return HeightStackResult(
            pcb_thickness_m=0.0016,
            cu_protrusion_m=oz_to_m(1.0),
            solder_mask_m=20e-6,
            air_gap_m=mm(0.5),
            magnet_height_m=mm(4.0),
            back_iron_thickness_m=mm(1.0),
            tolerance_m=mm(0.3),
        )

    def test_total_height(self, typical_stack):
        expected = (
            0.0016 + oz_to_m(1.0) + 20e-6 + mm(0.5) + mm(4.0) + mm(1.0) + mm(0.3)
        )
        assert typical_stack.total_height_m == pytest.approx(expected)

    def test_fits_in_budget_pass(self, typical_stack):
        assert typical_stack.fits_in_budget(mm(10)) is True

    def test_fits_in_budget_fail(self, typical_stack):
        assert typical_stack.fits_in_budget(mm(5)) is False

    def test_headroom_positive(self, typical_stack):
        assert typical_stack.headroom_m(mm(10)) > 0

    def test_headroom_negative_when_over_budget(self, typical_stack):
        assert typical_stack.headroom_m(mm(4)) < 0

    def test_zero_back_iron_allowed(self):
        s = HeightStackResult(
            pcb_thickness_m=0.0016,
            cu_protrusion_m=35e-6,
            solder_mask_m=20e-6,
            air_gap_m=mm(0.5),
            magnet_height_m=mm(4.0),
            back_iron_thickness_m=0.0,  # no back-iron
            tolerance_m=mm(0.3),
        )
        assert s.back_iron_thickness_m == 0.0

    def test_negative_air_gap_raises(self):
        with pytest.raises(ValueError, match="air_gap_m"):
            HeightStackResult(
                pcb_thickness_m=0.0016,
                cu_protrusion_m=35e-6,
                solder_mask_m=20e-6,
                air_gap_m=-0.001,
                magnet_height_m=mm(4),
                back_iron_thickness_m=0.0,
                tolerance_m=mm(0.3),
            )

    def test_summary_is_string(self, typical_stack):
        s = typical_stack.summary()
        assert isinstance(s, str) and "Total height" in s

    def test_summary_shows_back_iron_when_present(self, typical_stack):
        assert "Back-iron" in typical_stack.summary()

    def test_summary_no_back_iron_line_when_zero(self):
        s = HeightStackResult(
            pcb_thickness_m=0.0016,
            cu_protrusion_m=35e-6,
            solder_mask_m=20e-6,
            air_gap_m=mm(0.5),
            magnet_height_m=mm(4),
            back_iron_thickness_m=0.0,
            tolerance_m=mm(0.3),
        )
        assert "Back-iron" not in s.summary()


# ===========================================================================
# FrictionBudget
# ===========================================================================


class TestFrictionBudget:
    @pytest.fixture
    def ball_bearing_budget(self) -> FrictionBudget:
        return FrictionBudget(
            bearing_friction_n=0.035,
            cable_drag_n=0.020,
            wiper_contact_n=0.0,
            cogging_n=0.002,
        )

    def test_total_n(self, ball_bearing_budget):
        expected = 0.035 + 0.020 + 0.0 + 0.002
        assert ball_bearing_budget.total_n == pytest.approx(expected)

    def test_minimum_drive_force_is_total_times_margin(self, ball_bearing_budget):
        assert ball_bearing_budget.minimum_drive_force_n == pytest.approx(
            ball_bearing_budget.total_n * 1.3
        )

    def test_zero_friction_allowed(self):
        fb = FrictionBudget(
            bearing_friction_n=0.0,
            cable_drag_n=0.0,
            wiper_contact_n=0.0,
            cogging_n=0.0,
        )
        assert fb.total_n == pytest.approx(0.0)

    def test_negative_bearing_raises(self):
        with pytest.raises(ValueError, match="bearing_friction_n"):
            FrictionBudget(
                bearing_friction_n=-0.01,
                cable_drag_n=0.0,
                wiper_contact_n=0.0,
            )

    def test_summary_is_string(self, ball_bearing_budget):
        s = ball_bearing_budget.summary()
        assert isinstance(s, str) and "Total" in s

    def test_summary_shows_minimum_drive_force(self, ball_bearing_budget):
        assert "Min drive" in ball_bearing_budget.summary()

    def test_wiper_default_zero(self):
        fb = FrictionBudget(bearing_friction_n=0.05, cable_drag_n=0.02)
        assert fb.wiper_contact_n == pytest.approx(0.0)

    def test_cogging_default_zero(self):
        fb = FrictionBudget(bearing_friction_n=0.05, cable_drag_n=0.02)
        assert fb.cogging_n == pytest.approx(0.0)

    def test_with_wiper_contact(self):
        fb = FrictionBudget(
            bearing_friction_n=0.05,
            cable_drag_n=0.02,
            wiper_contact_n=0.06,
        )
        assert fb.total_n == pytest.approx(0.05 + 0.02 + 0.06)


# ===========================================================================
# PowerBudget
# ===========================================================================


class TestPowerBudget:
    @pytest.fixture
    def typical_power(self) -> PowerBudget:
        return PowerBudget(
            phase_resistance_ohm=2.1,
            continuous_power_w=0.63,
            burst_power_w=3.6,
            temperature_rise_c=14.0,
            capacitor_required_uf=800.0,
            efficiency_pct=2.5,
        )

    def test_constructs(self, typical_power):
        assert typical_power.phase_resistance_ohm == pytest.approx(2.1)

    def test_summary_is_string(self, typical_power):
        s = typical_power.summary()
        assert isinstance(s, str) and "Efficiency" in s

    def test_negative_resistance_raises(self):
        with pytest.raises(ValueError, match="phase_resistance_ohm"):
            PowerBudget(
                phase_resistance_ohm=-1.0,
                continuous_power_w=0.5,
                burst_power_w=2.0,
                temperature_rise_c=15.0,
                capacitor_required_uf=1000.0,
                efficiency_pct=3.0,
            )

    def test_efficiency_over_100_raises(self):
        with pytest.raises(ValueError, match="efficiency_pct"):
            PowerBudget(
                phase_resistance_ohm=2.0,
                continuous_power_w=0.5,
                burst_power_w=2.0,
                temperature_rise_c=15.0,
                capacitor_required_uf=1000.0,
                efficiency_pct=101.0,
            )

    def test_zero_values_allowed(self):
        pb = PowerBudget(
            phase_resistance_ohm=0.0,
            continuous_power_w=0.0,
            burst_power_w=0.0,
            temperature_rise_c=0.0,
            capacitor_required_uf=0.0,
            efficiency_pct=0.0,
        )
        assert pb.continuous_power_w == pytest.approx(0.0)

    def test_100_pct_efficiency_allowed(self):
        pb = PowerBudget(
            phase_resistance_ohm=0.0,
            continuous_power_w=0.0,
            burst_power_w=0.0,
            temperature_rise_c=0.0,
            capacitor_required_uf=0.0,
            efficiency_pct=100.0,
        )
        assert pb.efficiency_pct == pytest.approx(100.0)


# ===========================================================================
# Top-level import sanity
# ===========================================================================


class TestImports:
    def test_all_new_names_importable_from_package(self):
        from pcbstatorgen import (
            AxialMotorConfig,
            BaseMotorConfig,
            CoilTopology,
            FrictionBudget,
            HeightStackResult,
            LinearMotorConfig,
            MagnetArrangement,
            MotorConfig,
            PowerBudget,
        )
        assert MotorConfig is LinearMotorConfig

    def test_version_bumped(self):
        import pcbstatorgen
        major, minor, *_ = pcbstatorgen.__version__.split(".")
        assert int(minor) >= 2  # 0.2.0 or higher
