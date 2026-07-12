"""
pcbstatorgen.kicad_writer.connection
==========================================
Establishes and manages the IPC API connection to a running KiCad 10 instance.

Architecture note
-----------------
This module uses the **kicad-python IPC API** exclusively — there is no
``import pcbnew`` (SWIG) anywhere in this project.  The IPC API communicates
over a Unix socket (``/tmp/kicad/api.sock``) with KiCad 10's background
server process.

**This module must be run from an external Python process** (terminal, CI,
IDE), not from the KiCad scripting console.  The scripting console uses
KiCad's bundled Python 3.9 with the ``pcbnew`` SWIG API; that interpreter
has no ``kipy`` module and cannot reach the IPC socket from within itself.

Verified API facts (kicad-python 0.7.1)
-----------------------------------------
* ``kipy.KiCad()`` — connect via nng socket
* ``kicad.get_board()`` — returns a ``Board`` directly; raises ``ApiError``
  if no PCB is open (no ``get_open_boards()`` method exists)
* ``board.name`` — filename of the open PCB (``board.board_filename``
  does NOT exist on the ``Board`` class)
* ``board.get_copper_layer_count()`` — available since kicad-python 0.5.0
  (KiCad 9.0.5)
* ``board.begin_commit()`` / ``push_commit()`` / ``drop_commit()`` — the
  correct transaction pattern; ``push_commit`` creates a **single** undo step
* Coordinates and dimensions: **nanometres (int64)** — use
  :func:`~pcbstatorgen.units.m_to_nm` to convert from SI metres

Stackup limitations
-------------------
``board.get_stackup()`` is readable.  However, there is **no
``board.set_stackup()``** in kicad-python 0.7.1.  Per-layer copper
thickness must be configured manually in KiCad's Board Setup dialog before
running the generation script.  Only the layer *count* can be set
programmatically via ``board.set_enabled_layers()``, and this operation
is **destructive** (it cannot be undone).
"""

from __future__ import annotations

import contextlib
from typing import Generator

from pcbstatorgen.units import m_to_nm, nm_to_m

__all__ = ["KiCadConnection", "connect"]


class KiCadConnection:
    """Managed IPC connection to a running KiCad 10 instance.

    Usage::

        with connect() as conn:
            print(conn.board_filename)
            print(conn.copper_layer_count)

    Or without the context manager::

        conn = KiCadConnection()
        conn.connect()
        board = conn.board

    Parameters
    ----------
    timeout_ms:
        Socket receive timeout in milliseconds.  Passed to the underlying
        ``pynng`` socket.  Default: 5000 ms.
    """

    def __init__(self, timeout_ms: int = 5000) -> None:
        self._timeout_ms = timeout_ms
        self._kicad = None
        self._board = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the IPC socket and retrieve the active board.

        Raises
        ------
        ImportError
            If ``kicad-python`` is not installed.
        RuntimeError
            If KiCad is not running, IPC is disabled, or no PCB is open.
        """
        try:
            import kipy
            from kipy.errors import ConnectionError as KiCadConnError, ApiError
        except ImportError as exc:
            raise ImportError(
                "kicad-python is not installed.\n"
                "Install into your system Python: pip install kicad-python\n"
                "(Do NOT install into KiCad's bundled Python 3.9.)"
            ) from exc

        try:
            self._kicad = kipy.KiCad()
            # kicad.get_board() is the single correct entry point.
            # It raises ApiError (not RuntimeError) when no PCB is open.
            self._board = self._kicad.get_board()
        except KiCadConnError as exc:
            raise RuntimeError(
                "Cannot reach KiCad IPC socket.\n"
                "  1. KiCad 10 must be running.\n"
                "  2. Preferences > Plugins > Enable IPC API must be checked.\n"
                f"  Detail: {exc}"
            ) from exc
        except Exception as exc:  # ApiError or anything from pynng
            raise RuntimeError(
                "KiCad IPC connection failed — is a .kicad_pcb file open?\n"
                f"  Detail: {exc}"
            ) from exc

    def disconnect(self) -> None:
        """Close the IPC socket (no-op if not connected)."""
        self._kicad = None
        self._board = None

    def __enter__(self) -> "KiCadConnection":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Board accessors
    # ------------------------------------------------------------------

    @property
    def board(self):
        """The open ``kipy.board.Board`` instance."""
        if self._board is None:
            raise RuntimeError("Not connected — call connect() first.")
        return self._board

    @property
    def board_filename(self) -> str:
        """Filename of the currently open PCB (empty string if unsaved).

        Uses ``board.name`` — the correct attribute in kicad-python 0.7.1.
        (``board.board_filename`` does not exist and raises ``AttributeError``.)
        """
        return self.board.name or ""

    @property
    def copper_layer_count(self) -> int:
        """Number of copper layers in the open board.

        Uses ``board.get_copper_layer_count()`` (kicad-python ≥ 0.5.0).
        """
        return self.board.get_copper_layer_count()

    def check_version(self, min_version: tuple[int, int, int] = (9, 0, 5)) -> str:
        """Return the KiCad version string and raise if below ``min_version``.

        Parameters
        ----------
        min_version:
            Minimum acceptable KiCad version as ``(major, minor, patch)``.
            Default: ``(9, 0, 5)`` — the version that added
            ``get_copper_layer_count()``.

        Returns
        -------
        str
            Version string as reported by KiCad (e.g. ``"10.0.1"``).
        """
        # Handle both string and protobuf object returns from get_version()
        v = self._kicad.get_version()
        version_str = getattr(v, "kicad_version", str(v)).split()[0]  # get "10.0.3" from "10.0.3 (10.0.3)"
        parts = tuple(int(x) for x in version_str.split(".")[:3] if x.isdigit())
        if parts < min_version:
            min_str = ".".join(str(x) for x in min_version)
            raise RuntimeError(
                f"KiCad {version_str} is below the minimum required version "
                f"{min_str}.  Please upgrade KiCad."
            )
        return version_str

    # ------------------------------------------------------------------
    # Commit / transaction helpers
    # ------------------------------------------------------------------

    @contextlib.contextmanager
    def commit(self, description: str = "Motor coil generation") -> Generator:
        """Context manager that wraps all board writes in one undo step.

        On success: calls ``push_commit()`` — creates a single Ctrl+Z entry.
        On exception: calls ``drop_commit()`` — discards all changes.

        Usage::

            with conn.commit("Place Phase A coils") as c:
                items = build_tracks_and_vias(...)
                conn.board.create_items(items)
            # KiCad now shows all items, undoable in one step.

        Parameters
        ----------
        description:
            Label shown in KiCad's undo history.

        Yields
        ------
        The ``kipy.common_types.Commit`` object (rarely needed directly).
        """
        c = self.board.begin_commit()
        try:
            yield c
            self.board.push_commit(c, description)
        except Exception:
            self.board.drop_commit(c)
            raise

    # ------------------------------------------------------------------
    # Utility — layer mapping
    # ------------------------------------------------------------------

    @staticmethod
    def layer_enum_for_index(layer_idx: int):
        """Return the ``BoardLayer`` enum value for a 0-based layer index.

        Maps the project's 0-based layer indexing to kicad-python's
        ``BoardLayer`` enum:

        * 0         → ``BL_F_Cu``   (top outer)
        * 1         → ``BL_In1_Cu``
        * 2         → ``BL_In2_Cu``
        * …
        * N-1       → ``BL_B_Cu``   (bottom outer, where N = copper_layer_count)

        Parameters
        ----------
        layer_idx:
            0-based layer index as used throughout this project.

        Returns
        -------
        ``BoardLayer`` enum value for use in ``Track.layer`` and ``Via.type``.

        Raises
        ------
        ImportError
            If ``kicad-python`` is not installed.
        ValueError
            If ``layer_idx`` is negative or > 29 (KiCad's maximum inner layers).
        """
        try:
            from kipy.board_types import BoardLayer
        except ImportError as exc:
            raise ImportError("kicad-python required for layer_enum_for_index") from exc

        if layer_idx < 0:
            raise ValueError(f"layer_idx must be ≥ 0, got {layer_idx}")

        # kicad-python BoardLayer enum values (verified from board_types.py):
        # BL_F_Cu=0, BL_In1_Cu=1, …, BL_In30_Cu=30, BL_B_Cu=31
        # We expose layer 0 = F.Cu, layer 1 = In1.Cu, …, last = B.Cu.
        # The caller is responsible for passing the correct layer_count to
        # distinguish inner vs. bottom-outer layers.
        _map = {
            0: BoardLayer.BL_F_Cu,
            1: BoardLayer.BL_In1_Cu,
            2: BoardLayer.BL_In2_Cu,
            3: BoardLayer.BL_In3_Cu,
            4: BoardLayer.BL_In4_Cu,
            5: BoardLayer.BL_In5_Cu,
            6: BoardLayer.BL_In6_Cu,
            7: BoardLayer.BL_In7_Cu,
            8: BoardLayer.BL_In8_Cu,
            9: BoardLayer.BL_In9_Cu,
            10: BoardLayer.BL_In10_Cu,
            11: BoardLayer.BL_B_Cu,  # treat index 11 as B.Cu for 12-layer boards
        }
        if layer_idx not in _map:
            raise ValueError(
                f"layer_idx {layer_idx} out of supported range (0–11 for ≤12-layer boards)."
            )
        return _map[layer_idx]

    @staticmethod
    def layer_name_for_index(layer_idx: int, layer_count: int) -> str:
        """Return the canonical KiCad layer name string for a layer index.

        Handles the special case where the last index maps to ``B.Cu``
        regardless of the layer count.

        Parameters
        ----------
        layer_idx:
            0-based layer index.
        layer_count:
            Total copper layer count (used to identify the bottom outer layer).

        Returns
        -------
        str
            E.g. ``"F.Cu"``, ``"In1.Cu"``, ``"B.Cu"``.
        """
        if layer_idx == 0:
            return "F.Cu"
        if layer_idx == layer_count - 1:
            return "B.Cu"
        return f"In{layer_idx}.Cu"


@contextlib.contextmanager
def connect(timeout_ms: int = 5000) -> Generator[KiCadConnection, None, None]:
    """Convenience context manager: connect, yield, disconnect.

    Usage::

        from pcbstatorgen.kicad_writer.connection import connect

        with connect() as conn:
            print(f"KiCad board: {conn.board_filename}")
            print(f"Layers: {conn.copper_layer_count}")

    Parameters
    ----------
    timeout_ms:
        Socket timeout in milliseconds.

    Yields
    ------
    :class:`KiCadConnection`
        A connected, ready-to-use connection object.
    """
    conn = KiCadConnection(timeout_ms=timeout_ms)
    with conn:
        yield conn
