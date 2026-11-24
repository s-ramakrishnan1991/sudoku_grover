"""Grover search for the 3x3 Sudoku with an *in-circuit* rule oracle.

Used by the in-circuit Streamlit app. Puzzle generation and decoding come from ``grover_engine``.

How the oracle is built
-----------------------
The oracle never sees the list of solutions. It is built only from the *rule*:

    A grid whose rows are permutations of (0, 1, 2) is a valid Sudoku
    <=>  no two rows hold the same value in the same column
    <=>  every pair of rows (0,1), (0,2), (1,2) is "compatible".

For each row pair the circuit computes a flag qubit "these two rows are
compatible" from the two row-index registers, a multi-controlled Z on the three
flags flips the sign of exactly the valid grids, and the flags are uncomputed.

Honest limitation: the pair-compatibility check is synthesised from a small
truth table (which pairs of row permutations never agree in a column). That is a
local rule table over two rows, not the set of solutions, and the solutions are
never enumerated to build the circuit. The iteration count still needs the number
of solutions M, which here comes from classical enumeration (it only picks how
many times to repeat the loop).
"""
from __future__ import annotations

import itertools
import math
from qiskit import QuantumCircuit

import grover_engine as ge

PAIRS = [(0, 1), (0, 2), (1, 2)]


def rows_compatible(p, q) -> bool:
    """Two rows can sit in the same grid iff they never agree in any column."""
    return all(a != b for a, b in zip(p, q))


def _match(qc, qubits, value, undo=False):
    """X gates so that the register equals ``value`` <=> all qubits are |1>."""
    for k, q in enumerate(qubits):
        if not (value >> k) & 1:
            qc.x(q)


def _mcx(qc, controls, target, ancillas):
    controls = list(controls)
    if not controls:
        qc.x(target)
    elif len(controls) == 1:
        qc.cx(controls[0], target)
    elif len(controls) == 2:
        qc.ccx(controls[0], controls[1], target)
    else:
        need = len(controls) - 2
        if len(ancillas) >= need:
            qc.mcx(controls, target, ancilla_qubits=list(ancillas[:need]), mode="v-chain")
        else:
            qc.mcx(controls, target)


class Layout:
    """Qubit layout: data (row indices) | 3 pair flags | clean ancillas."""

    def __init__(self, prob: ge.Problem, ancillas: bool = True):
        self.prob = prob
        n = prob.num_qubits
        self.data = list(range(n))
        self.flags = list(range(n, n + 3))
        max_controls = max(
            [prob.row_widths[i] + prob.row_widths[j] for i, j in PAIRS] + [n, 3]
        )
        self.n_anc = max(0, max_controls - 2) if ancillas else 0
        self.anc = list(range(n + 3, n + 3 + self.n_anc))
        self.num_qubits = n + 3 + self.n_anc

    def reg(self, row):
        off, w = self.prob.offsets[row], self.prob.row_widths[row]
        return self.data[off:off + w]


def compute_flags(qc, lay: Layout):
    """flag[k] ^= compatible(row_i, row_j) for the k-th row pair (self-inverse)."""
    prob = lay.prob
    for k, (i, j) in enumerate(PAIRS):
        ri, rj = lay.reg(i), lay.reg(j)
        for a, pa in enumerate(prob.row_choices[i]):
            for b, pb in enumerate(prob.row_choices[j]):
                if not rows_compatible(pa, pb):
                    continue
                _match(qc, ri, a)
                _match(qc, rj, b)
                _mcx(qc, ri + rj, lay.flags[k], lay.anc)
                _match(qc, rj, b)
                _match(qc, ri, a)


def rule_oracle(qc, lay: Layout):
    """Phase-flip every basis state that encodes a valid Sudoku grid."""
    compute_flags(qc, lay)
    f = lay.flags
    qc.h(f[2])
    qc.ccx(f[0], f[1], f[2])
    qc.h(f[2])
    compute_flags(qc, lay)  # uncompute: all gates are self-inverse and toggles commute


def diffuser(qc, lay: Layout):
    d = lay.data
    qc.h(d)
    qc.x(d)
    if len(d) == 1:
        qc.z(d[0])
    else:
        qc.h(d[-1])
        _mcx(qc, d[:-1], d[-1], lay.anc)
        qc.h(d[-1])
    qc.x(d)
    qc.h(d)


def oracle_circuit(prob: ge.Problem, ancillas: bool = True) -> tuple[QuantumCircuit, Layout]:
    lay = Layout(prob, ancillas)
    qc = QuantumCircuit(lay.num_qubits, name="rule_oracle")
    rule_oracle(qc, lay)
    return qc, lay


def build_grover_incircuit(prob: ge.Problem, iterations: int | None = None,
                           ancillas: bool = True) -> QuantumCircuit:
    """Full Grover circuit with the in-circuit rule oracle (measures the data qubits)."""
    lay = Layout(prob, ancillas)
    if iterations is None:
        # M is only needed to choose the repeat count, not to build the oracle.
        iterations = ge.grover_iterations(prob.search_space, len(prob.marked))
    qc = QuantumCircuit(lay.num_qubits, len(lay.data), name="incircuit_grover")
    qc.h(lay.data)
    for _ in range(iterations):
        rule_oracle(qc, lay)
        diffuser(qc, lay)
    qc.measure(lay.data, range(len(lay.data)))
    return qc
