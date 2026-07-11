"""
pcbstatorgen.geometry.coil_generators
======================================
Concentrated, Rhombic, and Spiral coil generators for the PCB stator.

All three generators produce :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil`
objects — the same data structure used by the Magpylib force model and the
KiCad writer — so topology comparison is a single argument change:

.. code-block:: python

    from pcbstatorgen.geometry.coil_generators import make_coil_generator
    from pcbstatorgen.config import CoilTopology

    for topo in CoilTopology:
        gen = make_coil_generator(topo)
        coils = gen.generate(config)
        result = ForceEvaluator(n_positions=10).evaluate(config, coils)
        print(topo.value, result.summary())

Topology summary
----------------

**SERPENTINE** (see :class:`~pcbstatorgen.geometry.wave_winding.WaveWindingGenerator`)
    Continuous zigzag.  Highest fill factor.  End-turns at board edges only.
    Each phase on its own layer pair (end-turns of different phases overlap in X).

**CONCENTRATED** (:class:`ConcentratedCoilGenerator`)
    Discrete rectangular coil loops.  Each loop is a self-contained go/return
    pair joined by a top end-turn (length = ``coil_pitch_m``) and a bottom
    inter-coil link (length = ``2 × pole_pitch - coil_pitch_m``).  All loops
    have the same orientation (go side always UP), unlike the serpentine which
    alternates.  Best for prototyping or when individual coil replacement is
    required.

    *Trade-off vs. serpentine:*  when ``coil_pitch_m < pole_pitch_m``, the
    bottom inter-coil links are longer than the serpentine's end-turns, raising
    resistance by 10–35%.  Force is within a few percent of serpentine.

**RHOMBIC** (:class:`RhombicCoilGenerator`)
    Diamond-shaped coils: the active conductors run at an angle ``angle_deg``
    to the board-width (Y) axis.  Because each conductor spans multiple X
    positions as it crosses the board, it couples to a range of field values
    simultaneously.  This distributes the force production spatially and
    reduces force ripple vs. CONCENTRATED without adding layers.  The trade-off
    is a fill-factor reduction of ``cos(angle_deg)`` and slightly longer
    end-turns.

    *Typical value:* ``angle_deg = 30°`` (cos = 0.866; ~13% force reduction,
    significant ripple reduction).

**SPIRAL** (:class:`SpiralCoilGenerator`)
    Flat rectangular Archimedean spirals, one spiral unit per pole pitch.
    **Requires a layer pair**: the trace spirals inward on the primary layer,
    transitions to the secondary layer via a centre via cluster, then spirals
    outward.  The two layers together form one closed coil.

    This is the natural topology for **axial flux disk stators** (the active
    conductors are the left and right sides of each spiral rectangle).  For
    linear motors it provides moderate force but is included here for design
    exploration and as the foundation for the future axial motor phase.

    *Multi-layer wiring:* ``generate()`` returns **two** ``PhaseCoil`` objects
    per phase (one per layer in the pair).  Both carry the same ``phase_idx``
    so ``ForceEvaluator`` sums them correctly.  ``center_via_positions`` holds
    the centre-via coordinates for the KiCad writer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Union

from pcbstatorgen.config import CoilTopology, LinearMotorConfig, MotorConfig
from pcbstatorgen.geometry.wave_winding import (
    CoilSegment,
    PhaseCoil,
    PHASE_NAMES,
    WaveWindingGenerator,
)

__all__ = [
    "make_coil_generator",
    "ConcentratedCoilGenerator",
    "RhombicCoilGenerator",
    "SpiralCoilGenerator",
]

# Type alias for the generator union
CoilGenerator = Union[
    WaveWindingGenerator,
    "ConcentratedCoilGenerator",
    "RhombicCoilGenerator",
    "SpiralCoilGenerator",
]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_coil_generator(topology: CoilTopology, **kwargs) -> CoilGenerator:
    """Return the correct generator for *topology*.

    Parameters
    ----------
    topology:
        One of the :class:`~pcbstatorgen.config.CoilTopology` enum values.
    **kwargs:
        Forwarded to the generator constructor.  See individual class docs
        for available parameters.

    Returns
    -------
    Generator instance.

    Raises
    ------
    ValueError
        If *topology* is not a recognised ``CoilTopology`` value.

    Examples
    --------
    >>> from pcbstatorgen.config import CoilTopology
    >>> gen = make_coil_generator(CoilTopology.RHOMBIC, angle_deg=25)
    >>> type(gen).__name__
    'RhombicCoilGenerator'
    """
    match topology:
        case CoilTopology.SERPENTINE:
            return WaveWindingGenerator(**kwargs)
        case CoilTopology.CONCENTRATED:
            return ConcentratedCoilGenerator(**kwargs)
        case CoilTopology.RHOMBIC:
            return RhombicCoilGenerator(**kwargs)
        case CoilTopology.SPIRAL:
            return SpiralCoilGenerator(**kwargs)
        case _:
            raise ValueError(f"Unknown CoilTopology: {topology!r}")


# ---------------------------------------------------------------------------
# ConcentratedCoilGenerator
# ---------------------------------------------------------------------------


class ConcentratedCoilGenerator:
    """Generate discrete rectangular concentrated coil loops.

    Each loop consists of:

    * **Go conductor** — perpendicular to travel (Y-direction, always upward).
    * **Top end-turn** — horizontal at ``y = board_width``, length =
      ``coil_pitch_m``.
    * **Return conductor** — perpendicular to travel (Y-direction, downward).
    * **Bottom inter-coil link** — horizontal at ``y = 0``, length =
      ``2 × pole_pitch − coil_pitch_m``.  When ``coil_pitch_m = pole_pitch_m``
      this equals the serpentine's end-turn length and the two topologies are
      geometrically identical (different metadata only).

    All loops in the phase have the same orientation (go always UP), in
    contrast to the serpentine which alternates direction.  For a 3-phase
    motor with alternating poles this still produces correct thrust: the go
    side at ``x₀`` (under a North pole) and the return side at ``x₀ +
    coil_pitch`` (under a South pole) both produce force in the same direction
    because both the conductor direction and the field sign flip together.

    Parameters
    ----------
    coil_pitch_m:
        Go-to-return conductor separation [m].  Defaults to ``None``, which
        means "use ``config.pole_pitch_m``" (full-pitch concentrated = same
        geometry as SERPENTINE).  Set to ``2 × slot_pitch`` (= 2τ/3) for a
        2/3-pitch concentrated winding with shorter top end-turns and longer
        bottom inter-coil links.
    """

    def __init__(self, coil_pitch_m: float | None = None) -> None:
        if coil_pitch_m is not None and coil_pitch_m <= 0:
            raise ValueError(f"coil_pitch_m must be positive, got {coil_pitch_m}")
        self.coil_pitch_m = coil_pitch_m

    def generate(self, config: MotorConfig, layer_idx: int = 0) -> list[PhaseCoil]:
        """Generate concentrated coil loops for all phases on one layer.

        Parameters
        ----------
        config:
            Motor configuration.
        layer_idx:
            Copper layer index (0 = top outer).

        Returns
        -------
        list[PhaseCoil]
            One :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil` per
            phase, each tagged with ``topology=CONCENTRATED``.
        """
        coil_pitch = (
            self.coil_pitch_m
            if self.coil_pitch_m is not None
            else config.pole_pitch_m
        )
        if coil_pitch > config.pole_pitch_m:
            raise ValueError(
                f"coil_pitch_m ({coil_pitch * 1e3:.2f} mm) must be ≤ "
                f"pole_pitch_m ({config.pole_pitch_m * 1e3:.2f} mm)"
            )
        return [
            self._generate_phase(config, p, layer_idx, coil_pitch)
            for p in range(config.phases)
        ]

    def _generate_phase(
        self,
        config: MotorConfig,
        phase_idx: int,
        layer_idx: int,
        coil_pitch: float,
    ) -> PhaseCoil:
        pole_pitch = config.pole_pitch_m
        slot_pitch = config.slot_pitch_m
        board_width = config.board_width_m
        x_offset = phase_idx * slot_pitch
        # Balanced upper bound (same formula as WaveWindingGenerator)
        x_max = config.active_length_m + (config.phases - 1) * slot_pitch

        segments: list[CoilSegment] = []
        x = x_offset

        while x <= x_max + 1e-9:
            # Go conductor — always upward (y=0 → y=W)
            segments.append(CoilSegment(
                start=(x, 0.0),
                end=(x, board_width),
                is_active=True,
            ))

            x_return = x + coil_pitch
            if x_return <= x_max + 1e-9:
                # Top end-turn at y=W (length = coil_pitch)
                segments.append(CoilSegment(
                    start=(x, board_width),
                    end=(x_return, board_width),
                    is_active=False,
                ))
                # Return conductor — always downward (y=W → y=0)
                segments.append(CoilSegment(
                    start=(x_return, board_width),
                    end=(x_return, 0.0),
                    is_active=True,
                ))
                # Bottom inter-coil link at y=0 (length = 2τ − coil_pitch)
                x_next = x + 2.0 * pole_pitch
                if x_next <= x_max + 1e-9:
                    segments.append(CoilSegment(
                        start=(x_return, 0.0),
                        end=(x_next, 0.0),
                        is_active=False,
                    ))

            x = x + 2.0 * pole_pitch   # next coil's go conductor

        phase_name = PHASE_NAMES[phase_idx % len(PHASE_NAMES)]
        return PhaseCoil(
            phase_idx=phase_idx,
            layer_idx=layer_idx,
            segments=segments,
            phase_name=phase_name,
            topology=CoilTopology.CONCENTRATED,
        )

    @staticmethod
    def top_end_turn_length(coil_pitch_m: float) -> float:
        """Top end-turn length [m] = ``coil_pitch_m``."""
        return coil_pitch_m

    @staticmethod
    def bottom_link_length(coil_pitch_m: float, pole_pitch_m: float) -> float:
        """Bottom inter-coil link length [m] = ``2τ − coil_pitch_m``."""
        return 2.0 * pole_pitch_m - coil_pitch_m


# ---------------------------------------------------------------------------
# RhombicCoilGenerator
# ---------------------------------------------------------------------------


class RhombicCoilGenerator:
    """Generate rhombic (diamond) coils with angled active conductors.

    The active conductors run at ``angle_deg`` from the board-width (Y) axis,
    creating a parallelogram-shaped coil.  Because each conductor passes over
    a range of X positions as it crosses the board, it couples to the spatially
    varying magnetic field continuously, producing a sinusoidal net force
    profile and reduced force ripple compared to the rectangular CONCENTRATED
    topology.

    Path for one coil (going positive X, angle θ from vertical):

    .. code-block:: text

        Δx = board_width × tan(θ)

        Go:      (x₀, 0)          → (x₀ − Δx, W)      [active, angled]
        Top ET:  (x₀ − Δx, W)     → (x₀ − Δx + τ, W)  [end-turn, horizontal]
        Return:  (x₀ − Δx + τ, W) → (x₀ + τ, 0)       [active, angled]
        Link:    (x₀ + τ, 0)      → (x₀ + 2τ, 0)      [end-turn, horizontal]

    The active conductors are NOT vertical — their ``is_active=True`` flag
    tells the Magpylib force model to treat them as force-generating (the
    model computes the Lorentz force on each sub-segment correctly, including
    the X-component contribution to normal force).

    Parameters
    ----------
    angle_deg:
        Tilt of the active conductor from vertical [degrees].  Range (0, 45].
        At 0° the coil degenerates to a CONCENTRATED coil.  At larger angles
        the conductor spans a greater X range, improving sinusoidal distribution
        but increasing trace length and reducing fill factor (× cos(angle_deg)).
        Default: 30°.

    Notes
    -----
    The go and return conductors are mirror-symmetric about the centre of the
    coil, so the X-component forces on the go and return sides partially cancel.
    The net thrust force comes from the Y-component of the conductor (∝ cos θ),
    giving a force multiplier of ``cos(angle_deg)`` relative to CONCENTRATED at
    the same current level.  For 30°: cos 30° ≈ 0.87.
    """

    #: Maximum angle that keeps the conductor within the pole pitch.
    #: Beyond this the coil would span more than one pole pitch on one side.
    _MAX_ANGLE_DEG: float = 45.0

    def __init__(self, angle_deg: float = 30.0) -> None:
        if not (0.0 < angle_deg <= self._MAX_ANGLE_DEG):
            raise ValueError(
                f"angle_deg must be in (0, {self._MAX_ANGLE_DEG}], got {angle_deg}"
            )
        self.angle_deg = angle_deg

    def generate(self, config: MotorConfig, layer_idx: int = 0) -> list[PhaseCoil]:
        """Generate rhombic coil paths for all phases on one layer.

        Parameters
        ----------
        config:
            Motor configuration.
        layer_idx:
            Copper layer index.

        Returns
        -------
        list[PhaseCoil]
            One coil per phase tagged ``topology=RHOMBIC``.
        """
        return [
            self._generate_phase(config, p, layer_idx)
            for p in range(config.phases)
        ]

    def _generate_phase(
        self,
        config: MotorConfig,
        phase_idx: int,
        layer_idx: int,
    ) -> PhaseCoil:
        pole_pitch = config.pole_pitch_m
        slot_pitch = config.slot_pitch_m
        board_width = config.board_width_m
        x_offset = phase_idx * slot_pitch
        x_max = config.active_length_m + (config.phases - 1) * slot_pitch
        angle_rad = math.radians(self.angle_deg)
        # Horizontal displacement as conductor crosses board width
        delta_x = board_width * math.tan(angle_rad)

        segments: list[CoilSegment] = []
        x = x_offset

        while x <= x_max + 1e-9:
            # Go conductor: angled, from (x, 0) to (x-Δx, W)
            segments.append(CoilSegment(
                start=(x, 0.0),
                end=(x - delta_x, board_width),
                is_active=True,
            ))

            x_top_left = x - delta_x
            x_top_right = x_top_left + pole_pitch

            if x_top_right <= x_max + delta_x + 1e-9:
                # Top end-turn: horizontal at y=W, length = τ
                segments.append(CoilSegment(
                    start=(x_top_left, board_width),
                    end=(x_top_right, board_width),
                    is_active=False,
                ))
                # Return conductor: angled, from (x-Δx+τ, W) to (x+τ, 0)
                segments.append(CoilSegment(
                    start=(x_top_right, board_width),
                    end=(x + pole_pitch, 0.0),
                    is_active=True,
                ))
                # Bottom inter-coil link: horizontal at y=0
                x_next = x + 2.0 * pole_pitch
                if x_next <= x_max + 1e-9:
                    segments.append(CoilSegment(
                        start=(x + pole_pitch, 0.0),
                        end=(x_next, 0.0),
                        is_active=False,
                    ))

            x = x + 2.0 * pole_pitch

        phase_name = PHASE_NAMES[phase_idx % len(PHASE_NAMES)]
        return PhaseCoil(
            phase_idx=phase_idx,
            layer_idx=layer_idx,
            segments=segments,
            phase_name=phase_name,
            topology=CoilTopology.RHOMBIC,
        )

    @property
    def force_factor(self) -> float:
        """Force multiplier relative to CONCENTRATED at the same current.

        ``cos(angle_deg)`` — the fraction of the conductor path that is
        perpendicular to travel and therefore contributes to thrust.
        """
        return math.cos(math.radians(self.angle_deg))

    @property
    def conductor_length_factor(self) -> float:
        """Conductor length multiplier relative to board_width.

        ``1 / cos(angle_deg)`` — angled conductors are longer than vertical
        ones, increasing copper resistance by this factor.
        """
        return 1.0 / math.cos(math.radians(self.angle_deg))


# ---------------------------------------------------------------------------
# SpiralCoilGenerator
# ---------------------------------------------------------------------------


class SpiralCoilGenerator:
    """Generate rectangular spiral coils requiring a layer pair.

    Each spiral unit occupies ``pole_pitch_m × board_width_m`` on the PCB.
    The trace winds inward as a rectangular Archimedean spiral on the primary
    layer, transitions to the secondary layer via a centre-via cluster, then
    winds outward back to the perimeter.

    The two layers together form one complete coil.  ``generate()`` returns
    **two** :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil` objects per
    phase (primary = inward, secondary = outward) so that the Magpylib force
    model sums both contributions automatically.  Both coils carry the same
    ``phase_idx`` and the ``center_via_positions`` attribute holds the
    inter-layer transition coordinates for the KiCad writer.

    Force contribution
    ------------------
    For a linear motor the active segments are the **left and right vertical
    sides** of the spiral rectangle.  The horizontal top and bottom segments
    are end-turns that do not contribute to thrust.  The inner turns have
    their go and return sides very close together (< slot_pitch apart), so
    their force contributions partially cancel.  The outermost turn has the
    full pole-pitch separation and contributes nearly the same force as one
    CONCENTRATED coil.  Overall force efficiency ≈ 55–65% of SERPENTINE at
    the same current and layer count.

    Multi-layer note
    ----------------
    When the :class:`~pcbstatorgen.stackup.optimizer.LayerOptimizer` selects
    layer count for spiral topology it allocates layers in **pairs** per phase:
    ``(L1, L2)`` for Phase A, ``(L3, L4)`` for Phase B, etc.

    Parameters
    ----------
    n_turns:
        Number of spiral turns per unit.  ``None`` (default) auto-computes
        the maximum that fits within the pole-pitch × board-width area given
        the config's DFM trace/space rules.  Capped at 10 to avoid over-dense
        coils that are impractical to manufacture.
    """

    #: Hard cap on auto-computed turns — prevents impractical coil density.
    _MAX_AUTO_TURNS: int = 10

    def __init__(self, n_turns: int | None = None) -> None:
        if n_turns is not None and n_turns < 1:
            raise ValueError(f"n_turns must be ≥ 1, got {n_turns}")
        self.n_turns = n_turns

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        config: MotorConfig,
        layer_pair: tuple[int, int] = (0, 1),
    ) -> list[PhaseCoil]:
        """Generate spiral coils for all phases on a layer pair.

        Returns **two** PhaseCoil objects per phase (one per layer):

        * ``layer_pair[0]`` — inward spiral (primary layer).
        * ``layer_pair[1]`` — outward spiral (secondary layer, reverse path).

        Both coils share the same ``phase_idx`` and ``center_via_positions``.

        Parameters
        ----------
        config:
            Motor configuration.
        layer_pair:
            ``(primary_layer_idx, secondary_layer_idx)``.  Default: ``(0, 1)``.

        Returns
        -------
        list[PhaseCoil]
            ``2 × config.phases`` coils, ordered as
            ``[PhaseA_L1, PhaseA_L2, PhaseB_L1, PhaseB_L2, …]``.
        """
        coils: list[PhaseCoil] = []
        for p in range(config.phases):
            primary, secondary = self._generate_phase_pair(config, p, layer_pair)
            coils.append(primary)
            coils.append(secondary)
        return coils

    def max_turns(self, config: MotorConfig) -> int:
        """Maximum spiral turns that fit in ``pole_pitch × board_width``.

        Capped at :attr:`_MAX_AUTO_TURNS`.

        Parameters
        ----------
        config:
            Motor configuration supplying DFM trace/space rules.
        """
        pitch = config.min_trace_m + config.min_space_m
        # The spiral is limited by the smaller of the two bounding dimensions
        half_min = min(config.pole_pitch_m, config.board_width_m) / 2.0
        computed = max(1, int(half_min / pitch) - 1)
        return min(computed, self._MAX_AUTO_TURNS)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_phase_pair(
        self,
        config: MotorConfig,
        phase_idx: int,
        layer_pair: tuple[int, int],
    ) -> tuple[PhaseCoil, PhaseCoil]:
        """Return (primary_coil, secondary_coil) for one phase."""
        n = self.n_turns if self.n_turns is not None else self.max_turns(config)
        pole_pitch = config.pole_pitch_m
        slot_pitch = config.slot_pitch_m
        board_width = config.board_width_m
        x_offset = phase_idx * slot_pitch
        x_max = config.active_length_m + (config.phases - 1) * slot_pitch
        pitch = config.min_trace_m + config.min_space_m
        phase_name = PHASE_NAMES[phase_idx % len(PHASE_NAMES)]

        primary_segments: list[CoilSegment] = []
        secondary_segments: list[CoilSegment] = []
        center_vias: list[tuple[float, float]] = []

        # Spiral unit centres along the travel axis for this phase
        # Phase offset + every 2*pole_pitch (same spacing as CONCENTRATED)
        x_unit = x_offset
        is_first = True

        while x_unit <= x_max + 1e-9:
            cx = x_unit + pole_pitch / 2.0
            cy = board_width / 2.0
            center_vias.append((cx, cy))

            # Build inward and outward spiral segments
            inward = self._spiral_inward(cx, cy, pole_pitch, board_width, pitch, n)
            outward = self._spiral_outward(cx, cy, pole_pitch, board_width, pitch, n)

            # Connect previous unit to this one via a horizontal link at y=0
            if not is_first and primary_segments:
                prev_exit = primary_segments[-1].end
                if outward:
                    entry = inward[0].start if inward else (cx, 0.0)
                    primary_segments.append(CoilSegment(
                        start=prev_exit,
                        end=entry,
                        is_active=False,
                    ))

            primary_segments.extend(inward)
            secondary_segments.extend(outward)
            x_unit += 2.0 * pole_pitch
            is_first = False

        primary = PhaseCoil(
            phase_idx=phase_idx,
            layer_idx=layer_pair[0],
            segments=primary_segments,
            phase_name=phase_name,
            topology=CoilTopology.SPIRAL,
            layer_pair=layer_pair,
            center_via_positions=center_vias,
        )
        secondary = PhaseCoil(
            phase_idx=phase_idx,
            layer_idx=layer_pair[1],
            segments=secondary_segments,
            phase_name=phase_name,
            topology=CoilTopology.SPIRAL,
            layer_pair=layer_pair,
            center_via_positions=center_vias,
        )
        return primary, secondary

    @staticmethod
    def _spiral_inward(
        cx: float,
        cy: float,
        tau: float,
        W: float,
        pitch: float,
        n_turns: int,
    ) -> list[CoilSegment]:
        """Build segments for a rectangular spiral winding inward on L1.

        Starts at the outer-bottom-left corner and winds clockwise toward
        the centre.  Vertical sides are ``is_active=True``; horizontal sides
        (top/bottom) are ``is_active=False``.
        """
        segments: list[CoilSegment] = []
        half_tau = tau / 2.0
        half_W = W / 2.0

        for k in range(n_turns):
            hx = half_tau - (k + 0.5) * pitch
            hy = half_W  - (k + 0.5) * pitch
            if hx < pitch * 0.5 or hy < pitch * 0.5:
                break  # no space for this turn

            x_left  = cx - hx
            x_right = cx + hx
            y_bot   = cy - hy
            y_top   = cy + hy

            if k == 0:
                # Entry: start at bottom-left
                entry_y = y_bot
            else:
                # Entry from previous turn's jog
                entry_y = y_bot

            # Left side UP (active)
            segments.append(CoilSegment(
                start=(x_left, entry_y),
                end=(x_left, y_top),
                is_active=True,
            ))
            # Top → right (end-turn)
            segments.append(CoilSegment(
                start=(x_left, y_top),
                end=(x_right, y_top),
                is_active=False,
            ))
            # Right side DOWN (active)
            segments.append(CoilSegment(
                start=(x_right, y_top),
                end=(x_right, y_bot),
                is_active=True,
            ))

            # Connect to next inner turn or centre
            if k < n_turns - 1:
                hx_next = half_tau - (k + 1.5) * pitch
                hy_next = half_W  - (k + 1.5) * pitch
                if hx_next > pitch * 0.5 and hy_next > pitch * 0.5:
                    x_left_next = cx - hx_next
                    y_bot_next  = cy - hy_next
                    # Bottom partial left (end-turn)
                    segments.append(CoilSegment(
                        start=(x_right, y_bot),
                        end=(x_left_next, y_bot),
                        is_active=False,
                    ))
                    # Short vertical jog down to inner-level bottom (end-turn)
                    segments.append(CoilSegment(
                        start=(x_left_next, y_bot),
                        end=(x_left_next, y_bot_next),
                        is_active=False,
                    ))
                else:
                    # No room for another turn — route to centre
                    segments.append(CoilSegment(
                        start=(x_right, y_bot),
                        end=(cx, y_bot),
                        is_active=False,
                    ))
                    segments.append(CoilSegment(
                        start=(cx, y_bot),
                        end=(cx, cy),
                        is_active=False,
                    ))
                    break
            else:
                # Last turn — route to centre via
                segments.append(CoilSegment(
                    start=(x_right, y_bot),
                    end=(cx, y_bot),
                    is_active=False,
                ))
                segments.append(CoilSegment(
                    start=(cx, y_bot),
                    end=(cx, cy),
                    is_active=False,
                ))

        return segments

    @staticmethod
    def _spiral_outward(
        cx: float,
        cy: float,
        tau: float,
        W: float,
        pitch: float,
        n_turns: int,
    ) -> list[CoilSegment]:
        """Build segments for the outward spiral on L2 (reverse of inward).

        Starts at the centre via and winds counter-clockwise outward.
        Vertical sides are ``is_active=True``; horizontal sides are
        ``is_active=False``.  The current flows in the opposite direction to
        the inward spiral, but the net Lorentz force contribution is the same
        sign (both go and return sides move the coil in the same direction
        because both the conductor direction and the field polarity they see
        are reversed together).
        """
        # The outward spiral is geometrically the reverse of the inward spiral.
        # We generate the inward path and reverse all segments to get the outward path.
        inward = SpiralCoilGenerator._spiral_inward(cx, cy, tau, W, pitch, n_turns)
        if not inward:
            return []
        # Reverse: flip each segment start/end and reverse the list order
        return [
            CoilSegment(start=seg.end, end=seg.start, is_active=seg.is_active)
            for seg in reversed(inward)
        ]
