"""
tests/test_units.py — unit tests for pcbstatorgen.units
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.units import (
    mm,
    um,
    mils_to_m,
    m_to_mm,
    m_to_um,
    m_to_mils,
    mt_to_t,
    t_to_mt,
    oz_to_m,
    m_to_oz,
    skin_depth_m,
    cu_resistance_per_length,
    STANDARD_CU_WEIGHTS,
    RHO_CU,
    MU_0,
)


# ---------------------------------------------------------------------------
# Length conversions
# ---------------------------------------------------------------------------


class TestLengthConversions:
    def test_mm_to_m(self):
        assert mm(1.0) == pytest.approx(0.001)
        assert mm(0.0) == pytest.approx(0.0)
        assert mm(100.0) == pytest.approx(0.1)

    def test_um_to_m(self):
        assert um(1.0) == pytest.approx(1e-6)
        assert um(35.0) == pytest.approx(35e-6)

    def test_mils_to_m(self):
        assert mils_to_m(1.0) == pytest.approx(25.4e-6)
        assert mils_to_m(5.0) == pytest.approx(127e-6)
        assert mils_to_m(10.0) == pytest.approx(254e-6)

    def test_m_to_mm(self):
        assert m_to_mm(0.001) == pytest.approx(1.0)
        assert m_to_mm(0.075) == pytest.approx(75.0)

    def test_m_to_um(self):
        assert m_to_um(35e-6) == pytest.approx(35.0)
        assert m_to_um(1e-3) == pytest.approx(1000.0)

    def test_m_to_mils(self):
        assert m_to_mils(25.4e-6) == pytest.approx(1.0)
        assert m_to_mils(127e-6) == pytest.approx(5.0)

    def test_round_trip_mm(self):
        for val in [0.5, 1.0, 10.0, 75.0, 127.0]:
            assert m_to_mm(mm(val)) == pytest.approx(val, rel=1e-10)

    def test_round_trip_mils(self):
        for val in [1.0, 5.0, 8.0, 10.0]:
            assert m_to_mils(mils_to_m(val)) == pytest.approx(val, rel=1e-10)


# ---------------------------------------------------------------------------
# Magnetic flux density conversions
# ---------------------------------------------------------------------------


class TestFluxDensity:
    def test_mt_to_t(self):
        assert mt_to_t(1000.0) == pytest.approx(1.0)
        assert mt_to_t(500.0) == pytest.approx(0.5)
        assert mt_to_t(1350.0) == pytest.approx(1.35)

    def test_t_to_mt(self):
        assert t_to_mt(1.0) == pytest.approx(1000.0)
        assert t_to_mt(1.35) == pytest.approx(1350.0)

    def test_round_trip(self):
        for val in [0.1, 0.5, 1.0, 1.35, 2.0]:
            assert t_to_mt(mt_to_t(val * 1e3)) == pytest.approx(val * 1e3, rel=1e-10)


# ---------------------------------------------------------------------------
# Copper weight / thickness
# ---------------------------------------------------------------------------


class TestCopperWeight:
    def test_oz_to_m_one_oz(self):
        assert oz_to_m(1.0) == pytest.approx(35e-6)

    def test_oz_to_m_two_oz(self):
        assert oz_to_m(2.0) == pytest.approx(70e-6)

    def test_oz_to_m_half_oz(self):
        assert oz_to_m(0.5) == pytest.approx(17.5e-6)

    def test_oz_to_m_four_oz(self):
        assert oz_to_m(4.0) == pytest.approx(140e-6)

    def test_m_to_oz_round_trip(self):
        for oz in [0.5, 1.0, 2.0, 3.0, 4.0]:
            assert m_to_oz(oz_to_m(oz)) == pytest.approx(oz, rel=1e-10)

    def test_standard_weights_complete(self):
        ozs = [cw.oz for cw in STANDARD_CU_WEIGHTS]
        assert 0.5 in ozs
        assert 1.0 in ozs
        assert 2.0 in ozs
        assert 4.0 in ozs

    def test_standard_weights_thicknesses(self):
        for cw in STANDARD_CU_WEIGHTS:
            assert cw.thickness_m == pytest.approx(oz_to_m(cw.oz))

    def test_standard_weights_labels_nonempty(self):
        for cw in STANDARD_CU_WEIGHTS:
            assert cw.label


# ---------------------------------------------------------------------------
# Skin depth
# ---------------------------------------------------------------------------


class TestSkinDepth:
    def test_positive_frequency(self):
        delta = skin_depth_m(1000.0)
        assert delta > 0

    def test_skin_depth_increases_with_lower_frequency(self):
        delta_high = skin_depth_m(10_000.0)
        delta_low = skin_depth_m(100.0)
        assert delta_low > delta_high

    def test_skin_depth_formula(self):
        f = 1000.0
        expected = math.sqrt(RHO_CU / (math.pi * f * MU_0))
        assert skin_depth_m(f) == pytest.approx(expected, rel=1e-9)

    def test_skin_depth_1MHz_approx_66um(self):
        # δ(Cu, 1 MHz) ≈ 66 µm — known reference value
        # (Note: at 1 kHz, δ ≈ 2.09 mm; the 66 µm figure is at 1 MHz)
        assert skin_depth_m(1e6) == pytest.approx(66.1e-6, rel=0.01)

    def test_skin_depth_10MHz_approx_21um(self):
        # δ(Cu, 10 MHz) ≈ 20.9 µm
        assert skin_depth_m(1e7) == pytest.approx(20.9e-6, rel=0.01)

    def test_skin_depth_1kHz_approx_2mm(self):
        # δ(Cu, 1 kHz) ≈ 2.09 mm — skin effects negligible for low-speed fader drive
        assert skin_depth_m(1000.0) == pytest.approx(2.09e-3, rel=0.01)

    def test_zero_frequency_raises(self):
        with pytest.raises(ValueError, match="frequency_hz must be positive"):
            skin_depth_m(0.0)

    def test_negative_frequency_raises(self):
        with pytest.raises(ValueError, match="frequency_hz must be positive"):
            skin_depth_m(-500.0)

    def test_custom_rho(self):
        # Aluminium: ρ ≈ 2.82e-8 Ω·m — skin depth should be larger than copper
        delta_cu = skin_depth_m(1000.0, rho=RHO_CU)
        delta_al = skin_depth_m(1000.0, rho=2.82e-8)
        assert delta_al > delta_cu

    def test_outer_layer_1oz_thinner_than_delta_at_1MHz(self):
        """1 oz copper (35 µm) is thinner than skin depth at 1 MHz.

        At 1 MHz (PWM high-frequency harmonics), δ ≈ 66 µm > 35 µm, so the
        full 1 oz outer layer participates in current conduction with reduced
        AC loss.  This is the rationale for thinner copper on outer layers.
        """
        delta = skin_depth_m(1e6)
        assert oz_to_m(1.0) < delta

    def test_outer_layer_2oz_thicker_than_delta_at_1MHz(self):
        """2 oz copper (70 µm) is thicker than skin depth at 1 MHz.

        At 1 MHz, δ ≈ 66 µm < 70 µm: a 2 oz outer layer would have mild skin
        effect losses.  This demonstrates why inner layers should stay at 2oz
        or above while outer layers are held to 1 oz for AC performance.
        """
        delta = skin_depth_m(1e6)
        assert oz_to_m(2.0) > delta

    def test_all_layers_thinner_than_delta_at_500hz(self):
        """At 500 Hz (low-speed mechanical frequency), δ ≈ 2.95 mm.

        All practical PCB copper layers (up to 4 oz = 140 µm) are far thinner
        than the skin depth at the base motor drive frequency, meaning eddy
        current losses from the fundamental are negligible.
        """
        delta = skin_depth_m(500.0)
        for oz in [0.5, 1.0, 2.0, 3.0, 4.0]:
            assert oz_to_m(oz) < delta


# ---------------------------------------------------------------------------
# DC resistance per unit length
# ---------------------------------------------------------------------------


class TestCuResistancePerLength:
    def test_basic_value(self):
        # 0.2 mm × 35 µm trace in copper
        r = cu_resistance_per_length(0.2e-3, oz_to_m(1.0))
        expected = RHO_CU / (0.2e-3 * 35e-6)
        assert r == pytest.approx(expected, rel=1e-9)

    def test_wider_trace_lower_resistance(self):
        r_narrow = cu_resistance_per_length(0.1e-3, oz_to_m(1.0))
        r_wide = cu_resistance_per_length(0.3e-3, oz_to_m(1.0))
        assert r_narrow > r_wide

    def test_thicker_cu_lower_resistance(self):
        r_thin = cu_resistance_per_length(0.2e-3, oz_to_m(1.0))
        r_thick = cu_resistance_per_length(0.2e-3, oz_to_m(2.0))
        assert r_thin > r_thick

    def test_zero_width_raises(self):
        with pytest.raises(ValueError, match="width_m must be positive"):
            cu_resistance_per_length(0.0, oz_to_m(1.0))

    def test_negative_width_raises(self):
        with pytest.raises(ValueError, match="width_m must be positive"):
            cu_resistance_per_length(-1e-3, oz_to_m(1.0))

    def test_zero_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness_m must be positive"):
            cu_resistance_per_length(0.2e-3, 0.0)

    def test_units_ohm_per_meter(self):
        # For a 1 mm × 35 µm trace, R' = ρ / (1e-3 * 35e-6) ≈ 0.493 Ω/m
        r = cu_resistance_per_length(1e-3, 35e-6)
        assert r == pytest.approx(RHO_CU / (1e-3 * 35e-6), rel=1e-9)
