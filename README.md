# pcbstatorgen

A Python tool for generating multi-layer PCB stator layouts for linear
coreless motors. Designed for **flying fader** applications — motorised
faders used in professional audio mixing consoles.

Rather than drawing copper traces by hand, `pcbstatorgen` computes the
optimal coil geometry analytically, validates the motor force with
[Magpylib](https://magpylib.readthedocs.io), and writes the complete track
and via layout to an open KiCad 10 PCB file via the
[kicad-python IPC API](https://pypi.org/project/kicad-python/).

---

## What it generates

Given mechanical and electrical parameters the tool produces:

- **3-phase wave windings** — continuous serpentine conductor paths across
  the full travel length, one phase per layer pair
- **Pyramid trace widths** — thinner copper on outer layers (reduces AC eddy
  current losses at PWM frequencies) and thicker copper on inner layers
  (reduces DC resistance for burst-current events)
- **Grid via arrays** at every end-turn — dozens of small parallel vias
  instead of a single large one, eliminating current crowding and thermal
  hotspots
- **Optimal layer count** — determined automatically from target force,
  current limit, and PCB manufacturing constraints

The result is sent directly to KiCad as a single undoable commit via the
IPC API.

---

## Toolchain

| Library | Role |
|---|---|
| [kicad-python 0.7.1](https://pypi.org/project/kicad-python/) | KiCad 10 IPC API — writes `Track` and `Via` objects to the live PCB |
| [Magpylib 5.2.3](https://magpylib.readthedocs.io) | Analytical magnet field + Lorentz force (`getFT`) — validates layout before writing |
| [bfieldtools](https://bfieldtools.github.io) *(optional)* | Stream function optimisation — refines coil paths for minimum force ripple |
| [GMSH](https://gmsh.info) + [Elmer FEM](https://www.elmerfem.org) *(optional)* | 3D mesh + finite-element validation of AC eddy current losses and thermal hotspots |
| [Streamlit](https://streamlit.io) *(optional)* | Interactive dashboard — configure, preview field/force plots, write to KiCad |

---

## Requirements

- **KiCad 10.0+** — PCB editor open, IPC API enabled
- **Python 3.11+** — system Python (not KiCad's bundled Python 3.9)
- macOS 12+ or Linux (Windows untested)

---

## Installation

```bash
git clone https://github.com/<your-handle>/pcbstatorgen.git
cd pcbstatorgen

# Core dependencies + dev tools
pip install -e ".[dev]"

# Interactive dashboard
pip install -e ".[gui]"

# Stream function optimisation (bfieldtools — optional)
pip install -e ".[optimize]"

# Elmer FEM mesh export (gmsh — optional)
pip install -e ".[fea]"
```

---

## Quick start

### 1. Enable the KiCad IPC API (one-time)

1. Open KiCad 10
2. **Preferences → Plugins → Enable IPC API**
3. Restart KiCad

### 2. Run the dashboard

```bash
streamlit run gui/streamlit_app.py
```

Opens in a browser tab. Configure your motor with sliders, preview the
magnetic field and force plots, then click **Write to KiCad** when ready.

### 3. Run from the terminal (no GUI)

Open a `.kicad_pcb` file in the KiCad PCB editor, then:

```bash
# Uses the default flying-fader configuration
python plugin_entry.py

# Custom parameters
python scripts/run_headless.py --travel 90 --force 0.8 --current 1.5

# Geometry + force preview only — no KiCad connection needed
python scripts/run_headless.py --dry-run
```

All generated tracks and vias appear as **one undo step** — `Ctrl+Z` rolls
back the entire layout cleanly.

> **Note:** Run from your system Python, not from the KiCad scripting console.
> KiCad's embedded Python 3.9 has no `kipy` module and cannot reach the IPC socket.

---

## Dashboard

```bash
streamlit run gui/streamlit_app.py
```

| Tab | Contents |
|---|---|
| **Summary** | Live parameter readout, conductor counts, skin-depth guide |
| **Coil Geometry** | Wave winding plot (phase colours), via grid preview, current margin indicator |
| **Magnet Field** | Live `getB` plot with fader-position slider — watch the field shift |
| **Force Preview** | `getFT` sweep on demand — thrust vs position, per-phase contributions, ripple % |
| **Write to KiCad** | IPC connection check, pipeline status, Generate button |

---

## Running tests

```bash
# Fast offline tests (no KiCad, no heavy computation)
pytest -m "not integration and not slow"

# Include Magpylib force calculations (~10 s)
pytest -m "not integration"

# Full suite including IPC integration (requires KiCad running with a PCB open)
pytest
```

| Marker | Meaning |
|---|---|
| *(none)* | Pure Python — runs in < 1 s |
| `slow` | Calls `magpy.getB` / `getFT` — a few seconds |
| `integration` | Requires live KiCad 10 IPC connection |

---

## Project structure

```
pcbstatorgen/
│
├── plugin_entry.py          # Entry point — run from terminal
├── pyproject.toml
│
├── pcbstatorgen/            # Main Python package
│   ├── config.py            # MotorConfig + StackupResult dataclasses (SI units)
│   ├── units.py             # mm(), oz_to_m(), m_to_nm(), skin_depth_m(), …
│   │
│   ├── geometry/
│   │   ├── wave_winding.py  # WaveWindingGenerator → PhaseCoil serpentine paths
│   │   ├── via_grid.py      # ViaGridGenerator → parallel via arrays
│   │   └── end_turn.py      # EndTurnRouter → via specs, overlap detection
│   │
│   ├── magnetic/
│   │   ├── magnet_model.py  # MagnetArray — N44H Cuboid collection (Magpylib)
│   │   ├── coil_model.py    # CoilCurrentModel — PhaseCoil → Polyline sources
│   │   └── force_eval.py    # ForceEvaluator — position sweep + ForceResult
│   │
│   ├── stackup/             # [Phase 4] LayerOptimizer, pyramid trace assignment
│   ├── kicad_writer/
│   │   └── connection.py    # KiCadConnection — verified IPC API wrapper
│   │   # [Phase 5] track_writer, via_writer, net_manager, board_setup
│   ├── optimization/        # [Phase 6] bfieldtools stream function (optional)
│   └── export/              # [Phase 7] GMSH + Elmer FEM export
│
├── gui/
│   └── streamlit_app.py     # 5-tab Streamlit dashboard
│
├── scripts/
│   └── run_headless.py      # CLI wrapper with argparse
│
└── tests/                   # 273 tests — fast, slow, integration tiers
```

---

## Configuration

All `MotorConfig` fields use SI units internally. Human-readable helpers are in `units.py`:

```python
from pcbstatorgen.config import MotorConfig
from pcbstatorgen.units import mm, mils_to_m

cfg = MotorConfig(
    travel_m=mm(75),                         # 75 mm fader travel
    magnet_dims_m=(mm(10), mm(10), mm(4)),   # 10×10×4 mm N44H magnets
    magnet_count=10,                         # 10 magnets, alternating poles
    magnet_pitch_m=mm(12),                   # 12 mm pole pitch
    phases=3,
    target_force_n=0.5,                      # 500 mN continuous thrust
    max_current_a=1.0,                       # 1 A peak phase current
    min_trace_m=mils_to_m(5),               # JLCPCB standard tier
    min_space_m=mils_to_m(5),
    min_via_drill_m=mm(0.2),
    min_via_annular_ring_m=mm(0.1),
    board_width_m=mm(20),
    air_gap_m=mm(0.5),
)

# Derived properties
print(cfg.slot_pitch_m)       # 4 mm  (pole_pitch / phases)
print(cfg.active_length_m)    # 195 mm  (travel + coil span)
```

---

## KiCad IPC API — verified patterns

Audited against kicad-python 0.7.1:

```python
import kipy

kicad = kipy.KiCad()
board = kicad.get_board()          # correct  (get_open_boards() does NOT exist)
board.name                         # correct  (board.board_filename does NOT exist)

# Units: all positions and dimensions are nanometres (int64)
from pcbstatorgen.units import m_to_nm
track.width = m_to_nm(0.000127)    # 5-mil trace → 127 000 nm
via.drill_diameter = m_to_nm(0.0002)

# Atomic commit — one Ctrl+Z step in KiCad
commit = board.begin_commit()
board.create_items(tracks_and_vias)
board.push_commit(commit, "Stator coils")
```

### Stackup note

`board.set_stackup()` does not exist in kicad-python 0.7.1.
Configure per-layer copper thickness manually in **Board Setup → Physical Stackup**
before running the generator.

---

## Implementation status

| Phase | Module | Status |
|---|---|---|
| 1 | `config.py`, `units.py`, scaffolding | ✅ Complete |
| 2 | `geometry/` — wave winding, via grids, end-turn routing | ✅ Complete |
| 3 | `magnetic/` — Magpylib force model, B-field + `getFT` sweep | ✅ Complete |
| 4 | `stackup/` — LayerOptimizer, pyramid trace assignment | 🔲 Next |
| 5 | `kicad_writer/` — Track, Via, Net, BoardStackup via IPC | 🔲 Pending |
| 6 | `optimization/` — bfieldtools stream function refinement | 🔲 Pending |
| 7 | `export/` — GMSH mesh + Elmer FEM `.sif` case files | 🔲 Pending |

**273 tests** across fast / slow / integration tiers.

---

## Physics background

### Why a wave winding?

Each phase forms a serpentine across the PCB width, stepping one pole pitch
along the travel axis at each reversal:

```
Phase A (τ = 12 mm, W = 20 mm):

  y=W  ──┬──────────┬──────────┬──
         │  active  │  active  │     ← conductors ⊥ to travel → generate thrust
  y=0  ──┴──────────┴──────────┴──
         x=0       τ          2τ
          └─ end-turn (‖ travel) ─┘
```

Phase B starts at `x = τ/3` (4 mm), Phase C at `x = 2τ/3` (8 mm).
Adjacent phases' end-turns overlap in X, so each phase occupies its own
layer pair.

### Why pyramid traces?

At 1 MHz (PWM harmonic frequencies), the copper skin depth is ~66 µm.
A 1 oz outer layer (35 µm) fits within the skin depth — the full conductor
participates with minimal AC loss. A 2 oz layer (70 µm) exceeds it. Inner
layers can be 2–4 oz for lower DC resistance because they are shielded from
the strongest field gradients by the outer layers.

### Why grid vias?

For the default config (12 mm pole pitch, 0.2 mm drill):
- Via pitch: 0.53 mm → **19 × 3 = 57 vias per end-turn**
- Current capacity: 57 × 0.5 A = **28.5 A** (28× headroom at 1 A peak)
- Thermal: current distributed across 57 parallel paths → no hotspot

---

## kicad-cli (macOS)

```bash
# Add to ~/.zshrc
export PATH="/Applications/KiCad/KiCad.app/Contents/MacOS:$PATH"

# Export Gerbers from a finished board
kicad-cli pcb export gerbers --output ./gerbers/ board.kicad_pcb
```

---

## License

MIT
