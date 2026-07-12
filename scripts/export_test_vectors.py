#!/usr/bin/env python3
"""
Export canonical JSON test vectors from the Python pcbstatorgen oracle.

These fixtures are consumed by Rust unit tests to validate the ported
physics core (Phase 5). Run after any Python physics change to refresh.

Usage:  python scripts/export_test_vectors.py [--out scripts/fixtures/]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path

from pcbstatorgen.config import LinearMotorConfig
from pcbstatorgen.units import mm, mils_to_m
from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator, SineWaveWindingGenerator
from pcbstatorgen.geometry.coil_generators import (
    ConcentratedCoilGenerator, RhombicCoilGenerator, SpiralCoilGenerator,
)
from pcbstatorgen.magnetic.magnet_model import MagnetArray
from pcbstatorgen.magnetic.force_eval import ForceEvaluator


def default_config() -> LinearMotorConfig:
    return LinearMotorConfig(
        name="test-vector",
        active_area_length_m=mm(195),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=10,
        magnet_pitch_m=mm(12),
        phases=3,
        target_force_n=0.5,
        max_current_a=1.0,
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
    )


def config_vector(cfg: LinearMotorConfig) -> dict:
    """Config serialization + derived values for assertion."""
    return {
        "active_area_length_mm": cfg.active_area_length_m * 1e3,
        "coil_span_mm": cfg.coil_span_m * 1e3,
        "travel_mm": cfg.travel_m * 1e3,
        "pole_pitch_mm": cfg.pole_pitch_m * 1e3,
        "slot_pitch_mm": cfg.slot_pitch_m * 1e3,
        "magnet_gap_mm": cfg.magnet_gap_m * 1e3,
        "magnet_count": cfg.magnet_count,
        "phases": cfg.phases,
        "board_width_mm": cfg.board_width_m * 1e3,
        "air_gap_mm": cfg.air_gap_m * 1e3,
    }


def coil_vector(coils) -> list:
    out = []
    for c in coils:
        out.append({
            "phase_idx": c.phase_idx,
            "phase_name": c.phase_name,
            "layer_idx": c.layer_idx,
            "topology": c.topology.value,
            "active_conductor_count": c.active_conductor_count,
            "total_length_mm": c.total_length_m * 1e3,
            "active_length_mm": c.active_length_m * 1e3,
            "end_turn_length_mm": c.end_turn_length_m * 1e3,
            "bounding_box_mm": [v * 1e3 for v in c.bounding_box],
            "segments": [
                {
                    "start_mm": [s.start[0] * 1e3, s.start[1] * 1e3],
                    "end_mm": [s.end[0] * 1e3, s.end[1] * 1e3],
                    "is_active": s.is_active,
                }
                for s in c.segments
            ],
        })
    return out


def bfield_vector(cfg: LinearMotorConfig, n_samples: int = 50) -> dict:
    """Sample B along board centerline for magba validation."""
    import numpy as np
    arr = MagnetArray(cfg)
    xs = np.linspace(0, cfg.coil_span_m, n_samples)
    B = arr.bfield_at_pcb_surface(xs, mover_position_m=0.0)
    return {
        "x_mm": (xs * 1e3).tolist(),
        "Bx_T": B[:, 0].tolist(),
        "By_T": B[:, 1].tolist(),
        "Bz_T": B[:, 2].tolist(),
    }


def force_vector(cfg: LinearMotorConfig, n_positions: int = 20) -> dict:
    """Force sweep (reduced n_positions for speed)."""
    gen = WaveWindingGenerator()
    coils = gen.generate(cfg)
    ev = ForceEvaluator(n_positions=n_positions, meshing=20)
    res = ev.evaluate(cfg, coils)
    return {
        "positions_mm": (res.positions_m * 1e3).tolist(),
        "force_x_mn": (res.force_x_n * 1e3).tolist(),
        "force_y_mn": (res.force_y_n * 1e3).tolist(),
        "force_z_mn": (res.force_z_n * 1e3).tolist(),
        "mean_thrust_mn": res.mean_thrust_n * 1e3,
        "peak_thrust_mn": res.peak_thrust_n * 1e3,
        "min_thrust_mn": res.min_thrust_n * 1e3,
        "ripple_pct": res.ripple_pct,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="scripts/fixtures", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    cfg = default_config()
    vectors = {"config": config_vector(cfg)}

    # Geometry vectors for all topologies
    for name, gen_fn in [
        ("serpentine", lambda: WaveWindingGenerator().generate(cfg)),
        ("sine_wave", lambda: SineWaveWindingGenerator().generate(cfg)),
        ("concentrated", lambda: ConcentratedCoilGenerator().generate(cfg)),
        ("rhombic", lambda: RhombicCoilGenerator().generate(cfg)),
    ]:
        coils = gen_fn()
        vectors[f"coils_{name}"] = coil_vector(coils)

    # B-field vector
    vectors["bfield"] = bfield_vector(cfg)

    # Force sweep vector (may be slow — uses Magpylib getFT)
    print("Computing force sweep (this may take a moment)...", file=sys.stderr)
    try:
        vectors["force_sweep"] = force_vector(cfg, n_positions=20)
    except Exception as e:
        print(f"WARNING: force sweep failed: {e}", file=sys.stderr)
        vectors["force_sweep"] = {"error": str(e)}

    out_path = args.out / "test_vectors.json"
    with open(out_path, "w") as f:
        json.dump(vectors, f, indent=2)
    print(f"Wrote {out_path} ({len(vectors)} sections)")


if __name__ == "__main__":
    main()
