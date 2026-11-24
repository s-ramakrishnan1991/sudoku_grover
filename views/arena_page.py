"""Arena page: the same in-circuit puzzle on seven noisy simulators, ranked."""
import pandas as pd
import streamlit as st

import arena
import state
import ui


def hardware_rows(items, iters):
    out = []
    for r in st.session_state.get("hw_results", {}).values():
        if r["fixed_items"] == items and r["iters"] == iters:
            a = r["analysis"]
            out.append({"name": f"{r['provider']} · {r['backend']}", "family": "Real hardware" if r.get("kind", "Real hardware") == "Real hardware" else r.get("kind"),
                        "success": a["success"], "best_valid": a["best_valid"], "two_q": r["metrics"]["2Q gates"] if r.get("metrics") else 0,
                        "depth": r["metrics"]["total depth"] if r.get("metrics") else 0, "seconds": 0, "note": "your hardware job"})
    return out


def render():
    state.ensure()
    ui.hero("Noisy arena", "One in-circuit Grover circuit, seven noisy backends, one ranking")
    ss = st.session_state
    items = state.fixed_items()
    c = state.case(items)
    prob = c["prob"]
    dl = "Easy"
    st.markdown(f'<span class="tag">{dl}</span><span class="tag">seed {ss.seed}</span>'
                f'<span class="tag">{len(items)} clues</span><span class="tag">{c["circuit"].num_qubits} qubits</span>'
                f'<span class="tag">{c["iters"]} iterations</span>', unsafe_allow_html=True)
    st.caption("Change the puzzle on the Lab page. Every simulator uses noise data that ships with a vendor package; "
               "the two ideal runs (Aer ideal, IonQ-style ideal) have no noise and are references, not part of the seven.")

    cA, cB = st.columns([7, 3], gap="large")
    with cA:
        pick = st.multiselect("Backends to run", list(arena.ARENA), default=list(arena.ARENA), key="arena_pick")
    with cB:
        st.slider("Shots", 256, 8192, step=256, key="shots")
    st.caption("Seven backends can take a few minutes in total; results are cached per puzzle and shot count.")
    if st.button("▶ Run the arena", type="primary", disabled=not pick):
        names = arena.IDEALS + pick
        with st.status("Running simulators…", expanded=True) as status:
            bar = st.progress(0.0)
            for i, name in enumerate(names):
                st.write(f"{name} …")
                try:
                    state.record(items, name, ss.shots)
                except Exception as exc:
                    st.write(f"⚠️ {name} failed: {type(exc).__name__}: {exc}")
                bar.progress((i + 1) / len(names))
            status.update(label="Arena finished", state="complete", expanded=False)

    recs = []
    for name in arena.ALL_RUNNABLE:
        if _cached(items, name, ss.shots):  # only list runs that already finished
            r = state.record(items, name, ss.shots)
            r["note"] = arena.IDEAL_NOTES[name] if name in arena.IDEALS else arena.ARENA[name][1]
            recs.append(r)
    recs += hardware_rows(items, c["iters"])
    if not recs:
        st.info("Press **Run the arena** to simulate this puzzle.")
        return

    df = pd.DataFrame(recs)
    for col in ("depth", "two_q", "seconds"):
        if col not in df:
            df[col] = 0
    df[["depth", "two_q", "seconds"]] = df[["depth", "two_q", "seconds"]].fillna(0)
    noisy = df[df["family"] != "Reference"].sort_values("success", ascending=False)
    ref = df[df["family"] == "Reference"]
    base = len(prob.marked) / prob.search_space
    st.markdown("---")
    l, r = st.columns([6, 5], gap="large")
    with l:
        st.markdown("#### Leaderboard")
        st.markdown(ui.ranking_html(noisy.to_dict("records")), unsafe_allow_html=True)
        if len(ref):
            st.caption("Ideal runs: " + " · ".join(f"{r['name']} {r['success']:.0%}" for _, r in ref.iterrows())
                       + f" · random guess: {base:.0%}")
    with r:
        st.markdown("#### Success by backend")
        st.altair_chart(ui.dot_plot(df, base), width="stretch")
    st.markdown("#### Valid puzzle")
    found = next((state.best_valid_from_counts(items, r["counts"]) for r in
                  sorted(recs, key=lambda r: -r["success"]) if r.get("counts") and r["family"] != "Reference"), None)
    g1, g2 = st.columns([3, 8], gap="large")
    with g1:
        ui.show_board(dict(items), found or (state.solved_grids(items) or [None])[0], "ok", size=220)
    with g2:
        if found is not None:
            st.success("The most frequent valid grid measured by the best-ranked noisy backend.")
        else:
            st.warning("No noisy backend measured a valid grid; this is the valid completion from classical enumeration.")
    st.markdown("#### Cost against quality")
    st.altair_chart(ui.cost_scatter(df[df["two_q"] > 0]), width="stretch")
    show = df.rename(columns={"name": "backend", "family": "vendor", "best_valid": "best grid valid", "two_q": "2Q gates",
                              "seconds": "run time (s)"})
    show["success"] = (show["success"] * 100).round(1)
    st.dataframe(show[["backend", "vendor", "success", "best grid valid", "2Q gates", "depth", "run time (s)"]],
                 hide_index=True, width="stretch",
                 column_config={"success": st.column_config.ProgressColumn("success %", min_value=0, max_value=100, format="%.1f")})


def _cached(items, name, shots) -> bool:
    """True when this simulation result is already in Streamlit's cache (so showing it costs nothing)."""
    return (items, name, shots) in st.session_state.setdefault("done_runs", set())
