# Oracle Lab: Grover's algorithm on a 3×3 Sudoku with an in-circuit oracle

An interactive [Streamlit](https://streamlit.io) app that solves a 3×3 Sudoku with **Grover's search algorithm**
where the **oracle checks the Sudoku rule with gates inside the circuit**, runs the same circuit on a range of
simulated quantum backends, and (optionally) on real quantum hardware and cloud simulators using your own accounts.
It is the in-circuit companion to the [3x3_quantum_sudoku](https://github.com/s-ramakrishnan1991/3x3_quantum_sudoku)
app, whose oracle is built from a list of solutions computed beforehand in Python.

> **Rules of the puzzle.** Fill the 3×3 grid with the values 0, 1 and 2 so that every row and every column
> contains each value exactly once (a 3×3 Latin square). A few cells are given as clues.

---

## Contents

1. [Features](#features)
2. [How the quantum solver works](#how-the-quantum-solver-works)
3. [Backends and where their noise comes from](#backends-and-where-their-noise-comes-from)
4. [Example results](#example-results)
5. [Real hardware and cloud tab](#real-hardware-and-cloud-tab)
6. [Project structure](#project-structure)
7. [Run locally](#run-locally)
8. [Deploy on Streamlit Community Cloud](#deploy-on-streamlit-community-cloud)
9. [Dependencies and version pins](#dependencies-and-version-pins)
10. [Resource requirements](#resource-requirements)
11. [Troubleshooting](#troubleshooting)
12. [Limitations and honest caveats](#limitations-and-honest-caveats)
13. [Security and privacy](#security-and-privacy)
14. [Licenses](#licenses)

---

## Features

| Page | What it does |
|---|---|
| 🧪 **Lab** | Shows the random puzzle, the circuit size and the **circuit diagram of one Grover iteration**. Choose a backend and run the circuit. Shows the most frequent outcome, the success probability against a blind guess, the top outcomes, and the **valid puzzle**. |
| 🔬 **Oracle anatomy** | Flow of one iteration, the real gate diagram, the 6×6 pair-compatibility table, the register layout, and an **oracle probe**: pick a permutation for each row and the app runs the real oracle circuit on that basis state and shows the three flags and the phase (−1 valid, +1 otherwise). |
| 🏟️ **Noisy arena** | Runs the same circuit on the noisy backends you select (and the two ideal references), ranks them, and shows a leaderboard, a dot plot, a cost-versus-quality scatter, a table, and the valid puzzle. Finished real-hardware jobs are added to the same table. |
| 🛰️ **Hardware** | Optional. Submit the circuit to IBM Quantum, IQM or IonQ (QPU, or IonQ's noisy cloud simulator) with your own credentials. Jobs run asynchronously and are polled automatically. |
| ℹ️ **About** | What the circuit does, and its limits. |

Other features:

* **Random easy puzzles.** Each puzzle has 3 clues placed anywhere on the grid. *Draw a random puzzle* gives a new one.
* **Adjustable shots** (256 to 8192).
* **Seven noisy backends plus two ideal references**, all credential-free and local.
* **UI:** top navigation, light "lab notebook" theme (monospace type, square
  corners, teal accent) with a dark variant.
* **Cached simulations**, so repeated runs of the same puzzle, backend and shot count return instantly.

---

## How the quantum solver works

### Encoding
Every row of a valid grid is a permutation of (0, 1, 2), so there are only 6 possible rows. After the clues
are applied, each row has *n* remaining candidate permutations, encoded in ⌈log₂ n⌉ qubits (zero qubits if only
one candidate remains). The search register holds one index per row, and the search space has
*N* = product of the per-row candidate counts. Easy puzzles use 3 to 4 search qubits.

### Oracle (checked inside the circuit)
Rows are valid by construction, and the columns are valid exactly when **no two rows hold the same value in the
same column**. So the oracle tests the three row pairs (0,1), (0,2) and (1,2):

1. **Compute flags.** For each pair, a flag qubit is set to 1 when the two row choices are *compatible* (never
   equal in a column). This uses one multi-controlled X per compatible pair of row indices (V-chain decomposition
   with clean helper qubits).
2. **Sign flip.** A CCZ (H · CCX · H) on the three flags flips the sign of exactly the valid grids.
3. **Uncompute flags.** The flag computation is repeated; all gates are self-inverse, so the flags return to 0.

Register layout: `data qubits | 3 flag qubits | helper qubits`. The oracle is built from a small truth table of
which pairs of row permutations never agree in a column (the rule for two rows). **The list of solutions is never
used to build the circuit.**

### Diffuser and iteration count
After the oracle, the standard Grover diffuser amplifies the marked states. With *M* valid solutions out of *N* states
the ideal success probability after *k* iterations is

```
P(k) = sin²((2k + 1)·θ),   θ = asin(√(M/N))
```

The app picks *k* at the first peak of P(k). *M* comes from a classical count and only sets how often the loop
repeats (see [Limitations](#limitations-and-honest-caveats)).

### Success metric and the valid puzzle
A run counts as successful when a measured bit string decodes to a **valid, complete grid** consistent with the clues.
The app reports the fraction of shots that did so, the most frequent outcome, and whether it is valid. After a result
it shows the **valid puzzle**: the most frequent measured outcome that decodes to a valid grid. If no shot was valid,
it shows the classically enumerated solution and says so.

---

## Backends and where their noise comes from

All simulators run locally inside the app and need no account. The table says exactly what each one does, because
"noisy simulator" can mean very different things.

| Backend | Noise | Source of the noise / what actually runs |
|---|---|---|
| **Aer ideal** | none | Qiskit Aer simulation of the transpiled circuit. The reference. |
| **IonQ-style ideal** | none | Circuit transpiled to an IonQ-like gate set (`h, t, tdg, rx/ry/rz, cx, …`) and simulated without noise. Not IonQ's own simulator. |
| **IQM Garnet noisy** | yes | `IQMFakeGarnet` from `iqm-client`: 20 qubits, native `r` and `cz` gates, with the noise model IQM ships with the fake backend (per-qubit T1/T2, gate depolarizing errors, readout errors, gate durations). |
| **IBM Marrakesh noisy** | yes | `FakeMarrakesh` from `qiskit-ibm-runtime` (156 qubits, heavy-hex), noise model built from the stored calibration snapshot. |
| **IBM Boston noisy** | yes | `FakeBoston` snapshot (156 qubits). Data bundled in `fake_backends/` (see below). |
| **IBM Miami noisy** | yes | `FakeMiami` snapshot (120 qubits, square lattice). Data bundled in `fake_backends/`. |
| **Cirq noisy (Willow data)** | yes | The **median calibration of Google's Willow device** (`willow_pink`, shipped inside `cirq-google`): per-qubit single-qubit Pauli error, per-pair CZ Pauli error, T1/Tphi decay during each gate, and readout errors. The circuit is routed onto a compact block of Willow qubits and the numbers are applied as a **Qiskit Aer noise model** (density matrix). Cirq's own `NoiseModelFromGoogleNoiseProperties` with its density-matrix simulator gives the same kind of model but took about 7 minutes per circuit here, so Aer runs it in seconds. |
| **IonQ Forte noisy** | yes | **Published IonQ figures**: single-qubit fidelity 99.98%, two-qubit fidelity 99.6%, SPAM 99.5%, applied as depolarizing and readout errors in Aer. All-to-all connectivity, so no SWAP gates. Approximate public numbers, not a live calibration and not IonQ's own simulator (use the Hardware page for that). |
| **Quantinuum noisy** | yes | `pytket-quantinuum` compiles the circuit for the **H2** native gate set and the PECOS emulator runs it (all-to-all connectivity) with the **typical figures from the H2 Product Data Sheet v2.00 (15 Oct 2024)**: single-qubit infidelity 3×10⁻⁵, two-qubit infidelity 1.5×10⁻³, SPAM error 1.5×10⁻³ (split evenly between preparation and measurement). Memory and cross-talk errors are not modelled. |

Why some backends are missing: Braket, CUDA-Q, QuEra and Pasqal were dropped. CUDA-Q needs about 1.6 GB of CUDA
libraries, and QuEra's and Pasqal's simulators cannot run a transpiled gate-model Grover circuit in this setup.

---

## Example results

Success probability for one example puzzle (easy, 4 search qubits, 3 Grover iterations, 8192 shots). Other puzzles
differ, and calibration data changes over time, so treat this as an illustration of the *ordering*, not a benchmark.

| Backend | Success | Most frequent outcome valid | Two-qubit gates after transpiling |
|---|---|---|---|
| Aer ideal | 0.96 | yes | 544 |
| IonQ-style ideal | 0.96 | yes | 636 |
| Quantinuum noisy (H2 data sheet) | 0.52 | yes | 544 |
| IBM Boston noisy | 0.29 | yes | 1072 |
| IBM Miami noisy | 0.19 | yes | 752 |
| IonQ Forte noisy (published figures) | 0.17 | yes | 544 |
| IBM Marrakesh noisy | 0.14 | yes | 1072 |
| Cirq noisy (Willow data) | 0.08 | yes | 790 |
| IQM Garnet noisy | 0.06 | no | 769 |

A blind guess succeeds about 1 time in 16 (6%). Checking the rule inside the circuit takes hundreds of two-qubit
gates, so on the noisiest devices the search barely beats guessing. Backends with all-to-all connectivity and low
two-qubit error (Quantinuum, IonQ) need no SWAP gates and keep the gate count at its minimum; sparse connectivity
roughly doubles it, and about 1% two-qubit error (IQM, Google) then compounds quickly.

---

## Real hardware and cloud tab

Everything here is optional and runs on **your** account, so it may consume quota, credits or money.
Tick the acknowledgement checkbox before submitting.

| Provider | You enter | Notes |
|---|---|---|
| **IBM Quantum** | API key, CRN (instance), choice of backend | Click *Connect and list QPUs* to load the backends your instance can use, with their queue length. |
| **IQM** | API key, choice of quantum computer (`garnet`, `emerald`, `sirius`, or a custom alias) | Defaults to the IQM Resonance URL; an advanced field overrides it. |
| **IonQ** | API key, QPU or **noisy simulator** | The noisy cloud simulator lets you pick a noise model. The QPU needs the device to be enabled for your project; otherwise IonQ returns an HTTP 403. |

How jobs work:

* Submitting returns a job ID immediately. The page polls every 15 seconds and shows the status (queued, running, done, error).
* Finished jobs are decoded, scored and added to the **Noisy arena** (labelled *Real hardware* or *Cloud simulator*).
* **Retrieve an earlier job by ID** fetches a job you submitted before (the API key is needed again). Use the same
  puzzle, shots and iteration count as when you submitted.
* Hardware circuits are transpiled for the device: IBM and IQM use the backend's own target, IonQ uses its native gate set.

---

## Project structure

```
app.py                Entry point: page config, top navigation
state.py              Session state, cached puzzle/circuit/simulation helpers, circuit diagram
arena.py              The noisy backends and ideal references with their noise models
incircuit.py          The in-circuit rule oracle, diffuser and full Grover circuit
grover_engine.py      Puzzle generation, row-permutation encoding, decoding, metrics, ideal and Quantinuum runs
real_backends.py      IBM / IQM / IonQ submission, status polling and result fetching
ui.py                 CSS, SVG puzzle board, charts, leaderboard
fake_ibm_extra.py     FakeBoston / FakeMiami backend classes
fake_backends/        Bundled IBM calibration snapshots for Boston and Miami (Apache-2.0)
views/                lab.py, oracle.py, arena_page.py, hardware.py, about.py
tests/                test_incircuit.py: oracle vs. an independent rule checker
.streamlit/config.toml  Theme settings (light and dark)
pyproject.toml        Dependencies (managed with uv)
uv.lock               Locked, reproducible versions
.python-version       Python 3.12
.gitignore
LICENSE
```

Key entry points: `incircuit.build_grover_incircuit(prob, iterations)`, `arena.run(name, circuit, shots)`,
`grover_engine.make_puzzle(difficulty, seed)`, `build_problem(fixed)` and `analyse_counts(prob, counts)`.
A new simulator is added by registering an entry in `arena.ARENA` and a branch in `arena.run`.

---

## Run locally

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management. Python 3.12 is tested.
Install uv once (see the uv docs), then:

```bash
git clone https://github.com/s-ramakrishnan1991/<repo>.git
cd <repo>
uv sync                      # creates .venv with Python 3.12 and installs the locked versions
uv run streamlit run app.py
```

Other useful commands:

```bash
uv run python tests/test_incircuit.py   # oracle checked against an independent rule checker
uv pip check                   # verify the environment is consistent
uv add <package>               # add a dependency (updates pyproject.toml and uv.lock)
uv lock --upgrade-package <p>  # upgrade one package; re-test before committing uv.lock
uv export --no-hashes -o requirements.txt   # only if a host needs a requirements.txt
```

If you prefer not to use uv, `uv export --no-hashes -o requirements.txt` gives a pinned file that `pip install -r`
can read; use a fresh virtual environment, because the pinned Qiskit must not be mixed with other Qiskit versions.

---

## Deploy on Streamlit Community Cloud

1. Push the files to a GitHub repository **with `app.py`, `pyproject.toml` and `uv.lock` at the repository root**.
2. At <https://share.streamlit.io> choose **Create app**, select the repo and branch, and set **Main file path** to `app.py`.
3. Under **Advanced settings** choose **Python 3.12**, then deploy.
4. After a push, Streamlit redeploys automatically. If the app shows an old version, open **Manage app → logs**,
   check which commit was cloned and look for install errors, then use **Reboot app**.

Read [Resource requirements](#resource-requirements) before deploying: this app can exceed the memory of the free tier.
Other hosts that work: Hugging Face Spaces, Render, Railway, Fly.io, Google Cloud Run, or your own server
(`uv sync && uv run streamlit run app.py`).

---

## Dependencies and version pins

Declared in `pyproject.toml` and locked in `uv.lock` (170 packages).

| Package | Why |
|---|---|
| `qiskit==2.1.2`, `qiskit-aer==0.17.2` | Circuit construction, transpilation, Aer simulation. Pinned because `iqm-client[qiskit]` 36 needs `qiskit<2.2`, and newer Qiskit 2.6.x / Aer 0.18.x **crashed (segfault) the Streamlit server on the second rerun** during testing. |
| `qiskit-ibm-runtime==0.43.1` | IBM backends and fake devices. Newer versions that include FakeBoston/FakeMiami need Qiskit ≥ 2.2, hence the bundled data in `fake_backends/`. |
| `qiskit-ionq==1.1.1` | IonQ QPU and cloud simulator. |
| `iqm-client[qiskit]==36.0.0` | IQM fake backend (Garnet) and the real-hardware provider. |
| `ibm-cloud-sdk-core==3.24.1`, `python-dateutil<3` | Needed so that `ibm-platform-services` (pulled in by `qiskit-ibm-runtime`) builds. |
| `cirq-core`, `cirq-google` | The Google Willow calibration data (`willow_pink`). |
| `pytket-quantinuum[pecos]==0.59.3`, `quantum-pecos==0.8.0.dev8` | pytket compiler for H2 and the local PECOS emulator. The `[pecos]` extra depends on a **pre-release** of `quantum-pecos`, which is why it is pinned explicitly. It is the only pre-release pinned on purpose. |
| `pandas`, `altair`, `matplotlib`, `pylatexenc`, `streamlit>=1.50,<2` | Tables, charts, circuit drawing, UI. |

Do not loosen the Qiskit pins without re-testing, and run `uv pip check` after any change. Note that `uv lock` prints a
harmless warning that `quantum-pecos` has no extra named `wasmtime`.

---

## Resource requirements

* **Disk:** a few GB for the full environment. Most of it is the Quantinuum PECOS emulator and its toolchain.
* **Memory:** one simulated backend uses a few hundred MB. Running **all** backends in one session peaks at about
  **1.2 to 1.3 GB**, which can exceed Streamlit Community Cloud's limit of roughly 1 GB. The app limits memory by keeping
  only one IBM noise model loaded at a time, but if the app restarts during **Run the arena**, run fewer backends at a
  time or deploy on a host with more memory.
* **Time** (2 CPUs, example puzzle, 8192 shots): Aer ideal about 10 s, IBM about 10 to 13 s, IQM about 4 s, Cirq/Willow about
  5 s, IonQ about 2 s, Quantinuum about 50 s. Fewer shots are proportionally faster.

---

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `git push` is rejected (non-fast-forward) | The GitHub repo already has commits. Push to a new empty repo (do not force-push over an existing project). |
| `fatal: 'origin' does not appear to be a git repository` | No remote is set. Run `git remote add origin <url>`, then `git push -u origin main`. |
| Cloud app shows old code after a push | Check that `app.py` and `pyproject.toml`/`uv.lock` are at the repo root and the app watches the pushed branch, then **Manage app → logs** and **Reboot app**. |
| Build fails or app restarts when running the arena | Out of memory or disk on the host. Check the logs for `Killed` or `No space left on device`. |
| `ModuleNotFoundError` locally | Packages are in a different environment. Use `uv run streamlit run app.py`, or activate `.venv`. |
| Streamlit server crashes (segfault) on the second run | A newer Qiskit/Aer than the pinned ones is installed. Recreate the environment with `uv sync`. |
| IonQ `403 … not enabled` | Your IonQ project does not have that QPU enabled. Use the noisy simulator or ask IonQ to enable the device. |
| IBM backend list is empty | Check the API key and the CRN (instance), and that your plan has access to backends. |

---

## Limitations and honest caveats

* **This is a demonstration.** A 3×3 Sudoku has only a handful of candidate grids and a classical program solves it
  instantly, so there is no quantum speedup.
* **The number of Grover iterations comes from a classical count** of the solutions. The oracle never uses that list, but
  the repeat count does.
* **The pair table is a truth table** for two rows. It is not the answer to the puzzle, but it is classical knowledge of the
  rule built into the gates.
* The noisy simulators use **stored or published error figures**, not live calibration, so results are indicative.
  The Google Willow data is a *median* over the chip; the Quantinuum and IonQ figures are published *typical* values.
  Crosstalk, leakage and drift are not modelled.
* **IonQ-style ideal** is not IonQ's simulator; it is a noiseless run with an IonQ-like gate set. **IonQ Forte noisy** uses
  approximate published fidelities. Use the Hardware page's IonQ noisy cloud simulator for IonQ's own noise models.
* **Cirq noisy (Willow data)** uses Cirq's Willow calibration numbers but simulates with Aer, not Cirq's own simulator (see the table).
* Fake-backend noise models describe the devices as of their snapshot date.
* The real-hardware and cloud-simulator paths depend on third-party services and were checked offline but not against
  live accounts, so provider-side errors (permissions, queues, quotas) can occur.
* Success probability is measured over a finite number of shots, so small differences between backends are within noise.
* The oracle was verified exhaustively against an independent rule checker on 24 random easy and medium puzzles in a
  separate test; the app itself offers easy puzzles only.

---

## Security and privacy

* API keys and CRNs are entered in the UI, held only in the running session, used for the requested call, and **never
  stored, cached, logged or written to environment variables**.
* Job records contain only the provider, backend, job ID, shot count and circuit metrics, never credentials.
* Error messages are scrubbed of secrets before they are shown.
* Because the app runs on a shared server when deployed, use API keys with the minimum permissions you can, and rotate any
  key you pasted into a screenshot or chat.
* `.gitignore` excludes `.env`, `.venv` and `.streamlit/secrets.toml`; never commit keys.

---

## Licenses

* The app code is released under the **MIT License** (see `LICENSE`).
* The IBM FakeBoston and FakeMiami data in `fake_backends/` are unmodified files from the IBM Qiskit ecosystem under the
  **Apache License 2.0** (see `fake_backends/LICENSE.txt`).
* Qiskit, Qiskit Aer, `qiskit-ibm-runtime`, `qiskit-ionq`, `iqm-client`, Cirq, `cirq-google`, pytket and PECOS are
  distributed under their own open-source licenses.
* Google, IBM, IQM, IonQ and Quantinuum names refer to the respective companies' devices and tools; this project is
  not affiliated with or endorsed by them.
