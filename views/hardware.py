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


def _creds(provider):
    ss = st.session_state
    if provider == "IBM Quantum":
        return {"token": ss.get("ibm_token", ""), "crn": ss.get("ibm_crn", "")}
    if provider == "IQM":
        return {"token": ss.get("iqm_token", ""), "iqm_url": (ss.get("iqm_url") or rb.IQM_DEFAULT_URL).strip()}
    return {"token": ss.get("ionq_token", "")}


def _refresh(job):
    try:
        status, counts, err = rb.fetch(job["provider"], job["job_id"], backend_name=job["backend"], creg="c",
                                       **_creds(job["provider"]))
    except rb.HardwareError as exc:
        job["poll_error"], job["polled_at"] = str(exc), time.time()
        return
    job.update(poll_error=None, status=status, polled_at=time.time())
    if status == "done":
        prob = ge.build_problem(dict(job["fixed_items"]))
        st.session_state.hw_results[job["job_id"]] = {
            **{k: job[k] for k in ("provider", "backend", "job_id", "shots", "metrics", "fixed_items", "iters")},
            "kind": job.get("kind", "Real hardware"), "detail": job.get("detail", ""),
            "counts": counts, "analysis": ge.analyse_counts(prob, counts)}
    elif status in ("error", "cancelled"):
        job["error"] = err or f"Job {status}."


def _job_card(job):
    prob = ge.build_problem(dict(job["fixed_items"]))
    fixed = dict(job["fixed_items"])
    status = job["status"]
    with st.container(border=True):
        st.markdown(f"**{ICON[status]} {job['provider']} · {job['backend']}** "
                    f"<span class='tag {'good' if status == 'done' else 'bad' if status in ('error', 'cancelled') else 'warn'}'>{status}</span>",
                    unsafe_allow_html=True)
        st.caption(f"Job `{job['job_id']}` · {job['shots']} shots · submitted "
                   f"{time.strftime('%H:%M:%S', time.localtime(job['submitted']))}")
        if job.get("metrics"):
            m = job["metrics"]
            st.caption(f"Transpiled: {m['active qubits']} qubits · {m['2Q gates']} two-qubit gates · depth {m['total depth']}")
        if job.get("poll_error"):
            st.warning(f"Could not check status: {job['poll_error']}")
        if status in ("error", "cancelled"):
            st.error(job.get("error") or "The job did not complete.")
        res = st.session_state.hw_results.get(job["job_id"])
        if status == "done" and res:
            a = res["analysis"]
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
            sub = rb.submit(provider, c["circuit"], shots, **kw)
        except rb.HardwareError as exc:
            st.error(f"Submission failed: {exc}")
            return
    st.session_state.hw_jobs.append({
        "provider": sub.provider, "backend": sub.backend, "job_id": sub.job_id, "shots": sub.shots,
        "metrics": sub.metrics, "kind": sub.kind, "detail": sub.detail, "fixed_items": items, "iters": c["iters"],
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
                st.text_input("Server URL", value=rb.IQM_DEFAULT_URL, key="iqm_url")
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
                    st.text_input("QPU name", value=rb.IONQ_BACKEND, key="ionq_backend")
            if st.button("🚀 Launch on IonQ", type="primary", disabled=not ack, key="ionq_go"):
                _submit("IonQ", items, c, ss.shots, token=ss.ionq_token,
                        backend_name=(ss.get("ionq_backend") or rb.IONQ_BACKEND).strip(), ionq_noise_model=noise)

    st.markdown("#### Jobs")
    active = any(j["status"] not in rb.FINAL_STATES for j in ss.hw_jobs)
    st.fragment(run_every=POLL_SECONDS if active else None)(_jobs_panel)()

    with st.expander("Retrieve an earlier job by ID"):
        st.caption("The result is decoded against the puzzle currently selected, so use the same puzzle, "
                   "shots and iteration count as when you submitted. Enter your credentials above first.")
        p = st.selectbox("Provider", rb.PROVIDERS, key="ret_provider")
        jid = st.text_input("Job ID", key="ret_id")
        bn = st.text_input("Backend or quantum computer name", key="ret_backend",
                           help="Needed for IQM (alias) and IonQ (QPU name). Optional for IBM.")
        if st.button("Retrieve", disabled=not jid.strip(), key="ret_go"):
            if any(j["job_id"] == jid.strip() for j in ss.hw_jobs):
                st.info("That job is already listed.")
            else:
                ss.hw_jobs.append({
                    "provider": p, "backend": bn.strip() or ("ionq_qpu" if p == "IonQ" else "unknown"),
                    "job_id": jid.strip(), "shots": ss.shots, "metrics": None,
                    "kind": "Cloud simulator" if "simulator" in bn.lower() else "Real hardware", "detail": "",
                    "fixed_items": items, "iters": c["iters"], "status": "queued", "submitted": time.time(), "polled_at": 0})
                st.rerun()
