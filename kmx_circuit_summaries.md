# Executive summaries: the five EC point-add `.kmx` circuits

`gen_and_validate_kmx.sh` emits and validates five quantum elliptic-curve
point-addition circuits. All five compute the same in-place affine `P += Q` on
secp256k1; they differ only in the modular-inversion engine and its qubit/Toffoli
operating point, and validate through the same native zkp_ecc Simulator over 9000
Fiat-Shamir shots.

| config | emit bin | inversion engine | qubits | Toffoli |
|---|---|---|--:|--:|
| low-qubit | `emit_test_ec_add_schrottenloher` | Schrottenloher EEA dialog, `dialog_m=5`, no vents | 1173 | ~2.48M |
| low-tof | `emit_test_ec_add_schrottenloher_lowtof` | Schrottenloher EEA dialog, `dialog_m=3` + venting | 1416 | ~2.03M |
| jump-lowqubit | `emit_test_ec_add_schrottenloher_jump` | jump-GCD dialog (Stein-style, `jump=2`), no vents | 1169 | ~2.09M |
| jump-lowtof | `emit_test_ec_add_schrottenloher_jump_lowtof` | jump-GCD dialog (`jump=2`) + venting | 1412 | ~1.90M |
| shrunken-PZ | `emit_test_ec_add_shrunken_pz` | reversible Proos-Zalka divstep state machine | 1050 | ~32.3M (~100M ops) |

Costs are quoted from `gen_and_validate_kmx.sh`, in-code doc-comments, and
`circuit_gen/notes/schrottenloher_status.md`. File references point at the
implementation; paper references give the arXiv/eprint id.

---

## 0. Shared structure: the affine point-add and the validation harness

### 0.1 The cost target

The cost target is the Google Quantum AI ECC whitepaper -- Babbush, Zalcman,
Gidney, Broughton, Khattar, Neven, Bergamaschi, Drake, Boneh, "Securing Elliptic
Curve Cryptocurrencies against Quantum Vulnerabilities: Resource Estimates and
Mitigations" (`papers/cryp_paper.txt`, 30 Mar 2026; "Babbush et al. (arXiv
2026)"). Its two validated configurations are `Clow-qubit` = <= 1175 logical
qubits / <= 2,700,000 Toffoli and `Clow-gate` = <= 1425 logical qubits / <=
2,100,000 Toffoli (`cryp_paper.txt`). Google validates these with a
zero-knowledge proof over a kickmix-format circuit replayed in a kickmix
simulator that counts CCX+CCZ executed across 9024 test runs
(`cryp_paper.txt`).

The Schrottenloher-family configs build on Andre Schrottenloher, "Optimized Point
Addition Circuits for Elliptic Curve Discrete Logarithms" (arXiv:2606.02235v1,
1 Jun 2026; Univ Rennes, Inria, CNRS, IRISA), whose abstract claims Babbush et
al.'s secp256k1 result at ~1.5% more qubits and 6.5-10% fewer Toffoli
(`papers/arxiv_2606.02235.pdf`, p.1). The in-repo implementation ports
Schrottenloher's own reference code -- the `gcd_functions.py` / `gcd.py` /
`special_mod_arithmetic.py` / `compressor.py` sources distributed with the
paper (in Schrottenloher's `qarton` reference library).

### 0.2 The affine addition formula

All five use the standard affine Weierstrass addition `R = P + Q` for `P != +/-Q`:
`dx = R.x - P.x`, `dy = R.y - P.y`, `lambda = dy/dx`, `new_x = lambda^2 - R.x -
P.x`, `new_y = lambda*(P.x - new_x) - P.y` (classical reference
`pointadd.rs`, `ec_add_classical_secp256k1`). In all five, `P` is the
quantum point in registers `x2/y2` (or `tx/ty`), and `Q` is the classical point
supplied per shot in input registers `ox/oy` -- the fuzzer's runtime controls
(`emit_..._schrottenloher.rs`).

The two families realize this differently:

- The Schrottenloher family (low-qubit, low-tof, and the two jump variants)
  follows Schrottenloher Algorithm 1 (`pointadd.rs`; itself adapted from ref [11]
  of that paper). It runs a sequence of field-addend steps plus two in-place
  modular multiplications. The inverse `1/dx` comes from running the same
  multiply circuit backwards (`pointadd.rs`: `mod_mul_..._reverse` =
  division), so `P += Q` is `x2 -= ox; y2 -= oy; y2 *= x2^-1; x2 += 3*ox; x2 -=
  y2^2; y2 *= x2; x2 := -x2; y2 -= oy; x2 += ox` (`pointadd.rs`). No
  explicit `lambda` register -- the slope lives in `y2` between the two
  multiplies.
- shrunken-PZ (`point_add.rs`) materializes `lambda` explicitly: a
  reversible divstep inversion computes `lambda = dy/dx` (`point_add.rs`),
  and a second alt-witness divstep cancels `lambda` after the coordinates are
  built (`point_add.rs`). This realizes the Roetteler slope-invariance
  structure (Roetteler/Naehrig/Svore/Lauter, arXiv:1706.06752) with two
  inversions instead of Roetteler's four; the two-inversion group shift is also
  Proos-Zalka Sec 4.3.1.

### 0.3 The validation harness

Each emit bin builds the circuit, then defragments the quantum registers back to
canonical contiguous ids: the in-place multiply/divide scatters `x2/y2` to high
ids, but the fuzzer writes input and reads output from the same ids
(`emit_..._schrottenloher.rs`). It then registers reg0=x2/tx, reg1=y2/ty,
reg2=ox, reg3=oy, writes a random `P.x P.y Q.x Q.y -> R.x R.y Q.x Q.y` case file,
and serializes to `.kmx` on stdout.

`gen_and_validate_kmx.sh` builds and runs the native zkp_ecc Simulator
(`native_fuzz`, the same `sim.rs`/Simulator compiled into the SP1 zkVM guest) on
each `.kmx` under explicit caps, over `NUM_TESTS=9000` Fiat-Shamir shots:

- low-qubit: 1175 qubits / 2,700,000 Toffoli / 15M ops
- low-tof: 1420 qubits / 2,100,000 Toffoli / 15M ops
- jump-lowqubit: 1175 qubits / 2,100,000 Toffoli / 13M ops
- jump-lowtof: 1420 qubits / 1,950,000 Toffoli / 14M ops
- shrunken-PZ: 1060 qubits / 50,000,000 Toffoli / 140M ops

The Toffoli cap counts CCX+CCZ executed, the metric Google uses; the in-repo
convention is `tof = executed_toffoli_shots / 64` (per fired shot). The op
stream is input-independent (`ox/oy` are classical controls), so each emit loads
one random 64-shot block just to satisfy construction-time slope contracts; the
fuzzer reloads its own 9000 cases (`emit_..._schrottenloher.rs`).

---

## 1. low-qubit -- Schrottenloher EEA dialog, `dialog_m=5`, no venting

Basis: Schrottenloher arXiv:2606.02235 (Alg 1 point-add + Alg 2/3/4 EEA dialog
inversion), replicating Google's `Clow-qubit` target of 1175q / 2.7M Toffoli.

### (a) What it computes

In-place affine `P += Q` (`pointadd.rs`,
`ec_add_inplace_schrottenloher_secp256k1`). `x2` is `256 + u_padding(256)` bits,
`y2` is 257 bits; `ox/oy` are 256-bit classical inputs. The body is Schrottenloher
Alg 1 steps 3-15 (`pointadd.rs`): five field-addend steps that XOR the
classical coordinate into a fresh 257-bit temp (0-Toffoli `x_if_bit` load), apply
the unconditional pseudo-Mersenne mod-add/sub, then XOR-unload (`coord_addsub`,
`pointadd.rs`); two in-place modular multiplications (`y2 *= x2^-1`
forward = backward run of the multiply, `y2 *= x2` forward); one controlled
mod-square-sub; one controlled mod-negation (`pointadd.rs`).

### (b) The inversion algorithm

The inversion is modular multiplication via the extended-Euclidean "dialog"
(Schrottenloher Alg 2/3/4; `mod_mul_in_place_eea_secp256k1_m`,
`mod_mul_eea.rs`), in three phases (`mod_mul_eea.rs`):

1. Forward GCD pack (Alg 2): drive the binary-GCD pair `(u,v)` from `(q, x)`
   toward `(1, 0)`, packing the per-iteration choice bits `(b0 = v.parity, b0&b1
   = "u > v")` into a compressed garbage bit-vector (`gcd_pack.rs`). Each
   iteration: `b0 = v[0]`; a top-bits comparator sets `b0&b1`; a controlled swap;
   `v -= b0*u`; `v >>= 1`. This consumes `x` (ending `u~1, v~0`) and produces the
   dialog tape, a classical record of the GCD trajectory. Port of Schrottenloher's
   reference `to_bitvector` (`gcd_pack.rs`).
2. Apply bit-vector (Alg 3, Bezout reconstruction): read the tape in reverse and
   run linear modular updates on `(u,v)` seeded at `(y,0)`, ending at `(0, y*x^-1
   mod q)`. Per reverse iter: `v *= 2 mod q`; if `b0` then `v += u`; if `b0&b1`
   swap (`bezout_unpack.rs`). Port of Schrottenloher's reference
   `apply_bitvector` (`bezout_unpack.rs`).
3. Reverse GCD pack (Alg 2^-1): restore `x` from the tape and drain the garbage
   register to |0> (`gcd_pack.rs`).

Schrottenloher's identity (`mod_mul_eea.rs`): the inverse of this
in-place multiply divides. So Alg 1 line 6's `y2 *= x2^-1` is the same circuit
run backwards (`pointadd.rs` -> `mod_mul_..._reverse_m`), and line 11's `y2
*= x2` is the forward direction (`pointadd.rs`). The whole add reduces to a
few dialog multiplications.

`dialog_m = 5` (`gcd_pack.rs`) is an M=5 base-3 radix compressor.
Five successive `(b0, b0&b1)` pairs are each one of `{(0,0), (1,0), (1,1)}` -- the
GCD invariant forbids `(0,1)` -- so a window is a base-3 digit string in 8 bits
(`3^5 = 243 < 256`), density 8/5 = 1.600 bits/pair vs the M=3 compressor's 5/3 =
1.667. The narrower tape lowers the peak (`gcd_compress5.rs`). The 5-pair
encoder and its 8/5 density are an in-repo extension -- Schrottenloher Sec 3.1 /
Fig 1 gives only the 3-pair->5-bit compressor (see Novel improvements). To
amortize the encoder, the GCD holds the current window decompressed and fires
`compress_5iter` once per 5 iterations rather than recompressing every iteration
(`gcd_pack.rs`; an in-repo amortization).

### (c) Cost and where the peak lives

1173 qubits / ~2.484M Toffoli for the full EC-add (`pointadd.rs`;
`gen_and_validate_kmx.sh`). The standalone inversion replicates (in-repo
measurement) at 1191q / 2,281,568 Toffoli, below Schrottenloher's 1192q / 2,385,517
on both axes (`circuit_gen/notes/schrottenloher_status.md`); the EC-add config measures
1173q, under the 1175 target (`pointadd.rs`).

The peak sits in `apply_bv` (Bezout reconstruction), not the GCD: the 670-bit
(M=3) / 648-bit (M=5) garbage tape is live there alongside the 257-bit `x2` and
`y2` registers (`670 + 514 + 7 ~ 1191`, `circuit_gen/notes/schrottenloher_status.md`).
Because the GCD phase runs below the peak, its controlled-subtract has full
ancilla headroom and uses the Gidney 2n adder (`GCD_CSUB_VENTS = usize::MAX`,
`gcd_pack.rs`), while peak-setting `apply_bv` stays on the Cuccaro 3n path
with no venting in this config. The GCD per-iteration register width shrinks on a
schedule -- freed `u/v` bits feed the garbage allocator (`gcd_pack.rs`), which is what makes the dialog fit.

### (d) Component citations and the deltas layered on top

| component | prior-work basis | this implementation's delta |
|---|---|---|
| EC-add formula / step sequence | Schrottenloher 2026 Alg 1 (arXiv:2606.02235; adapted from ref [11] of that paper) | direct port; `ec_add_classical_secp256k1` cross-checks G+2G=3G (`pointadd.rs`). |
| Inversion = in-place EEA dialog multiply | Schrottenloher Alg 2/3/4; reference impl `gcd.py` (`IPModMul`) | `mod_mul_eea.rs`; uses the inverse-circuit-divides identity for the slope (`mod_mul_eea.rs`). |
| Binary-GCD reduction / dialog pack | Schrottenloher Alg 2; reference impl `ToBitVector` (`gcd.py`) | `gcd_pack.rs`; per-window decompressed hold + once-per-M compress (`gcd_pack.rs`) -- in-repo amortization (see Novel improvements). |
| Window compressor | Schrottenloher Sec 3.1 / Fig 1: the 3-pair->5-bit ad-hoc 5-Toffoli compressor (reference impl `compressor.py`) | `gcd_compress5.rs`: extended to an M=5 in-place radix-3 5-pair->8-bit encoder (8/5 density, -22 peak qubits, `gcd_compress5.rs`), replacing the 3-pair `Compressor` (`gcd_compress.rs`) -- in-repo (see Novel improvements). |
| Top-k comparator | Schrottenloher Sec 4 `clt_uint` (top-k controlled-LT); the `compare_geq_theorem3` core attributed in-code to Vandaele 2026 (arXiv:2603.12917) | `msb_compare.rs`: strict top-k less-than; GCD uses the Gidney measure-uncompute comparator (`controlled_lt_msbs_gidney`), n Toffoli vs 2n (`gcd_pack.rs`). |
| Controlled register adder (GCD csub, squares) | CDKM ripple-carry adder (Cuccaro-Draper-Kutin-Moulton, arXiv:quant-ph/0410184, `cuccaro.rs`; Schrottenloher ref [5]); Gidney measure-and-fixup (Quantum 2, 74, 2018; `gidney1709.pdf`; Schrottenloher ref [7]) | `gidney_const_adder.rs` `controlled_hybrid_add`: threaded carries with the first `vents` carry-uncomputes replaced by Gidney AND-erasure; Toffoli = 3n-2-vents (the parametrization is in-repo). |
| Pseudo-Mersenne modular reduction | Schrottenloher Sec 4 Alg 5-11 (`q = 2^256 - (2^32+977)`) | `pm_prims.rs`: mod-double = 1 shift + one ~bitlen(f) constant add; mod-add/sub Alg 10/11; borrowed-dirty constant adder borrows the register's own idle high bits as carry scratch (`pm_prims.rs`). |
| Constant adder (the +f reduction) | Gidney 2025 classical-quantum constant adder, arXiv:2507.23079 (`gidney_const_adder.rs`) | ported via the multi-term ghost-discharge API (n-1 borrowed dirty bits, O(1) clean ancillae, `gidney_const_adder.rs`). |
| Mod-square-sub / mod-neg (Alg 1 lines 10, 12) | Schrottenloher reference impl `ControlledSpecialPrimeModularSquareAdd` (`special_mod_arithmetic.py`), per Schrottenloher Sec 4 | `pm_prims.rs`: Horner MSB-first composing `mod_double_pm` + `controlled_mod_add_pm`, ~2x mod_mul cost; the square gets full venting (`pm_prims.rs`). |
| Uncomputation | Gidney, "Verifying Measurement Based Uncomputation" (algassert.com/post/1903, 2019; Google whitepaper ref [324], `cryp_paper.txt`) + Gidney 2018 (ref [329]) | HMR + phase-correction ghost API (`khattar_gidney.rs`); reverse-GCD restores `x` reversibly rather than Bennett-doubling the whole multiply. |

---

## 2. low-tof -- Schrottenloher EEA dialog, `dialog_m=3` + coupled venting

Same Schrottenloher dialog as config 1, operated at Google's `Clow-gate` point
(1425q / 2.1M Toffoli) -- and below it on both axes.

### (a)-(b) What it computes / inversion algorithm

Identical algorithm and code path to config 1 (Alg 1 point-add, three-phase EEA
dialog inversion), through the parameterized entry
`ec_add_inplace_schrottenloher_secp256k1_m(..., dialog_m = 3, vents = 222)`
(`emit_..._lowtof.rs`; `pointadd.rs`). Only two knobs change:
the dialog window packing and the apply_bv-peak venting.

### (c) Cost and where the peak lives

1416 qubits / ~2.030M Toffoli (`emit_..._lowtof.rs`;
`gen_and_validate_kmx.sh`; the in-source test asserts `run_random_pairs(3, 222,
1420)`, `pointadd.rs`), below Google's `Clow-gate` 1425q/2.1M on both
axes. The trade vs config 1 is the canonical qubit<->Toffoli exchange: +~240 qubits
buys ~-450k Toffoli (`circuit_gen/notes/quantum_resource_metrics.md`).

The peak is still `apply_bv`, but the venting pool is now spent at that peak,
raising it by roughly the vent budget. The pool is reused across ops, so the peak
grows by `vents`, not per op (`pointadd.rs`). Because the +f reduction
venting materializes the ~63-bit constant, the peak rises ~122 rather than ~90
(`pointadd.rs`).

### (d) The deltas vs config 1

Everything in Sec 1(d) applies; two knobs change:

1. `dialog_m = 3` Fig.1 pack (`gcd_pack.rs`). The M=3 compressor
   maps three `(b0, b0&b1)` pairs (6 bits) -> 5 packed bits + 1 reusable zero with
   ~5 Toffoli and no scratch -- Schrottenloher's Fig 1 compressor (an ad-hoc in-place
   5-Toffoli circuit, SAT-synthesized in the reference impl, `compressor.py`),
   replicated gate-for-gate (`gcd_compress.rs`, port of `compressor.py`). M=3 gives
   5/3 = 1.667 density vs M=5's base-3 8/5. The emit-bin header describes it as "a
   cheap tape shrink 810->675 freeing ~132 qubits" (`emit_..._lowtof.rs`):
   dropping the heavier base-3 arithmetic encoder (~316 Toffoli/window,
   `gcd_pack.rs`) is itself a Toffoli win, paid for in tape width.
2. Coupled apply_bv-peak venting, `vents = 222` (`emit_..._lowtof.rs`). The
   shared measurement-vent pool is spent at the `apply_bv` peak, turning the ~2n
   controlled register adds and the materialized ~63-bit +f reductions from
   Cuccaro 3n into Gidney measure-and-fixup 2n adders (each vent -1 Toffoli / +1
   peak qubit; `pointadd.rs`, `pm_prims.rs`). Config 1 uses
   this Gidney mechanism (`gidney1709.pdf` Fig 3) only in the headroom-rich
   GCD/square; here it is pushed onto the binding apply_bv phase, trading qubits
   for -2.1M->2.03M Toffoli. The coupling of the register-add vents to the
   +f-reduction vents at the binding phase is an in-repo construction (see Novel
   improvements).

`circuit_gen/notes/schrottenloher_status.md` records that the exact, failure-neutral
Toffoli levers are exhausted at ~2.28M for M=5; further reduction requires either
the qubit budget (wider window / venting) or relaxing the 99% / 9000-point
reliability target. This config takes the former.

---

## 2.5 jump-lowqubit / jump-lowtof -- jump-GCD dialog

Basis: the same Schrottenloher dialog as Sec 1/Sec 2 (Alg 1 point-add + Alg 3 `apply_bv`
Bezout reconstruction), with the binary-GCD inner loop replaced by a Stein-style
"jump" GCD (`gcd_jump.rs`, `jump_schedule.rs`; entry points
`ec_add_inplace_schrottenloher_jump_cfg` / `_jump_lowtof_secp256k1` in
`pointadd.rs`). These are the same two operating points as low-qubit / low-tof,
reached with a cheaper inversion.

### (a) What it computes

Identical in-place affine `P += Q` and identical `apply_bv` reconstruction; only
the forward GCD pack and the per-step dialog symbol change.

### (b) The jump-GCD

The divstep dialog (Sec 1) removes exactly one factor of 2 from `v` per step. The
jump-GCD removes up to `jump` trailing zeros at once (`jump = 2` here), so each
step makes more progress and the GCD converges in fewer steps
(`gcd_jump.rs`). Fewer steps means the per-step adders -- the GCD
subtract/swap and the `apply_bv` controlled mod-add -- fire fewer times, which is
the Toffoli saving. The cost is one extra field per step: the dialog symbol is
`(b0 = subtract, b0&b1 = swap, j = trailing zeros removed, 1..=jump)` rather than
`(b0, b0&b1)`. At `jump = 1` it reproduces the divstep dialog exactly.

Packing keeps that extra field affordable relative to the step reduction. The
symbol is a base-5 digit (the five valid `(subtract, swap, s2)` combinations), and
three successive windows pack into a 7-bit code (`5^3 = 125 < 128`). The packer
(`compress_3sym_qrom_refs`, `gcd_compress_jump.rs`) builds the radix-5 value
`d0 + 5*d1 + 25*d2` into a 7-bit accumulator with controlled constant-adds (the
`*5`/`*25`, `controlled_add_const_gidney`), then clears the nine symbol bits by
measurement-based uncomputation: each is HMR'd and its phase corrected through a
unary-tree QROM keyed on the code (`discharge_codes`). At ~147 Toffoli/window to
pack and ~224 to unpack (`qrom_compress_roundtrip`), the recorded transcript
(7 bits / 3 symbols) stays well under what the jump's step reduction buys back.

### (c) Cost

- jump-lowqubit (`emit_test_ec_add_schrottenloher_jump`): 1169 qubits / ~2.09M
  Toffoli, validated at 1175q / 2.1M tof / 13M ops (`gen_and_validate_kmx.sh`).
  This single config sits under Google's `Clow-qubit` (1175q / 2.7M) on both axes
  and under `Clow-gate`'s 2.1M-Toffoli bound as well.
- jump-lowtof (`emit_test_ec_add_schrottenloher_jump_lowtof`): 1412 qubits /
  ~1.90M Toffoli, validated at 1420q / 1.95M tof / 14M ops. Same coupled
  `apply_bv`-peak venting as low-tof (Sec 2(d)); under `Clow-gate` (1425q / 2.1M) on
  both axes, and below the M=3 low-tof (1416q / 2.03M) on both.

The peak structure is unchanged from Sec 1/Sec 2 (the peak is `apply_bv`); the jump-GCD
changes the GCD/reconstruction step counts, not the register layout.

### (d) Prior art

The jump rule is Stein's binary GCD (J. Stein, 1967) applied to the Schrottenloher
dialog framework (arXiv:2606.02235); the dialog encode/reconstruct and the venting
knob are the Sec 1/Sec 2 machinery. The base-5 window codec is in-repo.

---

## 3. shrunken-PZ -- reversible Proos-Zalka divstep inversion

Basis: Proos & Zalka, "Shor's discrete logarithm quantum algorithm for elliptic
curves" (2003, arXiv:quant-ph/0301141, `papers/proos_zalka_2003.pdf`), Section 5
("The Extended Euclidean Algorithm"). "PZ" = Proos-Zalka. PZ Sec 5 computes `x^-1
mod p` as a reversible extended-Euclidean / divstep: maintain two Euclidean pairs
`(a,A),(b,B)` initialized `(0,p),(1,x)`, replace the larger pair by `(a-qb,
A-qB)` with `q=floor(A/B)`, and record only the coefficient of `x` (so the surviving
`a` is `x^-1`). PZ Sec 5.3.1 realizes each iteration as a flag-gated state machine;
Sec 5.3.2 computes the quotient by base-2 long division (fewer subtractions for
small `q`) and runs the cofactor multiply as that same long division backwards.
The in-repo design driving this is `pz_big_step` (`circuit_gen/scripts/kaliski_test.py`,
a reference simulator) -- a repo design artifact, not prior art; the prior-art
basis is Proos-Zalka.

It targets the same Google q/tof envelope but lands far higher on Toffoli -- the
qubit-minimal, Toffoli-expensive corner.

### (a) What it computes

In-place affine `P += Q` (`point_add.rs`, `ec_add_inplace_shrunken_pz`).
`tx/ty` are 256-bit value registers padded to 257-bit work registers (the divstep
needs a sign bit, `point_add.rs`). Unlike the Schrottenloher family, it
materializes the slope `lambda` explicitly in seven phases
(`point_add.rs`):

- Phase 1-2: `ty := dy = oy - ty`, `tx := dx = ox - tx`.
- Phase 3: `lambda = dy/dx` with `dx, dy` preserved (`shrunken_pz_divide_forward`,
  `point_add.rs`).
- Phase 4-5: `tx := new_x = lambda^2 - tx_orig - ox` (`mod_mac_inplace`, exact
  mod-p multiply-accumulate, `point_add.rs`).
- Phase 6: `ty := new_y = dy + lambda*(tx_orig - new_x) - oy`
  (`point_add.rs`).
- Phase 7: cancel `lambda` via the alt-witness `lambda = new_dy/new_dx`
  (`shrunken_pz_divide_cancel`, `point_add.rs`), then restore `new_x/new_y`.

This realizes the Roetteler slope-invariance structure
(`(y1-y2)/(x1-x2) = -(y3+y2)/(x3-x2)`, arXiv:1706.06752 Alg 1 / Remark 1) with two
inversions per add, where Roetteler uses four; the two-inversion group shift is
also Proos-Zalka Sec 4.3.1.

### (b) The inversion algorithm

The inversion is a reversible bit-by-bit pipelined divstep state machine
(`shrunken_pz_state_machine/mod.rs`), the quantum realization of the
Proos-Zalka extended-Euclidean inversion (PZ Sec 5). The flag-gated cycle is PZ
Sec 5.3.1; the bit-by-bit long-division quotient (fast for small `q`) is PZ Sec 5.3.2.
The in-repo design `pz_big_step` (`circuit_gen/scripts/kaliski_test.py`) normalizes
`x -> min(x, P-x)` via a sign bit, then runs divstep on `(A,B) = (P,x)` with
cofactors `(a,b) = (0,1)`:

- DIVISION substep: `s = bitlen(A) - bitlen(B)`; align `B << s`; if `A >= B` then
  `A -= B`, set quotient bit `q_div ^= 1<<s`; restore `B >> s`. `A < B`
  deactivates division. (PZ Sec 5.3.2 long division.)
- MULTIPLY substep (pipelined): `s = ctz(q_mul)`; clear it; `a += b<<s`; restore.
  When `q_mul == 0`: swap `a,b`, flip parity, deactivate multiply. (PZ Sec 5.3.2: the
  cofactor multiply is the division run backwards.)
- TRANSITION: `q_div -> q_mul`, swap `A,B`.

All shifts are `controlled_cyclic_rotate` (rotate-in-place at fixed width). The
whole inversion is built from one primitive -- restoring long division -- used
forward on the GCD pair and in reverse as the consuming cofactor multiply `|a| +=
q|b|` (`shrunken_pz_primitives.rs`); this self-inverse decomposition is
Proos-Zalka Sec 5.3.2. The single `q_0 == 1` degeneracy per inversion is routed by a
1-bit decrement tape (`shrunken_pz_primitives.rs`), an in-repo routing
(loosely analogous to PZ Sec 5.3.4's one bit of `x^-1-p` garbage).

`bitlen` is computed by the streaming prefix-AND ladder of Khattar-Gidney
(arXiv:2407.17966, conditionally-clean log\*-ancilla prefix-AND), on top of which
sits a gray-code bit-length deposit (`mod.rs`), ~2n Toffoli with no
per-row position-equality scan (the gray-code deposit is in-repo; see Novel
improvements).

The per-step register widths follow a fixed precomputed schedule
(`shrunken_pz_schedule.rs`, generated): `SHRUNKEN_PZ_NSTEPS = 530`, with per-step
`A/B/ca/cb/q` widths bounded over 120,000,000 samples
(`shrunken_pz_schedule.rs`). The registers shrink as the GCD pair shrinks,
then regrow on the backward pass. This is the engineering analogue of the PZ
Sec 5.3.5 / Sec 5.4.3 register-sharing and size-perturbation analysis, here as a hard
precomputed width schedule rather than a `2 sqrt(n)` margin.

The forward divide (`shrunken_pz_divide_forward`, `mod.rs`):

- sign-adjust `dx -> |dx|`; set up `S_0` (`B=|dx|, A=p, cb=1, parity=1`);
- run the forward divstep to get `1/|dx|` in `cb`;
- tear down the converged constant registers (`A=0, B=1, ca=p, q=0`) so only `cb`
  is live during the multiply (~258 qubits saved at peak, `mod.rs`);
- compute `lambda = dy * cb`, parity/sign corrected (`mod.rs`);
- HMR-ghost `dy` to free 256 qubits so the reverse runs `dy`-free
  (`mod.rs`);
- reverse-invert to restore `dx`; reconstruct `dy = lambda*dx` and resolve the
  ghosts (`mod.rs`).

The cancel direction (`shrunken_pz_divide_cancel`, `mod.rs`) mirrors this
but ghosts `lambda` instead, clearing it after the coordinates are built.

### (c) Cost and where the peak lives

1050 qubits / ~32.3M Toffoli / ~100M ops (~1.4 GB `.kmx`)
(`gen_and_validate_kmx.sh`; validates under the script's 1060q / 50M tof / 140M
ops caps -- the circuit's ~100M ops fit under both that 140M cap and the larger
build-time op buffer raised for serialization, `CIRC_OPS_CAP=150000000`); the
emit bin sets a construction peak ceiling
of 1300 (`emit_..._shrunken_pz.rs`).

The peak sits inside the divstep, in the `clz`/`bit_length` section of
`shrunken_pz_divide_forward`, where the running diff register `pa` is the binding
live register (`mod.rs`). The divide peak is `EEA-peak + 256`:
exactly one 256-bit passenger (`dy` forward, `new_dy` in cancel) rides through
the inversion while the other coordinate is ghosted (`mod.rs`).
The schedule note records a state-register peak `A+B+ca+cb+q = 741 at step 348`
(`shrunken_pz_schedule.rs`); the EC-add peak is that plus the live coordinate
passengers and the constant `p`.

It spends ~13-17x the Toffoli of the Schrottenloher configs to reach 1050
qubits. Almost all EC-add cost is the inversion, and a reversible divstep with an
explicit Bennett-style reverse (two passes per inversion) is inherently
Toffoli-heavy relative to Google's MBU-folded design. The reciprocal is the qubit
saving (`circuit_gen/notes/quantum_resource_metrics.md`).

### (d) Component citations and the deltas layered on top

| component | prior-work basis | this implementation's delta |
|---|---|---|
| Inversion algorithm | Proos-Zalka 2003 Sec 5 reversible extended-Euclidean / divstep inversion (`proos_zalka_2003.pdf`); flag-gated cycle = Sec 5.3.1; long-division quotient = Sec 5.3.2. In-repo design `pz_big_step` (`circuit_gen/scripts/kaliski_test.py`, not prior art). | pipelined divstep state machine with counter-free intrinsic termination -- division builds the next quotient while the multiply drains the previous (`mod.rs`) -- in-repo (PZ Sec 5.3.4 uses an explicit completion counter; see Novel improvements). |
| Core divstep primitive | Proos-Zalka Sec 5.3.2: the cofactor multiply `a,b,q |-> a-qb,b` is the long division run backwards. | `shrunken_pz_primitives.rs`: one primitive, `long_division` forward = GCD reduce, `long_division_reverse` = consuming cofactor multiply; self-inverse, no spooky pebbling. |
| `bitlen` / clz | Khattar-Gidney conditionally-clean log\*-ancilla streaming prefix-AND (arXiv:2407.17966, Sec 6.1) | `mod.rs`: prefix-AND ladder + gray-code bit-length deposit, ~2n Toffoli, no per-row position-equality scan -- the gray-code deposit is in-repo (see Novel improvements). |
| Cofactor degeneracy routing | in-repo EEA invariant; cf. PZ Sec 5.3.4 one-bit `x^-1-p` garbage | `shrunken_pz_primitives.rs`: 1-bit decrement tape for the single `q_0==1` step -- in-repo (see Novel improvements). |
| Register adders | CDKM ripple-carry adder (Cuccaro et al., arXiv:quant-ph/0410184, `cuccaro.rs`) | `controlled_add_cuccaro_3n_refs` (`shrunken_pz_primitives.rs`); O(1)-ancilla keeps the divstep polylog-ancilla. |
| Comparators | `compare_geq_theorem3` core attributed in-code to Vandaele 2026 (arXiv:2603.12917); Khattar-Gidney Sec 6.3 `LessThanConst` is a distinct equivalent | borrow-ripple `compare_geq_const` with 1 dirty ancilla (`compare.rs`); used as the compute/use/uncompute `(A < B<<s)` offset (`mod.rs`). |
| Modular reduction / mod_mul (lambda build) | in-repo rfold-MBU pseudo-Mersenne reduce (`q = 2^256 - (2^32+977)`, `point_add.rs`) | `mod_mul_rfold_mbu` for `lambda = dy*cb` and the dy/dx reconstruct (`mod.rs`); `mod_mac_inplace`/`mod_msc_inplace` Horner MAC (`point_add.rs`). |
| Uncomputation | Gidney measurement-based uncomputation (algassert.com/post/1903, 2019) + Bennett reverse (Bennett, SIAM J. Comput. 18(4), 1989); spooky-pebble game = Kornerup-Sadun-Soloveichik (arXiv:2110.08973) | `mod.rs`: HMR-ghost the non-witness coordinate (`hmr_ghost`/`resolve_ghost`, `mod.rs`) so `dy` and `lambda` are never both live -> peak = EEA-peak + 256, plus a Bennett reverse-invert to restore `dx`; no windowed spooky-Kaliski pebbling -- the single-passenger ghost application is in-repo (see Novel improvements). |

---

## Cross-config summary

All five compute the same affine secp256k1 `P += Q` and validate through the
native zkp_ecc Simulator (the SP1 guest's) over 9000 Fiat-Shamir shots under
explicit q/Toffoli/op caps (`gen_and_validate_kmx.sh`). They differ only in
the inversion engine and its point on the qubit<->Toffoli exchange curve:

- low-qubit and low-tof are the same Schrottenloher EEA-dialog inversion
  (arXiv:2606.02235, ported from Schrottenloher's reference code, replicating
  Google `Clow-qubit`/`Clow-gate`, `cryp_paper.txt`); low-tof spends
  ~+240 qubits (wider/cheaper M=3 tape + apply_bv venting) to drop ~450k Toffoli.
- jump-lowqubit and jump-lowtof (Sec 2.5) run the same dialog over a Stein-style
  jump-GCD (jump=2, base-5 packed); the fewer GCD/reconstruct steps cut Toffoli
  at the same two operating points, putting jump-lowqubit (1169q / 2.09M) under
  both Google points at once.
- shrunken-PZ is a different family: a reversible Proos-Zalka divstep state
  machine (Proos & Zalka 2003, `proos_zalka_2003.pdf`; design `pz_big_step`),
  reaching 1050 qubits for ~32.3M Toffoli -- the qubit-minimal, Toffoli-maximal
  corner.

Prior art shared across all five: CDKM/Cuccaro adders (arXiv:quant-ph/0410184),
Gidney measure-and-fixup uncomputation (Quantum 2, 74, 2018; algassert.com/post/1903),
Gidney 2025 constant adder (arXiv:2507.23079, Schrottenloher configs),
Khattar-Gidney prefix-AND/MCX (arXiv:2407.17966), and the Google ECC whitepaper as
the cost target (`papers/cryp_paper.txt`).

---

## Novel improvements

Each technique below layers on cited prior art; the listed delta is the part that
originates in this repo rather than in a published source. Two of the seven (item
3, and the termination half of item 4) are thin specializations of
explicitly-published tradeoffs. The reference point for items 1-3 is
Schrottenloher's `qarton` library: its compressor is hard-coded to M=3 (a
SAT-synthesized 6-bit -> 5-bit map, `compressor.py`) with no parametric-M or
base-3 packing; it decompresses and recompresses the window every iteration rather
than holding it (`compressor.py`); and its adder vent budget is
register-only, leaving the +f reduction a fixed, uncoupled primitive
(`special_mod_arithmetic.py`). Items 1 and 3 add what that reference lacks;
item 2 narrows to the in-repo buffer below.

1. **M=5 base-3 5-pair -> 8-bit radix-3 dialog compressor** (`gcd_compress5.rs`).
   Schrottenloher Sec 3.1 / Fig 1 defines only the 3-pair -> 5-bit ad-hoc compressor
   (density 5/3); its cited compressor sources (CFS eprint 2026/280, DQI 2510.10967)
   carry no base-3 packing either. The 5-pair generalization, its 8/5 = 1.600
   density, and the -22 peak-qubit reduction are in-repo
   (`circuit_gen/notes/schrottenloher_status.md`): a clean M=3->M=5 generalization with a
   new in-place radix-merge encoder, where the reference compressor is hard-coded to
   M=3 (a SAT-synthesized 6-bit -> 5-bit map, `compressor.py`). Builds on:
   Schrottenloher's 3-pair compressor.

2. **Once-per-window decompressed-hold buffer** (`gcd_pack.rs`). The
   per-window compress cadence is intrinsic to Schrottenloher's windowed compressor
   (Sec 3.1 fires once per M-iteration window by construction), so it is not itself
   new. The in-repo part is narrower: the explicit decompressed-slot hold-and-swap
   buffer that feeds the M=5 encoder. An implementation specialization, not a
   separate algorithm. Builds on: Schrottenloher Sec 3.1 / Alg 2.

3. **Lockstep vent-budget coupling at the apply_bv peak** (`pm_prims.rs`,
   `pointadd.rs`; low-tof). Schrottenloher Sec 3.2 already describes spending
   extra ancillas at the Bezout reconstruction to swap Cuccaro-3n adders for
   Gidney-2n, trading qubits for Toffoli, and names this as the low-qubit/low-gate
   config split (he attributes the same split to Babbush et al.'s two variants). The
   published tradeoff is the basis. The only in-repo part is the lockstep coupling:
   one shared `vents` budget threaded across both the register add and the
   materialized +f pseudo-Mersenne reduction in a single call. Builds on:
   Schrottenloher Sec 3.2; Gidney 2018 measure-and-fixup (`gidney1709.pdf`).

4. **Pipelined two-quotient-stream divstep** (`mod.rs`). Two parts. (i)
   Counter-free, state-flag-gated termination improves on Proos-Zalka Sec 5.3.4 (which
   uses an explicit completion counter and accumulates "quantum-halting" garbage),
   but this is *not* unique: Luo et al. (arXiv:2604.02311) already terminates on a
   length-register state (`lr'=0`) over a fixed step bound rather than a halting
   counter. (ii) The pipelined interleaving -- division builds the next quotient
   while the multiply drains the previous -- is in neither PZ (four phases run
   sequentially per iteration) nor Luo (per-iteration cofactor update), and is the
   in-repo contribution. Builds on: Proos-Zalka Sec 5; cf. Luo et al. for the
   termination.

5. **Gray-code bit-length deposit on the Khattar-Gidney prefix-AND** (`mod.rs`).
   The running-flag bit-length scan itself is prior art (Proos-Zalka Sec 5.3.2; Luo et
   al. Fig 9 length-update). The in-repo delta is the gray-code `(k^(k+1))`
   telescoping deposit gated on the KG conditionally-clean prefix flag, which removes
   the per-row position-equality scan (~2n Toffoli). The prefix-AND ladder is genuine
   Khattar-Gidney (arXiv:2407.17966). A circuit-engineering optimization of
   leading-zero count, not a new capability.

6. **Single-passenger HMR-ghost** (`hmr_ghost`/`resolve_ghost`, `mod.rs`). The
   measure-defer-discharge mechanism is the spooky-pebble game
   (Kornerup-Sadun-Soloveichik, arXiv:2110.08973) / Gidney MBU (algassert.com/post/1903)
   -- the basis, correctly cited. The in-repo part is the application: ghosting a
   whole 256-bit EC coordinate for the duration of the reversible inversion so `dy`
   and `lambda` never co-reside (peak = EEA-peak + 256). The MBU literature stays at
   single-qubit granularity (arXiv:2407.20167); whole-register ghosting in an EC
   inversion is the delta.

7. **1-bit decrement-tape routing of the `q_0==1` cofactor degeneracy**
   (`shrunken_pz_primitives.rs`). Proos-Zalka's one-bit garbage is Sec 5.3.4 (the
   result-sign bit, x^-1 vs x^-1-p), a different bit than the repo's per-step
   `q_0==1` quotient-degeneracy flag. Threading a retained 1-bit-per-step flag
   through a reversible divstep is itself standard in this lineage (PZ's flag-gated
   cycle; Luo's `Sign`/`Phase` bits). The in-repo part is the specific
   `eq=(grow_old==base)` subtract / long-division-reverse / add routing for the
   single `q_0==1` step. A narrow specialization.

Net: items 1, 4(ii), 5, and 6 carry a genuine in-repo kernel (the M=5
generalization; the cross-iteration quotient pipelining; the gray-code deposit; the
whole-coordinate ghost). Items 2, 3, and 7 are specializations of published
techniques. Also not separate novelties -- the `3n-2-vents` adder parametrization,
the borrowed-dirty own-idle-bits scratch, the multi-term ghost-discharge API, and
the per-window register-shrinking schedule. The 2-divisions-vs-4 lambda-cancel advantage
is a published structural fact (Roetteler; Proos-Zalka Sec 4.3.1), not a repo
invention -- only its in-place EC-add wiring (`point_add.rs`) is the repo's.
