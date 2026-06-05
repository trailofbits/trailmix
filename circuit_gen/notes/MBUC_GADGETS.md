# MBUC gadgets — phase correction for arbitrary boolean ancillae

Practical catalog of **measurement-based uncomputation** patterns: how to
free an ancilla holding `c = f(k)` for any boolean `f` of the data register
`k`.

## 1. The fundamental identity (Google 2025 §4, corrected)

State before measurement:
    |ψ⟩ = Σ_k α_k |k⟩ |f(k)⟩.

X-basis measurement (HMR) of the `f(k)` qubit gives a uniformly random
classical bit `b ∈ {0, 1}` and projects:

    b = 0 (|+⟩ outcome):
        |ψ⟩ → Σ_k α_k |k⟩
        Clean disentanglement. NO phase correction needed.

    b = 1 (|-⟩ outcome):
        |ψ⟩ → Σ_k α_k (-1)^f(k) |k⟩
        Ancilla erased BUT a phase kickback — every basis state |k⟩
        with f(k) = 1 has its amplitude negated.

**Repair**: in the `b = 1` branch, apply a quantum operation that
multiplies every |k⟩ by `(-1)^f(k)` again. Two minus signs cancel.

In code that operation is *any* diagonal unitary
    P_f := diag((-1)^f(k))   over the data register
that we apply *conditional on `b = 1`*. Concretely:

```rust
// ancilla c was deterministically c = f(k_qubits)
let bit = circ.alloc_bit();
circ.hmr(c, bit);              // measures c, frees its qubit slot
circ.free_qubit(c);
circ.push_condition(bit);      // gates everything until pop
apply_phase_oracle(&mut circ, &k_qubits, &f_anf);
circ.pop_condition();
```

Where `apply_phase_oracle(... , f_anf)` emits the gates implementing
`P_f`, and `f_anf` is the description of `f` (see §3).

## 2. Why the phase correction is often cheap

Quoting Google 2025 (and references [328] table-lookup, [329]
temporary-AND): the phase correction "is usually slightly smaller
[329], and sometimes much smaller [328], than the cost of computing
f(k)". Two reasons:

1. **Diagonal-only**: the correction emits no Toffolis if `f` is at
   most quadratic (only Z and CZ are needed). It emits Toffoli-like
   CCZ only for cubic ANF terms, etc. Typical comparators have many
   linear and quadratic terms but few high-degree ones.
2. **Doesn't need clean ancillae**: the phase oracle can leave any
   workspace it allocates "dirty" — it only cares about adding the
   right phase, not about preserving qubits afterward. A sub-ancilla
   computed for the correction can itself be MBU-freed (recursive),
   yielding nested conditions.

## 3. Encoding `f` as ANF (algebraic normal form)

Every boolean function over n bits has a unique multilinear polynomial
representation over GF(2):

    f(x_1, ..., x_n) = c_0 ⊕ Σ_{S ⊆ {1..n}, |S|>0} c_S · ∏_{i ∈ S} x_i

where each c_S ∈ {0, 1}. The *constant* term `c_0` corresponds to a
global phase flip (apply `NEG` once if c_0 = 1). Each non-zero
*non-constant* term corresponds to a multi-Z gate spanning the
qubits of S:

| `|S|` | Gate                  | Op-count |
|-------|-----------------------|----------|
|  0    | `NEG` (only if c_0=1) | 1        |
|  1    | `Z(x_i)`              | 1        |
|  2    | `CZ(x_i, x_j)`        | 1        |
|  3    | `CCZ(x_i, x_j, x_k)`  | 1        |
|  ≥4   | C^{|S|-1}Z synthesis  | several  |

All emitted under a single `push_condition(bit) ... pop_condition()`
block, which adds 2 ops total regardless of how many terms there are.

So **the ANF of `f` directly tells you the phase-correction circuit**.

## 4. Gadget catalog (basic boolean ops on 2-3 inputs)

In all cases the ancilla `c = f(...)` is HMR'd into classical `bit`,
qubit freed, then the listed corrections fire under
`push_condition(bit)` / `pop_condition()`. Op-count includes the HMR,
the push/pop, and each gate.

| `f`                | ANF                       | Correction gates                       | Total ops |
|--------------------|---------------------------|----------------------------------------|-----------|
| `AND(a, b)`        | `a·b`                     | `CZ(a, b)`                             | 4         |
| `XOR(a, b)`        | `a + b`                   | `Z(a); Z(b)`                           | 5         |
| `OR(a, b)`         | `a + b + a·b`             | `Z(a); Z(b); CZ(a, b)`                 | 6         |
| `NAND(a, b)`       | `1 + a·b`                 | `NEG; CZ(a, b)`                        | 5         |
| `NOR(a, b)`        | `1 + a + b + a·b`         | `NEG; Z(a); Z(b); CZ(a, b)`            | 7         |
| `IMPLIES(a → b)`   | `1 + a + a·b`             | `NEG; Z(a); CZ(a, b)`                  | 6         |
| `MAJ(a, b, c)`     | `a·b + a·c + b·c`         | `CZ(a,b); CZ(a,c); CZ(b,c)`            | 6         |
| `MUX(s, x, y)`     | `s·x + (1+s)·y` =         |                                        |           |
|  = `s ? x : y`     | `y + s·x + s·y`           | `Z(y); CZ(s, x); CZ(s, y)`             | 6         |
| `XOR3(a, b, c)`    | `a + b + c`               | `Z(a); Z(b); Z(c)`                     | 6         |
| `AND3(a, b, c)`    | `a·b·c`                   | `CCZ(a, b, c)`                         | 4         |
| `Z=≠(a, b)` (NEQ)  | `a + b`                   | same as XOR                            | 5         |
| `Z=(a, b)`  (EQ)   | `1 + a + b`               | `NEG; Z(a); Z(b)`                      | 6         |

Compare to the cost of *computing* the same `f`:
- `AND(a, b)` forward: `CCX` into ancilla (1 op + maybe T-magic) — MBU
  ties or saves.
- `MAJ(a, b, c)` forward: 1-2 CCX + several CX (3-5 ops) — MBU saves.
- Comparator (next section) forward: O(n) ops — MBU saves a lot.

## 5. Recursive / nested gadgets for compound `f`

When `f(k)` does NOT decompose into a small ANF, two strategies make
the correction cheap by *introducing further MBU layers* inside the
`push_condition(bit)` block.

### 5.1 Decompose-and-recurse

If `f = g XOR h`, the correction is just `Z^g(k) ⨁ Z^h(k)`, both
conditioned on the outer `bit`. Implement each term independently:

```rust
push_condition(outer_bit);
emit_phase_oracle_for(g);   // recurses if g is itself compound
emit_phase_oracle_for(h);
pop_condition();
```

Because `Z^a · Z^b = Z^(a+b)`, and ANF addition IS XOR, this is the
ANF expansion in code form. Same total cost.

### 5.2 Inner ancilla for shared subexpressions

If `g` and `h` both depend on a common subexpression `s(k)`, compute
`s` once into a fresh ancilla `c_s`, use it in both Z's, then MBU-free
`c_s` *under the same outer condition*. The inner MBU's correction is
itself a phase oracle for `s`; if `s` is simpler than `f`, this is
cheaper than expanding `f` flat.

```rust
push_condition(outer_bit);                 // (a)
let c_s = circ.alloc_qubit();              // compute s(k) → c_s
forward_compute_s(&mut circ, &k, c_s);
// Use c_s in two diagonal phases:
emit_phase_for_g_using(c_s, &k);
emit_phase_for_h_using(c_s, &k);
// MBU-free c_s — its phase correction is *also* under outer_bit
let inner_bit = circ.alloc_bit();
circ.hmr(c_s, inner_bit);
circ.free_qubit(c_s);
circ.push_condition(inner_bit);            // NESTED: outer ∧ inner
emit_phase_oracle_for_s(&k);
circ.pop_condition();
circ.pop_condition();                      // closes (a)
```

The inner `push_condition(inner_bit)` is *physically nested* inside
the outer `push_condition(outer_bit)`. The condition stack ANDs them,
so the inner gates only fire when both bits are 1. The classical
post-processing thus computes `outer_bit · inner_bit` for free — which
is exactly the parity required to keep the recursive correction
correct.

### 5.3 Carry-chain example: `f = 1[a >= b]` for n-bit a, b

This is the comparator we care about for `mod_add_mbu`. Direct ANF
of `1[a >= b]` over 2n inputs has O(2^n) terms. Don't write it out.
Instead, use the *ripple structure*: each carry bit `c_i` is a MAJ
of three earlier bits, MAJ has a small ANF (3 quadratic terms), and
MAJ is its own MBU gadget.

For the `add_physical`-style ripple where each step allocates a
fresh `and_q[i] = a_i' ∧ b_i'`:

- Forward: per bit, emit `2 CX (carry XOR into a, b) + CCX (and_q) +
  CX (and_q → carry)` = 4 ops.
- Cleanup (per bit, in reverse): `CX(and_q, carry)` to recover the
  previous carry, then `mbuc_free(and_q, a_i, b_i)` (the AND gadget,
  ≈ HMR + push + CZ + pop = 4 ops), then 2 CX to restore a and b.
  **But all `and_q[i]` corrections are independent, so they share the
  outer `push_condition(bit)` once.** The naive "push/pop per HMR"
  costs `n × 4` per bit; sharing the push/pop costs
  `2 + n × (HMR + CZ) = 2 + 2n` total for the correction layer.

That sharing only works if every per-bit MBU has the same outer bit
to condition on, which is exactly the case when we're cleaning the
*same* compute (not n independent ancillae of n different `f`s).

For the comparator's *outermost* correction (the `temp` qubit holding
`1[a < b]` in `mod_add_mbu` step 5), the natural form is:

```
push_condition(outer_bit_from_HMR_of_temp)
  emit_phase_oracle_for_1_lt(a_qubits, b_qubits)   // see below
pop_condition()
```

And `emit_phase_oracle_for_1_lt` itself uses §5.2 to MBU compute
the comparison's intermediate `and_q[i]` ancillae and apply Z^...
on them — entirely under the outer bit's condition.

## 6. Generic API (proposed)

A single primitive captures the table in §4 and the generic case:

```rust
/// Description of an ANF term: a list of qubits whose product is
/// the monomial. Empty list = constant 1 (NEG).
pub type AnfTerm = Vec<u32>;

/// Apply (-1)^f(k) to the data register, conditional on the
/// classical bit `b`. `f` is given as its ANF (a list of AnfTerm).
pub fn phase_oracle_if_bit(
    circ: &mut Circuit,
    bit: u32,
    f_anf: &[AnfTerm],
) {
    if f_anf.is_empty() { return; }
    circ.push_condition(bit);
    for term in f_anf {
        match term.len() {
            0 => circ.neg(),
            1 => circ.z(term[0]),
            2 => circ.cz(term[0], term[1]),
            3 => circ.ccz(term[0], term[1], term[2]),
            _ => emit_multi_z(circ, term),  // C^{n-1}Z synthesis
        }
    }
    circ.pop_condition();
}

/// MBU-free an ancilla `q` that is known to equal `f(k_qubits)`,
/// where `f`'s ANF over k_qubits is `f_anf`.
pub fn mbuc_free_anf(
    circ: &mut Circuit,
    q: u32,
    f_anf: &[AnfTerm],
) {
    let bit = circ.alloc_bit();
    circ.hmr(q, bit);
    circ.free_qubit(q);
    phase_oracle_if_bit(circ, bit, f_anf);
}
```

The current `mbuc_free(q, cz_a, cz_b)` is the `f = a ∧ b` special
case: `f_anf = vec![vec![cz_a, cz_b]]`.

For convenience, a constructor library:

```rust
pub fn anf_and(a: u32, b: u32) -> Vec<AnfTerm>
    { vec![vec![a, b]] }
pub fn anf_xor(a: u32, b: u32) -> Vec<AnfTerm>
    { vec![vec![a], vec![b]] }
pub fn anf_or(a: u32, b: u32) -> Vec<AnfTerm>
    { vec![vec![a], vec![b], vec![a, b]] }
pub fn anf_maj(a: u32, b: u32, c: u32) -> Vec<AnfTerm>
    { vec![vec![a, b], vec![a, c], vec![b, c]] }
// etc.
```

## 7. When to skip MBU and use reverse arithmetic

MBU (the per-AND `mbuc_free` pattern) is best when:

- The ancilla you want to free is a fresh `c = a ∧ b` (or short ANF)
  written into its own qubit slot, with `a` and `b` still live at
  cleanup time.
- Multiple sibling ancillae share the same outer `bit`, so a single
  `push_condition(bit) ... pop_condition()` block amortizes.

It's a wash or a loss when:

- `f`'s ANF has many terms AND no useful sub-expression sharing.
- The forward computation modified the data register in place (so
  you already need a backward pass to restore it; the ancilla
  cleanup rides along for free).
- Allocating per-bit AND ancillae blows the peak qubit count.

For `compare_geq_physical`'s current in-place pattern, backward UMA
is ~8 ops/bit; converting to AND-ancilla MBU with shared push/pop is
~6-9 ops/bit — borderline. The Toffoli count halves (1 CCX/bit vs 2),
which matters for *Toffoli budgets* (CFS, ZKP non-Clifford counts)
but not for the `total_ops` ceiling, which counts every gate
equally.

## 8. References

- Google Quantum AI 2025 (arXiv:2603.28846) §4 — the kickmix /
  MBUC framework.
- Gidney 2017 (arXiv 1709.06648) — the temporary AND gadget.
- Berry-Gidney-Motta-McClean-Babbush 2019 (arXiv 1902.02134),
  Appendix C — table-lookup MBU showing the correction can be
  much smaller than the forward.
- Luongo et al. (arXiv 2407.20167), Lemma 4.1 — the specific
  reduction-flag identity used in `mod_*_mbu` primitives.
