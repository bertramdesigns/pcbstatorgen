"""
pcbstatorgen.config
========================
Central parameter dataclasses for the PCB stator generator.

All physical quantities are stored and passed between modules in SI units:
metres, Tesla, Amperes, Ohms, Watts.  Use :mod:`pcbstatorgen.units`
helpers to build values from human-readable inputs.

Classes
-------
MotorConfig
    User-supplied mechanical and electrical parameters.
StackupResult
    Computed PCB stackup recommendation (output of LayerOptimizer).

Example
-------
Build a config for a 75 mm travel fader with JLCPCB 4-layer constraints::

    from pcbstatorgen.config import MotorConfig
    from pcbstatorgen.units import mm, mils_to_m, oz_to_m

    cfg = MotorConfig(
        travel_m=mm(75),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=10,
        magnet_pitch_m=mm(12),
        phases=3,
        target_force_n=0.5,
        max_current_a=1.0,
        min_trace_m=mils_to_m(5),
        min_space_m=mils_to_m(5),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(20),
        air_gap_m=mm(0.5),
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from pcbstatorgen.units import mm, mils_to_m, oz_to_m

__all__ = ["MotorConfig", "StackupResult"]


# ---------------------------------------------------------------------------
# MotorConfig
# ---------------------------------------------------------------------------


@dataclass
class MotorConfig:
    """All user-supplied parameters for the linear motor stator.

    Every length field is in **metres** and every current/force field is in
    **SI units**.  Use helpers from :mod:`pcbstatorgen.units` when
    constructing from human-readable values.

    Parameters
    ----------
    travel_m:
        Total travel range of the fader carriage [m].
        Typical range: 0.060 – 0.090 m (60–90 mm).
    magnet_dims_m:
        (width, length, height) of a single N44H permanent magnet [m].
        ``width`` is along the travel axis, ``length`` is perpendicular
        (across the PCB), ``height`` is the out-of-plane dimension.
    magnet_count:
        Number of magnets in the linear array on the carriage.  Must be even
        for a symmetric alternating-pole arrangement.  Default: 10.
    magnet_pitch_m:
        Centre-to-centre spacing of adjacent magnets along the travel axis [m].
        This equals one pole pitch.  Default: 12 mm.
    magnet_remanence_t:
        Remnant flux density (Br) of the magnet grade at operating temperature
        [T].  N44H at 20 °C: Br ≈ 1.32 – 1.38 T.  Default: 1.35 T.
    phases:
        Number of electrical phases.  3 for standard 3-phase.  Default: 3.
    target_force_n:
        Minimum acceptable continuous linear force [N].  The LayerOptimizer
        will add layers until this is achievable with ``max_current_a``.
        Typical fader feel: 0.2 – 1.0 N.
    max_current_a:
        Peak phase current available from the STM G4 drive circuit [A].
        Default: 1.0 A.
    min_trace_m:
        Minimum manufacturable trace width [m].  Set by copper weight and
        the PCB manufacturer's DFM rules.  JLCPCB 2oz outer: 0.1 mm (≈4 mil).
        Default: 5 mil (0.127 mm).
    min_space_m:
        Minimum clearance between adjacent traces [m].  Usually matches
        ``min_trace_m`` for the same manufacturer tier.  Default: 5 mil.
    min_via_drill_m:
        Minimum laser or mechanical drill diameter for vias [m].
        JLCPCB standard: 0.2 mm.  Default: 0.2 mm.
    min_via_annular_ring_m:
        Minimum copper annular ring around each via [m].  Default: 0.1 mm.
    board_width_m:
        PCB width (dimension perpendicular to the travel axis) [m].
        Constrains coil winding width.  Default: 20 mm.
    air_gap_m:
        Clearance between the magnet face and the nearest PCB copper surface
        [m].  Smaller gaps increase force but raise assembly tolerance
        requirements.  Default: 0.5 mm.
    max_layers:
        Hard upper limit on the number of copper layers the optimizer may
        consider.  Prevents runaway iteration.  Default: 12.
    drive_frequency_hz:
        Nominal electrical drive frequency at mid-travel speed [Hz].  Used to
        calculate skin depth for outer-layer copper weight selection.
        For a fader with 10 pole-pairs/m at 0.1 m/s: f ≈ 1 Hz – set per
        application.  Default: 500 Hz (conservative high end).
    name:
        Optional human-readable label for this configuration.
    """

    # ------------------------------------------------------------------
    # Mechanical geometry
    # ------------------------------------------------------------------
    travel_m: float
    """Total travel range [m]."""

    magnet_dims_m: tuple[float, float, float]
    """(width_travel, width_cross, height) of one N44H magnet [m]."""

    magnet_count: int = 10
    """Number of magnets in the carriage array."""

    magnet_pitch_m: float = field(default_factory=lambda: mm(12))
    """Centre-to-centre magnet spacing along the travel axis [m]."""

    magnet_remanence_t: float = 1.35
    """Remnant flux density Br of the magnet grade at 20 °C [T]."""

    # ------------------------------------------------------------------
    # Electrical
    # ------------------------------------------------------------------
    phases: int = 3
    """Number of electrical phases."""

    target_force_n: float = 0.5
    """Minimum continuous linear force the stackup must deliver [N]."""

    max_current_a: float = 1.0
    """Peak phase current from the drive circuit [A]."""

    # ------------------------------------------------------------------
    # PCB manufacturing constraints
    # ------------------------------------------------------------------
    min_trace_m: float = field(default_factory=lambda: mils_to_m(5))
    """Minimum trace width [m]."""

    min_space_m: float = field(default_factory=lambda: mils_to_m(5))
    """Minimum trace-to-trace clearance [m]."""

    min_via_drill_m: float = field(default_factory=lambda: mm(0.2))
    """Minimum via drill diameter [m]."""

    min_via_annular_ring_m: float = field(default_factory=lambda: mm(0.1))
    """Minimum annular ring width [m]."""

    board_width_m: float = field(default_factory=lambda: mm(20))
    """PCB dimension perpendicular to the travel axis [m]."""

    air_gap_m: float = field(default_factory=lambda: mm(0.5))
    """Clearance from magnet face to nearest PCB copper surface [m]."""

    # ------------------------------------------------------------------
    # Optimiser bounds
    # ------------------------------------------------------------------
    max_layers: int = 12
    """Maximum number of copper layers the optimizer may try."""

    drive_frequency_hz: float = 500.0
    """Nominal electrical drive frequency for skin depth calculation [Hz]."""

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    name: Optional[str] = None
    """Optional human-readable label for this configuration."""

    # ------------------------------------------------------------------
    # Derived / computed properties
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        """Validate all parameters after construction."""
        self._validate()

    def _validate(self) -> None:
        """Raise ValueError for physically invalid combinations."""
        if self.travel_m <= 0:
            raise ValueError(f"travel_m must be positive, got {self.travel_m}")
        if len(self.magnet_dims_m) != 3:
            raise ValueError("magnet_dims_m must be a 3-tuple (width, length, height)")
        if any(d <= 0 for d in self.magnet_dims_m):
            raise ValueError(f"All magnet dimensions must be positive, got {self.magnet_dims_m}")
        if self.magnet_count < 2:
            raise ValueError(f"magnet_count must be ≥ 2, got {self.magnet_count}")
        if self.magnet_count % 2 != 0:
            raise ValueError(
                f"magnet_count must be even for alternating poles, got {self.magnet_count}"
            )
        if self.magnet_pitch_m <= 0:
            raise ValueError(f"magnet_pitch_m must be positive, got {self.magnet_pitch_m}")
        if self.magnet_pitch_m < self.magnet_dims_m[0]:
            raise ValueError(
                f"magnet_pitch_m ({self.magnet_pitch_m * 1e3:.2f} mm) must be ≥ "
                f"magnet width ({self.magnet_dims_m[0] * 1e3:.2f} mm)"
            )
        if self.magnet_remanence_t <= 0 or self.magnet_remanence_t > 2.5:
            raise ValueError(
                f"magnet_remanence_t must be in (0, 2.5] T, got {self.magnet_remanence_t}"
            )
        if self.phases < 1:
            raise ValueError(f"phases must be ≥ 1, got {self.phases}")
        if self.target_force_n <= 0:
            raise ValueError(f"target_force_n must be positive, got {self.target_force_n}")
        if self.max_current_a <= 0:
            raise ValueError(f"max_current_a must be positive, got {self.max_current_a}")
        if self.min_trace_m <= 0:
            raise ValueError(f"min_trace_m must be positive, got {self.min_trace_m}")
        if self.min_space_m <= 0:
            raise ValueError(f"min_space_m must be positive, got {self.min_space_m}")
        if self.min_via_drill_m <= 0:
            raise ValueError(f"min_via_drill_m must be positive, got {self.min_via_drill_m}")
        if self.min_via_annular_ring_m <= 0:
            raise ValueError(
                f"min_via_annular_ring_m must be positive, got {self.min_via_annular_ring_m}"
            )
        if self.board_width_m <= 0:
            raise ValueError(f"board_width_m must be positive, got {self.board_width_m}")
        if self.air_gap_m < 0:
            raise ValueError(f"air_gap_m must be ≥ 0, got {self.air_gap_m}")
        if self.max_layers < 2 or self.max_layers % 2 != 0:
            raise ValueError(
                f"max_layers must be an even number ≥ 2, got {self.max_layers}"
            )
        if self.drive_frequency_hz <= 0:
            raise ValueError(
                f"drive_frequency_hz must be positive, got {self.drive_frequency_hz}"
            )

    # ------------------------------------------------------------------
    # Derived geometry properties
    # ------------------------------------------------------------------

    @property
    def pole_pitch_m(self) -> float:
        """Distance between adjacent magnet poles [m].

        Equal to ``magnet_pitch_m`` for a standard alternating-pole array.
        """
        return self.magnet_pitch_m

    @property
    def slot_pitch_m(self) -> float:
        """Coil slot pitch for the given phase count [m].

        For a 3-phase motor: slot_pitch = pole_pitch / 3.
        """
        return self.pole_pitch_m / self.phases

    @property
    def coil_span_m(self) -> float:
        """Full span of the active winding region [m].

        Equal to ``magnet_count × magnet_pitch_m``.  The coil must cover this
        span to remain in the magnet field across the full travel.
        """
        return self.magnet_count * self.magnet_pitch_m

    @property
    def active_length_m(self) -> float:
        """Minimum PCB length required [m].

        ``travel_m + coil_span_m``: the coil must extend past both ends of
        the travel to avoid force drop-off at the extremes.
        """
        return self.travel_m + self.coil_span_m

    @property
    def min_via_pad_m(self) -> float:
        """Minimum via pad diameter [m] (drill + 2 × annular ring)."""
        return self.min_via_drill_m + 2.0 * self.min_via_annular_ring_m

    def summary(self) -> str:
        """Return a compact human-readable summary of key parameters."""
        lines = [
            f"MotorConfig: {self.name or '(unnamed)'}",
            f"  Travel:         {self.travel_m * 1e3:.1f} mm",
            f"  Magnet:         {self.magnet_count}× N44H "
            f"{self.magnet_dims_m[0]*1e3:.0f}×"
            f"{self.magnet_dims_m[1]*1e3:.0f}×"
            f"{self.magnet_dims_m[2]*1e3:.0f} mm  "
            f"Br={self.magnet_remanence_t:.2f} T",
            f"  Pole pitch:     {self.pole_pitch_m * 1e3:.1f} mm",
            f"  Slot pitch:     {self.slot_pitch_m * 1e3:.2f} mm  ({self.phases}-phase)",
            f"  Active length:  {self.active_length_m * 1e3:.1f} mm",
            f"  Target force:   {self.target_force_n:.3f} N  @ {self.max_current_a:.1f} A peak",
            f"  Min trace/space:{self.min_trace_m * 1e3:.3f} / "
            f"{self.min_space_m * 1e3:.3f} mm",
            f"  Via drill/ring: {self.min_via_drill_m * 1e3:.2f} / "
            f"{self.min_via_annular_ring_m * 1e3:.2f} mm",
            f"  Board width:    {self.board_width_m * 1e3:.1f} mm",
            f"  Air gap:        {self.air_gap_m * 1e3:.2f} mm",
            f"  Drive freq:     {self.drive_frequency_hz:.0f} Hz",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# StackupResult
# ---------------------------------------------------------------------------


@dataclass
class StackupResult:
    """Computed PCB stackup recommendation from the LayerOptimizer.

    Every field that changes per-layer is represented as a tuple indexed
    ``0 … layer_count - 1``, where index 0 is the top outer layer and
    ``layer_count - 1`` is the bottom outer layer.

    Parameters
    ----------
    layer_count:
        Total number of copper layers (always even: outer pairs + inner pairs).
    trace_widths_m:
        Per-layer trace width [m].  Outer layers are narrower (pyramid scheme)
        to minimise AC eddy current losses; inner layers are wider to reduce DC
        resistance.
    cu_thickness_m:
        Per-layer copper thickness [m].  Outer layers: 1 oz (35 µm);
        inner layers: 2–4 oz depending on optimiser output.
    via_drill_m:
        Recommended via drill diameter [m].
    via_annular_ring_m:
        Recommended via annular ring width [m].
    via_grid_rows:
        Number of via rows in the end-turn grid (along board width axis).
    via_grid_cols:
        Number of via columns in the end-turn grid (along travel axis).
    estimated_force_n:
        Model-estimated peak linear force [N] with ``MotorConfig.max_current_a``.
    estimated_dc_resistance_ohm:
        Estimated per-phase DC resistance [Ω] (sum of all layers, both sides).
    outer_layer_ids:
        Indices of the outer copper layers (top and bottom).
    inner_layer_ids:
        Indices of inner copper layers.
    notes:
        Human-readable notes from the optimiser (e.g. why a layer count
        was chosen).
    """

    layer_count: int
    """Total copper layer count."""

    trace_widths_m: tuple[float, ...]
    """Per-layer trace width [m]."""

    cu_thickness_m: tuple[float, ...]
    """Per-layer copper thickness [m]."""

    via_drill_m: float
    """Via drill diameter [m]."""

    via_annular_ring_m: float
    """Via annular ring width [m]."""

    via_grid_rows: int
    """Via grid row count (across board width)."""

    via_grid_cols: int
    """Via grid column count (along travel axis)."""

    estimated_force_n: float
    """Model-estimated peak linear force [N]."""

    estimated_dc_resistance_ohm: float
    """Estimated per-phase DC resistance [Ω]."""

    notes: list[str] = field(default_factory=list)
    """Optimiser notes."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.layer_count < 2 or self.layer_count % 2 != 0:
            raise ValueError(
                f"layer_count must be even and ≥ 2, got {self.layer_count}"
            )
        if len(self.trace_widths_m) != self.layer_count:
            raise ValueError(
                f"trace_widths_m must have {self.layer_count} entries, "
                f"got {len(self.trace_widths_m)}"
            )
        if len(self.cu_thickness_m) != self.layer_count:
            raise ValueError(
                f"cu_thickness_m must have {self.layer_count} entries, "
                f"got {len(self.cu_thickness_m)}"
            )
        if any(w <= 0 for w in self.trace_widths_m):
            raise ValueError("All trace widths must be positive")
        if any(t <= 0 for t in self.cu_thickness_m):
            raise ValueError("All copper thicknesses must be positive")
        if self.via_drill_m <= 0:
            raise ValueError(f"via_drill_m must be positive, got {self.via_drill_m}")
        if self.via_annular_ring_m <= 0:
            raise ValueError(
                f"via_annular_ring_m must be positive, got {self.via_annular_ring_m}"
            )
        if self.via_grid_rows < 1:
            raise ValueError(f"via_grid_rows must be ≥ 1, got {self.via_grid_rows}")
        if self.via_grid_cols < 1:
            raise ValueError(f"via_grid_cols must be ≥ 1, got {self.via_grid_cols}")

    @property
    def outer_layer_ids(self) -> tuple[int, int]:
        """Indices of the top and bottom outer copper layers."""
        return (0, self.layer_count - 1)

    @property
    def inner_layer_ids(self) -> tuple[int, ...]:
        """Indices of all inner copper layers."""
        return tuple(range(1, self.layer_count - 1))

    @property
    def via_pad_m(self) -> float:
        """Via pad diameter [m] (drill + 2 × annular ring)."""
        return self.via_drill_m + 2.0 * self.via_annular_ring_m

    @property
    def via_grid_count(self) -> int:
        """Total number of vias in one end-turn grid."""
        return self.via_grid_rows * self.via_grid_cols

    def summary(self) -> str:
        """Return a compact human-readable summary of the stackup result."""
        lines = [
            f"StackupResult: {self.layer_count} layers",
            f"  Estimated force:  {self.estimated_force_n:.3f} N",
            f"  DC resistance:    {self.estimated_dc_resistance_ohm:.3f} Ω / phase",
            f"  Via grid:         {self.via_grid_rows}×{self.via_grid_cols} "
            f"({self.via_grid_count} vias/end-turn)",
            f"  Via drill/pad:    {self.via_drill_m*1e3:.2f} / "
            f"{self.via_pad_m*1e3:.2f} mm",
            "  Layer trace widths and copper weights:",
        ]
        for i, (w, t) in enumerate(zip(self.trace_widths_m, self.cu_thickness_m)):
            role = "outer" if i in self.outer_layer_ids else "inner"
            oz = t / 35e-6  # approximate oz/ft²
            lines.append(
                f"    L{i + 1:>2} ({role}): "
                f"trace={w*1e3:.3f} mm  Cu={t*1e6:.0f} µm (~{oz:.1f} oz)"
            )
        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    • {note}")
        return "\n".join(lines)
