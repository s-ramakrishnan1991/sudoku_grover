"""Shared session state and cached simulation helpers for the in-circuit Grover app."""
from __future__ import annotations

import random

import streamlit as st

import arena
import grover_engine as ge
import incircuit as gi



def ensure():
    ss = st.session_state
    ss.setdefault("seed", random.SystemRandom().randrange(1, 10**6))
    ss.setdefault("shots", 1024)
    ss.setdefault("runs", {})        # (fixed_items, backend, shots) -> record


def new_puzzle():
    st.session_state.seed = random.SystemRandom().randrange(1, 10**6)


def fixed_items():
    ss = st.session_state
    fixed = ge.make_puzzle("easy", ss.seed)
    return tuple(sorted(fixed.items()))


@st.cache_resource(show_spinner=False, max_entries=6)
def case(items: tuple):
    """Problem, Grover iteration count and the in-circuit circuit for one puzzle."""
    prob = ge.build_problem(dict(items))
    # M comes from classical counting and only sets how many times Grover repeats.
    iters = ge.grover_iterations(prob.search_space, len(prob.marked))
    return {"prob": prob, "iters": iters, "circuit": gi.build_grover_incircuit(prob, iters)}


@st.cache_data(show_spinner=False, max_entries=48)
def simulate(items: tuple, backend: str, shots: int) -> dict:
    c = case(items)
    tc, counts, sec = arena.run(backend, c["circuit"], shots)
    m = ge.circuit_metrics(tc)
    return {"counts": counts, "seconds": sec, "two_q": m["2Q gates"], "two_q_depth": m["2Q depth"],
            "depth": m["total depth"], "qubits": m["active qubits"]}


@st.cache_data(show_spinner=False, max_entries=12)
def circuit_size(items: tuple) -> dict:
    """Size of the in-circuit Grover circuit after transpiling to a plain gate set (no device noise)."""
    c = case(items)
    tc, _, _ = ge.run_backend("Aer ideal", c["circuit"], 16)
    m = ge.circuit_metrics(tc)
    return {"qubits": m["active qubits"], "two_q": m["2Q gates"], "depth": m["total depth"]}


@st.cache_data(show_spinner=False, max_entries=12)
def solved_grids(items: tuple) -> list:
    """Every valid completion of the puzzle, found by classical enumeration (used only for display)."""
    prob = case(items)["prob"]
    return [prob.decode(tuple(m)) for m in prob.marked]


def best_valid_from_counts(items: tuple, counts: dict):
    """Most frequently measured outcome that decodes to a valid grid, or None."""
    prob = case(items)["prob"]
    for key, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
        g = prob.decode(prob.key_to_bits(key))
        if prob.is_valid(g):
            return g
    return None


@st.cache_data(show_spinner=False)
def iteration_diagram(items: tuple) -> bytes:
    """PNG of one Grover iteration (H, rule oracle, diffuser) drawn from the real gate functions."""
    import io

    import matplotlib
    matplotlib.use("Agg")
    from qiskit import QuantumCircuit, QuantumRegister

    prob = case(items)["prob"]
    lay = gi.Layout(prob)
    qc = QuantumCircuit(QuantumRegister(len(lay.data), "data"), QuantumRegister(3, "flag"),
                        QuantumRegister(lay.n_anc, "helper"))
    qc.h(lay.data)
    qc.barrier()
    gi.compute_flags(qc, lay)
    qc.barrier()
    f = lay.flags
    qc.h(f[2]); qc.ccx(f[0], f[1], f[2]); qc.h(f[2])
    qc.barrier()
    gi.compute_flags(qc, lay)
    qc.barrier()
    gi.diffuser(qc, lay)
    fig = qc.draw("mpl", fold=26, scale=0.7)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return buf.getvalue()


def family(backend: str) -> str:
    return "Reference" if backend in arena.IDEALS else arena.ARENA[backend][0]


def record(items: tuple, backend: str, shots: int) -> dict:
    """Run (cached) and return a result record with the decoded analysis."""
    sim = simulate(items, backend, shots)
    st.session_state.setdefault("done_runs", set()).add((items, backend, shots))
    c = case(items)
    a = ge.analyse_counts(c["prob"], sim["counts"])
    return {"name": backend, "family": family(backend), "success": a["success"], "best_valid": a["best_valid"],
            "best_rows": a["best_rows"], "two_q": sim["two_q"], "seconds": round(sim["seconds"], 1),
            "counts": sim["counts"], "depth": sim["depth"], "qubits": sim["qubits"]}
