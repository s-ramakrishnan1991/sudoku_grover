"""Oracle page: how the in-circuit rule oracle is built, with a probe that runs the real oracle circuit."""
import itertools

import altair as alt
import pandas as pd
import streamlit as st
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

import incircuit as gi
import state
import ui

PERMS = list(itertools.permutations(range(3)))


def probe(prob, choice):
    """Run the real oracle and the flag computation on one basis state. Returns (flags, phase)."""
    lay = gi.Layout(prob)
    idx = 0
    for r, a in enumerate(choice):
        idx |= a << prob.offsets[r]
    qc = QuantumCircuit(lay.num_qubits)
    gi.compute_flags(qc, lay)
    sv = Statevector.from_int(idx, 2 ** lay.num_qubits).evolve(qc)
    top = int(abs(sv.data).argmax())
    flags = [(top >> f) & 1 for f in lay.flags]
    oc, _ = gi.oracle_circuit(prob)
    amp = Statevector.from_int(idx, 2 ** lay.num_qubits).evolve(oc).data[idx]
    return flags, float(amp.real)


def render():
    state.ensure()
    ui.hero("Oracle anatomy", "What the in-circuit oracle computes, and what it costs")
    items = state.fixed_items()
    c = state.case(items)
    prob = c["prob"]

    st.markdown("#### One Grover iteration")
    st.markdown(
        '<div class="flow"><div>H on data qubits</div><div class="arr">→</div>'
        '<div class="hot">compute 3 pair flags</div><div class="arr">→</div>'
        '<div class="hot">CCZ on the flags (sign flip)</div><div class="arr">→</div>'
        '<div class="hot">uncompute flags</div><div class="arr">→</div>'
        '<div>diffuser</div><div class="arr">×k →</div><div>measure data</div></div>', unsafe_allow_html=True)
    st.image(state.iteration_diagram(items), width="stretch")
    st.caption("The real gates of one iteration for this puzzle: data qubits on top, then the three flags and the helper qubits.")
    st.markdown(
        "A grid whose rows are permutations of 0, 1, 2 is a valid Sudoku exactly when **no two rows hold the "
        "same value in the same column**. So the circuit tests the three row pairs (0,1), (0,2) and (1,2). "
        "Each test writes a *compatible* flag into its own qubit. The sign flip happens only when all three "
        "flags are 1, and the flags are then uncomputed so they leave no trace.")

    a, b = st.columns([6, 5], gap="large")
    with a:
        st.markdown("#### Pair-compatibility table")
        rows = [{"p": "".join(map(str, p)), "q": "".join(map(str, q)), "ok": gi.rows_compatible(p, q)}
                for p in PERMS for q in PERMS]
        df = pd.DataFrame(rows)
        order = ["".join(map(str, p)) for p in PERMS]
        heat = alt.Chart(df).mark_rect(stroke="#8885", strokeWidth=1).encode(
            x=alt.X("q:N", sort=order, title="row j"), y=alt.Y("p:N", sort=order, title="row i"),
            color=alt.Color("ok:N", legend=None, scale=alt.Scale(domain=[True, False], range=[ui.TEAL, "#8883"])),
            tooltip=["p", "q", "ok"]).properties(height=260)
        st.altair_chart(heat, width="stretch")
        st.caption("Teal = the two row permutations never agree in a column. This small table is the only "
                   "rule knowledge the circuit is built from; the list of solutions is never used.")
    with b:
        st.markdown("#### Register layout for this puzzle")
        lay = gi.Layout(prob)
        regs = [(f"row {r}", f"{len(lay.reg(r))} qubit(s)", f"{len(prob.row_choices[r])} choice(s)")
                for r in range(3)]
        regs += [("pair flags", "3 qubits", "(0,1) (0,2) (1,2)"), ("helper qubits", f"{lay.n_anc}", "clean, for multi-controlled X")]
        st.dataframe(pd.DataFrame(regs, columns=["register", "size", "holds"]), hide_index=True, width="stretch")
        cost = state.circuit_size(items)
        st.markdown("**Full circuit size** (plain gate set, no routing)")
        st.dataframe(pd.DataFrame([{"qubits": cost["qubits"], "2Q gates": cost["two_q"], "depth": cost["depth"]}]),
                     hide_index=True, width="stretch")

    st.markdown("---")
    st.markdown("#### Probe the oracle")
    st.caption("Choose a permutation for each row. The app runs the real oracle circuit on that one basis state "
               "and shows the flag qubits and the resulting phase.")
    cols = st.columns(3)
    choice = []
    for r in range(3):
        opts = list(range(len(prob.row_choices[r])))
        with cols[r]:
            choice.append(st.selectbox(f"Row {r}", opts, key=f"probe_{r}_{st.session_state.seed}",
                                       format_func=lambda i, r=r: "".join(map(str, prob.row_choices[r][i]))))
    grid = [list(prob.row_choices[r][choice[r]]) for r in range(3)]
    flags, phase = probe(prob, choice)
    p1, p2 = st.columns([4, 6], gap="large")
    with p1:
        ui.show_board(dict(items), grid, "ok" if phase < 0 else "bad", size=220)
    with p2:
        names = ["rows 0 and 1", "rows 0 and 2", "rows 1 and 2"]
        for n, f in zip(names, flags):
            st.markdown(f'<span class="tag {"good" if f else "bad"}">{"compatible" if f else "clash"}</span> {n}',
                        unsafe_allow_html=True)
        st.markdown("")
        if phase < 0:
            st.success("Phase −1: this grid is valid, so the oracle marks it.")
        else:
            st.warning("Phase +1: not marked, because at least one pair clashes in a column.")
    with st.expander("What this is, and is not"):
        st.markdown(
            "* The oracle contains no list of solutions, and the circuit decides validity from the rule.\n"
            "* The pair table above is derived from the rule for two rows; it is not the answer to the puzzle.\n"
            f"* The number of repeats ({c['iters']}) is taken from classical counting of solutions. It only sets how "
            "often the loop runs.\n"
            "* Checking the rule inside the circuit takes many two-qubit gates, which is why noisy devices "
            "find the answer less often.")
