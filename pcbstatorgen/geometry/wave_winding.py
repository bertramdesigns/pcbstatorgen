"""
pcbstatorgen.geometry.wave_winding
=======================================
Generates rectangular 3-phase wave winding coil paths for a linear coreless
PCB stator.

Coordinate system
-----------------
* **X-axis**: travel direction (along the length of the PCB).
* **Y-axis**: perpendicular to travel (across the width of the PCB).
* All coordinates in **metres**.

Wave winding structure
----------------------
Each phase produces a continuous **serpentine** path::

    Phase A (offset x = 0, pole pitch τ = 12 mm):

      y=W  ─┬──────────┬──────────┬──
            │          │          │
            │ active   │ active   │    ← active conductors (⊥ to travel,
            │          │          │      generate force via Lorentz law)
      y=0  ─┴──────────┴──────────┴──
            x=0  τ   2τ   3τ   4τ

      Horizontal segments at y=W and y=0 are *end-turns* (parallel to travel,
      connect adjacent active conductors, generate negligible net force).

    Phase B starts at x = slot_pitch = τ/3.
    Phase C starts at x = 2·slot_pitch = 2τ/3.

End-turn overlap (multi-layer requirement)
------------------------------------------
The end-turns of adjacent phases *overlap* in the X range when they are at
the same Y edge.  Therefore each phase **must be placed on its own layer pair**
to avoid copper-to-copper shorts.  The ``WaveWindingGenerator`` produces
geometry only; layer assignment is performed by ``LayerOptimizer`` (Phase 4).

Conductor count balance
-----------------------
To keep all three phases balanced (same resistance and inductance), the
generator uses the condition::

    x_conductor ≤ active_length + (phases - 1) × slot_pitch

which ensures all phases produce the same number of active conductors despite
starting at different X offsets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from pcbstatorgen.config import CoilTopology, MotorConfig

__all__ = [
    "CoilSegment",
    "PhaseCoil",
    "WaveWindingGenerator",
    "PHASE_NAMES",
]

#: Standard phase names, indexed by phase_idx.
PHASE_NAMES: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoilSegment:
    """One straight trace segment in a coil path.

    Parameters
    ----------
    start:
        Start point ``(x, y)`` in metres.
    end:
        End point ``(x, y)`` in metres.
    is_active:
        ``True`` if this is an *active conductor* (perpendicular to travel,
        generates Lorentz force).  ``False`` if this is an *end-turn* (parallel
        to travel, connects active conductors).
    """

    start: tuple[float, float]
    end: tuple[float, float]
    is_active: bool

    @property
    def length_m(self) -> float:
        """Euclidean length of the segment [m]."""
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.hypot(dx, dy)

    @property
    def midpoint(self) -> tuple[float, float]:
        """Midpoint of the segment."""
        return (
            (self.start[0] + self.end[0]) / 2.0,
            (self.start[1] + self.end[1]) / 2.0,
        )

    def is_vertical(self, tol: float = 1e-9) -> bool:
        """True if the segment is vertical (active conductor)."""
        return abs(self.end[0] - self.start[0]) < tol

    def is_horizontal(self, tol: float = 1e-9) -> bool:
        """True if the segment is horizontal (end-turn)."""
        return abs(self.end[1] - self.start[1]) < tol


@dataclass
class PhaseCoil:
    """Complete serpentine coil path for one phase on one PCB layer.

    Parameters
    ----------
    phase_idx:
        0-based phase index (0 = A, 1 = B, 2 = C, ...).
    layer_idx:
        0-based layer index (0 = top outer layer).
    segments:
        Ordered list of :class:`CoilSegment` forming a continuous chain.
    phase_name:
        Human-readable phase name ("A", "B", "C", ...).
    """

    phase_idx: int
    layer_idx: int
    segments: list[CoilSegment]
    phase_name: str
    topology: CoilTopology = field(default=CoilTopology.SERPENTINE)
    """Coil path topology — informs the KiCad writer and the dashboard."""
    layer_pair: tuple[int, int] | None = field(default=None)
    """For SPIRAL topology: ``(primary_layer_idx, secondary_layer_idx)``.
    The primary layer holds the inward spiral; the secondary holds the
    outward return spiral.  ``None`` for all other topologies."""
    center_via_positions: list[tuple[float, float]] = field(default_factory=list)
    """(x, y) centres of spiral centre-vias [m].  Populated by
    :class:`~pcbstatorgen.geometry.coil_generators.SpiralCoilGenerator`
    so the KiCad writer knows where to place the inter-layer transition vias."""

    # ------------------------------------------------------------------
    # Derived geometry
    # ------------------------------------------------------------------

    @property
    def polyline(self) -> list[tuple[float, float]]:
        """Ordered list of all waypoints ``(x, y)`` along the coil path.

        The returned list has length ``len(segments) + 1``.
        """
        if not self.segments:
            return []
        pts: list[tuple[float, float]] = [self.segments[0].start]
        for seg in self.segments:
            pts.append(seg.end)
        return pts

    @property
    def active_segments(self) -> list[CoilSegment]:
        """All active conductor segments (perpendicular to travel)."""
        return [s for s in self.segments if s.is_active]

    @property
    def end_turn_segments(self) -> list[CoilSegment]:
        """All end-turn segments (parallel to travel)."""
        return [s for s in self.segments if not s.is_active]

    @property
    def active_conductor_count(self) -> int:
        """Number of active conductors in the coil."""
        return sum(1 for s in self.segments if s.is_active)

    @property
    def bounding_box(self) -> tuple[float, float, float, float]:
        """``(min_x, min_y, max_x, max_y)`` of all waypoints [m]."""
        pts = self.polyline
        if not pts:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def terminal_start(self) -> tuple[float, float]:
        """Electrical input terminal (first waypoint)."""
        return self.segments[0].start if self.segments else (0.0, 0.0)

    @property
    def terminal_end(self) -> tuple[float, float]:
        """Electrical output terminal (last waypoint)."""
        return self.segments[-1].end if self.segments else (0.0, 0.0)

    @property
    def total_length_m(self) -> float:
        """Total copper trace length [m]."""
        return sum(s.length_m for s in self.segments)

    @property
    def active_length_m(self) -> float:
        """Total length of active conductor segments [m]."""
        return sum(s.length_m for s in self.active_segments)

    @property
    def end_turn_length_m(self) -> float:
        """Total length of end-turn segments [m]."""
        return sum(s.length_m for s in self.end_turn_segments)

    @property
    def end_turn_midpoints_top(self) -> list[tuple[float, float]]:
        """Midpoints of all end-turns at ``y = max_y`` (top edge).

        These are the via placement reference points for top-edge layer
        transitions.
        """
        max_y = self.bounding_box[3]
        return [
            s.midpoint
            for s in self.end_turn_segments
            if abs(s.start[1] - max_y) < 1e-9
        ]

    @property
    def end_turn_midpoints_bottom(self) -> list[tuple[float, float]]:
        """Midpoints of all end-turns at ``y = min_y`` (bottom edge).

        These are the via placement reference points for bottom-edge layer
        transitions.
        """
        min_y = self.bounding_box[1]
        return [
            s.midpoint
            for s in self.end_turn_segments
            if abs(s.start[1] - min_y) < 1e-9
        ]

    def is_continuous(self, tol: float = 1e-9) -> bool:
        """Return ``True`` if every segment starts exactly where the previous ends.

        Parameters
        ----------
        tol:
            Maximum coordinate discrepancy treated as zero [m].
        """
        for i in range(len(self.segments) - 1):
            ex, ey = self.segments[i].end
            sx, sy = self.segments[i + 1].start
            if abs(ex - sx) > tol or abs(ey - sy) > tol:
                return False
        return True

    def active_conductor_x_positions(self) -> list[float]:
        """X positions of all active conductors, in order along the path [m]."""
        return [s.start[0] for s in self.active_segments]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class WaveWindingGenerator:
    """Generate rectangular wave winding coil paths for a linear motor stator.

    Each phase produces a single serpentine that covers the board width
    repeatedly, stepping by one pole pitch along the travel axis at each
    reversal.

    The class is stateless: ``generate()`` / ``generate_all_layers()`` may be
    called multiple times with different configs.

    Examples
    --------
    Basic 3-phase generation::

        gen = WaveWindingGenerator()
        coils = gen.generate(config)
        for coil in coils:
            print(coil.phase_name, coil.active_conductor_count)

    All layers with default phase assignment::

        coils = gen.generate_all_layers(config, layer_count=6)
    """

    def generate(
        self,
        config: MotorConfig,
        layer_idx: int = 0,
    ) -> list[PhaseCoil]:
        """Generate coil paths for all phases on a single layer.

        Parameters
        ----------
        config:
            Motor parameters.  The relevant fields are ``pole_pitch_m``,
            ``slot_pitch_m``, ``board_width_m``, ``active_length_m``,
            and ``phases``.
        layer_idx:
            Layer index to assign to all generated coils (default: 0).

        Returns
        -------
        list[PhaseCoil]
            One :class:`PhaseCoil` per phase, in phase order (A, B, C, …).
        """
        return [
            self._generate_phase(config, p, layer_idx)
            for p in range(config.phases)
        ]

    def generate_all_layers(
        self,
        config: MotorConfig,
        layer_count: int,
        phase_layer_map: dict[int, list[int]] | None = None,
    ) -> list[PhaseCoil]:
        """Generate coil paths for all phases on all layers.

        Parameters
        ----------
        config:
            Motor parameters.
        layer_count:
            Total number of copper layers.  Must be even (outer pair + inner
            pairs) and ≥ ``config.phases``.
        phase_layer_map:
            Optional mapping ``{phase_idx: [layer_idx, …]}``.  When omitted,
            a default interleaved assignment is used (see
            :meth:`default_phase_layer_map`).

        Returns
        -------
        list[PhaseCoil]
            All coils, sorted by layer index then phase index.

        Examples
        --------
        6-layer board with 3 phases — each phase gets 2 layers::

            gen.generate_all_layers(config, layer_count=6)
            # → phase A on layers 0,3; phase B on layers 1,4; phase C on 2,5
        """
        if layer_count < config.phases:
            raise ValueError(
                f"layer_count ({layer_count}) must be ≥ phases ({config.phases})"
            )
        if layer_count % 2 != 0:
            raise ValueError(
                f"layer_count must be even, got {layer_count}"
            )

        if phase_layer_map is None:
            phase_layer_map = self.default_phase_layer_map(config.phases, layer_count)

        coils: list[PhaseCoil] = []
        for phase_idx, layer_indices in phase_layer_map.items():
            for layer_idx in layer_indices:
                coils.append(self._generate_phase(config, phase_idx, layer_idx))
        coils.sort(key=lambda c: (c.layer_idx, c.phase_idx))
        return coils

    @staticmethod
    def default_phase_layer_map(phases: int, layer_count: int) -> dict[int, list[int]]:
        """Build the default interleaved phase→layer assignment.

        Layers are distributed in round-robin order across phases so that
        each phase gets ``layer_count // phases`` layers (plus one extra for
        the first few phases if ``layer_count`` is not divisible by
        ``phases``).

        Parameters
        ----------
        phases:
            Number of motor phases.
        layer_count:
            Total number of copper layers.

        Returns
        -------
        dict[int, list[int]]
            ``{phase_idx: [layer_idx, …]}``

        Examples
        --------
        >>> WaveWindingGenerator.default_phase_layer_map(3, 6)
        {0: [0, 3], 1: [1, 4], 2: [2, 5]}
        >>> WaveWindingGenerator.default_phase_layer_map(3, 8)
        {0: [0, 3, 6], 1: [1, 4, 7], 2: [2, 5]}
        """
        mapping: dict[int, list[int]] = {p: [] for p in range(phases)}
        for layer in range(layer_count):
            mapping[layer % phases].append(layer)
        return mapping

    @staticmethod
    def conductor_x_positions(config: MotorConfig, phase_idx: int) -> list[float]:
        """Return the X positions of all active conductors for a phase [m].

        Uses the balanced-count condition so all phases receive the same
        number of conductors despite their different X offsets.

        Parameters
        ----------
        config:
            Motor parameters.
        phase_idx:
            0-based phase index.

        Returns
        -------
        list[float]
            Sorted list of X positions in metres.
        """
        pole_pitch = config.pole_pitch_m
        slot_pitch = config.slot_pitch_m
        x_offset = phase_idx * slot_pitch
        # Allow each phase to extend up to (phases-1)*slot_pitch past active_length
        # so that the conductor count is equal across all phases.
        x_max = config.active_length_m + (config.phases - 1) * slot_pitch
        positions: list[float] = []
        x = x_offset
        while x <= x_max + 1e-9:
            positions.append(x)
            x += pole_pitch
        return positions

    def _generate_phase(
        self,
        config: MotorConfig,
        phase_idx: int,
        layer_idx: int,
    ) -> PhaseCoil:
        """Build the serpentine path for one phase on one layer.

        The path is a continuous zigzag::

            (x0, 0) → (x0, W) → (x0+τ, W) → (x0+τ, 0) → (x0+2τ, 0) → …

        where ``W = board_width_m`` and ``τ = pole_pitch_m``.
        """
        board_width = config.board_width_m
        pole_pitch = config.pole_pitch_m
        x_positions = self.conductor_x_positions(config, phase_idx)

        if not x_positions:
            phase_name = PHASE_NAMES[phase_idx % len(PHASE_NAMES)]
            return PhaseCoil(
                phase_idx=phase_idx,
                layer_idx=layer_idx,
                segments=[],
                phase_name=phase_name,
                topology=CoilTopology.SERPENTINE,
            )

        segments: list[CoilSegment] = []
        going_up = True  # first active conductor: y=0 → y=board_width

        for k, x in enumerate(x_positions):
            y_start = 0.0 if going_up else board_width
            y_end = board_width if going_up else 0.0

            # Active conductor (perpendicular to travel axis)
            segments.append(CoilSegment(
                start=(x, y_start),
                end=(x, y_end),
                is_active=True,
            ))

            # End-turn to the next conductor (if one exists)
            if k < len(x_positions) - 1:
                x_next = x_positions[k + 1]
                y_edge = board_width if going_up else 0.0
                segments.append(CoilSegment(
                    start=(x, y_edge),
                    end=(x_next, y_edge),
                    is_active=False,
                ))

            going_up = not going_up

        phase_name = PHASE_NAMES[phase_idx % len(PHASE_NAMES)]
        return PhaseCoil(
            phase_idx=phase_idx,
            layer_idx=layer_idx,
            segments=segments,
            phase_name=phase_name,
            topology=CoilTopology.SERPENTINE,
        )
