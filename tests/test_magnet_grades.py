"""
tests/test_magnet_grades.py — unit tests for the magnet grade lookup table.
"""

from __future__ import annotations

import pytest

from pcbstatorgen.config import LinearMotorConfig
from pcbstatorgen.magnet_grades import (
    CUSTOM_GRADE,
    GRADE_NAMES,
    MAGNET_GRADES,
    MagnetGrade,
    get_grade,
    get_remanence,
)
from pcbstatorgen.units import mm


class TestMagnetGradesTable:
    def test_contains_all_six_grades(self):
        for name in ["N35", "N38", "N42", "N44", "N48", "N52"]:
            assert name in MAGNET_GRADES

    def test_grade_names_list(self):
        assert GRADE_NAMES == ["N35", "N38", "N42", "N44", "N48", "N52"]

    def test_custom_grade_constant(self):
        assert CUSTOM_GRADE == "Custom"

    def test_each_grade_has_valid_fields(self):
        for name in GRADE_NAMES:
            g = MAGNET_GRADES[name]
            assert isinstance(g, MagnetGrade)
            assert g.name == name
            assert 0.5 < g.br_min_t < g.br_typ_t < g.br_max_t < 2.0
            assert "Std" in g.max_temp_c
            assert g.max_temp_c["Std"] == 80

    def test_n52_has_only_std_temp(self):
        n52 = MAGNET_GRADES["N52"]
        assert list(n52.max_temp_c.keys()) == ["Std"]

    def test_n44_has_full_temp_suffixes(self):
        n44 = MAGNET_GRADES["N44"]
        assert set(n44.max_temp_c.keys()) == {"Std", "H", "SH", "UH", "EH", "AH"}
        assert n44.max_temp_c["AH"] == 220


class TestGetRemanence:
    def test_n44_typical(self):
        assert get_remanence("N44") == pytest.approx(1.34)

    def test_n52_typical(self):
        assert get_remanence("N52") == pytest.approx(1.45)

    def test_n35_typical(self):
        assert get_remanence("N35") == pytest.approx(1.19)

    def test_n48_typical(self):
        assert get_remanence("N48") == pytest.approx(1.40)

    def test_grade_with_h_suffix(self):
        assert get_remanence("N44H") == pytest.approx(1.34)

    def test_grade_with_sh_suffix(self):
        assert get_remanence("N42SH") == pytest.approx(1.30)

    def test_grade_with_uh_suffix(self):
        assert get_remanence("N48UH") == pytest.approx(1.40)

    def test_grade_lowercase(self):
        assert get_remanence("n44h") == pytest.approx(1.34)

    def test_custom_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_remanence("Custom")

    def test_unknown_grade_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_remanence("N99")


class TestGetGrade:
    def test_returns_magnet_grade_instance(self):
        g = get_grade("N42")
        assert isinstance(g, MagnetGrade)
        assert g.name == "N42"

    def test_n42_fields_correct(self):
        g = get_grade("N42")
        assert g.br_min_t == pytest.approx(1.28)
        assert g.br_typ_t == pytest.approx(1.30)
        assert g.br_max_t == pytest.approx(1.32)
        assert g.max_temp_c["SH"] == 150

    def test_with_suffix(self):
        g = get_grade("N44H")
        assert g.name == "N44"
        assert g.br_typ_t == pytest.approx(1.34)

    def test_custom_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_grade("Custom")


class TestConfigIntegration:
    def test_default_config_has_n44_grade(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195))
        assert cfg.magnet_grade == "N44"

    def test_default_config_remanence_synced_to_n44(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195))
        assert cfg.magnet_remanence_t == pytest.approx(1.34)

    def test_n52_grade_syncs_remanence(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195), magnet_grade="N52")
        assert cfg.magnet_remanence_t == pytest.approx(1.45)

    def test_n35_grade_syncs_remanence(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195), magnet_grade="N35")
        assert cfg.magnet_remanence_t == pytest.approx(1.19)

    def test_custom_grade_keeps_manual_remanence(self):
        cfg = LinearMotorConfig(
            active_area_length_m=mm(195),
            magnet_grade="Custom",
            magnet_remanence_t=1.50,
        )
        assert cfg.magnet_remanence_t == pytest.approx(1.50)

    def test_custom_grade_default_remanence_unchanged(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195), magnet_grade="Custom")
        assert cfg.magnet_remanence_t == pytest.approx(1.35)

    def test_grade_with_suffix_in_config(self):
        cfg = LinearMotorConfig(active_area_length_m=mm(195), magnet_grade="N44H")
        assert cfg.magnet_remanence_t == pytest.approx(1.34)

    def test_custom_grade_with_unrealistic_remanence_still_validated(self):
        with pytest.raises(ValueError, match="magnet_remanence_t"):
            LinearMotorConfig(
                active_area_length_m=mm(195),
                magnet_grade="Custom",
                magnet_remanence_t=5.0,
            )
