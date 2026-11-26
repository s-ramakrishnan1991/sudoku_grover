"""Optional real-hardware execution on IBM Quantum, IQM and IonQ.

Design notes
------------
* Credentials are passed in by the caller on every call. Nothing here stores,
  caches or logs them, and error messages are scrubbed of the secrets.
* Real QPU jobs queue for minutes to hours, so execution is split into
  ``submit`` (returns a job id immediately) and ``fetch`` (poll status / get
  counts). The UI never blocks waiting on a queue.
* Each provider SDK is imported lazily so the simulator-only parts of the app
  still work if an SDK is missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from qiskit import QuantumCircuit, transpile

import grover_engine as ge

PROVIDERS = ["IBM Quantum", "IQM", "IonQ"]

IQM_DEFAULT_URL = "https://resonance.iqm.tech/"
# Common IQM Resonance system aliases; the UI also accepts a custom alias.
IQM_COMPUTERS = ["garnet", "emerald", "sirius"]
IONQ_BACKEND = "ionq_qpu"
IONQ_SIMULATOR = "ionq_simulator"
# Noise models of IonQ's cloud simulator (docs.ionq.com). aria-1/aria-2 are legacy (QPUs retired).
IONQ_NOISE_MODELS = ["forte-1", "forte-enterprise-1", "aria-2", "aria-1"]
FINAL_STATES = {"done", "error", "cancelled"}


class HardwareError(Exception):
    """A user-presentable error (credentials scrubbed)."""


@dataclass
class Submission:
    provider: str
    backend: str
    job_id: str
    shots: int
    metrics: dict  # transpiled-circuit metrics (see grover_engine.circuit_metrics)
    kind: str = "Real hardware"  # or "Cloud simulator"
    detail: str = ""             # e.g. "forte-1 noise model"


# ---------------------------------------------------------------- puzzle tag (stored with the job)
def encode_puzzle(items: dict) -> str:
    """Short, provider-safe tag such as 'qsud_02v2_20v0_12v0' (row, column, value) kept with the job so the
    result can be decoded later without remembering the puzzle."""
    return "qsud_" + "_".join(f"{r}{c}v{v}" for (r, c), v in sorted(items.items()))


def decode_puzzle(tag: str | None):
    """Inverse of encode_puzzle; returns {(row, col): value} or None if the tag is not ours."""
    m = re.fullmatch(r"qsud((?:_[0-2][0-2]v[0-2])+)", (tag or "").strip())
    if not m:
        return None
    return {(int(x[0]), int(x[1])): int(x[3]) for x in m.group(1).strip("_").split("_")}


def parse_clues(text: str):
    """Read clues typed by hand: '02=2, 20=0' or '0,2=2; 2,0=0' (row, column = value). None if nothing valid."""
    found = re.findall(r"([0-2])\s*,?\s*([0-2])\s*[=:]\s*([0-2])", text or "")
    return {(int(r), int(c)): int(v) for r, c, v in found} or None


# ---------------------------------------------------------------- utilities
def _scrub(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _wrap(exc: Exception, *secrets: str | None) -> HardwareError:
    msg = _scrub(f"{type(exc).__name__}: {exc}", *secrets)
    return HardwareError(msg[:600])


def normalize_status(status) -> str:
    """Map provider-specific job states onto queued / running / done / error / cancelled."""
    name = str(getattr(status, "name", status)).upper().replace("JOBSTATUS.", "")
    if name in {"DONE", "COMPLETED", "SUCCEEDED"}:
        return "done"
    if name in {"ERROR", "FAILED"}:
        return "error"
    if name in {"CANCELLED", "CANCELED", "CANCELLING"}:
        return "cancelled"
    if name in {"RUNNING", "EXECUTING"}:
        return "running"
    return "queued"  # INITIALIZING, VALIDATING, QUEUED, SUBMITTED, ...


# ---------------------------------------------------------------- IBM
def _ibm_service(token: str, crn: str):
    from qiskit_ibm_runtime import QiskitRuntimeService

    # Explicit token + instance (CRN) so no saved account on disk is ever used.
    return QiskitRuntimeService(channel="ibm_quantum_platform", token=token, instance=crn)


def ibm_list_backends(token: str, crn: str) -> list[dict]:
    """Operational, non-simulator IBM QPUs available to this account/instance."""
    try:
        service = _ibm_service(token, crn)
        out = []
        for be in service.backends(simulator=False, operational=True):
            try:
                pending = be.status().pending_jobs
            except Exception:
                pending = None
            out.append({"name": be.name, "qubits": be.num_qubits, "pending_jobs": pending})
        out.sort(key=lambda d: (d["pending_jobs"] is None, d["pending_jobs"] or 0))
        return out
    except Exception as exc:
        raise _wrap(exc, token, crn) from None


def _ibm_submit(circuit, shots, token, crn, backend_name, tag=None) -> Submission:
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from qiskit_ibm_runtime import SamplerV2

    service = _ibm_service(token, crn)
    backend = service.backend(backend_name)
    isa = generate_preset_pass_manager(backend=backend, optimization_level=3,
                                       seed_transpiler=1234).run(circuit)
    sampler = SamplerV2(mode=backend)
    if tag:
        try:
            sampler.options.environment.job_tags = [tag]   # lets the puzzle be recovered from the job later
        except Exception:
            pass
    job = sampler.run([isa], shots=shots)
    return Submission("IBM Quantum", backend_name, job.job_id(), shots, ge.circuit_metrics(isa))


def _ibm_fetch(job_id, token, crn, creg):
    service = _ibm_service(token, crn)
    job = service.job(job_id)
    status = normalize_status(job.status())
    info = {}
    try:
        info["backend"] = job.backend().name
    except Exception:
        pass
    try:
        info["tag"] = next((t for t in (job.tags or []) if decode_puzzle(t)), None)
    except Exception:
        pass
    if status == "done":
        pub = job.result()[0]
        return status, dict(getattr(pub.data, creg).get_counts()), None, info
    err = None
    if status == "error":
        try:
            err = str(job.error_message())
        except Exception:
            err = "The job failed on the IBM side."
    return status, None, err, info


# ---------------------------------------------------------------- IQM
def _iqm_backend(token, url, computer):
    from iqm.qiskit_iqm import IQMProvider

    kwargs = {"quantum_computer": computer} if computer else {}
    return IQMProvider(url or IQM_DEFAULT_URL, token=token, **kwargs).get_backend()


def _iqm_submit(circuit, shots, token, url, computer, tag=None) -> Submission:
    backend = _iqm_backend(token, url, computer)
    tc = transpile(circuit, backend, optimization_level=3, seed_transpiler=1234)
    if tag:
        tc.metadata = {"qsud": tag}   # IQM sends circuit metadata with the job and returns it with the result
    job = backend.run(tc, shots=shots)
    return Submission("IQM", computer or "default", job.job_id(), shots, ge.circuit_metrics(tc))


def _iqm_fetch(job_id, token, url, computer):
    job = _iqm_backend(token, url, computer).retrieve_job(job_id)
    status = normalize_status(job.status())
    info = {"backend": computer} if computer else {}
    if status == "done":
        counts = dict(job.result().get_counts())
        try:   # filled in from the stored job once the result has been fetched
            info["tag"] = next((m.get("qsud") for m in (job.circuit_metadata or [])
                                if isinstance(m, dict) and decode_puzzle(m.get("qsud"))), None)
        except Exception:
            pass
        return status, counts, None, info
    err = None
    if status == "error":
        try:
            err = str(job.error_message())
        except Exception:
            err = "The job failed on the IQM side."
    return status, None, err, info


# ---------------------------------------------------------------- IonQ
def _ionq_backend(token, name=None):
    import warnings

    from qiskit_ionq import IonQProvider

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # SDK warns about transpile level / qubit lookups
        return IonQProvider(token).get_backend(name or IONQ_BACKEND)


def _ionq_submit(circuit, shots, token, name, noise_model=None, tag=None) -> Submission:
    simulator = bool(noise_model)
    backend = _ionq_backend(token, IONQ_SIMULATOR if simulator else name)
    if simulator:
        backend.set_options(noise_model=noise_model)  # IonQ cloud simulator with a QPU noise model
    # IonQ is all-to-all connected; translate to its gate set without a device target (the SDK's
    # online qubit-count lookup can fall back to 4 qubits). Level 0 matches the notebook.
    tc = transpile(circuit, basis_gates=ge.IONQ_BASIS, optimization_level=0, seed_transpiler=1234)
    try:
        job = backend.run(tc, shots=shots, extra_metadata={"qsud": tag}) if tag else backend.run(tc, shots=shots)
    except TypeError:
        job = backend.run(tc, shots=shots)
    return Submission("IonQ", backend.name, job.job_id(), shots, ge.circuit_metrics(tc),
                      kind="Cloud simulator" if simulator else "Real hardware",
                      detail=f"{noise_model} noise model" if simulator else "")


def _ionq_fetch(job_id, token, name):
    job = _ionq_backend(token, name).retrieve_job(job_id)
    status = normalize_status(job.status())
    info = {}
    try:
        info["backend"] = job.backend().name
    except Exception:
        pass
    try:
        md = getattr(job, "_metadata", None) or {}
        cands = [(md.get("metadata") or {}).get("qsud"), (getattr(job, "extra_metadata", None) or {}).get("qsud")]
        info["tag"] = next((t for t in cands if decode_puzzle(t)), None)
    except Exception:
        pass
    if status == "done":
        return status, dict(job.result().get_counts()), None, info
    err = None
    if status == "error":
        try:
            err = str(job.status().value)
        except Exception:
            err = "The job failed on the IonQ side."
    return status, None, err, info


# ---------------------------------------------------------------- public API
def submit(provider: str, circuit: QuantumCircuit, shots: int, *, token: str = "",
           crn: str | None = None, backend_name: str | None = None,
           iqm_url: str | None = None,
           ionq_noise_model: str | None = None, puzzle_tag: str | None = None) -> Submission:
    """Transpile for the chosen QPU and queue the job. Returns immediately.

    """
    if not token or not token.strip():
        raise HardwareError("Please enter an API key.")
    token = token.strip()
    try:
        if provider == "IBM Quantum":
            if not crn or not crn.strip():
                raise HardwareError("Please enter the instance CRN.")
            if not backend_name:
                raise HardwareError("Please connect and choose an IBM backend first.")
            return _ibm_submit(circuit, shots, token, crn.strip(), backend_name, puzzle_tag)
        if provider == "IQM":
            if not backend_name:
                raise HardwareError("Please choose an IQM quantum computer.")
            return _iqm_submit(circuit, shots, token, iqm_url, backend_name.strip(), puzzle_tag)
        if provider == "IonQ":
            return _ionq_submit(circuit, shots, token, backend_name, ionq_noise_model, puzzle_tag)
        raise HardwareError(f"Unknown provider: {provider}")
    except HardwareError:
        raise
    except Exception as exc:
        raise _wrap(exc, token, crn) from None


def fetch_full(provider: str, job_id: str, *, token: str = "", crn: str | None = None,
               backend_name: str | None = None, iqm_url: str | None = None, creg: str = "c"):
    """Poll a job. Returns (status, counts_or_None, error_or_None, info) where info may hold the device name
    ('backend') and the puzzle tag stored with the job ('tag'). A valid API key is always required: the
    providers do not release job results without authentication."""
    if not token or not token.strip():
        raise HardwareError("Please enter the API key to check this job.")
    token = token.strip()
    try:
        if provider == "IBM Quantum":
            if not (crn or "").strip():
                raise HardwareError("Please enter the instance CRN (and API key) to check this job.")
            return _ibm_fetch(job_id, token, crn.strip(), creg)
        if provider == "IQM":
            return _iqm_fetch(job_id, token, iqm_url, (backend_name or "").strip())
        if provider == "IonQ":
            return _ionq_fetch(job_id, token, backend_name)
        raise HardwareError(f"Unknown provider: {provider}")
    except HardwareError:
        raise
    except Exception as exc:
        raise _wrap(exc, token, crn) from None


def fetch(provider: str, job_id: str, **kw):
    """Same as fetch_full without the info dict: (status, counts, error)."""
    return fetch_full(provider, job_id, **kw)[:3]
