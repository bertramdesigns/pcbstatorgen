"""
tests/test_kicad_writer.py
Tests for units.m_to_nm/nm_to_m and kicad_writer.connection (offline, no KiCad required).
All tests that require a live KiCad instance are marked @pytest.mark.integration.
"""

from __future__ import annotations

import pytest

from pcbstatorgen.units import m_to_nm, nm_to_m, mm, mils_to_m, oz_to_m
from pcbstatorgen.kicad_writer.connection import KiCadConnection


# ===========================================================================
# m_to_nm / nm_to_m unit conversion
# ===========================================================================


class TestMToNm:
    def test_zero(self):
        assert m_to_nm(0.0) == 0

    def test_returns_int(self):
        assert isinstance(m_to_nm(0.001), int)

    def test_1mm(self):
        assert m_to_nm(0.001) == 1_000_000

    def test_5mil_trace(self):
        # 5 mil = 0.127 mm = 127 µm = 127_000 nm
        assert m_to_nm(mils_to_m(5)) == 127_000

    def test_via_drill_02mm(self):
        assert m_to_nm(mm(0.2)) == 200_000

    def test_via_pad_04mm(self):
        assert m_to_nm(mm(0.4)) == 400_000

    def test_board_width_20mm(self):
        assert m_to_nm(mm(20)) == 20_000_000

    def test_travel_75mm(self):
        assert m_to_nm(mm(75)) == 75_000_000

    def test_1oz_copper_35um(self):
        # 1 oz copper = 35 µm = 35_000 nm
        assert m_to_nm(oz_to_m(1.0)) == 35_000

    def test_2oz_copper_70um(self):
        assert m_to_nm(oz_to_m(2.0)) == 70_000

    def test_truncates_not_rounds(self):
        # 0.1273mm = 127_300.0... nm → truncates to 127_300
        result = m_to_nm(0.0001273)
        assert result == 127_300

    def test_large_value(self):
        # 200 mm PCB
        assert m_to_nm(0.200) == 200_000_000

    def test_small_via_annular_ring_01mm(self):
        assert m_to_nm(mm(0.1)) == 100_000


class TestNmToM:
    def test_zero(self):
        assert nm_to_m(0) == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(nm_to_m(1_000_000), float)

    def test_1mm(self):
        assert nm_to_m(1_000_000) == pytest.approx(0.001)

    def test_127000nm_is_5mil(self):
        assert nm_to_m(127_000) == pytest.approx(mils_to_m(5))

    def test_200000nm_is_02mm(self):
        assert nm_to_m(200_000) == pytest.approx(mm(0.2))

    def test_35000nm_is_1oz(self):
        assert nm_to_m(35_000) == pytest.approx(oz_to_m(1.0))


class TestMToNmRoundTrip:
    def test_round_trip_mm_values(self):
        for v_mm in [0.1, 0.127, 0.2, 1.0, 10.0, 20.0, 75.0]:
            m = mm(v_mm)
            assert nm_to_m(m_to_nm(m)) == pytest.approx(m, rel=1e-6)

    def test_round_trip_oz_values(self):
        for oz in [0.5, 1.0, 2.0, 3.0, 4.0]:
            t = oz_to_m(oz)
            assert nm_to_m(m_to_nm(t)) == pytest.approx(t, rel=1e-4)


# ===========================================================================
# KiCadConnection — offline structural tests (no KiCad required)
# ===========================================================================


class TestKiCadConnectionOffline:
    def test_constructs(self):
        conn = KiCadConnection()
        assert conn is not None

    def test_board_raises_before_connect(self):
        conn = KiCadConnection()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = conn.board

    def test_board_filename_raises_before_connect(self):
        conn = KiCadConnection()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = conn.board_filename

    def test_copper_layer_count_raises_before_connect(self):
        conn = KiCadConnection()
        with pytest.raises(RuntimeError, match="Not connected"):
            _ = conn.copper_layer_count

    def test_connect_raises_importerror_without_kipy(self, monkeypatch):
        """When kipy is not installed, connect() raises ImportError with helpful message."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "kipy":
                raise ImportError("No module named 'kipy'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        conn = KiCadConnection()
        with pytest.raises(ImportError, match="kicad-python is not installed"):
            conn.connect()

    def test_layer_name_for_index_f_cu(self):
        assert KiCadConnection.layer_name_for_index(0, 6) == "F.Cu"

    def test_layer_name_for_index_b_cu(self):
        assert KiCadConnection.layer_name_for_index(5, 6) == "B.Cu"
        assert KiCadConnection.layer_name_for_index(7, 8) == "B.Cu"

    def test_layer_name_for_index_inner(self):
        assert KiCadConnection.layer_name_for_index(1, 6) == "In1.Cu"
        assert KiCadConnection.layer_name_for_index(3, 6) == "In3.Cu"
        assert KiCadConnection.layer_name_for_index(4, 8) == "In4.Cu"

    def test_layer_name_inner_layers_sequential(self):
        for i in range(1, 7):  # In1.Cu through In6.Cu for 8-layer board
            name = KiCadConnection.layer_name_for_index(i, 8)
            assert name == f"In{i}.Cu"

    def test_layer_enum_negative_raises(self):
        pytest.importorskip("kipy")  # skip if kipy not installed
        with pytest.raises(ValueError, match="layer_idx must be ≥ 0"):
            KiCadConnection.layer_enum_for_index(-1)

    def test_layer_enum_out_of_range_raises(self):
        pytest.importorskip("kipy")
        with pytest.raises(ValueError, match="out of supported range"):
            KiCadConnection.layer_enum_for_index(99)


# ===========================================================================
# Integration tests — require a live KiCad 10 instance
# ===========================================================================


@pytest.mark.integration
class TestKiCadConnectionIntegration:
    def test_connect_succeeds(self):
        """IPC connection to a running KiCad 10 with a board open."""
        from pcbstatorgen.kicad_writer.connection import connect
        with connect() as conn:
            assert conn.copper_layer_count >= 2

    @pytest.mark.integration
    def test_board_filename_is_string(self):
        from pcbstatorgen.kicad_writer.connection import connect
        with connect() as conn:
            assert isinstance(conn.board_filename, str)

    @pytest.mark.integration
    def test_check_version_kicad10(self):
        from pcbstatorgen.kicad_writer.connection import connect
        with connect() as conn:
            version = conn.check_version((10, 0, 0))
            assert version.startswith("10")

    @pytest.mark.integration
    def test_layer_enum_f_cu(self):
        from pcbstatorgen.kicad_writer.connection import connect
        from kipy.board_types import BoardLayer
        with connect() as conn:
            layer = conn.layer_enum_for_index(0)
            assert layer == BoardLayer.BL_F_Cu
