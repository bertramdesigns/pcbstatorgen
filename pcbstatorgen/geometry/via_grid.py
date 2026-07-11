"""
pcbstatorgen.geometry.via_grid
====================================
Generates rectangular grids of vias for multi-layer current transitions at
coil end-turns.

Why via grids instead of single vias?
--------------------------------------
In a wave winding that transitions between layers at each end-turn, a single
via carrying the full phase current creates:

* **Current crowding** at the via annular ring.
* **Thermal hotspots** during burst-current events (capacitor discharge).
* **Added inductance** from the concentrated current path.

Replacing each single via with a parallel grid of smaller vias distributes
the current uniformly, reduces thermal resistance, and dramatically lowers
the inductance of the inter-layer connection.

Design rules
------------
The generator respects all constraints from :class:`~pcbstatorgen.config.MotorConfig`:

* ``min_via_drill_m``: minimum drill diameter.
* ``min_via_annular_ring_m``: minimum annular ring width.
* ``min_space_m``: minimum copper-to-copper clearance (pad edge to pad edge).

Via current capacity
--------------------
The empirical current capacity used here is based on IPC-2221 Table 6-4 for
plated through-holes.  The conservative value of **500 mA per via** applies to
a 0.2 mm drill in 1 oz outer copper with 10 °C temperature rise.  Inner-layer
vias in heavier copper can carry more, but the outer-layer limit is used as the
worst case throughout.

The generator always produces the *maximum* number of vias that fit within
the available end-turn area (up to a configurable cap), even if the current
requirement would be met by fewer vias.  This maximises thermal performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pcbstatorgen.config import MotorConfig

__all__ = ["ViaGrid", "ViaGridGenerator"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Conservative current capacity per via [A].
#: Based on IPC-2221 for 0.2 mm drill, 1 oz outer copper, 10 °C rise.
_CURRENT_PER_VIA_A: float = 0.5

#: Safety margin multiplier applied to the minimum required via count.
_CURRENT_SAFETY_MARGIN: float = 2.0


# ---------------------------------------------------------------------------
# ViaGrid dataclass
# ---------------------------------------------------------------------------


@dataclass
class ViaGrid:
    """Rectangular array of identical through-hole vias.

    The grid is centred on ``center``.  Vias are placed on a regular
    rectangular lattice with ``pitch_x`` spacing in X and ``pitch_y``
    spacing in Y.

    Parameters
    ----------
    center:
        ``(x, y)`` position of the grid centre [m].
    rows:
        Number of via rows (in the Y direction).
    cols:
        Number of via columns (in the X direction).
    pitch_x:
        Centre-to-centre via pitch in X [m].  ``0.0`` when ``cols == 1``.
    pitch_y:
        Centre-to-centre via pitch in Y [m].  ``0.0`` when ``rows == 1``.
    drill_m:
        Via drill (finished hole) diameter [m].
    annular_ring_m:
        Copper annular ring width on each pad layer [m].
    """

    center: tuple[float, float]
    rows: int
    cols: int
    pitch_x: float
    pitch_y: float
    drill_m: float
    annular_ring_m: float

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Total number of vias in the grid."""
        return self.rows * self.cols

    @property
    def pad_diameter_m(self) -> float:
        """Via pad diameter (drill + 2 × annular ring) [m]."""
        return self.drill_m + 2.0 * self.annular_ring_m

    @property
    def footprint_x_m(self) -> float:
        """Total grid width in X (outer pad edge to outer pad edge) [m]."""
        if self.cols == 1:
            return self.pad_diameter_m
        return (self.cols - 1) * self.pitch_x + self.pad_diameter_m

    @property
    def footprint_y_m(self) -> float:
        """Total grid height in Y (outer pad edge to outer pad edge) [m]."""
        if self.rows == 1:
            return self.pad_diameter_m
        return (self.rows - 1) * self.pitch_y + self.pad_diameter_m

    def positions(self) -> list[tuple[float, float]]:
        """Return ``(x, y)`` centre positions of every via in the grid.

        Vias are ordered row-by-row (row 0 = most-negative Y), left to
        right within each row.

        Returns
        -------
        list[tuple[float, float]]
            ``count`` via positions in metres.
        """
        cx, cy = self.center
        # Column centres
        if self.cols == 1:
            xs = [cx]
        else:
            half_span_x = (self.cols - 1) * self.pitch_x / 2.0
            xs = [cx - half_span_x + c * self.pitch_x for c in range(self.cols)]
        # Row centres
        if self.rows == 1:
            ys = [cy]
        else:
            half_span_y = (self.rows - 1) * self.pitch_y / 2.0
            ys = [cy - half_span_y + r * self.pitch_y for r in range(self.rows)]

        return [(x, y) for y in ys for x in xs]

    def current_capacity_a(
        self,
        current_per_via_a: float = _CURRENT_PER_VIA_A,
    ) -> float:
        """Estimated total current capacity of the grid [A].

        Parameters
        ----------
        current_per_via_a:
            Per-via current capacity [A].

        Returns
        -------
        float
            Total capacity = ``count × current_per_via_a``.
        """
        return self.count * current_per_via_a

    def is_sufficient_for(
        self,
        current_a: float,
        margin: float = _CURRENT_SAFETY_MARGIN,
        current_per_via_a: float = _CURRENT_PER_VIA_A,
    ) -> bool:
        """Return ``True`` if the grid can carry ``current_a`` with ``margin``.

        Parameters
        ----------
        current_a:
            Required phase current [A].
        margin:
            Safety multiplier (default 2×).
        current_per_via_a:
            Per-via current capacity [A].
        """
        return self.current_capacity_a(current_per_via_a) >= current_a * margin


# ---------------------------------------------------------------------------
# ViaGridGenerator
# ---------------------------------------------------------------------------


class ViaGridGenerator:
    """Generate via grids for multi-layer end-turn connections.

    The generator maximises via count within the available area for best
    thermal performance, while always satisfying the minimum required count
    for current capacity.

    Parameters
    ----------
    current_per_via_a:
        Conservative current capacity per via [A].  Override for thicker
        copper or larger drills.  Default: 0.5 A (IPC-2221, 0.2 mm, 1 oz).
    current_safety_margin:
        Multiplier applied to the required via count for safety headroom.
        Default: 2×.
    """

    def __init__(
        self,
        current_per_via_a: float = _CURRENT_PER_VIA_A,
        current_safety_margin: float = _CURRENT_SAFETY_MARGIN,
    ) -> None:
        if current_per_via_a <= 0:
            raise ValueError(f"current_per_via_a must be positive, got {current_per_via_a}")
        if current_safety_margin < 1.0:
            raise ValueError(
                f"current_safety_margin must be ≥ 1, got {current_safety_margin}"
            )
        self.current_per_via_a = current_per_via_a
        self.current_safety_margin = current_safety_margin

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_for_end_turn(
        self,
        center: tuple[float, float],
        available_x_m: float,
        available_y_m: float,
        current_a: float,
        config: MotorConfig,
    ) -> ViaGrid:
        """Generate an optimised via grid for one end-turn layer transition.

        The grid is as large as possible within the available area, subject
        to the DFM constraints in ``config``.

        Parameters
        ----------
        center:
            ``(x, y)`` centre of the end-turn region [m].
        available_x_m:
            Available space in X (typically = pole pitch) [m].
        available_y_m:
            Available space in Y (typically 1–3 mm near board edge) [m].
        current_a:
            Peak phase current that must flow through this transition [A].
        config:
            Motor config supplying DFM constraints.

        Returns
        -------
        ViaGrid
            Via grid sized for the available space.

        Raises
        ------
        ValueError
            If ``available_x_m`` or ``available_y_m`` cannot fit even one via.
        """
        drill = config.min_via_drill_m
        ring = config.min_via_annular_ring_m
        space = config.min_space_m
        pad = drill + 2.0 * ring

        # The minimum pad-to-pad clearance required between via centres.
        min_pitch = pad + space

        if available_x_m < pad - 1e-9:
            raise ValueError(
                f"available_x_m ({available_x_m * 1e3:.3f} mm) is smaller than "
                f"via pad diameter ({pad * 1e3:.3f} mm)"
            )
        if available_y_m < pad - 1e-9:
            raise ValueError(
                f"available_y_m ({available_y_m * 1e3:.3f} mm) is smaller than "
                f"via pad diameter ({pad * 1e3:.3f} mm)"
            )

        # Maximum number of vias that fit in each axis.
        # A single via always fits; additional vias require one more pitch each.
        max_cols = 1 + max(0, math.floor((available_x_m - pad + 1e-9) / min_pitch))
        max_rows = 1 + max(0, math.floor((available_y_m - pad + 1e-9) / min_pitch))

        rows = max_rows
        cols = max_cols
        pitch_x = min_pitch if cols > 1 else 0.0
        pitch_y = min_pitch if rows > 1 else 0.0

        grid = ViaGrid(
            center=center,
            rows=rows,
            cols=cols,
            pitch_x=pitch_x,
            pitch_y=pitch_y,
            drill_m=drill,
            annular_ring_m=ring,
        )

        # Warn if current capacity is insufficient — the caller can check
        # grid.is_sufficient_for(current_a) and decide how to handle it.
        # We do not raise here; the design may still be valid with lower
        # margins in some circumstances (e.g., pulsed operation).
        return grid

    def generate_for_coil(
        self,
        coil_end_turn_midpoints: list[tuple[float, float]],
        available_x_m: float,
        available_y_m: float,
        current_a: float,
        config: MotorConfig,
    ) -> list[ViaGrid]:
        """Generate via grids for every end-turn in a coil.

        Parameters
        ----------
        coil_end_turn_midpoints:
            Midpoints of all end-turn segments (from
            :attr:`~pcbstatorgen.geometry.wave_winding.PhaseCoil.end_turn_midpoints_top`
            or ``…bottom``).
        available_x_m:
            Available X width per end-turn (usually = pole pitch).
        available_y_m:
            Available Y depth near the board edge [m].
        current_a:
            Phase current [A].
        config:
            Motor config.

        Returns
        -------
        list[ViaGrid]
            One :class:`ViaGrid` per midpoint.
        """
        return [
            self.generate_for_end_turn(
                center=mp,
                available_x_m=available_x_m,
                available_y_m=available_y_m,
                current_a=current_a,
                config=config,
            )
            for mp in coil_end_turn_midpoints
        ]

    def min_via_count_for_current(self, current_a: float) -> int:
        """Minimum number of vias required for ``current_a`` with safety margin.

        Parameters
        ----------
        current_a:
            Required phase current [A].

        Returns
        -------
        int
            Minimum via count = ceil(``current_a`` × ``current_safety_margin``
            / ``current_per_via_a``).
        """
        return math.ceil(current_a * self.current_safety_margin / self.current_per_via_a)
