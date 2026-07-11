"""
pcbstatorgen.magnetic.coil_model
=======================================
Converts :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil` objects
into Magpylib v5 ``current.Polyline`` sources for magnetic field and force
calculations.

Conductor modelling
-------------------
Each *active conductor* segment (the vertical traces that run perpendicular to
the travel axis and actually generate thrust) is represented by a single
``Polyline`` object with two vertices — one segment from start to end.

End-turn segments (horizontal, parallel to travel) are **not included** by
default.  They contribute a Z-direction normal force and a small Y lateral
force, but their net X thrust contribution cancels out across the full coil
and they would roughly double the computation time.  Pass
``include_end_turns=True`` to include them when calculating normal or lateral
forces.

Current sign convention
-----------------------
The ``current`` parameter of a ``Polyline`` is always **positive**.  The
*direction* of current flow is encoded in the vertex order:

* Even-indexed active conductors in the serpentine go from ``(x, 0, 0)`` to
  ``(x, W, 0)``  — current flows in **+Y**.
* Odd-indexed active conductors go from ``(x, W, 0)`` to ``(x, 0, 0)``
  — current flows in **−Y**.

Combined with the alternating pole arrangement (Bz alternates sign with every
pole pitch), both conductor types produce thrust in the same **+X** direction
when the current magnitude is positive and the commutation is correct.

Layer Z offset
--------------
Conductors are placed in the Z = 0 plane by default (PCB top surface).  Pass
``layer_z_m`` to shift them to a specific layer depth when modelling a
multi-layer stackup.  The copper thickness (35–140 µm) is negligible compared
to the air gap (≥ 0.5 mm), so placing all conductors at their layer centre is
adequate for force estimation.
"""

from __future__ import annotations

import magpylib as magpy
import numpy as np

from pcbstatorgen.geometry.wave_winding import CoilSegment, PhaseCoil

__all__ = ["CoilCurrentModel", "PhaseCurrentSources"]

#: Default meshing density for Polyline targets in getFT.
#: Each active segment (~20 mm long) is divided into this many sub-segments
#: for the Lorentz-force integration.  20 gives sub-mm resolution.
DEFAULT_MESHING: int = 20


class PhaseCurrentSources:
    """Magpylib Polyline sources for one phase at one current level.

    Attributes
    ----------
    phase_idx:
        Phase index (0 = A, 1 = B, 2 = C).
    current_a:
        Signed phase current applied to this set of conductors [A].
    polylines:
        List of ``magpy.current.Polyline`` objects, one per included segment.
    """

    def __init__(
        self,
        phase_idx: int,
        current_a: float,
        polylines: list,
    ) -> None:
        self.phase_idx = phase_idx
        self.current_a = current_a
        self.polylines = polylines

    def __len__(self) -> int:
        return len(self.polylines)

    def as_collection(self) -> magpy.Collection:
        """Return all polylines as a single ``magpy.Collection``."""
        return magpy.Collection(*self.polylines)


class CoilCurrentModel:
    """Convert :class:`~pcbstatorgen.geometry.wave_winding.PhaseCoil`
    objects into Magpylib ``current.Polyline`` sources.

    Parameters
    ----------
    meshing:
        Number of sub-segments per conductor for ``getFT`` force integration.
        Higher values are more accurate but slower.  Default: 20.
    include_end_turns:
        If ``True``, end-turn segments are also converted to Polylines.
        Default: ``False`` (active conductors only).
    layer_z_m:
        Z coordinate of the conductor plane [m].  0 = PCB top surface.
        Useful when modelling buried layers in a multi-layer stackup.

    Examples
    --------
    Single-phase sources::

        model = CoilCurrentModel()
        sources = model.build_phase(coil_a, current_a=1.0)
        F, T = magpy.getFT(magnet_coll, sources.polylines)

    All phases at once::

        all_sources = model.build_all_phases(coils, currents=[1.0, -0.5, -0.5])
        flat = [p for src in all_sources for p in src.polylines]
        F, T = magpy.getFT(magnet_coll, flat)
    """

    def __init__(
        self,
        meshing: int = DEFAULT_MESHING,
        include_end_turns: bool = False,
        layer_z_m: float = 0.0,
    ) -> None:
        if meshing < 1:
            raise ValueError(f"meshing must be ≥ 1, got {meshing}")
        self.meshing = meshing
        self.include_end_turns = include_end_turns
        self.layer_z_m = layer_z_m

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_phase(
        self,
        coil: PhaseCoil,
        current_a: float,
    ) -> PhaseCurrentSources:
        """Build Polyline sources for a single phase coil.

        Parameters
        ----------
        coil:
            Phase coil from :class:`~pcbstatorgen.geometry.wave_winding.WaveWindingGenerator`.
        current_a:
            Phase current to apply [A].  Positive = rated peak current.
            The serpentine vertex ordering handles the alternating conductor
            direction automatically.

        Returns
        -------
        PhaseCurrentSources
        """
        segments = coil.active_segments
        if self.include_end_turns:
            segments = coil.segments  # type: ignore[assignment]

        polylines = [
            self._segment_to_polyline(seg, current_a)
            for seg in segments
        ]
        return PhaseCurrentSources(
            phase_idx=coil.phase_idx,
            current_a=current_a,
            polylines=polylines,
        )

    def build_all_phases(
        self,
        coils: list[PhaseCoil],
        currents_a: list[float],
    ) -> list[PhaseCurrentSources]:
        """Build sources for all phases simultaneously.

        Parameters
        ----------
        coils:
            Phase coils in phase order (A, B, C, …).
        currents_a:
            Signed phase current for each coil [A].  Must have the same
            length as ``coils``.

        Returns
        -------
        list[PhaseCurrentSources]
            One entry per phase.

        Raises
        ------
        ValueError
            If ``coils`` and ``currents_a`` have different lengths.
        """
        if len(coils) != len(currents_a):
            raise ValueError(
                f"coils ({len(coils)}) and currents_a ({len(currents_a)}) "
                "must have the same length"
            )
        return [
            self.build_phase(coil, I)
            for coil, I in zip(coils, currents_a)
        ]

    def flat_polylines(
        self,
        sources: list[PhaseCurrentSources],
    ) -> list:
        """Flatten all Polylines from multiple phases into one list.

        Parameters
        ----------
        sources:
            Output of :meth:`build_all_phases`.

        Returns
        -------
        list[magpy.current.Polyline]
            Flat list of all Polylines across all phases — pass directly to
            ``magpy.getFT(magnets, flat_polylines)``.
        """
        return [p for src in sources for p in src.polylines]

    # ------------------------------------------------------------------
    # Field sampling helpers
    # ------------------------------------------------------------------

    def bfield_at_conductor_positions(
        self,
        coil: PhaseCoil,
        magnet_collection: magpy.Collection,
    ) -> np.ndarray:
        """Sample the magnet B field at each active conductor midpoint.

        Useful for debugging the coupling and verifying pole alignment.

        Parameters
        ----------
        coil:
            Phase coil whose active conductor midpoints are the observers.
        magnet_collection:
            Magnet array at the desired fader position.

        Returns
        -------
        np.ndarray
            Shape ``(n_active_conductors, 3)`` — B [T] at each conductor.
        """
        midpoints = np.array([
            (seg.start[0], (seg.start[1] + seg.end[1]) / 2.0, self.layer_z_m)
            for seg in coil.active_segments
        ])
        return magpy.getB(magnet_collection, midpoints)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _segment_to_polyline(
        self,
        seg: CoilSegment,
        current_a: float,
    ) -> magpy.current.Polyline:
        """Convert one CoilSegment to a Magpylib Polyline."""
        return magpy.current.Polyline(
            current=current_a,
            vertices=[
                (seg.start[0], seg.start[1], self.layer_z_m),
                (seg.end[0],   seg.end[1],   self.layer_z_m),
            ],
            meshing=self.meshing,
        )
