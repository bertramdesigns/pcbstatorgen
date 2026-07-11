"""
pcbstatorgen.config
===================
Central configuration dataclasses and result types for the PCB stator generator.

All physical quantities are stored in SI units: metres, Tesla, Amperes, Ohms,
Watts.  Use :mod:`pcbstatorgen.units` helpers to build values from
human-readable inputs (mm, mils, oz/ft²).

Class hierarchy
---------------
:class:`BaseMotorConfig`
    Shared parameters for every PCB motor topology (magnetics, drive
    electronics, PCB manufacturing rules).

    :class:`LinearMotorConfig` ← **use this for flying fader / linear motors**
        Adds travel, board width, friction, and force targets.
        Aliased as :data:`MotorConfig` for backwards compatibility.

    :class:`AxialMotorConfig`
        Stub for future axial flux rotary motors (disk stators).
        Raises ``NotImplementedError`` until Phase F is implemented.

Enums
-----
:class:`MagnetArrangement`
    How the permanent magnets are arranged on the carriage.

:class:`CoilTopology`
    The conductor path pattern used on the PCB stator.

Result dataclasses
------------------
:class:`StackupResult`
    Computed PCB layer stackup from the LayerOptimizer.
:class:`HeightStackResult`
    Explicit vertical stack from PCB bottom to magnet top.
:class:`FrictionBudget`
    Breakdown of mechanical friction contributors.
:class:`PowerBudget`
    Continuous and burst power analysis.

Example
-------
Build a configuration for a 75 mm studio fader::

    from pcbstatorgen.config import LinearMotorConfig
    from pcbstatorgen.units import mm, mils_to_m

    cfg = LinearMotorConfig(
        travel_m=mm(75),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        target_force_n=0.25,      # 250 mN continuous
        peak_force_n=0.5,         # 500 mN burst
        friction_n=0.08,          # 80 mN estimated bearing + FFC
    )
    print(cfg.summary())
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from pcbstatorgen.units import mm, mils_to_m, oz_to_m

__all__ = [
    # Enums
    "MagnetArrangement",
    "CoilTopology",
    # Config classes
    "BaseMotorConfig",
    "LinearMotorConfig",
    "AxialMotorConfig",
    "MotorConfig",          # backwards-compatible alias for LinearMotorConfig
    # Result dataclasses
    "StackupResult",
    "HeightStackResult",
    "FrictionBudget",
    "PowerBudget",
]

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

_SAFETY_MARGIN = 1.3  # minimum drive force = friction × this factor


class MagnetArrangement(Enum):
    """Permanent magnet arrangement on the carriage.

    Affects achievable field strength at the PCB surface and carriage cost.

    Approximate force multipliers vs ALTERNATING baseline (same magnet volume,
    same current):

    * ``ALTERNATING``            → 1.0× (baseline)
    * ``ALTERNATING_BACK_IRON``  → 1.35–1.5× (+1 mm CRS steel keeper)
    * ``HALBACH``                → 1.35–1.55× (√2 ideal, finite-length practical)
    * ``HALBACH_BACK_IRON``      → 1.55–1.8× (diminishing returns — Halbach
                                              already self-cancels rear flux)
    """

    ALTERNATING = auto()
    """Simple alternating ±Z poles.  Cheapest, lowest force density."""

    ALTERNATING_BACK_IRON = auto()
    """Simple poles with a steel keeper on the rear face.  ~1.4× boost."""

    HALBACH = auto()
    """Halbach array: interleaved X-polarised magnets concentrate flux on the
    stator face, self-cancelling on the rear.  ~1.4× boost, no extra height."""

    HALBACH_BACK_IRON = auto()
    """Halbach + steel keeper.  Maximum force/height ratio, +1 mm height cost."""


class CoilTopology(Enum):
    """PCB stator conductor path topology.

    All four options produce :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil`
    objects and are consumed identically by the Magpylib force model and the
    KiCad writer.

    Quick comparison for a 3-phase linear motor:

    +----------------+------------------+-------------------+-------------------+
    | Topology       | Fill factor      | End-turn overhead | Force vs serp.    |
    +================+==================+===================+===================+
    | SERPENTINE     | ~80 % (highest)  | ~10 %             | 1.0× baseline     |
    +----------------+------------------+-------------------+-------------------+
    | CONCENTRATED   | ~55 %            | ~35–50 %          | ~0.65×            |
    +----------------+------------------+-------------------+-------------------+
    | RHOMBIC        | ~65 %            | ~20 %             | ~0.85× (low ripple|
    +----------------+------------------+-------------------+-------------------+
    | SPIRAL         | ~50 % (linear)   | center-via only   | ~0.60× (linear)   |
    +----------------+------------------+-------------------+-------------------+

    ``SPIRAL`` is primarily suited for **axial flux** disk stators.  For linear
    motors it is provided as a geometric stub; force estimates carry higher
    uncertainty because angled conductors reduce the Lorentz coupling.
    """

    SERPENTINE = "serpentine"
    """Continuous zigzag wave winding.  Highest fill factor.
    Recommended for production linear motors."""

    CONCENTRATED = "concentrated"
    """Individual rectangular coil loops, one per pole pair per phase.
    Simple to route and understand.  Good for prototypes."""

    RHOMBIC = "rhombic"
    """Diamond-shaped coils with angled active conductors.  Produces a naturally
    sinusoidal back-EMF → lower force ripple than CONCENTRATED without the
    layer complexity of SERPENTINE."""

    SPIRAL = "spiral"
    """Flat Archimedean spiral coils.  In-out layer pair required (spiral in on
    layer N, via at centre, spiral out on layer N+1).  Native topology for
    axial flux disk stators.  Linear motor support is a geometric stub.

    .. note::
        Spiral coils **require** layer pairs for the in-out return path.
        The :class:`~pcbstatorgen.geometry.coil_generators.SpiralCoilGenerator`
        automatically allocates centre vias and sets ``layer_pair`` metadata on
        each :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil`.
    """


# ---------------------------------------------------------------------------
# BaseMotorConfig
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class BaseMotorConfig:
    """Shared parameters for all PCB motor topologies.

    Do not instantiate directly — use :class:`LinearMotorConfig` (for
    flying faders / linear stages) or :class:`AxialMotorConfig` (for future
    disk-stator rotary motors).

    All length fields are in **metres**, flux density in **Tesla**, current in
    **Amperes**.  Use :mod:`pcbstatorgen.units` helpers (``mm``, ``mils_to_m``,
    ``oz_to_m``) when constructing from human-readable values.

    Parameters
    ----------
    magnet_dims_m:
        ``(width_travel, width_cross, height)`` of a single magnet [m].
        *width_travel* is along the travel/circumferential axis; *width_cross*
        is the dimension across the stator; *height* is the out-of-plane
        dimension toward the PCB.  Default: 10 × 10 × 4 mm (typical N44H).
    magnet_count:
        Number of magnets in the array.  Must be even for a symmetric
        alternating-pole arrangement.  Default: 10.
    magnet_pitch_m:
        Centre-to-centre magnet spacing along the travel axis [m].  Equals
        one pole pitch.  Must be ≥ ``magnet_dims_m[0] + 0.3 mm`` for assembly
        clearance.  Default: 12 mm.
    magnet_remanence_t:
        Remnant flux density **Br** at operating temperature [T].
        N44H at 20 °C: 1.32–1.38 T.  Default: 1.35 T.
    magnet_arrangement:
        Pole/flux-concentrator arrangement.  See :class:`MagnetArrangement`.
        Default: ``ALTERNATING``.
    back_iron_thickness_m:
        Thickness of the CRS steel keeper on the non-stator face of the
        magnets [m].  ``0.0`` = no back-iron.  Default: 0 mm.
    air_gap_m:
        Clearance from the magnet face to the nearest PCB copper surface [m].
        Smaller gap → exponentially stronger field.  Minimum practical value
        ≈ assembly tolerance + bearing runout (0.2–0.3 mm).  Default: 0.5 mm.
    coil_topology:
        PCB conductor path pattern.  See :class:`CoilTopology`.
        Default: ``SERPENTINE``.
    phases:
        Number of electrical phases.  3 for standard 3-phase BLDC.
        Default: 3.
    max_current_a:
        Peak phase current from the drive circuit [A].  Default: 1.0 A.
    supply_voltage_v:
        Drive electronics supply voltage [V].  Used for power budget and
        capacitor bank sizing.  Default: 5.0 V.
    min_trace_m:
        Minimum manufacturable trace width [m].  JLCPCB standard 4-layer:
        0.127 mm (5 mil).  Default: 5 mil.
    min_space_m:
        Minimum trace-to-trace clearance [m].  Default: 5 mil.
    min_via_drill_m:
        Minimum via drill diameter [m].  JLCPCB standard: 0.2 mm.
    min_via_annular_ring_m:
        Minimum copper annular ring width [m].  Default: 0.1 mm.
    max_layers:
        Hard upper limit on copper layers the optimizer may consider.
        Must be even.  Default: 12.
    drive_frequency_hz:
        Nominal electrical drive frequency at rated speed [Hz].  Used for
        skin-depth calculations.  For a fader at 0.1 m/s with 12 mm pole
        pitch: f ≈ 8 Hz; use 500 Hz as a conservative PWM-harmonic bound.
        Default: 500 Hz.
    max_temperature_rise_c:
        Maximum acceptable PCB temperature rise above ambient [°C].
        Used by the thermal model to verify copper sizing.  Default: 20 °C.
    name:
        Optional human-readable label.
    """

    magnet_dims_m: tuple[float, float, float] = field(
        default_factory=lambda: (mm(10), mm(10), mm(4))
    )
    """(width_travel, width_cross, height) of one magnet [m]."""

    magnet_count: int = 10
    """Number of magnets in the array (must be even)."""

    magnet_pitch_m: float = field(default_factory=lambda: mm(12))
    """Centre-to-centre magnet spacing = pole pitch [m]."""

    magnet_remanence_t: float = 1.35
    """Remnant flux density Br at 20 °C [T]."""

    magnet_arrangement: MagnetArrangement = MagnetArrangement.ALTERNATING
    """Pole/flux-concentrator arrangement."""

    back_iron_thickness_m: float = 0.0
    """CRS steel keeper thickness on rear face of magnets [m]."""

    air_gap_m: float = field(default_factory=lambda: mm(0.5))
    """Magnet face to PCB copper clearance [m]."""

    coil_topology: CoilTopology = CoilTopology.SERPENTINE
    """PCB stator conductor path topology."""

    phases: int = 3
    """Number of electrical phases."""

    max_current_a: float = 1.0
    """Peak phase current [A]."""

    supply_voltage_v: float = 5.0
    """Drive electronics supply voltage [V]."""

    min_trace_m: float = field(default_factory=lambda: mils_to_m(5))
    """Minimum trace width [m]."""

    min_space_m: float = field(default_factory=lambda: mils_to_m(5))
    """Minimum trace-to-trace clearance [m]."""

    min_via_drill_m: float = field(default_factory=lambda: mm(0.2))
    """Minimum via drill diameter [m]."""

    min_via_annular_ring_m: float = field(default_factory=lambda: mm(0.1))
    """Minimum annular ring width [m]."""

    max_layers: int = 12
    """Maximum copper layer count for the optimizer."""

    drive_frequency_hz: float = 500.0
    """Nominal electrical drive frequency for skin-depth calculation [Hz]."""

    max_temperature_rise_c: float = 20.0
    """Maximum acceptable PCB temperature rise above ambient [°C]."""

    name: Optional[str] = None
    """Optional human-readable label."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        self._validate_base()

    def _validate_base(self) -> None:
        """Validate fields common to all motor topologies."""
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
        # Assembly gap: at least 0.3 mm clearance between adjacent magnets.
        # Tolerance of 1e-10 m (~0.1 pm) absorbs float representation of mm(0.3).
        assembly_gap_m = self.magnet_pitch_m - self.magnet_dims_m[0]
        if assembly_gap_m < mm(0.3) - 1e-10:
            raise ValueError(
                f"magnet_pitch_m ({self.magnet_pitch_m * 1e3:.2f} mm) too close to "
                f"magnet width ({self.magnet_dims_m[0] * 1e3:.2f} mm) — "
                f"inter-magnet assembly gap must be ≥ 0.3 mm "
                f"(current gap: {assembly_gap_m * 1e3:.2f} mm)"
            )
        if self.magnet_remanence_t <= 0 or self.magnet_remanence_t > 2.5:
            raise ValueError(
                f"magnet_remanence_t must be in (0, 2.5] T, got {self.magnet_remanence_t}"
            )
        if self.phases < 1:
            raise ValueError(f"phases must be ≥ 1, got {self.phases}")
        if self.max_current_a <= 0:
            raise ValueError(f"max_current_a must be positive, got {self.max_current_a}")
        if self.supply_voltage_v <= 0:
            raise ValueError(f"supply_voltage_v must be positive, got {self.supply_voltage_v}")
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
        if self.air_gap_m < 0:
            raise ValueError(f"air_gap_m must be ≥ 0, got {self.air_gap_m}")
        if self.back_iron_thickness_m < 0:
            raise ValueError(
                f"back_iron_thickness_m must be ≥ 0, got {self.back_iron_thickness_m}"
            )
        if self.max_layers < 2 or self.max_layers % 2 != 0:
            raise ValueError(
                f"max_layers must be an even number ≥ 2, got {self.max_layers}"
            )
        if self.drive_frequency_hz <= 0:
            raise ValueError(
                f"drive_frequency_hz must be positive, got {self.drive_frequency_hz}"
            )
        if self.max_temperature_rise_c <= 0:
            raise ValueError(
                f"max_temperature_rise_c must be positive, got {self.max_temperature_rise_c}"
            )

    # ------------------------------------------------------------------
    # Derived geometry (shared)
    # ------------------------------------------------------------------

    @property
    def pole_pitch_m(self) -> float:
        """Magnet pole pitch [m] (= ``magnet_pitch_m`` for alternating arrays)."""
        return self.magnet_pitch_m

    @property
    def slot_pitch_m(self) -> float:
        """Coil slot pitch = pole_pitch / phases [m]."""
        return self.pole_pitch_m / self.phases

    @property
    def min_via_pad_m(self) -> float:
        """Minimum via pad diameter [m] (drill + 2 × annular ring)."""
        return self.min_via_drill_m + 2.0 * self.min_via_annular_ring_m


# ---------------------------------------------------------------------------
# LinearMotorConfig
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class LinearMotorConfig(BaseMotorConfig):
    """Configuration for a **linear** PCB coreless motor (flying fader).

    Extends :class:`BaseMotorConfig` with travel geometry, board dimensions,
    friction budget, and separate continuous / burst force targets.

    Parameters
    ----------
    travel_m:
        Total fader travel range [m].  Typical: 60–100 mm.
    board_width_m:
        PCB width perpendicular to the travel axis [m].  Constrains coil
        winding depth.  Default: 20 mm.
    pcb_thickness_m:
        PCB substrate thickness [m].  Used in height-stack calculations.
        Default: 1.6 mm (standard FR4).
    target_force_n:
        Minimum **continuous** thrust the stator must deliver at
        ``max_current_a`` [N].  This is the force the motor produces during
        steady-state position hold or slow automation moves.  Default: 0.5 N.
    peak_force_n:
        **Burst** thrust target for fast automation moves [N].  Must be ≥
        ``target_force_n``.  The burst is short-duration (< 200 ms) and can
        be sourced from a capacitor bank.  Default: 1.0 N.
    friction_n:
        Estimated total mechanical friction of the fader assembly [N].
        Includes bearing friction, cable drag, and (if applicable) wiper
        contact spring force.  Used by :class:`FrictionBudget` and the
        LayerOptimizer to compute the *minimum drive force* = friction ×
        1.3 safety margin.  Default: 0.05 N (50 mN — ball bearing estimate).
    carriage_mass_kg:
        Mass of the moving carriage (knob + magnets + hardware) [kg].
        Used to compute the acceleration force budget.  Default: 15 g.
    max_accel_m_s2:
        Maximum carriage acceleration [m/s²].  Sets peak inertial force
        requirement.  Default: 2 m/s².
    capacitor_bank_uf:
        Burst-current capacitor bank size [µF].  Sized to supply ``peak_force_n``
        current for ~100 ms without excessive voltage droop.
        Default: 1000 µF.
    """

    # Required — no sensible universal default
    travel_m: float

    # Optional with defaults
    board_width_m: float = field(default_factory=lambda: mm(20))
    """PCB dimension perpendicular to the travel axis [m]."""

    pcb_thickness_m: float = 0.0016
    """PCB substrate thickness [m]."""

    target_force_n: float = 0.5
    """Minimum continuous thrust [N]."""

    peak_force_n: float = 1.0
    """Burst thrust target [N] (must be ≥ target_force_n)."""

    friction_n: float = 0.05
    """Estimated total mechanical friction [N]."""

    carriage_mass_kg: float = 0.015
    """Moving carriage mass [kg]."""

    max_accel_m_s2: float = 2.0
    """Maximum carriage acceleration [m/s²]."""

    capacitor_bank_uf: float = 1000.0
    """Burst-current capacitor bank size [µF]."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        super().__post_init__()   # runs _validate_base()
        self._validate_linear()

    def _validate_linear(self) -> None:
        """Validate fields specific to linear motors."""
        if self.travel_m <= 0:
            raise ValueError(f"travel_m must be positive, got {self.travel_m}")
        if self.board_width_m <= 0:
            raise ValueError(f"board_width_m must be positive, got {self.board_width_m}")
        if self.pcb_thickness_m <= 0:
            raise ValueError(f"pcb_thickness_m must be positive, got {self.pcb_thickness_m}")
        if self.target_force_n <= 0:
            raise ValueError(f"target_force_n must be positive, got {self.target_force_n}")
        if self.peak_force_n < self.target_force_n:
            raise ValueError(
                f"peak_force_n ({self.peak_force_n:.3f} N) must be ≥ "
                f"target_force_n ({self.target_force_n:.3f} N)"
            )
        if self.friction_n < 0:
            raise ValueError(f"friction_n must be ≥ 0, got {self.friction_n}")
        if self.carriage_mass_kg <= 0:
            raise ValueError(f"carriage_mass_kg must be positive, got {self.carriage_mass_kg}")
        if self.max_accel_m_s2 <= 0:
            raise ValueError(f"max_accel_m_s2 must be positive, got {self.max_accel_m_s2}")
        if self.capacitor_bank_uf <= 0:
            raise ValueError(f"capacitor_bank_uf must be positive, got {self.capacitor_bank_uf}")

    # ------------------------------------------------------------------
    # Derived geometry
    # ------------------------------------------------------------------

    @property
    def coil_span_m(self) -> float:
        """Full span of the active winding region [m].

        ``magnet_count × magnet_pitch_m``.  The coil must cover this span so
        that magnets stay over the winding at both travel extremes.
        """
        return self.magnet_count * self.magnet_pitch_m

    @property
    def active_length_m(self) -> float:
        """Minimum PCB length required [m].

        ``travel_m + coil_span_m``: the coil must extend past both ends of the
        travel range to prevent force drop-off at the extremes.
        """
        return self.travel_m + self.coil_span_m

    @property
    def acceleration_force_n(self) -> float:
        """Peak inertial force to accelerate the carriage [N].

        ``carriage_mass_kg × max_accel_m_s2``.
        """
        return self.carriage_mass_kg * self.max_accel_m_s2

    @property
    def minimum_drive_force_n(self) -> float:
        """Minimum motor force to overcome friction with a safety margin [N].

        ``friction_n × 1.3``.  The position-control loop must produce at least
        this much force before any useful motion begins.
        """
        return self.friction_n * _SAFETY_MARGIN

    def summary(self) -> str:
        """Return a compact human-readable summary of key parameters."""
        arrangement_label = {
            MagnetArrangement.ALTERNATING: "alternating poles",
            MagnetArrangement.ALTERNATING_BACK_IRON: "alternating + back-iron",
            MagnetArrangement.HALBACH: "Halbach array",
            MagnetArrangement.HALBACH_BACK_IRON: "Halbach + back-iron",
        }[self.magnet_arrangement]
        topology_label = self.coil_topology.value
        lines = [
            f"LinearMotorConfig: {self.name or '(unnamed)'}",
            f"  Travel:          {self.travel_m * 1e3:.1f} mm",
            f"  Active length:   {self.active_length_m * 1e3:.1f} mm",
            f"  Magnet:          {self.magnet_count}× N44H "
            f"{self.magnet_dims_m[0]*1e3:.0f}×"
            f"{self.magnet_dims_m[1]*1e3:.0f}×"
            f"{self.magnet_dims_m[2]*1e3:.0f} mm  "
            f"Br={self.magnet_remanence_t:.2f} T",
            f"  Arrangement:     {arrangement_label}",
            f"  Coil topology:   {topology_label}",
            f"  Pole pitch:      {self.pole_pitch_m * 1e3:.1f} mm",
            f"  Slot pitch:      {self.slot_pitch_m * 1e3:.2f} mm  ({self.phases}-phase)",
            f"  Air gap:         {self.air_gap_m * 1e3:.2f} mm",
            f"  Board width:     {self.board_width_m * 1e3:.1f} mm",
            f"  Target force:    {self.target_force_n * 1e3:.0f} mN continuous  "
            f"/ {self.peak_force_n * 1e3:.0f} mN peak",
            f"  Friction est.:   {self.friction_n * 1e3:.0f} mN  "
            f"(min drive: {self.minimum_drive_force_n * 1e3:.0f} mN)",
            f"  Accel. budget:   {self.acceleration_force_n * 1e3:.0f} mN  "
            f"({self.carriage_mass_kg * 1e3:.0f} g × {self.max_accel_m_s2:.1f} m/s²)",
            f"  Current:         {self.max_current_a:.1f} A  @ {self.supply_voltage_v:.1f} V",
            f"  Cap. bank:       {self.capacitor_bank_uf:.0f} µF",
            f"  Min trace/space: {self.min_trace_m * 1e3:.3f} / "
            f"{self.min_space_m * 1e3:.3f} mm",
            f"  Via drill/ring:  {self.min_via_drill_m * 1e3:.2f} / "
            f"{self.min_via_annular_ring_m * 1e3:.2f} mm",
            f"  Drive freq:      {self.drive_frequency_hz:.0f} Hz",
            f"  Max ΔT:          {self.max_temperature_rise_c:.0f} °C",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# AxialMotorConfig  (stub — Phase F)
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class AxialMotorConfig(BaseMotorConfig):
    """Configuration for a future **axial flux** rotary PCB motor.

    .. admonition:: Not yet implemented

        This class is a design stub.  Instantiating it raises
        :exc:`NotImplementedError`.  See the TODO block below for the full
        list of work required before this class is functional.

    # TODO(axial-motor — GitHub Issue #axial): Implement AxialMotorConfig.
    #   The following must be completed before any instance can be used:
    #
    #   1. CoilTopology.SPIRAL generator (SpiralCoilGenerator) — the natural
    #      coil topology for disk stators (in-out layer-pair winding).
    #   2. Annular geometry in WaveWindingGenerator / SpiralCoilGenerator —
    #      conductors must follow circular arcs, not straight lines.
    #   3. MagnetArray updated to arrange Cuboid magnets in a ring at the
    #      correct radial positions, not a linear array.
    #   4. ForceEvaluator updated to compute *torque* [N·m] instead of linear
    #      force [N]; uses magpy.getFT() with a rotational pivot.
    #   5. LayerOptimizer constraints adapted for disk geometry (annular area,
    #      circumferential slot pitch at mean radius).
    #   6. KiCad writer updated to emit a circular board outline.
    #   7. HeightStackResult extended for the dual-sided axial flux gap.
    #   Tracked in GitHub Issue #axial-motor.

    Parameters
    ----------
    stator_OD_m:
        Stator disk outer diameter [m].
    stator_ID_m:
        Stator disk inner diameter (shaft bore clearance) [m].
    rated_speed_rpm:
        Continuous rated shaft speed [RPM].
    target_torque_nm:
        Minimum continuous output torque [N·m].
    peak_torque_nm:
        Burst torque target [N·m].  Must be ≥ ``target_torque_nm``.
    rotor_inertia_kgm2:
        Rotor disk rotational inertia [kg·m²].  Affects bandwidth.
    magnet_skew_deg:
        Rotor magnet skew angle to reduce cogging torque [degrees].
        0 = no skew.
    """

    stator_OD_m: float = field(default_factory=lambda: mm(80))
    stator_ID_m: float = field(default_factory=lambda: mm(30))
    rated_speed_rpm: float = 3000.0
    target_torque_nm: float = 0.1
    peak_torque_nm: float = 0.3
    rotor_inertia_kgm2: float = 1e-5
    magnet_skew_deg: float = 0.0

    def __post_init__(self) -> None:
        raise NotImplementedError(
            "AxialMotorConfig is not yet implemented.  "
            "See the TODO block in this class docstring and "
            "GitHub Issue #axial-motor for the full implementation checklist."
        )


# ---------------------------------------------------------------------------
# Backwards-compatible alias
# ---------------------------------------------------------------------------

#: Alias for :class:`LinearMotorConfig`.
#:
#: All existing code that imports or instantiates ``MotorConfig`` continues to
#: work without modification.  New code should prefer ``LinearMotorConfig``
#: directly to make the motor topology explicit.
MotorConfig = LinearMotorConfig


# ---------------------------------------------------------------------------
# StackupResult  (unchanged from Phase 1)
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
        Total number of copper layers (always even).
    trace_widths_m:
        Per-layer trace width [m].  Outer layers are narrower (pyramid scheme).
    cu_thickness_m:
        Per-layer copper thickness [m].
    via_drill_m:
        Recommended via drill diameter [m].
    via_annular_ring_m:
        Recommended via annular ring width [m].
    via_grid_rows:
        Number of via rows in the end-turn grid.
    via_grid_cols:
        Number of via columns in the end-turn grid.
    estimated_force_n:
        Model-estimated peak linear force [N].
    estimated_dc_resistance_ohm:
        Estimated per-phase DC resistance [Ω].
    notes:
        Human-readable notes from the optimiser.
    """

    layer_count: int
    trace_widths_m: tuple[float, ...]
    cu_thickness_m: tuple[float, ...]
    via_drill_m: float
    via_annular_ring_m: float
    via_grid_rows: int
    via_grid_cols: int
    estimated_force_n: float
    estimated_dc_resistance_ohm: float
    notes: list[str] = field(default_factory=list)

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
        return (0, self.layer_count - 1)

    @property
    def inner_layer_ids(self) -> tuple[int, ...]:
        return tuple(range(1, self.layer_count - 1))

    @property
    def via_pad_m(self) -> float:
        return self.via_drill_m + 2.0 * self.via_annular_ring_m

    @property
    def via_grid_count(self) -> int:
        return self.via_grid_rows * self.via_grid_cols

    def summary(self) -> str:
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
            oz = t / 35e-6
            lines.append(
                f"    L{i + 1:>2} ({role}): "
                f"trace={w*1e3:.3f} mm  Cu={t*1e6:.0f} µm (~{oz:.1f} oz)"
            )
        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    • {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# HeightStackResult
# ---------------------------------------------------------------------------


@dataclass
class HeightStackResult:
    """Explicit vertical stack from PCB bottom surface to magnet top face.

    Used by the wizard UI and the LayerOptimizer to verify that a design fits
    within the product's height budget.

    All dimensions in metres.

    Parameters
    ----------
    pcb_thickness_m:
        PCB substrate thickness [m].
    cu_protrusion_m:
        Outer copper layer protrusion above the substrate surface [m].
        Typically 35 µm (1 oz) or 70 µm (2 oz).
    solder_mask_m:
        Solder mask thickness [m].  Nominal LPI: ~20 µm.
    air_gap_m:
        Clearance from PCB copper surface to magnet bottom face [m].
    magnet_height_m:
        Magnet height (dimension toward the PCB) [m].
    back_iron_thickness_m:
        Steel keeper thickness [m].  0.0 if no back-iron.
    tolerance_m:
        Assembly margin (positional variance, adhesive fillet) [m].
    """

    pcb_thickness_m: float
    cu_protrusion_m: float
    solder_mask_m: float
    air_gap_m: float
    magnet_height_m: float
    back_iron_thickness_m: float
    tolerance_m: float

    def __post_init__(self) -> None:
        for name, val in [
            ("pcb_thickness_m", self.pcb_thickness_m),
            ("cu_protrusion_m", self.cu_protrusion_m),
            ("solder_mask_m", self.solder_mask_m),
            ("air_gap_m", self.air_gap_m),
            ("magnet_height_m", self.magnet_height_m),
            ("tolerance_m", self.tolerance_m),
        ]:
            if val < 0:
                raise ValueError(f"{name} must be ≥ 0, got {val}")
        if self.back_iron_thickness_m < 0:
            raise ValueError(
                f"back_iron_thickness_m must be ≥ 0, got {self.back_iron_thickness_m}"
            )

    @property
    def total_height_m(self) -> float:
        """Total stack height from PCB bottom to magnet top [m]."""
        return (
            self.pcb_thickness_m
            + self.cu_protrusion_m
            + self.solder_mask_m
            + self.air_gap_m
            + self.magnet_height_m
            + self.back_iron_thickness_m
            + self.tolerance_m
        )

    def fits_in_budget(self, budget_m: float) -> bool:
        """Return ``True`` if the total stack fits within ``budget_m``."""
        return self.total_height_m <= budget_m

    def headroom_m(self, budget_m: float) -> float:
        """Remaining height headroom [m]  (negative means over budget)."""
        return budget_m - self.total_height_m

    def summary(self) -> str:
        lines = [
            "HeightStackResult:",
            f"  PCB substrate:    {self.pcb_thickness_m * 1e3:.2f} mm",
            f"  Cu protrusion:    {self.cu_protrusion_m * 1e6:.0f} µm",
            f"  Solder mask:      {self.solder_mask_m * 1e6:.0f} µm",
            f"  Air gap:          {self.air_gap_m * 1e3:.2f} mm",
            f"  Magnet height:    {self.magnet_height_m * 1e3:.2f} mm",
        ]
        if self.back_iron_thickness_m > 0:
            lines.append(f"  Back-iron:        {self.back_iron_thickness_m * 1e3:.2f} mm")
        lines += [
            f"  Tolerance:        {self.tolerance_m * 1e3:.2f} mm",
            f"  ─────────────────────────────",
            f"  Total height:     {self.total_height_m * 1e3:.2f} mm",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FrictionBudget
# ---------------------------------------------------------------------------


@dataclass
class FrictionBudget:
    """Breakdown of mechanical friction contributors in the fader assembly.

    The dominant contributor is usually bearing friction driven by the
    magnetic normal (pull-in) force:
    ``F_bearing = µ_bearing × F_normal_magnetic``

    Typical values by bearing type:

    * Plastic channel guide:  µ ≈ 0.25 → 1500–3000 mN at 10 N normal force
    * PTFE-lined guide:       µ ≈ 0.12 → 600–1500 mN
    * Linear ball bearing:    µ ≈ 0.003 → 30–80 mN  ← studio-quality target

    Parameters
    ----------
    bearing_friction_n:
        Friction from the linear bearing/guide [N].
    cable_drag_n:
        Estimated FFC (flat flexible cable) drag [N].
        Empirical: ~0.02 N per conductor.
    wiper_contact_n:
        Potentiometer wiper contact spring force [N].
        0.0 if non-contact sensing (magnetic encoder, optical).
    cogging_n:
        Reluctance detent / cogging force [N].  Near zero for coreless designs.
    """

    bearing_friction_n: float
    cable_drag_n: float
    wiper_contact_n: float = 0.0
    cogging_n: float = 0.0

    def __post_init__(self) -> None:
        for name, val in [
            ("bearing_friction_n", self.bearing_friction_n),
            ("cable_drag_n", self.cable_drag_n),
            ("wiper_contact_n", self.wiper_contact_n),
            ("cogging_n", self.cogging_n),
        ]:
            if val < 0:
                raise ValueError(f"{name} must be ≥ 0, got {val}")

    @property
    def total_n(self) -> float:
        """Total friction force [N]."""
        return (
            self.bearing_friction_n
            + self.cable_drag_n
            + self.wiper_contact_n
            + self.cogging_n
        )

    @property
    def minimum_drive_force_n(self) -> float:
        """Minimum motor force to start motion with a 1.3× safety margin [N]."""
        return self.total_n * _SAFETY_MARGIN

    def summary(self) -> str:
        lines = [
            "FrictionBudget:",
            f"  Bearing friction: {self.bearing_friction_n * 1e3:.1f} mN",
            f"  Cable drag:       {self.cable_drag_n * 1e3:.1f} mN",
            f"  Wiper contact:    {self.wiper_contact_n * 1e3:.1f} mN",
            f"  Cogging:          {self.cogging_n * 1e3:.1f} mN",
            f"  ─────────────────────────────",
            f"  Total:            {self.total_n * 1e3:.1f} mN",
            f"  Min drive force:  {self.minimum_drive_force_n * 1e3:.1f} mN  (×{_SAFETY_MARGIN} margin)",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# PowerBudget
# ---------------------------------------------------------------------------


@dataclass
class PowerBudget:
    """Continuous and burst power analysis for the stator drive circuit.

    Computed by :class:`pcbstatorgen.stackup.power.PowerEstimator` (Phase B2).
    Stored here as a plain result dataclass for UI display and logging.

    Parameters
    ----------
    phase_resistance_ohm:
        Estimated per-phase DC winding resistance [Ω].
    continuous_power_w:
        Copper loss at rated continuous current [W].  ``I²R`` per phase × phases.
    burst_power_w:
        Copper loss at peak burst current [W].
    temperature_rise_c:
        Estimated PCB temperature rise at continuous current [°C] (IPC-2152).
    capacitor_required_uf:
        Minimum capacitor bank to supply burst current for 100 ms [µF].
    efficiency_pct:
        Mechanical efficiency at rated speed [%].
        ``(F × v_rated) / (V × I) × 100``.  Typically 2–15 % for a
        short-stroke positioning device.
    """

    phase_resistance_ohm: float
    continuous_power_w: float
    burst_power_w: float
    temperature_rise_c: float
    capacitor_required_uf: float
    efficiency_pct: float

    def __post_init__(self) -> None:
        for name, val in [
            ("phase_resistance_ohm", self.phase_resistance_ohm),
            ("continuous_power_w", self.continuous_power_w),
            ("burst_power_w", self.burst_power_w),
            ("temperature_rise_c", self.temperature_rise_c),
            ("capacitor_required_uf", self.capacitor_required_uf),
        ]:
            if val < 0:
                raise ValueError(f"{name} must be ≥ 0, got {val}")
        if not (0 <= self.efficiency_pct <= 100):
            raise ValueError(
                f"efficiency_pct must be in [0, 100], got {self.efficiency_pct}"
            )

    def summary(self) -> str:
        lines = [
            "PowerBudget:",
            f"  Phase resistance:  {self.phase_resistance_ohm:.3f} Ω",
            f"  Continuous loss:   {self.continuous_power_w * 1e3:.0f} mW",
            f"  Burst loss:        {self.burst_power_w * 1e3:.0f} mW",
            f"  Temperature rise:  +{self.temperature_rise_c:.1f} °C",
            f"  Capacitor needed:  {self.capacitor_required_uf:.0f} µF",
            f"  Efficiency (peak): {self.efficiency_pct:.1f} %",
        ]
        return "\n".join(lines)
