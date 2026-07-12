"""
pcbstatorgen.serialization
=========================
JSON serialization / deserialization for all core dataclasses.

This module is the **API boundary** between any frontend (Streamlit, Tauri,
CLI, or JSON-RPC server) and the pcbstatorgen core physics engine.  Every
config object, force result, field sample, and geometry path can be
converted to / from a plain ``dict`` that is ``json.dumps``-safe.

Design principles
-----------------
*  **No imports from streamlit, kipy, or any GUI framework.**
*  **Numpy arrays are converted to nested lists** with shape metadata.
*  **Tuples are preserved as lists** (JSON has no tuple type).
*  **Enums are serialized as their ``.value`` string.**
"""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any

import numpy as np

from pcbstatorgen.config import (
    AxialMotorConfig,
    BaseMotorConfig,
    CoilTopology,
    HeightStackResult,
    LinearMotorConfig,
    MagnetArrangement,
    PowerBudget,
)
from pcbstatorgen.magnetic.force_eval import ForceResult

__all__ = [
    "config_to_dict",
    "config_from_dict",
    "force_result_to_dict",
    "height_stack_to_dict",
    "power_budget_to_dict",
    "coil_paths_to_dict",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def config_to_dict(config: BaseMotorConfig) -> dict[str, Any]:
    """Serialize any motor config to a JSON-safe dictionary."""
    d = asdict(config)
    # Convert enums to their string values
    d["coil_topology"] = config.coil_topology.value
    d["magnet_arrangement"] = config.magnet_arrangement.value
    d["magnet_dims_m"] = list(config.magnet_dims_m)
    d["_config_type"] = type(config).__name__
    return d


def config_from_dict(data: dict[str, Any]) -> BaseMotorConfig:
    """Reconstruct a config from a dictionary (e.g. JSON payload from UI)."""
    data = dict(data)  # shallow copy — don't mutate the caller's dict
    # Pop our type tag
    config_type = data.pop("_config_type", None)

    # Reconstruct enums
    if "coil_topology" in data and isinstance(data["coil_topology"], str):
        data["coil_topology"] = CoilTopology(data["coil_topology"])
    if "magnet_arrangement" in data and isinstance(data["magnet_arrangement"], str):
        data["magnet_arrangement"] = MagnetArrangement(data["magnet_arrangement"])
    if "magnet_dims_m" in data:
        data["magnet_dims_m"] = tuple(data["magnet_dims_m"])

    # Choose the right class
    if config_type == "AxialMotorConfig" or "stator_OD_m" in data:
        return AxialMotorConfig(**_filter_fields(data, AxialMotorConfig))
    else:
        return LinearMotorConfig(**_filter_fields(data, LinearMotorConfig))


def _filter_fields(data: dict, cls) -> dict:
    """Keep only keys that are valid fields of *cls*."""
    if not is_dataclass(cls):
        return data
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    # Also include BaseMotorConfig fields
    for base in cls.__mro__:
        if is_dataclass(base) and base is not object:
            valid.update(f.name for f in base.__dataclass_fields__.values())
    return {k: v for k, v in data.items() if k in valid}


# ---------------------------------------------------------------------------
# ForceResult
# ---------------------------------------------------------------------------

def force_result_to_dict(result: ForceResult) -> dict[str, Any]:
    """Serialize a ForceResult to a JSON-safe dictionary."""
    return {
        "positions_mm": (result.positions_m * 1000).tolist(),
        "force_x_mn": (result.force_x_n * 1000).tolist(),
        "force_y_mn": (result.force_y_n * 1000).tolist(),
        "force_z_mn": (result.force_z_n * 1000).tolist(),
        "per_phase_force_x_mn": (result.per_phase_force_x * 1000).tolist(),
        "commutation": result.commutation,
        "current_a": result.current_a,
        "mean_thrust_mn": result.mean_thrust_n * 1000,
        "peak_thrust_mn": result.peak_thrust_n * 1000,
        "min_thrust_mn": result.min_thrust_n * 1000,
        "ripple_pct": result.ripple_pct,
        "n_positions": result.n_positions,
    }


# ---------------------------------------------------------------------------
# HeightStackResult
# ---------------------------------------------------------------------------

def height_stack_to_dict(hs: HeightStackResult) -> dict[str, Any]:
    """Serialize a HeightStackResult to a JSON-safe dictionary."""
    return {
        "pcb_thickness_mm": hs.pcb_thickness_m * 1000,
        "cu_protrusion_mm": hs.cu_protrusion_m * 1000,
        "solder_mask_mm": hs.solder_mask_m * 1000,
        "air_gap_mm": hs.air_gap_m * 1000,
        "magnet_height_mm": hs.magnet_height_m * 1000,
        "back_iron_thickness_mm": hs.back_iron_thickness_m * 1000,
        "tolerance_mm": hs.tolerance_m * 1000,
        "total_height_mm": hs.total_height_m * 1000,
    }


# ---------------------------------------------------------------------------
# PowerEstimate
# ---------------------------------------------------------------------------

def power_budget_to_dict(pb: PowerBudget) -> dict[str, Any]:
    """Serialize a PowerBudget to a JSON-safe dictionary."""
    return {
        "phase_resistance_ohm": pb.phase_resistance_ohm,
        "continuous_power_w": pb.continuous_power_w,
        "continuous_power_mw": pb.continuous_power_w * 1000,
        "burst_power_w": pb.burst_power_w,
        "temperature_rise_c": pb.temperature_rise_c,
        "capacitor_required_uf": pb.capacitor_required_uf,
        "efficiency_pct": pb.efficiency_pct,
    }


# ---------------------------------------------------------------------------
# Coil geometry (for SVG / canvas rendering)
# ---------------------------------------------------------------------------

def coil_paths_to_dict(coils: list) -> dict[str, Any]:
    """Serialize coil geometry to a JSON-safe dictionary for frontend rendering.

    Each phase produces a list of segments.  Active segments and end-turn
    segments are separated so the frontend can render them with different
    styles.
    """
    phases = []
    phase_colors = ["#e74c3c", "#2ecc71", "#3498db", "#9b59b6"]

    for coil in coils:
        active = []
        end_turns = []
        for seg in coil.segments:
            seg_data = {
                "start": [seg.start[0] * 1000, seg.start[1] * 1000],
                "end": [seg.end[0] * 1000, seg.end[1] * 1000],
            }
            if seg.is_active:
                active.append(seg_data)
            else:
                end_turns.append(seg_data)

        phases.append({
            "phase_idx": coil.phase_idx,
            "phase_name": coil.phase_name,
            "layer_idx": coil.layer_idx,
            "topology": coil.topology.value,
            "color": phase_colors[coil.phase_idx % len(phase_colors)],
            "active_segments": active,
            "end_turn_segments": end_turns,
            "active_conductor_count": coil.active_conductor_count,
            "active_length_mm": coil.active_length_m * 1000,
            "total_length_mm": coil.total_length_m * 1000,
        })

    return {
        "phases": phases,
        "n_phases": len(phases),
    }
