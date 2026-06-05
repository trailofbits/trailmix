# Schrottenloher EC-add: cost breakdown

The standalone modular inversion (the Schrottenloher EEA dialog at `dialog_m = 5`)
measures **1191 qubits / 2,281,568 Toffoli**, below the paper's 1192q / 2,385,517
on both axes (-1 qubit, -103,949 Toffoli). The full low-qubit EC-add config is
1173q / ~2.484M Toffoli.

## Toffoli progression

The peak is held at 1191 throughout; it is set by the `apply_bv` reconstruction
phase, not the GCD, so the GCD and square have ancilla headroom to spend on
cheaper adders.

| Toffoli | change |
|--:|---|
| 2,755,564 | baseline (matched the paper's qubit count) |
| 2,517,376 | GCD `csub` -> full Gidney hybrid adder (n ancillae free during the GCD) |
| 2,451,840 | square mod-adds -> full Gidney |
| 2,340,928 | GCD comparator -> Gidney measure-and-uncompute |
| 2,327,528 | GCD dialog packing -> per-window compression |
| 2,281,568 | square `+f` -> clean-vent (materialize f + hybrid 2n adder) |

## Per-section profile

- GCD (forward, all four passes): the per-iter `csub` is a Gidney hybrid 2n
  adder, not Cuccaro 3n -- TTK carry-threading with the first `vents` carry
  uncomputes replaced by measure-and-fixup AND erasure (the GCD has free
  ancillae).
- Square (`sqr_sub_pm`): the Horner controlled-adds use the same hybrid adder.
- `apply_bv` (forward + inverse): cswap + Cuccaro 3n controlled adds. This phase
  has no free ancillae, so 3n is correct here -- and it sets the peak.

## Mechanism

`controlled_hybrid_add` (`a += ctrl*b`) and `compare_geq_gidney_middle`
(`a >= b`, n Toffoli vs 2n) use Gidney 2018 measure-and-fixup (gidney1709.pdf
Fig.3): compute the carry ANDs into ancillae, then erase by X-basis measurement
plus a CZ on the alive AND inputs, via the ghost API (`hmr_ghost` +
`ghost_xor_cz` + `close_ghost`, sim-verified). `cz_if_bit` is a `Cz` op (T-count
0), so each measurement-erase removes exactly one Toffoli. The hybrid adder's
Toffoli count is `3n - 2 - vents`: `vents = 0` is TTK 3n, `vents = n-1` is Gidney
2n, and each vent ancilla saves one Toffoli at the cost of one peak qubit.
