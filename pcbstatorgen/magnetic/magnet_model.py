"""
pcbstatorgen.magnetic.magnet_model
========================================
Builds a Magpylib v5 collection of N44H cuboid permanent magnets representing
the fader carriage magnet array.

Motor topology
--------------
The fader carriage carries ``magnet_count`` rectangular N44H magnets
(e.g. 10× 10 mm × 10 mm × 4 mm) arranged in a line along the travel axis
(X) with alternating out-of-plane polarisation::

    Side view (Y axis points into page):

           N   S   N   S   N   ...  ← magnets (on carriage)
           ↕   ↕   ↕   ↕   ↕
    ─────────────────────────────── ← PCB copper surface  (Z = 0)
           ←── pole pitch τ ───→

    Top view:

    ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐
    │ N │ │ S │ │ N │ │ S │ │ N │   ← magnets
    └───┘ └───┘ └───┘ └───┘ └───┘
    x=0   τ     2τ    3τ    4τ

The Z-component of **B** at the PCB surface alternates sign with each pole.
The active conductors (running in Y) experience an X-directed Lorentz force
``F = I·L × B`` where ``L`` is in Y and ``B_z`` is the dominant component.

Coordinate system (all in metres, SI)
--------------------------------------
* X: travel direction (fader moves in +X)
* Y: perpendicular to travel (across PCB width)
* Z: out of PCB surface (positive toward magnets)

Magpylib v5 notes
-----------------
* All dimensions and positions in **metres** (v5 SI breaking change from v4).
* ``polarization`` is the remnant flux density vector **B_r** [T], not
  magnetisation **M**.  For N44H at 20 °C, |B_r| ≈ 1.32–1.38 T (typical 1.35 T).
* The fader position sweep is implemented by setting the Collection's
  ``position`` attribute to an (n_positions, 3) path array, so that a single
  ``getB`` / ``getFT`` call computes the field at all fader positions at once.
"""

from __future__ import annotations

import numpy as np

import magpylib as magpy

from pcbstatorgen.config import MotorConfig

__all__ = ["MagnetArray"]


class MagnetArray:
    """Builds and manages the N44H magnet collection for the fader carriage.

    Parameters
    ----------
    config:
        Motor configuration supplying magnet geometry, count, pitch,
        remanence, air gap, and board width.

    Examples
    --------
    Single fader position::

        arr = MagnetArray(config)
        coll = arr.build_collection(fader_position_m=0.0)
        B = magpy.getB(coll, [0.0, 0.01, 0.0])

    Vectorised sweep (efficient — one call for all positions)::

        arr = MagnetArray(config)
        positions = np.linspace(0, config.travel_m, 50)
        coll = arr.build_sweep_collection(positions)
        # coll has a path of 50 steps; getB / getFT vectorises over them
        B = magpy.getB(coll, observer)   # shape (50, 3)
    """

    def __init__(self, config: MotorConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_collection(self, fader_position_m: float = 0.0) -> magpy.Collection:
        """Return a Magpylib ``Collection`` with the carriage at ``fader_position_m``.

        Parameters
        ----------
        fader_position_m:
            Fader position along the X travel axis [m].  At position 0 the
            left edge of the first magnet is aligned with x = 0 on the stator.

        Returns
        -------
        magpy.Collection
            Collection of ``magnet_count`` ``Cuboid`` objects.  The collection
            has no path (single static position).
        """
        cfg = self.config
        z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
        y_center = cfg.board_width_m / 2.0

        magnets = []
        for k in range(cfg.magnet_count):
            x = fader_position_m + k * cfg.magnet_pitch_m
            # Alternating Z-polarisation: even k → +Z (north up), odd k → -Z (south up)
            pol_z = cfg.magnet_remanence_t * (1.0 if k % 2 == 0 else -1.0)
            magnets.append(
                magpy.magnet.Cuboid(
                    dimension=cfg.magnet_dims_m,
                    polarization=(0.0, 0.0, pol_z),
                    position=(x, y_center, z_center),
                )
            )

        return magpy.Collection(*magnets)

    def build_sweep_collection(self, positions_m: np.ndarray) -> magpy.Collection:
        """Return a Collection whose ``position`` path encodes a fader sweep.

        Setting a path on the Collection allows ``magpy.getB`` and
        ``magpy.getFT`` to vectorise the entire sweep in a single call,
        which is significantly faster than looping.

        Parameters
        ----------
        positions_m:
            1-D array of fader positions to evaluate [m].  Shape ``(n,)``.

        Returns
        -------
        magpy.Collection
            Same magnet collection as :meth:`build_collection` but with a
            path of length ``len(positions_m)``.  The individual magnets are
            built at ``fader_position_m = 0`` (the collection position
            translates them to each swept position).

        Notes
        -----
        Setting ``collection.position`` to an ``(n, 3)`` array creates a
        Magpylib *path* of length *n*.  At each path step the whole
        collection (and all its children) is translated by that position
        vector relative to the children's own positions.  Because the
        children are built at their *absolute* positions when
        ``fader_position_m = 0``, adding ``(p, 0, 0)`` at each step
        correctly places magnet ``k`` at ``(k·τ + p, y_c, z_c)``.
        """
        positions_m = np.asarray(positions_m, dtype=float)
        if positions_m.ndim != 1:
            raise ValueError(
                f"positions_m must be a 1-D array, got shape {positions_m.shape}"
            )

        coll = self.build_collection(fader_position_m=0.0)
        n = len(positions_m)
        # Path shape (n, 3): translate along X only
        path = np.zeros((n, 3), dtype=float)
        path[:, 0] = positions_m
        coll.position = path
        return coll

    # ------------------------------------------------------------------
    # Geometry accessors
    # ------------------------------------------------------------------

    def magnet_z_center_m(self) -> float:
        """Z position of magnet centres above PCB [m]."""
        return self.config.air_gap_m + self.config.magnet_dims_m[2] / 2.0

    def magnet_x_centers_m(self, fader_position_m: float = 0.0) -> np.ndarray:
        """X positions of all magnet centres at the given fader position [m].

        Returns
        -------
        np.ndarray
            Shape ``(magnet_count,)``.
        """
        k = np.arange(self.config.magnet_count)
        return fader_position_m + k * self.config.magnet_pitch_m

    def polarizations_t(self) -> np.ndarray:
        """Remnant polarisation vectors for each magnet, shape ``(magnet_count, 3)`` [T].

        Magnets alternate +Z / -Z.
        """
        br = self.config.magnet_remanence_t
        pols = np.zeros((self.config.magnet_count, 3))
        pols[:, 2] = br * np.where(np.arange(self.config.magnet_count) % 2 == 0, 1.0, -1.0)
        return pols

    def bfield_at_pcb_surface(
        self,
        x_sample: np.ndarray,
        fader_position_m: float = 0.0,
        z_observer: float = 0.0,
    ) -> np.ndarray:
        """Sample the B field along the PCB surface at the board centre line.

        Convenience method for visualisation and debugging.

        Parameters
        ----------
        x_sample:
            X positions at which to sample the field [m].
        fader_position_m:
            Fader position [m].
        z_observer:
            Z height of the observation plane [m].  Default 0 (PCB surface).

        Returns
        -------
        np.ndarray
            Shape ``(len(x_sample), 3)`` — B field [T] at each sample point.
        """
        x_sample = np.asarray(x_sample, dtype=float)
        y_center = self.config.board_width_m / 2.0
        observers = np.column_stack([
            x_sample,
            np.full_like(x_sample, y_center),
            np.full_like(x_sample, z_observer),
        ])
        coll = self.build_collection(fader_position_m=fader_position_m)
        return magpy.getB(coll, observers)
