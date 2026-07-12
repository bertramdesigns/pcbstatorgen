"""
tests/test_config.py — unit tests for MotorConfig and StackupResult
"""

from __future__ import annotations

import math
import pytest

from pcbstatorgen.config import MotorConfig, StackupResult
from pcbstatorgen.units import mm, mils_to_m, oz_to_m


# ===========================================================================
# MotorConfig
# ===========================================================================


class TestMotorConfigConstruction:
    def test_default_config_constructs(self, default_config):
        assert default_config is not None

    def test_minimal_config_constructs(self, minimal_config):
        assert minimal_config is not None

    def test_name_stored(self):
        cfg = MotorConfig(
            name="my-actuator",
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
            magnet_count=10,
            magnet_pitch_m=mm(12),
        )
        assert cfg.name == "my-actuator"

    def test_name_optional(self):
        cfg = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert cfg.name is None

    def test_default_phases(self):
        cfg = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert cfg.phases == 3

    def test_default_magnet_count(self):
        cfg = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert cfg.magnet_count == 10

    def test_default_max_layers_is_even(self):
        cfg = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert cfg.max_layers % 2 == 0


class TestMotorConfigValidation:
    def _base_kwargs(self):
        return dict(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
            magnet_count=10,
            magnet_pitch_m=mm(12),
        )

    def test_zero_travel_raises(self):
        with pytest.raises(ValueError, match="travel_m must be positive"):
            MotorConfig(travel_m=0.0, magnet_dims_m=(mm(10), mm(10), mm(4)))

    def test_negative_travel_raises(self):
        with pytest.raises(ValueError, match="travel_m must be positive"):
            MotorConfig(travel_m=-mm(10), magnet_dims_m=(mm(10), mm(10), mm(4)))

    def test_wrong_magnet_dims_length_raises(self):
        with pytest.raises(ValueError, match="magnet_dims_m must be a 3-tuple"):
            MotorConfig(travel_m=mm(75), magnet_dims_m=(mm(10), mm(10)))

    def test_zero_magnet_dim_raises(self):
        with pytest.raises(ValueError, match="All magnet dimensions must be positive"):
            MotorConfig(travel_m=mm(75), magnet_dims_m=(0.0, mm(10), mm(4)))

    def test_odd_magnet_count_raises(self):
        with pytest.raises(ValueError, match="magnet_count must be even"):
            MotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(10), mm(10), mm(4)),
                magnet_count=9,
            )

    def test_magnet_count_one_raises(self):
        with pytest.raises(ValueError):
            MotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(10), mm(10), mm(4)),
                magnet_count=1,
            )

    def test_pitch_smaller_than_magnet_width_raises(self):
        with pytest.raises(ValueError, match="magnet_pitch_m"):
            MotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(15), mm(10), mm(4)),
                magnet_pitch_m=mm(12),  # 12 mm < 15 mm magnet width
            )

    def test_unrealistic_remanence_raises(self):
        with pytest.raises(ValueError, match="magnet_remanence_t"):
            MotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(10), mm(10), mm(4)),
                magnet_remanence_t=3.0,  # above physical limit
            )

    def test_zero_remanence_raises(self):
        with pytest.raises(ValueError, match="magnet_remanence_t"):
            MotorConfig(
                travel_m=mm(75),
                magnet_dims_m=(mm(10), mm(10), mm(4)),
                magnet_remanence_t=0.0,
            )

    def test_zero_target_force_raises(self):
        with pytest.raises(ValueError, match="target_force_n must be positive"):
            MotorConfig(
                **self._base_kwargs(),
                target_force_n=0.0,
            )

    def test_zero_current_raises(self):
        with pytest.raises(ValueError, match="max_current_a must be positive"):
            MotorConfig(**self._base_kwargs(), max_current_a=0.0)

    def test_zero_trace_raises(self):
        with pytest.raises(ValueError, match="min_trace_m must be positive"):
            MotorConfig(**self._base_kwargs(), min_trace_m=0.0)

    def test_zero_via_drill_raises(self):
        with pytest.raises(ValueError, match="min_via_drill_m must be positive"):
            MotorConfig(**self._base_kwargs(), min_via_drill_m=0.0)

    def test_negative_air_gap_raises(self):
        with pytest.raises(ValueError, match="air_gap_m must be ≥ 0"):
            MotorConfig(**self._base_kwargs(), air_gap_m=-mm(0.1))

    def test_odd_max_layers_raises(self):
        with pytest.raises(ValueError, match="max_layers must be an even number"):
            MotorConfig(**self._base_kwargs(), max_layers=5)

    def test_max_layers_zero_raises(self):
        with pytest.raises(ValueError, match="max_layers must be an even number"):
            MotorConfig(**self._base_kwargs(), max_layers=0)

    def test_zero_drive_frequency_raises(self):
        with pytest.raises(ValueError, match="drive_frequency_hz must be positive"):
            MotorConfig(**self._base_kwargs(), drive_frequency_hz=0.0)

    def test_zero_board_width_raises(self):
        with pytest.raises(ValueError, match="board_width_m must be positive"):
            MotorConfig(**self._base_kwargs(), board_width_m=0.0)


class TestMotorConfigDerivedProperties:
    def test_pole_pitch_equals_magnet_pitch(self, default_config):
        assert default_config.pole_pitch_m == pytest.approx(default_config.magnet_pitch_m)

    def test_slot_pitch_three_phase(self, default_config):
        expected = default_config.magnet_pitch_m / 3.0
        assert default_config.slot_pitch_m == pytest.approx(expected)

    def test_coil_span(self, default_config):
        expected = default_config.magnet_count * default_config.magnet_pitch_m
        assert default_config.coil_span_m == pytest.approx(expected)

    def test_active_length(self, default_config):
        expected = default_config.travel_m + default_config.coil_span_m
        assert default_config.active_length_m == pytest.approx(expected)

    def test_min_via_pad(self, default_config):
        expected = default_config.min_via_drill_m + 2.0 * default_config.min_via_annular_ring_m
        assert default_config.min_via_pad_m == pytest.approx(expected)

    def test_active_length_greater_than_travel(self, default_config):
        assert default_config.active_length_m > default_config.travel_m

    def test_slot_pitch_single_phase(self, minimal_config):
        """Single-phase motor: slot_pitch == pole_pitch."""
        assert minimal_config.phases == 1
        assert minimal_config.slot_pitch_m == pytest.approx(minimal_config.pole_pitch_m)


class TestMotorConfigSummary:
    def test_summary_is_string(self, default_config):
        s = default_config.summary()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_summary_contains_key_values(self, default_config):
        s = default_config.summary()
        assert "75" in s       # travel mm
        assert "10" in s       # magnet count
        assert "500" in s      # target force (displayed as 500 mN)

    def test_summary_contains_name(self):
        cfg = MotorConfig(
            name="custom-name",
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert "custom-name" in cfg.summary()

    def test_summary_unnamed_placeholder(self):
        cfg = MotorConfig(
            travel_m=mm(75),
            magnet_dims_m=(mm(10), mm(10), mm(4)),
        )
        assert "(unnamed)" in cfg.summary()


# ===========================================================================
# StackupResult
# ===========================================================================


class TestStackupResultConstruction:
    def test_four_layer_constructs(self, four_layer_stackup):
        assert four_layer_stackup.layer_count == 4

    def test_eight_layer_constructs(self, eight_layer_stackup):
        assert eight_layer_stackup.layer_count == 8


class TestStackupResultValidation:
    def _base_4layer(self):
        return dict(
            layer_count=4,
            trace_widths_m=(mm(0.15), mm(0.25), mm(0.25), mm(0.15)),
            cu_thickness_m=(oz_to_m(1.0), oz_to_m(2.0), oz_to_m(2.0), oz_to_m(1.0)),
            via_drill_m=mm(0.2),
            via_annular_ring_m=mm(0.1),
            via_grid_rows=2,
            via_grid_cols=3,
            estimated_force_n=0.5,
            estimated_dc_resistance_ohm=3.0,
        )

    def test_odd_layer_count_raises(self):
        kwargs = self._base_4layer()
        kwargs["layer_count"] = 3
        with pytest.raises(ValueError, match="layer_count must be even"):
            StackupResult(**kwargs)

    def test_trace_width_count_mismatch_raises(self):
        kwargs = self._base_4layer()
        kwargs["trace_widths_m"] = (mm(0.15), mm(0.25), mm(0.15))  # 3 entries for 4 layers
        with pytest.raises(ValueError, match="trace_widths_m must have 4 entries"):
            StackupResult(**kwargs)

    def test_cu_thickness_count_mismatch_raises(self):
        kwargs = self._base_4layer()
        kwargs["cu_thickness_m"] = (oz_to_m(1.0), oz_to_m(2.0), oz_to_m(1.0))
        with pytest.raises(ValueError, match="cu_thickness_m must have 4 entries"):
            StackupResult(**kwargs)

    def test_zero_trace_width_raises(self):
        kwargs = self._base_4layer()
        kwargs["trace_widths_m"] = (0.0, mm(0.25), mm(0.25), mm(0.15))
        with pytest.raises(ValueError, match="All trace widths must be positive"):
            StackupResult(**kwargs)

    def test_zero_via_drill_raises(self):
        kwargs = self._base_4layer()
        kwargs["via_drill_m"] = 0.0
        with pytest.raises(ValueError, match="via_drill_m must be positive"):
            StackupResult(**kwargs)

    def test_zero_via_rows_raises(self):
        kwargs = self._base_4layer()
        kwargs["via_grid_rows"] = 0
        with pytest.raises(ValueError, match="via_grid_rows must be ≥ 1"):
            StackupResult(**kwargs)


class TestStackupResultDerivedProperties:
    def test_outer_layer_ids(self, four_layer_stackup):
        assert four_layer_stackup.outer_layer_ids == (0, 3)

    def test_outer_layer_ids_eight(self, eight_layer_stackup):
        assert eight_layer_stackup.outer_layer_ids == (0, 7)

    def test_inner_layer_ids_four(self, four_layer_stackup):
        assert four_layer_stackup.inner_layer_ids == (1, 2)

    def test_inner_layer_ids_eight(self, eight_layer_stackup):
        assert eight_layer_stackup.inner_layer_ids == (1, 2, 3, 4, 5, 6)

    def test_via_pad_diameter(self, four_layer_stackup):
        expected = mm(0.2) + 2.0 * mm(0.1)
        assert four_layer_stackup.via_pad_m == pytest.approx(expected)

    def test_via_grid_count(self, four_layer_stackup):
        assert four_layer_stackup.via_grid_count == 2 * 3

    def test_via_grid_count_eight(self, eight_layer_stackup):
        assert eight_layer_stackup.via_grid_count == 3 * 4

    def test_pyramid_outer_thinner_than_inner(self, eight_layer_stackup):
        outer_ids = eight_layer_stackup.outer_layer_ids
        inner_ids = eight_layer_stackup.inner_layer_ids
        outer_widths = [eight_layer_stackup.trace_widths_m[i] for i in outer_ids]
        inner_widths = [eight_layer_stackup.trace_widths_m[i] for i in inner_ids]
        assert max(outer_widths) < min(inner_widths)

    def test_pyramid_outer_thinner_cu_than_inner(self, eight_layer_stackup):
        outer_ids = eight_layer_stackup.outer_layer_ids
        inner_ids = eight_layer_stackup.inner_layer_ids
        outer_cu = [eight_layer_stackup.cu_thickness_m[i] for i in outer_ids]
        inner_cu = [eight_layer_stackup.cu_thickness_m[i] for i in inner_ids]
        assert max(outer_cu) < min(inner_cu)


class TestStackupResultSummary:
    def test_summary_is_string(self, four_layer_stackup):
        s = four_layer_stackup.summary()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_summary_contains_layer_count(self, four_layer_stackup):
        assert "4 layers" in four_layer_stackup.summary()

    def test_summary_contains_force(self, four_layer_stackup):
        assert "0.420" in four_layer_stackup.summary()

    def test_summary_contains_notes(self, four_layer_stackup):
        assert "4-layer stackup chosen by test fixture" in four_layer_stackup.summary()

    def test_summary_labels_outer_inner(self, eight_layer_stackup):
        s = eight_layer_stackup.summary()
        assert "outer" in s
        assert "inner" in s
