"""The eight noisy simulators used by the in-circuit Grover app (credential-free, run locally).

Every noise model comes from vendor data that ships inside a Python package:

* IBM Marrakesh / Boston / Miami          : calibration snapshots of the fake devices (Aer noise model)
* IQM Garnet                               : the noise model IQM ships with its fake backend
* Google Willow                            : median calibration data from cirq-google, simulated with Aer
* Quantinuum H2                            : pytket compile + PECOS emulator with data-sheet error figures
* IonQ Forte                               : Aer noise model from IonQ's published fidelities, all-to-all connectivity
"""
from __future__ import annotations

import gc
import time
from functools import lru_cache

from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap
from qiskit_aer import AerSimulator

import grover_engine as ge

REFERENCE = "Aer ideal"
IONQ_IDEAL = "IonQ-style ideal"
IDEALS = [REFERENCE, IONQ_IDEAL]
IDEAL_NOTES = {
    REFERENCE: "No noise. Qiskit Aer simulation of the transpiled circuit; the reference.",
    IONQ_IDEAL: "No noise. Circuit transpiled to an IonQ-like gate set (h, t, tdg, rx/ry/rz, cx, ...), all-to-all, simulated without noise. Not IonQ's own simulator.",
}

# key -> (vendor family, one-line description of where the noise comes from, qubits on the device)
ARENA = {
    "IBM Marrakesh noisy": ("IBM", "FakeMarrakesh calibration snapshot, heavy-hex lattice", 156),
    "IBM Boston noisy": ("IBM", "FakeBoston calibration snapshot (bundled, Apache-2.0)", 156),
    "IBM Miami noisy": ("IBM", "FakeMiami calibration snapshot (bundled, Apache-2.0)", 120),
    "IQM Garnet noisy": ("IQM", "IQMFakeGarnet with the noise data IQM ships (T1/T2, gate and readout errors)", 20),
    "Cirq noisy (Willow data)": ("Google", "Median Google Willow calibration inside cirq-google (gate Pauli errors, T1/Tphi, readout), applied as an Aer noise model", 105),
    "IonQ Forte noisy": ("IonQ", "IonQ published fidelities (1q 99.98%, 2q 99.6%, SPAM 99.5%) as an Aer noise model, all-to-all connectivity", 36),
    "Quantinuum noisy": ("Quantinuum", "pytket compile for H2 + PECOS emulator, H2 data-sheet figures (1q 3e-5, 2q 1.5e-3, SPAM 1.5e-3)", 56),
}
FAMILY_ORDER = ["IBM", "IQM", "Google", "IonQ", "Quantinuum"]
ALL_RUNNABLE = IDEALS + list(ARENA)


# ---------------------------------------------------------------- IBM (single slot to bound memory)
_IBM_SLOT: dict = {}


def _ibm_sim(device: str):
    """Noisy Aer simulator for one IBM fake device. Only one is kept alive, and the old one is freed
    *before* the new one is built, because each 120-156 qubit noise model costs 300-400 MB."""
    if device not in _IBM_SLOT:
        _IBM_SLOT.clear()
        gc.collect()
        if device == "marrakesh":
            from qiskit_ibm_runtime.fake_provider import FakeMarrakesh as Fake
        elif device == "boston":
            from fake_ibm_extra import FakeBoston as Fake
        elif device == "miami":
            from fake_ibm_extra import FakeMiami as Fake
        else:
            raise KeyError(device)
        _IBM_SLOT[device] = AerSimulator.from_backend(Fake())
    return _IBM_SLOT[device]


# ---------------------------------------------------------------- IQM
@lru_cache(maxsize=1)
def _iqm():
    from iqm.qiskit_iqm.fake_backends.fake_garnet import IQMFakeGarnet
    be = IQMFakeGarnet()
    # from_backend would drop IQM's error profile, so pass the noise model explicitly
    return be, AerSimulator(noise_model=be.noise_model)


# ---------------------------------------------------------------- Google Willow via Cirq
@lru_cache(maxsize=1)
def _willow():
    import cirq_google as cg
    from cirq_google.engine import load_device_noise_properties

    props = load_device_noise_properties("willow_pink")
    return props, cg.NoiseModelFromGoogleNoiseProperties(props)


def _willow_region(props, size: int):
    """A connected block of `size` Willow qubits (breadth-first from a central qubit)."""
    qubits = sorted(props.t1_ns)
    cx = sum(q.row for q in qubits) / len(qubits)
    cy = sum(q.col for q in qubits) / len(qubits)
    start = min(qubits, key=lambda q: (q.row - cx) ** 2 + (q.col - cy) ** 2)
    region, frontier = [start], [start]
    members = set(qubits)
    while frontier and len(region) < size:
        q = frontier.pop(0)
        for nb in sorted(q.neighbors(), key=str):
            if nb in members and nb not in region and len(region) < size:
                region.append(nb)
                frontier.append(nb)
    return region


def _willow_noise(props, region):
    """Aer noise model built from Google's Willow calibration data (the numbers inside cirq-google):
    per-qubit 1q Pauli error, per-pair CZ Pauli error, T1 and Tphi relaxation during each gate, readout errors."""
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error, thermal_relaxation_error

    gt = {g.__name__: t for g, t in props.gate_times_ns.items()}
    t1q, t2q = gt.get("PhasedXZGate", 25.0), gt.get("CZPowGate", 42.0)
    perr = {(k.gate_type.__name__, tuple(k.qubits)): v for k, v in props.gate_pauli_errors.items()}
    nm = NoiseModel(basis_gates=["rz", "sx", "x", "cx"])

    def relax(q, t):
        t1, tphi = props.t1_ns[q], props.tphi_ns[q]
        t2 = min(1.0 / (1.0 / (2.0 * t1) + 1.0 / tphi), 2.0 * t1)
        return thermal_relaxation_error(t1, t2, t)

    for i, q in enumerate(region):
        p1 = perr.get(("ZPowGate", (q,)), 1e-3)
        e1 = depolarizing_error(min(p1 * 4 / 3, 0.75), 1).compose(relax(q, t1q))
        nm.add_quantum_error(e1, ["sx", "x"], [i])
        r = props.readout_errors.get(q, [0.002, 0.012])
        nm.add_readout_error(ReadoutError([[1 - r[0], r[0]], [r[1], 1 - r[1]]]), [i])
    for i, a in enumerate(region):
        for j, b in enumerate(region):
            if i != j and a.is_adjacent(b):
                p2 = perr.get(("CZPowGate", (a, b)), perr.get(("CZPowGate", (b, a)), 4e-3))
                e2 = depolarizing_error(min(p2 * 16 / 15, 15 / 16), 2).compose(
                    relax(a, t2q).tensor(relax(b, t2q)))
                nm.add_quantum_error(e2, ["cx"], [i, j])
    return nm


def _run_willow(circuit: QuantumCircuit, shots: int, seed: int):
    """Route onto a compact block of Willow qubits and simulate with an Aer noise model made from the
    Willow calibration data in cirq-google. (Running the same data through Cirq's own density-matrix
    simulator was correct but took about 7 minutes per circuit, far too slow for an app.)"""
    props, _ = _willow()
    region = _willow_region(props, circuit.num_qubits + 1)
    idx = {q: i for i, q in enumerate(region)}
    edges = [[idx[a], idx[b]] for a in region for b in region if a < b and a.is_adjacent(b)]
    cmap = CouplingMap(edges + [[b, a] for a, b in edges])
    tc = transpile(circuit, coupling_map=cmap, basis_gates=["rz", "sx", "x", "cx", "measure"],
                   optimization_level=3, seed_transpiler=seed)
    sim = AerSimulator(noise_model=_willow_noise(props, region), method="density_matrix")
    res = sim.run(tc, shots=shots, seed_simulator=seed).result()
    return tc, dict(res.get_counts())


# ---------------------------------------------------------------- IonQ (published figures)
# IonQ Forte, published specifications: single-qubit fidelity 99.98%, two-qubit 99.6%, SPAM 99.5%.
# These are approximate public figures, not a live calibration. Trapped ions are all-to-all connected,
# so the circuit is transpiled without a coupling map. The same circuit can be sent to IonQ's own
# noisy cloud simulator from the Hardware page.
IONQ_ERR = {"p1": 2e-4, "p2": 4e-3, "readout": 5e-3}


def _run_ionq(circuit: QuantumCircuit, shots: int, seed: int):
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

    nm = NoiseModel(basis_gates=["rz", "sx", "x", "cx"])
    # average gate infidelity r maps to a depolarising parameter r*d/(d-1)
    nm.add_all_qubit_quantum_error(depolarizing_error(2 * IONQ_ERR["p1"], 1), ["sx", "x"])
    nm.add_all_qubit_quantum_error(depolarizing_error(4 / 3 * IONQ_ERR["p2"], 2), ["cx"])
    e = IONQ_ERR["readout"]
    nm.add_all_qubit_readout_error(ReadoutError([[1 - e, e], [e, 1 - e]]))
    tc = transpile(circuit, basis_gates=["rz", "sx", "x", "cx", "measure"], optimization_level=3,
                   seed_transpiler=seed)
    sim = AerSimulator(noise_model=nm)
    res = sim.run(tc, shots=shots, seed_simulator=seed).result()
    return tc, dict(res.get_counts())


# ---------------------------------------------------------------- public entry point
def run(name: str, circuit: QuantumCircuit, shots: int, seed: int = 1234):
    """Returns (transpiled circuit, counts, seconds) for the reference or one of the eight noisy backends."""
    t0 = time.time()
    if name in IDEALS:
        tc, counts, _ = ge.run_backend(name, circuit, shots, seed)
        return tc, counts, time.time() - t0
    if name in ("IBM Marrakesh noisy", "IBM Boston noisy", "IBM Miami noisy"):
        sim = _ibm_sim(name.split()[1].lower())
        tc = transpile(circuit, backend=sim, optimization_level=3, seed_transpiler=seed)
        res = sim.run(tc, shots=shots, seed_simulator=seed).result()
        return tc, dict(res.get_counts()), time.time() - t0
    if name == "IQM Garnet noisy":
        be, sim = _iqm()
        tc = transpile(circuit, backend=be, optimization_level=3, seed_transpiler=seed)
        res = sim.run(tc, shots=shots, seed_simulator=seed).result()
        return tc, dict(res.get_counts()), time.time() - t0
    if name == "Cirq noisy (Willow data)":
        tc, counts = _run_willow(circuit, shots, seed)
        return tc, counts, time.time() - t0
    if name == "IonQ Forte noisy":
        tc, counts = _run_ionq(circuit, shots, seed)
        return tc, counts, time.time() - t0
    if name == "Quantinuum noisy":
        tc, counts = ge._run_quantinuum(circuit, shots, seed)
        return tc, counts, time.time() - t0
    raise KeyError(name)
