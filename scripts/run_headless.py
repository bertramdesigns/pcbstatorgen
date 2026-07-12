"""
scripts/run_headless.py — CLI entry point
=========================================
Runs the stator generation pipeline without opening the KiCad GUI.  Useful
for batch iteration, CI validation of the geometry math, and automated
design-space sweeps.

This script still requires KiCad 10 to be running with the IPC API enabled in
order to write to a PCB document (step 5).  Steps 1–4 (geometry, Magpylib
force evaluation) work without a KiCad connection.

Usage
-----
.. code-block:: bash

    python scripts/run_headless.py
    python scripts/run_headless.py --force 0.8 --current 1.5 --travel 90
    python scripts/run_headless.py --dry-run   # skip KiCad write

Run ``python scripts/run_headless.py --help`` for full option list.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow importing the package from the project root without installation.
sys.path.insert(0, str(Path(__file__).parent.parent))

from pcbstatorgen.config import MotorConfig
from pcbstatorgen.units import mm, mils_to_m


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="run_headless.py",
        description="PCB stator generator — headless / CLI mode",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--travel", type=float, default=75.0, metavar="MM",
        help="Mover travel distance [mm]",
    )
    parser.add_argument(
        "--force", type=float, default=0.5, metavar="N",
        help="Target continuous linear force [N]",
    )
    parser.add_argument(
        "--current", type=float, default=1.0, metavar="A",
        help="Peak phase current [A]",
    )
    parser.add_argument(
        "--width", type=float, default=20.0, metavar="MM",
        help="PCB width (perpendicular to travel) [mm]",
    )
    parser.add_argument(
        "--air-gap", type=float, default=0.5, metavar="MM",
        help="Air gap between magnet face and PCB surface [mm]",
    )
    parser.add_argument(
        "--min-trace", type=float, default=5.0, metavar="MIL",
        help="Minimum trace width [mils]",
    )
    parser.add_argument(
        "--min-space", type=float, default=5.0, metavar="MIL",
        help="Minimum trace-to-trace clearance [mils]",
    )
    parser.add_argument(
        "--max-layers", type=int, default=12,
        help="Hard upper limit on copper layer count",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip KiCad board write; run geometry and force evaluation only",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Optional label for this configuration",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> MotorConfig:
    """Construct a MotorConfig from parsed CLI arguments."""
    return MotorConfig(
        name=args.name or f"headless-t{args.travel:.0f}mm-f{args.force:.2f}N",
        travel_m=mm(args.travel),
        magnet_dims_m=(mm(10), mm(10), mm(4)),
        magnet_count=10,
        magnet_pitch_m=mm(12),
        magnet_remanence_t=1.35,
        phases=3,
        target_force_n=args.force,
        max_current_a=args.current,
        min_trace_m=mils_to_m(args.min_trace),
        min_space_m=mils_to_m(args.min_space),
        min_via_drill_m=mm(0.2),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(args.width),
        air_gap_m=mm(args.air_gap),
        max_layers=args.max_layers,
        drive_frequency_hz=500.0,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns exit code 0 on success, 1 on error."""
    args = parse_args(argv)
    config = build_config(args)
    print(config.summary())

    if args.dry_run:
        print("\n[dry-run] Skipping KiCad board write.")
        print("Subsequent phases not yet implemented — nothing more to do.")
        return 0

    # Import and run the main pipeline.
    # Phase implementations will be wired in here as they are completed.
    try:
        import plugin_entry
        plugin_entry.run(config)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
