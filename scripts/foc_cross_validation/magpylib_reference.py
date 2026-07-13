#!/usr/bin/env python3
"""
Magpylib reference simulation for the Rust FOC cross-validation.

Builds a 3-phase, wave-wound, coreless, alternating-pole linear PCB motor
matching the Rust `LinearMotorConfig::default()` and runs the same
field-oriented-control (FOC) commutation the Rust `force_eval.rs` uses:

    theta_e = 2*pi*p / (2*tau) + phase_shift
    I_k     = I_pk * cos(theta_e - k * pi * slot_pitch / pole_pitch)

The mover is translated by `-p` in X (translation invariance) and the
magnet assembly is held fixed. The thrust force on the mover is computed
from the Lorentz law

    F_mover_x = -sum_k  I_k * sum_seg  dL_seg x B_seg

integrated piecewise over each active conductor with meshing=20 (matching
the Rust `ForceEvaluator::default()`).

The script runs the self-calibration guard exactly as the Rust does: at
`p = 0.1 * pole_pitch`, evaluate the force; if F_mover_x is negative, set
`phase_shift = pi`. The resulting sign is reported in the JSON output.

Outputs `magpylib_output.json` next to this script with the full force
sweep and summary statistics.

Dependencies
------------
pip install magpylib>=5 numpy plotly matplotlib
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np

import magpylib as magpy

try:
    import plotly.graph_objects as go
    _HAS_PLOTLY = True
except ImportError:  # pragma: no cover
    _HAS_PLOTLY = False


# ---------------------------------------------------------------------------
# Configuration — mirrors `LinearMotorConfig::default()` from
# crates/pcbstatorgen-rs/src/config.rs (after `sync_magnet_grade("N44")`).
# ---------------------------------------------------------------------------

MM = 1.0e-3  # 1 mm in metres


@dataclass(frozen=True)
class MotorConfig:
    """Python port of the Rust `LinearMotorConfig` defaults."""

    # Magnet array
    magnet_dims_m: Tuple[float, float, float] = (10 * MM, 10 * MM, 4 * MM)
    magnet_count: int = 10
    magnet_pitch_m: float = 12 * MM  # = pole_pitch for Alternating
    magnet_grade: str = "N44"
    # After `sync_magnet_grade`, N44 → 1.34 T (the magnet_grades.rs typical value).
    magnet_remanence_t: float = 1.34
    back_iron_thickness_m: float = 0.0  # no back-iron
    # Geometry
    active_area_length_m: float = 195 * MM
    board_width_m: float = 20 * MM
    pcb_thickness_m: float = 1.6 * MM
    air_gap_m: float = 0.5 * MM
    # Coil
    coil_topology: str = "serpentine"  # only topology supported here
    phases: int = 3
    spacing_ratio: float = 1.0  # 1:1 spacing (the only Vernier point supported)
    # Drive
    max_current_a: float = 1.0
    supply_voltage_v: float = 5.0
    # Sampling
    n_positions: int = 50  # matches Rust `ForceEvaluator::default()`
    meshing: int = 20  # matches Rust `ForceEvaluator::default()`

    # --- Derived helpers (mirror `LinearMotorConfig::*_m()` methods) ---
    @property
    def pole_pitch_m(self) -> float:
        return self.magnet_pitch_m

    @property
    def slot_pitch_m(self) -> float:
        return (self.pole_pitch_m / self.phases) * self.spacing_ratio

    @property
    def magnet_gap_m(self) -> float:
        return self.magnet_pitch_m - self.magnet_dims_m[0]

    @property
    def coil_span_m(self) -> float:
        return self.magnet_count * self.magnet_pitch_m

    @property
    def travel_m(self) -> float:
        return self.active_area_length_m - self.coil_span_m

    @property
    def rest_offset_m(self) -> float:
        # spacing_ratio = 1.0 → 0.0
        return max(0.0, (self.pole_pitch_m / self.phases) * (1.0 - self.spacing_ratio))


# ---------------------------------------------------------------------------
# Geometry helpers — port of `wave_winding::WaveWindingGenerator::generate`
# for a single layer (Rust `layer_idx = 0`).
# ---------------------------------------------------------------------------

PHASE_NAMES = ("A", "B", "C")


def conductor_x_positions(cfg: MotorConfig, phase_idx: int) -> List[float]:
    """X positions of active conductors for `phase_idx`.

    Mirrors `crate::geometry::wave_winding::conductor_x_positions`.
    """
    slot_pitch = cfg.slot_pitch_m
    x_offset = phase_idx * slot_pitch
    x_max = cfg.active_area_length_m + (cfg.phases - 1) * slot_pitch
    xs: List[float] = []
    x = x_offset
    while x <= x_max + 1e-9:
        xs.append(x)
        x += cfg.pole_pitch_m
    return xs


def build_phase_segments(
    cfg: MotorConfig, phase_idx: int
) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], bool]]:
    """Build the full segment list for one phase, one layer (Rust `layer_idx=0`).

    Returns a list of `(start_3d, end_3d, is_active)` tuples in metres.
    Z = 0 (PCB top surface), matching the Rust default `layer_z_m = 0.0`.
    """
    bw = cfg.board_width_m
    x_positions = conductor_x_positions(cfg, phase_idx)
    segments: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], bool]] = []
    going_up = True
    for k, x in enumerate(x_positions):
        if going_up:
            y_start, y_end = 0.0, bw
        else:
            y_start, y_end = bw, 0.0
        segments.append(((x, y_start, 0.0), (x, y_end, 0.0), True))
        if k < len(x_positions) - 1:
            x_next = x_positions[k + 1]
            y_edge = bw if going_up else 0.0
            segments.append(((x, y_edge, 0.0), (x_next, y_edge, 0.0), False))
        going_up = not going_up
    return segments


def build_active_subsegments(
    cfg: MotorConfig, phase_idx: int
) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """Subdivide each *active* conductor into `cfg.meshing` sub-segments.

    Returns one `(start_3d, end_3d)` pair per sub-segment. The Rust
    `CoilCurrentModel::build_phase_samples` does the same subdivision
    (one dL per sub-segment) and the force is summed across sub-segments
    at the same phase current.
    """
    sub_segs: List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]] = []
    for start, end, is_active in build_phase_segments(cfg, phase_idx):
        if not is_active:
            continue
        sx, sy, sz = start
        ex, ey, ez = end
        # Subdivide linearly: `meshing` equal pieces along the segment.
        n = cfg.meshing
        for k in range(n):
            t0 = k / n
            t1 = (k + 1) / n
            s = (sx + (ex - sx) * t0, sy + (ey - sy) * t0, sz + (ez - sz) * t0)
            e = (sx + (ex - sx) * t1, sy + (ey - sy) * t1, sz + (ez - sz) * t1)
            sub_segs.append((s, e))
    return sub_segs


# ---------------------------------------------------------------------------
# FOC — port of `force_eval.rs::commutation_currents`.
# ---------------------------------------------------------------------------

PI = math.pi


def foc_currents(
    cfg: MotorConfig,
    mover_position_m: float,
    phase_shift: float,
) -> List[float]:
    """Sinusoidal FOC with the slot-pitch offset.

    Mirrors `crate::magnetic::force_eval::commutation_currents` with
    `CommutationMode::MaxTorque`.
    """
    i_pk = cfg.max_current_a
    theta_e = (
        2.0 * PI * mover_position_m / (2.0 * cfg.pole_pitch_m) + phase_shift
    )
    phase_offset = PI * cfg.slot_pitch_m / cfg.pole_pitch_m
    return [
        i_pk * math.cos(theta_e - k * phase_offset) for k in range(cfg.phases)
    ]


# ---------------------------------------------------------------------------
# Magnet assembly — port of `magnet_model.rs::MagnetArray::build_alternating`.
# ---------------------------------------------------------------------------

def build_magnet_assembly(cfg: MotorConfig):
    """Build the 10-magnet alternating assembly (no back-iron, no Halbach)."""
    y_center = cfg.board_width_m / 2.0
    z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
    magnets = []
    for k in range(cfg.magnet_count):
        # Initial position: magnet 0 centred at x=0, magnet k at x = k*pitch
        x = k * cfg.magnet_pitch_m
        pol_z = cfg.magnet_remanence_t * (1.0 if k % 2 == 0 else -1.0)
        # `Cuboid` in magpylib uses polarization = J = mu0*M (Tesla), same
        # convention as the Rust `magba::CuboidMagnet::new`.
        mag = magpy.magnet.Cuboid(
            polarization=(0.0, 0.0, pol_z),
            position=(x, y_center, z_center),
            dimension=cfg.magnet_dims_m,
        )
        magnets.append(mag)
    return magpy.Collection(*magnets)


# ---------------------------------------------------------------------------
# Force evaluation — port of `force_eval.rs::evaluate_force_raw`.
# ---------------------------------------------------------------------------

def compute_force_x_at_position(
    cfg: MotorConfig,
    magnet_collection,
    mover_position_m: float,
    phase_shift: float,
) -> Tuple[float, float, float, List[float]]:
    """Compute the mover (F_mover) force vector at one position.

    Returns (F_x, F_y, F_z, per_phase_F_x). Mover force = -stator force
    (Newton's Third Law), matching the Rust convention.

    Implementation:
      1. Build the sub-segment list for every phase.
      2. Translate the sub-segment midpoints by `-mover_position_m` in X
         (translation invariance: relative to a fixed magnet assembly, this
         is the same as moving the magnet assembly by `+mover_position_m`).
      3. Vectorised `getB` over all sub-segment midpoints.
      4. For each sub-segment, accumulate `I_phase * dL × B` into the phase
         total; sum phases and negate to get mover force.
    """
    currents = foc_currents(cfg, mover_position_m, phase_shift)

    # Gather all sub-segments for all phases, keeping a per-phase index range.
    all_starts: List[Tuple[float, float, float]] = []
    all_ends: List[Tuple[float, float, float]] = []
    phase_slices: List[Tuple[int, int]] = []  # (start_idx, end_idx) in all_* lists
    for phase_idx in range(cfg.phases):
        start = len(all_starts)
        for s, e in build_active_subsegments(cfg, phase_idx):
            all_starts.append(s)
            all_ends.append(e)
        phase_slices.append((start, len(all_starts)))

    # Sub-segment dL vectors (constant per sub-segment)
    dl_arr = np.array(
        [list(e) for e in all_ends], dtype=float
    ) - np.array([list(s) for s in all_starts], dtype=float)

    # Sub-segment midpoints, translated by `-mover_position_m` in X
    mid_arr = 0.5 * (
        np.array([list(s) for s in all_starts], dtype=float)
        + np.array([list(e) for e in all_ends], dtype=float)
    )
    mid_arr[:, 0] -= mover_position_m

    # One vectorised getB call for all sub-segment midpoints
    B = magnet_collection.getB(mid_arr)  # shape (N, 3)

    # dL × B per sub-segment
    dL_cross_B = np.cross(dl_arr, B, axis=1)  # shape (N, 3)

    # Sum per phase × phase current → stator force
    stator_F = np.zeros(3)
    per_phase_x = []
    for phase_idx, (s, e) in enumerate(phase_slices):
        phase_force = currents[phase_idx] * dL_cross_B[s:e].sum(axis=0)
        stator_F += phase_force
        per_phase_x.append(phase_force[0])

    # Mover force = -stator force (Newton's Third Law)
    mover_F = -stator_F
    per_phase_mover_x = [-x for x in per_phase_x]
    return (
        float(mover_F[0]),
        float(mover_F[1]),
        float(mover_F[2]),
        per_phase_mover_x,
    )


# ---------------------------------------------------------------------------
# Self-calibration — port of `force_eval.rs::self_calibrate`.
# ---------------------------------------------------------------------------

def self_calibrate(
    cfg: MotorConfig,
    magnet_collection,
) -> float:
    """Return the FOC `phase_shift` to use, mirroring the Rust guard.

    At p = +0.1 * pole_pitch, evaluate force with phase_shift=0; if
    F_mover_x is negative, set phase_shift = pi.
    """
    test_pos = 0.1 * cfg.pole_pitch_m
    fx, _, _, _ = compute_force_x_at_position(cfg, magnet_collection, test_pos, 0.0)
    return math.pi if fx < 0.0 else 0.0


# ---------------------------------------------------------------------------
# Sweep — port of `force_eval.rs::ForceEvaluator::evaluate`.
# ---------------------------------------------------------------------------

@dataclass
class ForceResult:
    positions_m: List[float]
    force_x_n: List[float]
    force_y_n: List[float]
    force_z_n: List[float]
    per_phase_force_x: List[float]  # flat n_positions × n_phases
    n_phases: int
    current_a: float
    phase_shift: float
    pole_pitch_m: float
    slot_pitch_m: float

    def mean_thrust_n(self) -> float:
        return sum(self.force_x_n) / len(self.force_x_n) if self.force_x_n else 0.0

    def peak_thrust_n(self) -> float:
        return max(self.force_x_n)

    def min_thrust_n(self) -> float:
        return min(self.force_x_n)

    def ripple_pct(self) -> float:
        mean = self.mean_thrust_n()
        if abs(mean) < 1e-12:
            return 0.0
        return (self.peak_thrust_n() - self.min_thrust_n()) / abs(mean) * 100.0


def linspace(start: float, end: float, n: int) -> List[float]:
    if n == 1:
        return [start]
    step = (end - start) / (n - 1)
    return [start + i * step for i in range(n)]


def evaluate_sweep(
    cfg: MotorConfig,
    n_positions: int | None = None,
) -> Tuple[ForceResult, dict]:
    """Run the full FOC force sweep; return (result, summary_dict)."""
    n_positions = n_positions or cfg.n_positions
    magnet_collection = build_magnet_assembly(cfg)

    # Self-calibration guard
    phase_shift = self_calibrate(cfg, magnet_collection)

    # Position grid (same as Rust: rest to travel+rest, n points inclusive)
    rest = cfg.rest_offset_m
    positions = linspace(rest, cfg.travel_m + rest, n_positions)

    fx_list, fy_list, fz_list, ppx_list = [], [], [], []
    t0 = time.time()
    for i, p in enumerate(positions):
        fx, fy, fz, ppx = compute_force_x_at_position(
            cfg, magnet_collection, p, phase_shift
        )
        fx_list.append(fx)
        fy_list.append(fy)
        fz_list.append(fz)
        ppx_list.extend(ppx)
        if (i + 1) % 10 == 0:
            print(f"  position {i+1:3d}/{n_positions} (p={p*1e3:6.2f} mm)", file=sys.stderr)
    dt = time.time() - t0

    result = ForceResult(
        positions_m=positions,
        force_x_n=fx_list,
        force_y_n=fy_list,
        force_z_n=fz_list,
        per_phase_force_x=ppx_list,
        n_phases=cfg.phases,
        current_a=cfg.max_current_a,
        phase_shift=phase_shift,
        pole_pitch_m=cfg.pole_pitch_m,
        slot_pitch_m=cfg.slot_pitch_m,
    )

    summary = {
        "n_positions": n_positions,
        "mean_thrust_mn": result.mean_thrust_n() * 1e3,
        "peak_thrust_mn": result.peak_thrust_n() * 1e3,
        "min_thrust_mn": result.min_thrust_n() * 1e3,
        "ripple_pct": result.ripple_pct(),
        "phase_shift_rad": phase_shift,
        "wall_time_s": dt,
    }
    return result, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = MotorConfig()
    print("=" * 72, file=sys.stderr)
    print("Magpylib reference — Rust FOC cross-validation", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(f"  magnet: {cfg.magnet_count}x {cfg.magnet_dims_m[0]*1e3:.0f}x"
          f"{cfg.magnet_dims_m[1]*1e3:.0f}x{cfg.magnet_dims_m[2]*1e3:.0f} mm"
          f"  Br={cfg.magnet_remanence_t:.3f} T ({cfg.magnet_grade})", file=sys.stderr)
    print(f"  pole_pitch={cfg.pole_pitch_m*1e3:.2f} mm  "
          f"slot_pitch={cfg.slot_pitch_m*1e3:.2f} mm  "
          f"phases={cfg.phases}  spacing_ratio={cfg.spacing_ratio}",
          file=sys.stderr)
    print(f"  travel={cfg.travel_m*1e3:.2f} mm  active={cfg.active_area_length_m*1e3:.2f} mm"
          f"  air_gap={cfg.air_gap_m*1e3:.2f} mm  board_w={cfg.board_width_m*1e3:.1f} mm",
          file=sys.stderr)
    print(f"  I_pk={cfg.max_current_a:.2f} A  meshing={cfg.meshing}  "
          f"n_positions={cfg.n_positions}", file=sys.stderr)
    print(file=sys.stderr)

    result, summary = evaluate_sweep(cfg)

    # Print summary
    print("=" * 72, file=sys.stderr)
    print("Summary", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print(f"  phase_shift     = {result.phase_shift:.4f} rad  "
          f"({result.phase_shift/math.pi:.2f}*pi)", file=sys.stderr)
    print(f"  mean_thrust     = {summary['mean_thrust_mn']:8.4f} mN", file=sys.stderr)
    print(f"  peak_thrust     = {summary['peak_thrust_mn']:8.4f} mN", file=sys.stderr)
    print(f"  min_thrust      = {summary['min_thrust_mn']:8.4f} mN", file=sys.stderr)
    print(f"  ripple          = {summary['ripple_pct']:8.4f} %", file=sys.stderr)
    print(f"  wall_time       = {summary['wall_time_s']:6.2f} s", file=sys.stderr)
    print(file=sys.stderr)

    # Write JSON
    out_path = Path(__file__).parent / "magpylib_output.json"
    out = {
        "config": {
            "magnet_dims_mm": [d * 1e3 for d in cfg.magnet_dims_m],
            "magnet_count": cfg.magnet_count,
            "magnet_pitch_mm": cfg.magnet_pitch_m * 1e3,
            "pole_pitch_mm": cfg.pole_pitch_m * 1e3,
            "slot_pitch_mm": cfg.slot_pitch_m * 1e3,
            "magnet_grade": cfg.magnet_grade,
            "magnet_remanence_t": cfg.magnet_remanence_t,
            "active_area_length_mm": cfg.active_area_length_m * 1e3,
            "board_width_mm": cfg.board_width_m * 1e3,
            "air_gap_mm": cfg.air_gap_m * 1e3,
            "coil_topology": cfg.coil_topology,
            "phases": cfg.phases,
            "spacing_ratio": cfg.spacing_ratio,
            "max_current_a": cfg.max_current_a,
            "n_positions": cfg.n_positions,
            "meshing": cfg.meshing,
            "rest_offset_mm": cfg.rest_offset_m * 1e3,
            "travel_mm": cfg.travel_m * 1e3,
        },
        "summary": summary,
        "force_sweep": {
            "positions_mm": [p * 1e3 for p in result.positions_m],
            "force_x_mn": [f * 1e3 for f in result.force_x_n],
            "force_y_mn": [f * 1e3 for f in result.force_y_n],
            "force_z_mn": [f * 1e3 for f in result.force_z_n],
            "per_phase_force_x_mn": [f * 1e3 for f in result.per_phase_force_x],
        },
    }
    with out_path.open("w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {out_path}", file=sys.stderr)

    # Optional: write a Plotly HTML for at-a-glance inspection.
    # `pip install plotly` (already in the dependency list).
    if _HAS_PLOTLY:
        try:
            _write_plotly_html(out_path.with_suffix(".html"), result)
            print(f"Wrote {out_path.with_suffix('.html')}", file=sys.stderr)
        except Exception as e:  # pragma: no cover
            print(f"  (plotly write skipped: {e})", file=sys.stderr)

    return 0


def _write_plotly_html(path: Path, result: ForceResult) -> None:
    """Write a Plotly HTML showing the force sweep and a per-phase breakdown."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[p * 1e3 for p in result.positions_m],
        y=[f * 1e3 for f in result.force_x_n],
        mode="lines+markers",
        name="F_mover_x (thrust)",
        line=dict(color="crimson", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=[p * 1e3 for p in result.positions_m],
        y=[f * 1e3 for f in result.force_y_n],
        mode="lines",
        name="F_mover_y (lateral)",
        line=dict(color="steelblue", width=1, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=[p * 1e3 for p in result.positions_m],
        y=[f * 1e3 for f in result.force_z_n],
        mode="lines",
        name="F_mover_z (normal)",
        line=dict(color="seagreen", width=1, dash="dot"),
    ))
    # Per-phase thrust (convert flat vec back to n_phases × n_positions)
    n_p = result.n_phases
    n_x = len(result.positions_m)
    for phase_idx in range(n_p):
        per_phase = result.per_phase_force_x[phase_idx::n_p]
        fig.add_trace(go.Scatter(
            x=[p * 1e3 for p in result.positions_m],
            y=[f * 1e3 for f in per_phase],
            mode="lines",
            name=f"Phase {PHASE_NAMES[phase_idx]} (per-phase F_x)",
            line=dict(width=1, dash="dash"),
            opacity=0.5,
        ))
    fig.update_layout(
        title=(
            f"Magpylib reference — thrust vs position<br>"
            f"<sub>mean={result.mean_thrust_n()*1e3:.2f} mN, "
            f"ripple={result.ripple_pct():.2f}%, "
            f"phase_shift={result.phase_shift/math.pi:.2f}π</sub>"
        ),
        xaxis_title="Mover position [mm]",
        yaxis_title="Force [mN]",
        hovermode="x unified",
        template="plotly_white",
    )
    fig.write_html(str(path), include_plotlyjs="cdn")


if __name__ == "__main__":
    raise SystemExit(main())
