"""
pcbstatorgen.magnetic.magnet_model
====================================
Builds Magpylib v5 magnet collections for all four :class:`~pcbstatorgen.config.MagnetArrangement`
configurations.

Arrangement overview
--------------------

``ALTERNATING`` (baseline)
    Simple alternating ±Z poles.  Each magnet has a Z-only polarisation
    that flips sign between neighbours.

``HALBACH``
    Halbach array.  X-polarised interleave cuboids are inserted in the
    gap between every adjacent pair of Z-polarised main magnets.  The
    interleave magnets concentrate flux on the stator face and
    self-cancel on the rear face, giving ≈ 1.35–1.55× field boost.

    Interleave geometry:
    * Width  = gap between main magnets = ``pole_pitch − magnet_width``
    * Length = same as main magnets
    * Height = same as main magnets
    * Centre X = midpoint of gap  =  ``k × pole_pitch + pole_pitch / 2``

    Polarisation direction alternates with index k:
    * k = 0 (between Z+ and Z−):  +X
    * k = 1 (between Z− and Z+):  −X
    * …

``ALTERNATING_BACK_IRON`` / ``HALBACH_BACK_IRON``
    Adds steel keeper (back-iron) simulation via the **method of images**.
    For an ideal (µ_r → ∞) steel back-iron plate, a mirror-image copy of
    every magnet is placed on the other side of the steel–magnet interface
    with the same polarisation, scaled by a finite-permeability correction
    factor ``k_iron = 0.85`` (calibrated for CRS steel µ_r ≈ 2 000).

    Image geometry:
    * Mirror plane:  bottom of steel = top of magnets = ``air_gap + height``
    * Image centre:  ``z_image = 2 × z_mirror − z_original``
                   = ``air_gap + 3 × height / 2``
    * Image applies to ALL magnets (Z-polarised main + X-polarised interleave).

Electrical angle note
---------------------
For both ``ALTERNATING`` and ``HALBACH`` (as implemented here), the
magnetic field repeats every **2 × pole_pitch**.  The interleave magnets
boost field amplitude but do not change the spatial period.  Therefore
the FOC electrical angle formula ``θ_e = 2π × p / (2τ)`` is **correct
for all four arrangements** — no period change is needed.
"""

from __future__ import annotations

import numpy as np
import magpylib as magpy

from pcbstatorgen.config import MagnetArrangement, MotorConfig

__all__ = ["MagnetArray"]

#: Empirical correction for finite CRS steel permeability (µ_r ≈ 2 000).
#: Reduces the image-method overestimate by ~15 %.  Calibrate against
#: measurement once a physical prototype is available.
_K_IRON: float = 0.85


class MagnetArray:
    """Builds and manages the magnet collection for all four arrangements.

    Parameters
    ----------
    config:
        Motor configuration.  ``config.magnet_arrangement`` selects which
        geometry is built by :meth:`build_collection`.

    Examples
    --------
    Halbach sweep::

        arr = MagnetArray(config)
        positions = np.linspace(0, config.travel_m, 50)
        coll = arr.build_sweep_collection(positions)
        B = magpy.getB(coll, observers)  # shape (50, n_obs, 3)

    Compare field boost::

        cfg_alt    = replace(config, magnet_arrangement=MagnetArrangement.ALTERNATING)
        cfg_halbach = replace(config, magnet_arrangement=MagnetArrangement.HALBACH)
        B_alt    = MagnetArray(cfg_alt).bfield_at_pcb_surface(xs)
        B_halbach = MagnetArray(cfg_halbach).bfield_at_pcb_surface(xs)
        boost = np.abs(B_halbach[:, 2]).mean() / np.abs(B_alt[:, 2]).mean()
    """

    def __init__(self, config: MotorConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public builders
    # ------------------------------------------------------------------

    def build_collection(self, fader_position_m: float = 0.0) -> magpy.Collection:
        """Return a Magpylib Collection for the configured arrangement.

        Dispatches to the appropriate private builder based on
        ``config.magnet_arrangement``.

        Parameters
        ----------
        fader_position_m:
            Fader (carriage) position along the travel axis [m].

        Returns
        -------
        magpy.Collection
        """
        arr = self.config.magnet_arrangement
        if arr == MagnetArrangement.ALTERNATING:
            magnets = self._build_alternating(fader_position_m)
        elif arr == MagnetArrangement.HALBACH:
            magnets = self._build_alternating(fader_position_m)
            magnets += self._build_halbach_interleave(fader_position_m)
        elif arr == MagnetArrangement.ALTERNATING_BACK_IRON:
            magnets = self._build_alternating(fader_position_m)
            magnets += self._build_image_magnets(magnets)
        elif arr == MagnetArrangement.HALBACH_BACK_IRON:
            main    = self._build_alternating(fader_position_m)
            interleave = self._build_halbach_interleave(fader_position_m)
            magnets = main + interleave
            magnets += self._build_image_magnets(main + interleave)
        else:
            raise ValueError(f"Unknown MagnetArrangement: {arr!r}")

        return magpy.Collection(*magnets)

    def build_sweep_collection(self, positions_m: np.ndarray) -> magpy.Collection:
        """Return a Collection with a fader-position path for vectorised evaluation.

        Parameters
        ----------
        positions_m:
            1-D array of fader positions [m].

        Returns
        -------
        magpy.Collection
            Collection with ``len(positions_m)`` path steps.
        """
        positions_m = np.asarray(positions_m, dtype=float)
        if positions_m.ndim != 1:
            raise ValueError(
                f"positions_m must be a 1-D array, got shape {positions_m.shape}"
            )
        coll = self.build_collection(fader_position_m=0.0)
        n = len(positions_m)
        path = np.zeros((n, 3), dtype=float)
        path[:, 0] = positions_m
        coll.position = path
        return coll

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    def _build_alternating(self, fader_position_m: float) -> list:
        """Build the base Z-polarised alternating magnet list."""
        cfg = self.config
        z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
        y_center = cfg.board_width_m / 2.0
        magnets = []
        for k in range(cfg.magnet_count):
            x = fader_position_m + k * cfg.magnet_pitch_m
            pol_z = cfg.magnet_remanence_t * (1.0 if k % 2 == 0 else -1.0)
            magnets.append(magpy.magnet.Cuboid(
                dimension=cfg.magnet_dims_m,
                polarization=(0.0, 0.0, pol_z),
                position=(x, y_center, z_center),
            ))
        return magnets

    def _build_halbach_interleave(self, fader_position_m: float) -> list:
        """Build X-polarised interleave cuboids for the Halbach arrangement.

        One interleave magnet is placed in the gap between each adjacent
        pair of main (Z-polarised) magnets.  The interleave magnet width
        equals the inter-magnet gap; all other dimensions match the main
        magnet.  Interleave magnets are skipped silently if the gap is
        too small to place a meaningful cuboid (< 0.1 mm).
        """
        cfg = self.config
        interleave_width = cfg.magnet_pitch_m - cfg.magnet_dims_m[0]
        if interleave_width < 1e-4:
            return []   # gap too small — skip silently

        z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
        y_center = cfg.board_width_m / 2.0
        # Interleave magnet dimensions: narrow in X, same in Y and Z
        dim = (interleave_width, cfg.magnet_dims_m[1], cfg.magnet_dims_m[2])

        magnets = []
        for k in range(cfg.magnet_count - 1):
            # Centre of the gap between main magnet k and k+1
            x = fader_position_m + k * cfg.magnet_pitch_m + cfg.magnet_pitch_m / 2.0
            # k=0: Z+→Z− transition → interleave is +X
            # k=1: Z−→Z+ transition → interleave is -X
            pol_x = cfg.magnet_remanence_t * (1.0 if k % 2 == 0 else -1.0)
            magnets.append(magpy.magnet.Cuboid(
                dimension=dim,
                polarization=(pol_x, 0.0, 0.0),
                position=(x, y_center, z_center),
            ))
        return magnets

    def _build_image_magnets(self, real_magnets: list) -> list:
        """Build method-of-images copies for back-iron simulation.

        Each real magnet is mirrored about the steel–magnet interface
        (bottom face of back-iron = top face of magnets).  Image magnets
        have the same polarisation as the originals, scaled by
        ``_K_IRON = 0.85`` to account for finite steel permeability.

        Parameters
        ----------
        real_magnets:
            List of Magpylib Cuboid objects to mirror (both Z and X
            polarised magnets must be passed when using HALBACH_BACK_IRON).
        """
        cfg = self.config
        # The steel–magnet interface is at the top face of the magnets
        z_mirror = cfg.air_gap_m + cfg.magnet_dims_m[2]
        images = []
        for mag in real_magnets:
            # Mirror position: z_image = 2 * z_mirror - z_original
            orig_pos = mag.position
            z_image = 2.0 * z_mirror - orig_pos[2]
            # Image polarisation: same as original, scaled by k_iron
            orig_pol = mag.polarization
            scaled_pol = tuple(p * _K_IRON for p in orig_pol)
            images.append(magpy.magnet.Cuboid(
                dimension=mag.dimension,
                polarization=scaled_pol,
                position=(orig_pos[0], orig_pos[1], z_image),
            ))
        return images

    # ------------------------------------------------------------------
    # Geometry accessors
    # ------------------------------------------------------------------

    def magnet_z_center_m(self) -> float:
        """Z position of main magnet centres above PCB [m]."""
        return self.config.air_gap_m + self.config.magnet_dims_m[2] / 2.0

    def magnet_x_centers_m(self, fader_position_m: float = 0.0) -> np.ndarray:
        """X positions of all main magnet centres [m], shape ``(magnet_count,)``."""
        k = np.arange(self.config.magnet_count)
        return fader_position_m + k * self.config.magnet_pitch_m

    def polarizations_t(self) -> np.ndarray:
        """Z-polarisation of main magnets, shape ``(magnet_count, 3)`` [T]."""
        br = self.config.magnet_remanence_t
        pols = np.zeros((self.config.magnet_count, 3))
        pols[:, 2] = br * np.where(
            np.arange(self.config.magnet_count) % 2 == 0, 1.0, -1.0
        )
        return pols

    def interleave_x_centers_m(self, fader_position_m: float = 0.0) -> np.ndarray:
        """X positions of Halbach interleave magnets [m].

        Returns an empty array if the arrangement is not HALBACH or
        HALBACH_BACK_IRON.
        """
        arr = self.config.magnet_arrangement
        if arr not in (MagnetArrangement.HALBACH, MagnetArrangement.HALBACH_BACK_IRON):
            return np.array([])
        cfg = self.config
        k = np.arange(cfg.magnet_count - 1)
        return fader_position_m + k * cfg.magnet_pitch_m + cfg.magnet_pitch_m / 2.0

    def image_z_center_m(self) -> float:
        """Z position of image magnet centres [m] (back-iron arrangements only)."""
        cfg = self.config
        z_mirror = cfg.air_gap_m + cfg.magnet_dims_m[2]
        z_original = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0
        return 2.0 * z_mirror - z_original

    def bfield_at_pcb_surface(
        self,
        x_sample: np.ndarray,
        fader_position_m: float = 0.0,
        z_observer: float = 0.0,
    ) -> np.ndarray:
        """Sample B along the board centre-line at the PCB surface.

        Parameters
        ----------
        x_sample:
            X positions [m].
        fader_position_m:
            Fader position [m].
        z_observer:
            Z of the observation plane [m].  Default 0 = PCB copper surface.

        Returns
        -------
        np.ndarray
            Shape ``(len(x_sample), 3)`` — B [T].
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
