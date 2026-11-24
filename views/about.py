"""About page: what this app shows and its honest limits."""
import streamlit as st

import ui


def render():
    ui.hero("About this lab", "Grover's algorithm on a 3×3 Sudoku, with the rule checked inside the circuit")
    st.markdown(
        """
### What the circuit does
Each row of the grid is a permutation of 0, 1, 2, stored in qubits. For every pair of rows the circuit computes
a flag qubit that says "these two rows never hold the same value in a column". A sign flip on the grids where all
three flags are 1 marks the valid grids, the flags are uncomputed, and the usual Grover diffuser follows.
The oracle is built from the rule for two rows, not from a list of solutions.

### Limits you should know
* **Still a demonstration.** A 3×3 Sudoku has only 16 candidates here, and a classical program solves it
  instantly. There is no quantum speedup.
* **The repeat count uses classical counting.** The number of Grover iterations needs the number of
  solutions. That count is computed classically and only sets how often the loop repeats.
* **The pair table is a truth table.** It records which pairs of row permutations never share a column. It
  is the rule for two rows, not the answer to the puzzle.
* **Noise data are snapshots.** IBM, IQM and Google models come from data shipped in Python packages,
  Quantinuum from data-sheet figures, and IonQ from published fidelities (1q 99.98%, 2q 99.6%, SPAM 99.5%).
  None is live calibration. IonQ's own noisy cloud simulator is available on the Hardware page.
* **Hardware paths** (IBM Quantum, IQM, IonQ) depend on your accounts and were checked offline, not against live services.

### Puzzles
Random **easy** puzzles only: 3 random clues placed anywhere on the grid. Press *Draw a random puzzle* on the Lab page for a new one.
""")
