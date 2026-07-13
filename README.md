# pcbstatorgen

A tool for generating multi-layer PCB stator layouts for linear coreless
motors. Designed for **flying fader** applications — motorised faders used
in professional audio mixing consoles.

Rather than drawing copper traces by hand, `pcbstatorgen` computes the
optimal coil geometry analytically, validates the motor force, and writes
the complete track and via layout to an open KiCad 10 PCB file via the
[kicad-python IPC API](https://pypi.org/project/kicad-python/).

The user interface is a **Tauri + Svelte desktop app** backed by a pure
**Rust** physics core. There is no Python runtime — the Rust workspace is
the sole authoritative implementation.

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

## Requirements

- **KiCad 10.0+** — PCB editor open, IPC API enabled
- **Rust (stable, 1.80+)** — physics core + Tauri backend
- **Node.js 18+** — Svelte frontend
- macOS 12+ or Linux (Windows untested)

---

## Installation

```bash
git clone https://github.com/<your-handle>/pcbstatorgen.git
cd pcbstatorgen

# Desktop app (primary UI)
cd app
npm install
npm run tauri dev
```

---

## Quick start

### 1. Enable the KiCad IPC API (one-time)

1. Open KiCad 10
2. **Preferences → Plugins → Enable IPC API**
3. Restart KiCad

### 2. Launch the desktop app

```bash
cd app
npm run tauri dev
```

Configure your motor in the UI, preview the magnetic field and force plots,
then click **Write to KiCad** when ready.

All generated tracks and vias appear as **one undo step** — `Ctrl+Z` rolls
back the entire layout cleanly.

---

## Workspace structure

```
pcbstatorgen/
│
├── Cargo.toml                # Rust workspace root
├── crates/
│   └── pcbstatorgen-rs/      # Pure Rust physics core
│       ├── src/
│       │   ├── geometry/     # Wave winding, via grids, end-turn routing
│       │   ├── magnetic/     # Magnet array, coil model, force evaluation
│       │   ├── stackup/      # Layer optimizer, pyramid trace assignment
│       │   ├── kicad/        # KiCad 10 IPC client (kipy protocol port)
│       │   └── ...
│       └── tests/            # Rust unit + integration tests
│
├── app/                      # Tauri + Svelte desktop app
│   ├── src/                  # Svelte frontend
│   └── src-tauri/            # Rust Tauri commands (calls pcbstatorgen-rs)
│
├── scripts/
│   ├── sync_protos.sh        # Sync kipy protobuf definitions into the crate
│   └── fixtures/
│       └── test_vectors.json # Static test vectors (consumed by Rust tests)
│
└── docs/
    └── reference/
        └── plugin_entry.py   # kipy protocol reference (basis for Rust port)
```

---

## Testing

The Rust workspace is the sole implementation and is fully tested:

```bash
cargo test --workspace      # all unit + integration tests
cargo build --workspace     # release-able build check
```

Rust tests load static fixtures from `scripts/fixtures/test_vectors.json`.
These vectors are **committed to git as static data** — they are not
regenerated at test time.

---

## Configuration

Motor configuration is expressed in the UI and passed through Tauri
commands to the Rust core. All internal calculations use SI units. The
default config targets a 75 mm travel flying fader with 10×10×4 mm N44H
magnets on a 12 mm pole pitch, 3 phases, 500 mN continuous thrust at 1 A
peak.

---

## KiCad IPC API — verified patterns

Audited against kicad-python 0.7.1 (the basis for the Rust IPC port):

- `kipy.KiCad().get_board()` — fetch the live board
  (`get_open_boards()` does **not** exist)
- `board.name` — the board's display name
  (`board.board_filename` does **not** exist)
- All positions and dimensions are **nanometres (int64)**
  (e.g. 5-mil trace → 127 000 nm)
- Atomic commit — one `Ctrl+Z` step in KiCad:
  `begin_commit()` → `create_items()` → `push_commit()`

### Stackup note

`board.set_stackup()` does not exist in kicad-python 0.7.1.
Configure per-layer copper thickness manually in **Board Setup → Physical Stackup**
before running the generator.

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
