"""
pcbstatorgen.server
===================
A lightweight JSON-RPC 2.0 server that exposes the core pcbstatorgen
engine over a local TCP socket.  This is the **Python Sidecar** that
the Tauri (Rust) desktop application spawns and communicates with.

Protocol
--------
Each request is a single JSON object on one line (newline-delimited JSON):

    {"jsonrpc": "2.0", "id": 1, "method": "evaluate_force", "params": {...}}

Each response is a single JSON object on one line:

    {"jsonrpc": "2.0", "id": 1, "result": {...}}

Methods
-------
*  ``ping``               — health check
*  ``build_config``       — validate and return a config summary
*  ``estimate_force``     — fast analytical force/torque estimate
*  ``evaluate_force``     — full 3D Magpylib Biot-Savart force sweep
*  ``sample_bfield``      — sample B-field at PCB surface
*  ``coil_geometry``      — generate and return coil paths for rendering
*  ``height_stack``       — compute the mechanical height stackup
*  ``power_estimate``     — compute resistive power loss and thermal rise

Usage
-----
::

    python -m pcbstatorgen.server --port 8502

Or programmatically::

    from pcbstatorgen.server import run_server
    run_server(port=8502)
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import traceback
from typing import Any

import numpy as np

from pcbstatorgen.config import AxialMotorConfig, BaseMotorConfig, LinearMotorConfig
from pcbstatorgen.serialization import (
    coil_paths_to_dict,
    config_from_dict,
    config_to_dict,
    force_result_to_dict,
    height_stack_to_dict,
    power_budget_to_dict,
)
from pcbstatorgen.stackup.height_stack import HeightStackCalculator
from pcbstatorgen.stackup.power import PowerEstimator
from pcbstatorgen.units import mm

__all__ = ["run_server", "handle_request"]


# ---------------------------------------------------------------------------
# Fast analytical estimate (mirrors the Streamlit _estimate_force_n)
# ---------------------------------------------------------------------------

_ARR_MULT = {
    "ALTERNATING": 1.00,
    "HALBACH": 1.43,
    "ALTERNATING_BACK_IRON": 1.42,
    "HALBACH_BACK_IRON": 1.68,
}

_TOPO_MULT = {
    "serpentine": 1.00,
    "sine_wave": 0.78,
}


def _estimate_force_n(config: BaseMotorConfig, n_layers: int) -> float:
    """Quick analytical force estimate."""
    try:
        hz = HeightStackCalculator()
        bz_peak = hz.field_at_gap(config, config.air_gap_m)
        bz_mean = bz_peak * 0.55
        n_cond = config.active_length_m / config.pole_pitch_m
        layers_per_phase = n_layers // config.phases
        arr_key = config.magnet_arrangement.name
        topo_key = config.coil_topology.value
        F = (
            config.max_current_a
            * config.board_width_m
            * bz_mean
            * n_cond
            * layers_per_phase
            * _ARR_MULT.get(arr_key, 1.0)
            * _TOPO_MULT.get(topo_key, 1.0)
        )
        return max(0.0, float(F))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Request handlers
# ---------------------------------------------------------------------------

def handle_request(req: dict[str, Any]) -> dict[str, Any]:
    """Process a single JSON-RPC request and return a response dict."""
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    try:
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": "pong"}

        # --- config validation ---
        if method == "build_config":
            config = config_from_dict(params)
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "config": config_to_dict(config),
                "summary": config.summary(),
                "pole_pitch_mm": config.pole_pitch_m * 1000,
                "slot_pitch_mm": config.slot_pitch_m * 1000,
                "active_length_mm": config.active_length_m * 1000,
                "board_width_mm": config.board_width_m * 1000,
                "active_area_length_mm": getattr(config, "active_area_length_m", config.active_length_m) * 1000,
                "travel_mm": config.travel_m * 1000,
            }}

        # --- fast analytical force estimate ---
        if method == "estimate_force":
            config = config_from_dict(params["config"])
            n_layers = params.get("layers", 6)
            force = _estimate_force_n(config, n_layers)

            pb = PowerEstimator(
                layers_per_phase=n_layers // config.phases
            ).estimate(config)

            hz = HeightStackCalculator()
            hs = hz.calculate(config)

            result: dict[str, Any] = {
                "force_mn": force * 1000,
                "force_n": force,
            }
            if isinstance(config, AxialMotorConfig):
                result["torque_m_nm"] = force * config.mean_radius_m * 1000
                result["target_torque_m_nm"] = config.target_torque_nm * 1000
                result["target_met"] = result["torque_m_nm"] >= result["target_torque_m_nm"]
            else:
                result["target_force_mn"] = config.target_force_n * 1000
                result["target_met"] = force >= config.target_force_n

            result["power"] = power_budget_to_dict(pb)
            result["height_stack"] = height_stack_to_dict(hs)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        # --- full 3D Magpylib force sweep ---
        if method == "evaluate_force":
            config = config_from_dict(params["config"])
            n_positions = params.get("n_positions", 12)
            meshing = params.get("meshing", 5)
            commutation = params.get("commutation", "max_torque")

            from pcbstatorgen.geometry.coil_generators import make_coil_generator
            from pcbstatorgen.magnetic.force_eval import ForceEvaluator

            gen = make_coil_generator(config.coil_topology)
            if config.coil_topology.value == "spiral":
                coils = gen.generate(config, layer_pair=(0, 1))
            else:
                coils = gen.generate(config)

            ev = ForceEvaluator(
                n_positions=n_positions,
                meshing=meshing,
                commutation=commutation,
            )
            force_result = ev.evaluate(config, coils)

            return {"jsonrpc": "2.0", "id": req_id, "result": force_result_to_dict(force_result)}

        # --- B-field sampling ---
        if method == "sample_bfield":
            config = config_from_dict(params["config"])
            mover_pos_mm = params.get("mover_position_mm", 0.0)
            n_samples = params.get("n_samples", 200)

            from pcbstatorgen.magnetic.magnet_model import MagnetArray

            arr = MagnetArray(config)
            xs = np.linspace(0, config.active_length_m, n_samples)
            B = arr.bfield_at_pcb_surface(xs, mover_position_m=mm(mover_pos_mm))

            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "positions_mm": (xs * 1000).tolist(),
                "bx_mt": (B[:, 0] * 1000).tolist(),
                "by_mt": (B[:, 1] * 1000).tolist(),
                "bz_mt": (B[:, 2] * 1000).tolist(),
                "bz_peak_mt": float(np.abs(B[:, 2]).max()) * 1000,
                "bz_mean_mt": float(np.abs(B[:, 2]).mean()) * 1000,
            }}

        # --- coil geometry for SVG / canvas rendering ---
        if method == "coil_geometry":
            config = config_from_dict(params["config"])

            from pcbstatorgen.geometry.coil_generators import make_coil_generator

            gen = make_coil_generator(config.coil_topology)
            if config.coil_topology.value == "spiral":
                coils = gen.generate(config, layer_pair=(0, 1))
            else:
                coils = gen.generate(config)

            return {"jsonrpc": "2.0", "id": req_id, "result": coil_paths_to_dict(coils)}

        # --- height stack ---
        if method == "height_stack":
            config = config_from_dict(params["config"])
            hz = HeightStackCalculator()
            hs = hz.calculate(config)
            return {"jsonrpc": "2.0", "id": req_id, "result": height_stack_to_dict(hs)}

        # --- power / thermal estimate ---
        if method == "power_estimate":
            config = config_from_dict(params["config"])
            n_layers = params.get("layers", 6)
            pb = PowerEstimator(
                layers_per_phase=n_layers // config.phases
            ).estimate(config)
            return {"jsonrpc": "2.0", "id": req_id, "result": power_budget_to_dict(pb)}

        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": str(exc),
                      "data": traceback.format_exc()},
        }


# ---------------------------------------------------------------------------
# TCP server loop (newline-delimited JSON-RPC)
# ---------------------------------------------------------------------------

def run_server(host: str = "127.0.0.1", port: int = 8502) -> None:
    """Start the JSON-RPC server on the given TCP port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(1)
    print(f"pcbstatorgen JSON-RPC server listening on {host}:{port}", flush=True)

    try:
        while True:
            conn, addr = sock.accept()
            try:
                _handle_connection(conn)
            except Exception:
                pass
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
    finally:
        sock.close()


def _handle_connection(conn: socket.socket) -> None:
    """Handle a single client connection (newline-delimited JSON lines)."""
    buf = b""
    while True:
        data = conn.recv(65536)
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line.decode("utf-8"))
                resp = handle_request(req)
                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            except json.JSONDecodeError:
                err = {"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32700, "message": "Parse error"}}
                conn.sendall((json.dumps(err) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pcbstatorgen JSON-RPC server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
