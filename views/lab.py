"""Lab page: draw a random puzzle, run the in-circuit Grover circuit on one backend."""
import streamlit as st

import arena
import grover_engine as ge
import state
import ui


def outcome_rows(c, counts, top=8):
    prob = c["prob"]
    shots = sum(counts.values())
    rows = []
    for key, v in sorted(counts.items(), key=lambda kv: -kv[1])[:top]:
        grid = prob.decode(prob.key_to_bits(key))
        ok = prob.is_valid(grid)
        txt = " | ".join("".join(str(x) for x in r) for r in grid) if grid else "no grid"
        rows.append({"label": f"{key}  ·  {txt}", "share": v / shots, "valid": bool(ok)})
    return rows


def render():
    state.ensure()
    ui.hero("Oracle Lab", "Grover search whose oracle checks the Sudoku rule with gates inside the circuit")
    ss = st.session_state
    items = state.fixed_items()
    fixed = dict(items)
    c = state.case(items)
    prob = c["prob"]

    left, right = st.columns([5, 7], gap="large")
    with left:
        st.markdown('<span class="tag">easy puzzle · 3 random clues</span>', unsafe_allow_html=True)
        st.button("🎲 Draw a random puzzle", on_click=state.new_puzzle, width="stretch")
        ui.show_board(fixed)
        st.markdown(f'<span class="tag">{len(fixed)} clues</span><span class="tag">{prob.num_qubits} search qubits</span>'
                    f'<span class="tag">{prob.search_space} candidates</span>', unsafe_allow_html=True)
        st.caption("Dark discs are clues. Every row and column must hold 0, 1 and 2 exactly once.")

    with right:
        cost = state.circuit_size(items)
        k1, k2, k3 = st.columns(3)
        with k1:
            ui.stat("Circuit width", f"{c['circuit'].num_qubits} qubits", f"{prob.num_qubits} data + 3 flags + helpers")
        with k2:
            ui.stat("Two-qubit gates", f"{cost['two_q']}", "ideal gate set, before routing")
        with k3:
            ui.stat("Grover iterations", f"{c['iters']}", "oracle + diffuser repeats")
        st.write("")
        backend = st.selectbox("Backend", arena.ALL_RUNNABLE, key="lab_backend",
                               format_func=lambda b: b if b in arena.IDEALS else
                               f"{b}  ·  {arena.ARENA[b][0]}")
        st.caption(arena.IDEAL_NOTES[backend] if backend in arena.IDEALS else arena.ARENA[backend][1])
        st.slider("Shots", 256, 8192, step=256, key="shots")
        go = st.button("▶ Run circuit", type="primary", width="stretch")

    if go:
        with st.spinner(f"Simulating on {backend}…"):
            try:
                rec = state.record(items, backend, ss.shots)
            except Exception as exc:  # keep the page alive if one simulator fails
                st.error(f"{backend} failed: {type(exc).__name__}: {exc}")
                return
        ss.lab_last = (items, backend, ss.shots)
    with st.expander("Circuit diagram: one Grover iteration", expanded=True):
        st.image(state.iteration_diagram(items), width="stretch")
        st.caption("H on the data qubits, then compute the three pair flags, flip the sign when all three are 1 "
                   "(H·CCX·H on the last flag), uncompute the flags, then the diffuser. "
                   f"The full circuit repeats the oracle and diffuser {c['iters']} times, then measures the data qubits.")
    last = ss.get("lab_last")
    if not last or last[0] != items:
        st.info("Pick a backend and press **Run circuit**. Nothing is run until you do.")
        return
    rec = state.record(*last)

    st.markdown("---")
    r1, r2 = st.columns([4, 7], gap="large")
    with r1:
        st.markdown(f"##### Most frequent outcome · {rec['name']}")
        ui.show_board(fixed, rec["best_rows"], "ok" if rec["best_valid"] else "bad", size=240)
        st.markdown(('<span class="tag good">valid grid</span>' if rec["best_valid"] else
                     '<span class="tag bad">not a valid grid</span>')
                    + f'<span class="tag">{rec["seconds"]} s</span>', unsafe_allow_html=True)
    with r2:
        m1, m2, m3 = st.columns(3)
        with m1:
            ui.stat("Success", f"{rec['success']:.0%}", "shots that decode to a valid grid")
        with m2:
            ui.stat("Blind guess", f"{len(prob.marked) / prob.search_space:.0%}", "no quantum search at all")
        with m3:
            ui.stat("After routing", f"{rec['two_q']} CZ/CX", f"depth {rec['depth']}")
        st.altair_chart(ui.outcomes_chart(outcome_rows(c, rec["counts"])), width="stretch")
        st.caption("Top outcomes: bit string, then the grid it decodes to (rows separated by |).")

    st.markdown("---")
    st.markdown("##### Valid puzzle")
    found = state.best_valid_from_counts(items, rec["counts"])
    v1, v2 = st.columns([4, 7], gap="large")
    with v1:
        shown = found if found is not None else (state.solved_grids(items) or [None])[0]
        ui.show_board(fixed, shown, "ok", size=240)
    with v2:
        if found is not None:
            st.success("This is the most frequent measured outcome that decodes to a valid grid.")
        else:
            st.warning("No measured shot decoded to a valid grid on this noisy backend. The grid shown is the "
                       "valid completion found by classical enumeration, for comparison.")
        st.caption("Rows: " + " | ".join("".join(str(x) for x in r) for r in (shown or [])))
