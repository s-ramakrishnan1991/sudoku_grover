"""Tests for the in-circuit rule oracle.  Run from the repo root:  uv run python tests/test_incircuit.py"""
import itertools
import math
import sys
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import incircuit as gi  # noqa: E402
ge = gi.ge


def independent_is_valid(prob, bits):
    """Reference check written separately from the circuit: decode the grid and test the columns."""
    rows = prob.decode(bits)
    if rows is None:
        return False
    return all(sorted(rows[r][c] for r in range(3)) == [0, 1, 2] for c in range(3))


def oracle_phases(qc, lay, inputs=None):
    """Run the oracle on data basis states (ancillas/flags start in |0>).

    Returns ({input: amplitude on |input> afterwards}, max_leak) where max_leak is the largest
    amplitude found on any other basis state (flags or ancillas not restored, etc.)."""
    n = len(lay.data)
    inputs = range(2 ** n) if inputs is None else inputs
    phases, leak = {}, 0.0
    for i in inputs:
        sv = Statevector.from_int(i, 2 ** lay.num_qubits).evolve(qc)
        rest = np.abs(sv.data).copy()
        phases[i] = sv.data[i]
        rest[i] = 0
        leak = max(leak, rest.max())
    return phases, leak


def pick_inputs(prob, limit=128, seed=0):
    """All inputs for small registers; otherwise every valid grid plus a random sample of the rest."""
    n = prob.num_qubits
    if 2 ** n <= limit:
        return list(range(2 ** n))
    valid = [i for i in range(2 ** n)
             if independent_is_valid(prob, tuple((i >> k) & 1 for k in range(n)))]
    rng = np.random.default_rng(seed)
    others = [int(i) for i in rng.choice(2 ** n, size=limit - len(valid), replace=False)]
    return sorted(set(valid) | set(others))


def check_oracle(prob, ancillas=True, limit=128):
    qc, lay = gi.oracle_circuit(prob, ancillas)
    inputs = pick_inputs(prob, limit)
    phases, leak = oracle_phases(qc, lay, inputs)
    n = len(lay.data)
    bad = 0
    for i in inputs:
        bits = tuple((i >> k) & 1 for k in range(n))
        expected = -1 if independent_is_valid(prob, bits) else 1
        if abs(phases[i] - expected) > 1e-9:
            bad += 1
    return bad, leak, qc


def test_oracle_matches_rule_for_many_puzzles():
    checked = 0
    for diff in ("easy", "medium"):
        for seed in range(12):
            prob = ge.build_problem(ge.make_puzzle(diff, seed))
            for anc in (True, False):
                bad, leak, _ = check_oracle(prob, anc)
                assert bad == 0, f"{diff} seed {seed} anc={anc}: {bad} wrong phases"
                assert leak < 1e-9, f"{diff} seed {seed}: ancilla/flag leakage {leak}"
                checked += 1
    return checked


def test_oracle_on_hard_and_empty_puzzles():
    """Beyond the app's difficulties: 1 clue (hard) and no clues (empty, 9 search qubits).
    For 'empty' all 12 valid grids plus random other inputs are checked (512 states is slow to simulate)."""
    out = []
    for name, fixed in (("hard", {(1, 1): 2}), ("empty", {})):
        prob = ge.build_problem(fixed)
        bad, leak, qc = check_oracle(prob, True, limit=64 if name == "hard" else 24)
        assert bad == 0 and leak < 1e-9, (name, bad, leak)
        out.append((name, prob.num_qubits, len(prob.marked), qc.num_qubits))
    return out


def test_oracle_never_reads_solution_list():
    """The oracle must work even when the classical solution list is wiped."""
    prob = ge.build_problem(ge.make_puzzle("medium", 3))
    ref_bad, _, _ = check_oracle(prob)
    prob.marked.clear()
    bad, leak, _ = check_oracle(prob)
    assert ref_bad == 0 and bad == 0 and leak < 1e-9


def test_negative_control_broken_oracle_is_caught():
    """Sanity check of the test itself: drop one pair flag and the checker must fail."""
    prob = ge.build_problem(ge.make_puzzle("easy", 1))
    lay = gi.Layout(prob)
    qc = QuantumCircuit(lay.num_qubits)
    gi.compute_flags(qc, lay)
    qc.cz(lay.flags[0], lay.flags[1])          # only two of the three pair conditions
    gi.compute_flags(qc, lay)
    phases, _ = oracle_phases(qc, lay)
    n = len(lay.data)
    wrong = sum(
        abs(phases[i] - (-1 if independent_is_valid(prob, tuple((i >> k) & 1 for k in range(n))) else 1)) > 1e-9
        for i in phases
    )
    assert wrong > 0, "a broken oracle was not detected"
    return wrong


def test_full_grover_ideal():
    rows = []
    for diff in ("easy", "medium"):
        for seed in (1, 2, 3):
            prob = ge.build_problem(ge.make_puzzle(diff, seed))
            M, N = len(prob.marked), prob.search_space
            k = ge.grover_iterations(N, M)
            qc = gi.build_grover_incircuit(prob, k)
            _, counts, _ = ge.run_backend("Aer ideal", qc, 4096)
            a = ge.analyse_counts(prob, counts)
            theory = ge.grover_success_probability(N, M, k)
            assert a["best_valid"], f"{diff} {seed}: most frequent outcome is not a valid grid"
            assert abs(a["success"] - theory) < 0.03, (diff, seed, a["success"], theory)
            rows.append((diff, seed, N, M, k, round(theory, 3), round(a["success"], 3)))
    return rows


if __name__ == "__main__":
    t0 = time.time()
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage == "extra":
        for name, nq, M, width in test_oracle_on_hard_and_empty_puzzles():
            print(f"PASS oracle on '{name}' puzzle: {nq} search qubits, {M} solutions, circuit width {width}", flush=True)
        sys.exit(0)
    n = test_oracle_matches_rule_for_many_puzzles()
    print(f"PASS oracle == rule on 24 puzzles x 2 ancilla modes ({n} circuits, every basis state)", flush=True)
    test_oracle_never_reads_solution_list(); print("PASS oracle works with the solution list wiped")
    w = test_negative_control_broken_oracle_is_caught(); print(f"PASS broken oracle is detected ({w} wrong phases)")
    print("\nFull Grover run, ideal simulator (4096 shots):")
    print("  diff    seed   N   M  iters  theory  measured")
    for r in test_full_grover_ideal():
        print("  %-7s %-5d %3d %3d %5d %7.3f %9.3f" % r)
    print(f"\nTotal {time.time()-t0:.0f}s")
