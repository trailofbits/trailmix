# Schrottenloher secp256k1 EC point-add: aggressive & reckless parameter sets

Analysis of the approximate (pseudo-Mersenne EEA/GCD) Schrottenloher 2026
secp256k1 EC point-addition circuit. We trade per-shot correctness for circuit
cost (qubit peak, Toffoli count) by tuning four parameters and report the
cheapest sets meeting two validation targets.

**Validation model.** The zenodo fuzz tool runs `N = 9000` random secp256k1
on-curve point pairs; EVERY shot must be correct (value + clean ancilla +
correct phase) or the run fails. So with per-shot success `p_shot`,
`P(run) = p_shot^9000`, and the per-shot failure bound for a run target `P` is
`f_shot <= 1 - P^(1/9000)`:

| target        | P(run) | f_shot bound |
|---------------|--------|--------------|
| aggressive    | >= 0.90 | 1.171e-5 |
| reckless      | > 0.01  | 5.116e-4 |
| reckless >10% | > 0.10  | 2.558e-4 |

Scripts: `scripts/schr_param_model.py` (cost/failure model + empirical GCD/+f
ports, every formula cited to `src/...:line`), `scripts/schr_param_search.py`
(the sweep). Run `python3 scripts/schr_param_search.py` from `trailmix/`.
The RNG is never seeded (run-to-run wobble is signal).

---

## Parameters and their failure/cost coupling (with file:line)

| Rust constant | default | file:line | effect of LOWERING |
|---|---|---|---|
| `ITERATIONS_VAR` | 2.4 | `gcd_pack.rs:34`, used `:44` | fewer GCD iters -> smaller dialog tape (frees qubits) AND fewer per-iter Toffoli, but higher GCD-non-convergence failure |
| `padding` | 30 | `pm_prims.rs:193` (and `:117,194,202,268,344,595,620`) | shorter `lsbs = padding+33` carry chain (fewer +f Toffoli) but per-call truncation failure ~`2^-padding` |
| `TRUNCATE` | 40 | `gcd_pack.rs:271` | fewer GCD-comparator Toffoli (`comparators ~ iters*TRUNCATE`) but risk of wrong swap decisions breaking GCD convergence |
| `U_PAD_VAR` | 2.3 | `gcd_pack.rs:38`, used `:51` | smaller `u_padding` (fewer qubits, tighter compare window); we hold it at default — it does not gate the targets |
| `vents` (driver arg) | 0 | `pointadd.rs:64-72`; clamp `gcd_pack.rs:30` | per-call measurement-vent ancillae: each `-1` Toffoli over the ~810 ventable register-add calls, `+1` qubit peak (pool reused across ops) |
| `dialog_m` (driver arg) | 5 | `gcd_pack.rs:19`, `pointadd.rs:54,64` | M=5 packs the tape (`iters/5*8`, low qubits, +~204k compress Toffoli); M=1 raw (`2*iters`, wide tape, no compress) |

### Key derived quantities (n=256)
- `expected_iterations(256, 2.4) = ceil((1.413*256 + 2.4*16)/5)*5 = ceil(400.128/5)*5 = 405` (`gcd_pack.rs:43-46`).
- `u_padding(256, 2.3) = ceil(2.3*16) = 37` (`gcd_pack.rs:50-52`).
- `lsbs = padding + f_bitlen = 30 + 33 = 63`; `msbs = padding = 30` (`pm_prims.rs:193-194, 344`).
- dialog tape: M=5 -> `405/5*8 = 648`; M=1 -> `2*405 = 810` (`gcd_pack.rs:56-58, 66-79`).
- `q = 2^256 - F`, `F = 2^32 + 977` (`mod.rs:42`).

### Failure-mode formulas (cited)
- **GCD non-convergence**: the classical dialog GCD (`gcd_pack.rs:102-149`)
  must reach `(u,v)=(1,0)` within `iters` iters else `to_bitvector_classical`
  returns `None` (`gcd_pack.rs:150-152`). MEASURED empirically by porting that
  exact body (`schr_param_model.gcd_converges` / `gcd_fail_rate`), running
  `u=q, v=x` for random odd `x` (the inversion use case, `gcd_pack.rs:700`).
- **+f-window truncation**: the `lsbs`-bit constant add drops the carry beyond
  bit `lsbs-1` (`pm_prims.rs:24-25, 114-128, 148, 260`). On uniform low bits
  `P(carry dropped) = f/2^lsbs = f/2^(padding+33) ~ 2^-padding`. Validated:
  the empirical carry-drop event matches `f/2^lsbs` to within sampling noise
  (`reduction_fail_rate`, ratio ~1.0 at padding=14).
- **msbs comparator/clt**: the top-`msbs` compare misdecides ~`2^-msbs` per call
  (`pm_prims.rs:231, 263-268`).
- **mod_halve / "2x in [q,2^n)" drift**: ~`2^-224` per call — NEGLIGIBLE
  (`pm_prims.rs:124-128`).

### Reduction-call counts per EC-add shot (from the driver)
Counted from `pointadd.rs:81-102` + `bezout_unpack.rs` + `pm_prims.rs`
(`schr_param_model.reduction_event_counts`):
- division (step 6, `apply_bv_inv`): `iters` controlled_mod_sub (1 +f window +
  1 msbs each) (`bezout_unpack.rs:540-553`).
- multiply (step 11, `apply_bv`): `iters` mod_double (1 +f) + `iters`
  controlled_mod_add (1 +f + 1 msbs) (`bezout_unpack.rs:168-176`).
- square (step 10): ~`3(n-1)` mod_double + `n` controlled_mod_add
  (`pm_prims.rs:698-723, 499-523`).
- 7 coord add/sub steps (`pointadd.rs:82-102, 117-138`).

At iters=405: **2243 +f windows, 1073 msbs comparators** per shot. So at the
default `padding=30` the union-bound reduction failure is
`2243*(f/2^63) + 1073*2^-30 ~ 2.0e-6` — well under the aggressive bound, and
DOMINATED by the GCD-non-convergence floor.

---

## Cost model (derived from the profiler anchor)

Anchor (task spec, `profile_ec_add_schrottenloher`, raw M=1 / vents=0 /
iters=405): **total Toffoli 2,272,261**, with the component breakdown encoded
in `schr_param_model.ANCHOR_BREAKDOWN` (regadds 623k, gcd_csub 478k, sqr_add
227k, +f 313k, cswaps 240k, comparators 153k, double/halve 232k). Scaling:
regadds/gcd_csub/cswaps/double-halve ~linear in `iters`; +f ~`iters * lsbs`;
comparators ~`iters * TRUNCATE`; sqr_add fixed; M=5 adds ~204k compress;
venting subtracts `min(vents, 255) * 810`.

`qubit_peak ~ dialog_tape + 514 + vents + ~10` (task spec; +32 when f-venting
materializes the 63-bit constant at vents>0, `pm_prims.rs:55-77`).

**Model cross-check vs measured** (`pointadd.rs:62-63, 341-365`):

| config | model (q, tof) | measured (q, tof) |
|---|---|---|
| M=5 vents=0 (SP1 headline) | 1172, 2.470M | 1173, 2.477M |
| M=1 raw vents=0            | 1334, 2.266M | 1329, 2.272M |
| M=1 raw vents=90           | 1456, 2.193M | 1451, 2.126M |

Qubits within 5; Toffoli within ~3% (vented config is the loosest — the model
slightly under-credits +f venting, i.e. it is conservative on Toffoli).

---

## Results

### Aggressive (P(run) >= 90%): the DEFAULT config already meets it

The cheapest qubit set is at **iters = 405** (the round-up of the default
`ITERATIONS_VAR = 2.4`), M=5 packed, `TRUNCATE = 40`, `vents = 0`. The
iteration budget CANNOT drop below 405: empirically the GCD-non-convergence
floor is a cliff at the multiple-of-5 round-up boundary (2M-trial measurement):

| iters | GCD non-convergence (2M trials) |
|---|---|
| 415 | 0 / 2,000,000  (UB 1.5e-6) |
| 410 | 1.0e-6 (2/2M) |
| **405 (default)** | **2.0e-6 (4/2M)** |
| 400 | 2.6e-5 (52/2M) — exceeds the 1.17e-5 bound by itself |

So `iters=400` already busts aggressive on GCD non-convergence alone; `iters=405`
is the floor. `TRUNCATE` cannot be narrowed either: at iters=405 the DIRECT
truncated-comparator measurement gives T40 -> 0, T30 -> 9e-5, T24 -> 1.6e-3,
T20 -> 1.0e-2, T16 -> 5.1e-2 (so T30 already over the aggressive bound). `padding`
can drop to 28 at most (the msbs term `1073 * 2^-padding` dominates the
reduction failure).

**Aggressive set (cheapest, projected):**

| param | value | vs default |
|---|---|---|
| `ITERATIONS_VAR` | 2.4 (iters=405) | UNCHANGED |
| `padding` | 28 | -2 (saves ~10k Toffoli) |
| `TRUNCATE` | 40 | UNCHANGED |
| `vents` | 0 | UNCHANGED |
| `dialog_m` | 5 | UNCHANGED |

Projected: **qubits = 1172, Toffoli = 2,460,063, f_shot = 1.02e-5,
P(run over 9000) = 0.91.**

The practical recommendation is the **shipped default** (`padding=30`),
which gives **q=1172, tof=2.470M, f_shot=4.0e-6, P(run)=0.96** — i.e. the
already-validated 1173q/2.477M SP1 headline config IS the aggressive answer.
Dropping padding to 28 saves only ~10k Toffoli (0.4%) at the cost of halving
the run-success margin (0.96 -> 0.91); not worth it. **There is no qubit
reduction available at the aggressive correctness level** — iters is pinned at
405 and the tape/peak is fixed by it.

### Reckless (beat 1175q AND 1.7M Toffoli, P(run) > 1%): UNREACHABLE

The two cost bounds cannot be met simultaneously by ANY setting of these four
parameters. The **absolute Toffoli floor across the whole grid is ~1.78M**
(iters=385, M=1, vents=255, padding=10, TRUNCATE=16) at **1581 qubits** — and
that floor still exceeds 1.7M while being 400+ qubits OVER the 1175 bound.

Why: the venting saving is `vents * 810` Toffoli but costs `vents` qubits 1:1,
so driving Toffoli down ALWAYS drives qubits up. The non-ventable Toffoli
(cswaps 240k + comparators 153k + sqr_add 227k + GCD csub 478k + +f 313k +
double/halve 232k ~ 1.64M even before the ventable register-adds) is a hard
floor near 1.7M, and the only way under it (max venting, raw wide tape) blows
the qubit budget to ~1.6k. M=5 packs qubits to ~1156 (under 1175) but leaves
Toffoli at ~2.3M; M=1 + heavy venting reaches ~1.9M Toffoli but at ~1.6k
qubits. There is no overlap.

So we report, in lieu of an (impossible) dual-bound set, the realizable
single-axis frontier at each P(run). All rows below sit at **iters=395**
(the lowest iteration budget whose GCD non-convergence ~2.2e-4 still leaves room
under the reckless f_shot bounds) with `TRUNCATE=30` (the narrowest viable
comparator: T<=24 pushes GCD non-convergence over 1.6e-3).

**reckless (P(run) > 1%, f_shot <= 5.12e-4):**

| frontier | iters | M | pad | T | vents | qubits | Toffoli | f_shot | P9000 |
|---|---|---|---|---|---|---|---|---|---|
| q <= 1175 only (min Toffoli) | 395 | 5 | 23 | 30 | 0 | **1156** | 2,343,393 | 4.67e-4 | 0.015 |
| Toffoli minimised (busts q)  | 395 | 1 | 23 | 30 | 255 | 1601 | **1,937,880** | 4.67e-4 | 0.015 |
| best balance (busts both)    | 395 | 1 | 23 | 30 | 90 | 1436 | 2,071,530 | 4.67e-4 | 0.015 |

**reckless >10% (P(run) > 10%, f_shot <= 2.56e-4):**

| frontier | iters | M | pad | T | vents | qubits | Toffoli | f_shot | P9000 |
|---|---|---|---|---|---|---|---|---|---|
| q <= 1175 only (min Toffoli) | 395 | 5 | 26 | 40 | 0 | **1156** | 2,395,235 | 2.42e-4 | 0.113 |
| Toffoli minimised (busts q)  | 395 | 1 | 26 | 30 | 255 | 1601 | **1,952,416** | 2.42e-4 | 0.113 |

Reading: you can have **q=1156 < 1175** at ~2.34M Toffoli, OR **~1.94M Toffoli**
at 1601 qubits, but never both bounds. The 1.7M Toffoli line is below the
non-ventable Toffoli floor; it would require a structural change (cheaper
register adder / comparator / +f reduction), not a parameter tweak.

---

## How to realize each set (Rust constants to change)

- `ITERATIONS_VAR`: `gcd_pack.rs:34` — set to the listed value (the search
  prints the mid-bin `iv` that yields the target `expected_iterations`).
  **Affects BOTH `gcd_pack.rs` AND every caller of `expected_iterations`**
  (the apply_bv loop bound `bezout_unpack.rs:155`, the garbage tape length).
- `padding`: hardcoded `30usize` at `pm_prims.rs:193,202,209,215,341,448,473,594,620,672`
  and `msbs=padding` likewise. Change all of them together (or factor into a
  constant). `lsbs = padding + f_bitlen` follows automatically.
- `TRUNCATE`: `gcd_pack.rs:271` AND `gcd_pack.rs:509` (forward + reverse GCD).
- `vents` / `dialog_m`: driver arguments to
  `ec_add_inplace_schrottenloher_secp256k1_m` (`pointadd.rs:64`) — no constant
  edit needed; the test harness already plumbs them
  (`pointadd.rs:344-365`).

**Caveat (do NOT skip):** every reduced-correctness set below is a PROJECTION
from the ported classical references + the profiler-anchored cost model, NOT a
measured circuit run. Realizing any of them requires editing the constants
above and running the zenodo fuzz tool (9000 shots) to confirm `P(run)`, and
`profile_ec_add_schrottenloher` (or the EC-add test) to confirm (qubits,
Toffoli). The cost model is validated to ~3% on Toffoli and ~5 qubits against
the three documented configs; the GCD floor is measured to the trial-count
resolution stated in the search output.
