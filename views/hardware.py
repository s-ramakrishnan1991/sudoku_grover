"""Hardware page: submit the in-circuit circuit to IBM Quantum, IQM or IonQ (your own account)."""
import time

import streamlit as st

import grover_engine as ge
import incircuit as gi
import real_backends as rb
import state
import ui

ICON = {"queued": "⏳", "running": "⚙️", "done": "✅", "error": "❌", "cancelled": "🚫"}
POLL_SECONDS = 15


def _init():
    ss = st.session_state
    ss.setdefault("hw_jobs", [])
    ss.setdefault("hw_results", {})
    ss.setdefault("ibm_backends", [])
    ss.setdefault("ionq_backend", rb.IONQ_BACKEND)
    ss.setdefault("iqm_url", rb.IQM_DEFAULT_URL)


def _creds(provider):
    ss = st.session_state
    if provider == "IBM Quantum":
        return {"token": ss.get("ibm_token", ""), "crn": ss.get("ibm_crn", "")}
    if provider == "IQM":
        return {"token": ss.get("iqm_token", ""), "iqm_url": (ss.get("iqm_url") or rb.IQM_DEFAULT_URL).strip()}
    return {"token": ss.get("ionq_token", "")}


def _top_outcomes(counts, n=8):
    tot = sum(counts.values()) or 1
    return [{"bit string": k, "shots": v, "share": f"{v / tot:.1%}"}
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:n]]


def _analyse(job, counts):
    """Decode the counts against the job's puzzle. Returns (analysis or None, note)."""
    items = job.get("fixed_items")
    if not items:
        return None, "The puzzle is not stored with this job."
    prob = ge.build_problem(dict(items))
    bits = len(next(iter(counts)).replace(" ", "")) if counts else 0
    if bits != prob.num_qubits:
        return None, (f"This job measured {bits} bits but the selected puzzle needs {prob.num_qubits}, "
                      "so it is a different puzzle.")
    return ge.analyse_counts(prob, counts), ""


def _store_result(job, counts):
    analysis, note = _analyse(job, counts)
    job["shots"] = sum(counts.values())          # shots come from the result itself
    st.session_state.hw_results[job["job_id"]] = {
        **{k: job.get(k) for k in ("provider", "backend", "job_id", "shots", "metrics", "fixed_items", "iters")},
        "kind": job.get("kind", "Real hardware"), "detail": job.get("detail", ""),
        "counts": counts, "analysis": analysis, "note": note}


def _refresh(job):
    try:
        status, counts, err, info = rb.fetch_full(job["provider"], job["job_id"], backend_name=job["backend"],
                                                  creg="c", **_creds(job["provider"]))
    except rb.HardwareError as exc:
        job["poll_error"], job["polled_at"] = str(exc), time.time()
        return
    job.update(poll_error=None, status=status, polled_at=time.time())
    if info.get("backend") and job["backend"] in ("unknown", ""):
        job["backend"] = info["backend"]
    tagged = rb.decode_puzzle(info.get("tag"))
    if tagged and job.get("puzzle_source") in (None, "unknown", "current"):
        job["fixed_items"], job["puzzle_source"] = tagged, "stored in the job"
    if status == "done":
        _store_result(job, counts)
    elif status in ("error", "cancelled"):
        job["error"] = err or f"Job {status}."


def _job_card(job):
    fixed = dict(job["fixed_items"]) if job.get("fixed_items") else None
    status = job["status"]
    with st.container(border=True):
        st.markdown(f"**{ICON[status]} {job['provider']} · {job['backend']}** "
                    f"<span class='tag {'good' if status == 'done' else 'bad' if status in ('error', 'cancelled') else 'warn'}'>{status}</span>",
                    unsafe_allow_html=True)
        st.caption(f"Job `{job['job_id']}` · {str(job['shots']) + ' shots' if job.get('shots') else 'shots: from the result'} · submitted "
                   f"{time.strftime('%H:%M:%S', time.localtime(job['submitted']))}")
        if job.get("metrics"):
            m = job["metrics"]
            st.caption(f"Transpiled: {m['active qubits']} qubits · {m['2Q gates']} two-qubit gates · depth {m['total depth']}")
        if job.get("poll_error"):
            st.warning(f"Could not check status: {job['poll_error']}")
            if "API key" in job["poll_error"]:
                need = {"IBM Quantum": "the IBM API key and the CRN", "IQM": "the IQM API key", "IonQ": "the IonQ API key"}
                st.caption(f"Choose **{job['provider']}** in the provider selector above, enter {need[job['provider']]}, "
                           "then press *Refresh now*. Keys are kept for this browser session only.")
        if status in ("error", "cancelled"):
            st.error(job.get("error") or "The job did not complete.")
        res = st.session_state.hw_results.get(job["job_id"])
        if status == "done" and res:
            a = res["analysis"]
            if a is None:
                st.warning(res["note"] or "Could not decode this result.")
                st.caption(f"{res['shots']} shots measured. Most frequent bit strings:")
                st.dataframe(_top_outcomes(res["counts"]), hide_index=True, width="stretch")
                cur = state.fixed_items()
                if st.button("Decode with the puzzle selected in the Lab", key=f"dec_{job['job_id']}"):
                    job["fixed_items"], job["puzzle_source"] = cur, "manual"
                    _store_result(job, res["counts"])
                    st.rerun()
            else:
                prob = ge.build_problem(dict(job["fixed_items"]))
                st.caption(f"Puzzle: {job.get('puzzle_source', 'this app')} · shots counted from the result: {res['shots']}")
                c1, c2 = st.columns([1, 2])
                with c1:
                    ui.show_board(fixed, a["best_rows"], "ok" if a["best_valid"] else "bad", size=180)
                with c2:
                    ui.stat("Success probability", f"{a['success']:.1%}", f"blind guess {len(prob.marked) / prob.search_space:.1%}")
                    st.markdown('<span class="tag good">best outcome valid</span>' if a["best_valid"]
                                else '<span class="tag bad">best outcome not valid</span>', unsafe_allow_html=True)


def _jobs_panel():
    jobs = st.session_state.hw_jobs
    if not jobs:
        st.info("No hardware jobs yet.")
        return
    manual = st.button("🔄 Refresh now", key="hw_refresh")
    newly_final = False
    for job in jobs:
        if job["status"] in rb.FINAL_STATES:
            continue
        if manual or time.time() - job.get("polled_at", 0) >= POLL_SECONDS - 1:
            before = job["status"]
            _refresh(job)
            newly_final |= job["status"] != before and job["status"] in rb.FINAL_STATES
    for job in reversed(jobs):
        _job_card(job)
    if newly_final:
        st.rerun()


def _submit(provider, items, c, shots, **kw):
    with st.spinner(f"Transpiling and submitting to {provider}…"):
        try:
            sub = rb.submit(provider, c["circuit"], shots, puzzle_tag=rb.encode_puzzle(dict(items)), **kw)
        except rb.HardwareError as exc:
            st.error(f"Submission failed: {exc}")
            return
    st.session_state.hw_jobs.append({
        "provider": sub.provider, "backend": sub.backend, "job_id": sub.job_id, "shots": sub.shots,
        "metrics": sub.metrics, "kind": sub.kind, "detail": sub.detail, "fixed_items": items, "iters": c["iters"], "puzzle_source": "this app",
        "status": "queued", "submitted": time.time(), "polled_at": 0})
    st.toast(f"Submitted to {provider}: {sub.job_id}")
    st.rerun()


def render():
    state.ensure()
    _init()
    ui.hero("Real hardware", "Optional: send this circuit to IBM Quantum, IQM or IonQ with your own account")
    ss = st.session_state
    items = state.fixed_items()
    c = state.case(items)
    cost = state.circuit_size(items)

    a, b, d = st.columns(3)
    with a:
        ui.stat("Puzzle", f"{'Easy'}", f"seed {ss.seed} · {len(items)} clues")
    with b:
        ui.stat("Circuit", f"{c['circuit'].num_qubits} qubits", f"{cost['two_q']} two-qubit gates before routing")
    with d:
        ui.stat("Expect", "low success", "this circuit is deep; see the Arena for simulated noise")
    st.write("")
    st.warning("Jobs run on **your** account and may use quota or credits (IonQ and paid IBM plans can incur "
               "charges). Lower the shots first. Keys stay in this browser session, are never stored or logged "
               "by the app, and are scrubbed from error messages.")
    st.slider("Shots", 256, 8192, step=256, key="shots")
    ack = st.checkbox("I understand this uses real hardware or cloud services on my account.", key="hw_ack")

    prov = st.segmented_control("Provider", ["IBM Quantum", "IQM", "IonQ"], key="hw_provider")
    prov = prov or "IBM Quantum"
    with st.container(border=True):
        if prov == "IBM Quantum":
            k1, k2 = st.columns(2)
            k1.text_input("API key", type="password", key="ibm_token")
            k2.text_input("Instance CRN", key="ibm_crn", placeholder="crn:v1:bluemix:public:quantum-computing:...")
            if st.button("Connect and list QPUs", key="ibm_connect"):
                t, crn = ss.ibm_token.strip(), ss.ibm_crn.strip()
                if not t or not crn:
                    st.error("Enter both the API key and the CRN.")
                else:
                    with st.spinner("Contacting IBM Quantum…"):
                        try:
                            ss.ibm_backends = rb.ibm_list_backends(t, crn)
                            if not ss.ibm_backends:
                                st.warning("Connected, but no operational QPUs are available for this instance.")
                        except rb.HardwareError as exc:
                            ss.ibm_backends = []
                            st.error(f"Could not connect: {exc}")
            bk = ss.ibm_backends
            choice = None
            if bk:
                labels = {x["name"]: f"{x['name']} · {x['qubits']} qubits · "
                                     f"{'?' if x['pending_jobs'] is None else x['pending_jobs']} pending" for x in bk}
                choice = st.selectbox("QPU", list(labels), format_func=labels.get, key="ibm_backend")
            if st.button("🚀 Launch on IBM Quantum", type="primary", disabled=not (ack and choice), key="ibm_go"):
                _submit("IBM Quantum", items, c, ss.shots, token=ss.ibm_token, crn=ss.ibm_crn, backend_name=choice)
        elif prov == "IQM":
            st.text_input("API key", type="password", key="iqm_token")
            comp = st.selectbox("Quantum computer", rb.IQM_COMPUTERS + ["Other…"], key="iqm_computer")
            if comp == "Other…":
                comp = st.text_input("Alias", key="iqm_custom")
            with st.expander("Advanced"):
                st.text_input("Server URL", key="iqm_url")
            if st.button("🚀 Launch on IQM", type="primary", disabled=not (ack and comp), key="iqm_go"):
                _submit("IQM", items, c, ss.shots, token=ss.iqm_token, backend_name=comp, iqm_url=_creds("IQM")["iqm_url"])
        else:
            st.text_input("API key", type="password", key="ionq_token")
            target = st.radio("Target", ["QPU", "Noisy cloud simulator"], horizontal=True, key="ionq_target")
            noise = None
            if target.startswith("Noisy"):
                noise = st.selectbox("Noise model", rb.IONQ_NOISE_MODELS, key="ionq_noise")
            else:
                with st.expander("Advanced"):
                    st.text_input("QPU name", key="ionq_backend")
            if st.button("🚀 Launch on IonQ", type="primary", disabled=not ack, key="ionq_go"):
                _submit("IonQ", items, c, ss.shots, token=ss.ionq_token,
                        backend_name=(ss.get("ionq_backend") or rb.IONQ_BACKEND).strip(), ionq_noise_model=noise)

    st.markdown("#### Jobs")
    active = any(j["status"] not in rb.FINAL_STATES for j in ss.hw_jobs)
    st.fragment(run_every=POLL_SECONDS if active else None)(_jobs_panel)()

    with st.expander("Retrieve an earlier job by ID"):
        st.caption("You only need the job ID and the provider's API key (IBM also needs the CRN): the providers do not release "
                   "results without authentication. Shots are counted from the result and the iteration count is not needed. "
                   "The puzzle is read from the job when it was submitted from this version of the app; otherwise "
                   "you can type its clues, or just look at the raw outcomes.")
        p = st.selectbox("Provider", rb.PROVIDERS, key="ret_provider")
        jid = st.text_input("Job ID", key="ret_id")
        bn = st.text_input("Backend or quantum computer name (optional)", key="ret_backend",
                           help="IBM and IonQ report it themselves. Only IQM needs the alias (for example garnet).")
        pz = st.text_input("Puzzle clues (optional)", key="ret_clues", placeholder="02=2, 20=0, 12=0",
                           help="row, column = value, counting from 0. Leave empty to use the puzzle stored in the job.")
        if st.button("Retrieve", disabled=not jid.strip(), key="ret_go"):
            clues = rb.parse_clues(pz)
            if any(j["job_id"] == jid.strip() for j in ss.hw_jobs):
                st.info("That job is already listed.")
            elif pz.strip() and not clues:
                st.error("Could not read the clues. Use the form 02=2, 20=0 (row, column = value).")
            else:
                ss.hw_jobs.append({
                    "provider": p, "backend": bn.strip() or ("ionq_qpu" if p == "IonQ" else "unknown"),
                    "job_id": jid.strip(), "shots": 0, "metrics": None,
                    "kind": "Cloud simulator" if "simulator" in bn.lower() else "Real hardware", "detail": "",
                    "fixed_items": clues, "iters": None,
                    "puzzle_source": "typed clues" if clues else "unknown",
                    "status": "queued", "submitted": time.time(), "polled_at": 0})
                st.rerun()
