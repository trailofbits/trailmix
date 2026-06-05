# trailmix -- Overview

`trailmix` is a self-contained toolchain for synthesizing, simulating,
verifying, debugging, and profiling **reversible quantum circuits** -- built to
drive down the Toffoli x qubit cost of secp256k1 (plus Curve25519 / SM2 /
Brainpool) elliptic-curve point addition against Google's kickmix (kmx) scoring
harness. The toolchain is implemented in-house: the circuit IR, a 64-shot
parallel simulator, an abstract-interpretation phase-correctness gate, a "ghost"
spooky-pebble bookkeeping API, a full time-travel debugger, a per-section
profiler, and schedule-generator binaries (`gen_shrunken_pz_schedule`,
`gen_jump_schedule`).

> This file inventories the runtime (the reusable machinery). The specific
> circuits -- the Schrottenloher GCD-dialog and jump-GCD inversions and the
> shrunken-PZ EC-add -- are catalogued in
> [`kmx_circuit_summaries.md`](../../kmx_circuit_summaries.md). (The secp256k1
> circuits also have a Curve25519 / SM2 / Brainpool port under `src/ec/curves/`.)

---

## Highlights

- **64-shot parallel simulator, built into the builder.** Every qubit is one
  `u64` (one bit per shot); X/CX/CCX/Z/HMR are single bitwise ops across all 64
  shots at once. The HMR RNG is seeded from `thread_rng` once per run (never a
  fixed seed), so every run exercises a different measurement-bit pattern -- and Toffoli are
  counted *per fired shot* (`popcount(fire_mask)`), exactly matching Google's
  "average executed Toffoli" metric. (`circuit.rs` section 'The 64-shot Simulator')

- **The phase-lattice correctness gate** (`src/tracker/phase_lattice.rs`). A per-gate
  abstract interpreter carrying an `AbsVal` per qubit (Zero/One/CopyOf/AndOf/
  XorOf/ChooseOf/Anchor/Top). `prove_zero` is the hard gate before any free;
  `assert_clean` verifies every HMR obligation structurally cancels its
  discharges. The `declare_*` API injects symbolic facts *only after* a concrete
  64-shot sim check, with a version-staleness guard that catches "qubit modified
  between declare and discharge" -- it catches precondition violations the sim
  alone never would.

- **The time-travel debugger** (`src/tracker/debugger/`). A gate-by-gate replay
  engine over the 64-shot sim: full-state checkpoints every 10M ops + a 500K
  per-op `Delta` ring buffer for O(1) backward steps. `attach()` *moves* the
  Circuit's Vecs to avoid a ~5 GiB spike. 20+ REPL commands -- `src <op>` maps any
  op to its emitting `file:line` (auto-captured via `#[track_caller]`, no manual
  tagging), `watch q<N>` + `rb` (run *backward* to the op that broke an
  invariant) is the canonical debugging recipe, plus a three-mode profiler and
  per-command flushing for non-interactive FIFO driving. Auto-attaches on any
  failure under `DEBUG_ON_FAIL=1`.

- **The ghost / spooky-pebble API** (`src/tracker/ghost.rs`). A `#[must_use]` `Ghost`
  handle captures the HMR's 64-shot mask + an anchor; `resolve_ghost`
  sim-verifies the discharge register and emits the cancelling `z_if_bit`.
  Multi-term composite discharge via `ghost_xor_*`/`close_ghost`. A per-circuit
  event log lets the debugger's `gh` command reconstruct pending ghosts at any
  cursor -- the key diagnostic for windowed-tape desync.

- **Move-only qubit ownership + strict-dealloc.** `QReg` is a linear RAII handle
  (no Copy/Clone); drop queues a free that fires at the next gate. A `BTreeSet`
  free-pool hands out the lowest id (dense packing). Every free asserts
  *last-touch > last-alloc* (wasteful-retention) and `prove_zero` (R-on-nonzero),
  so leaks and dirty frees fail loudly at the exact site.

- **The redundant-op elider.** Involutary gate pairs (X-X, CCX-CCX, ...) that touch
  every operand uninterrupted are cancelled automatically -- the prior op becomes
  a tombstone, with full undo machinery so other qubits' retention pointers stay
  correct.

- **Precomputed per-step register-width schedules.** Standalone generator
  binaries (`gen_shrunken_pz_schedule`, `gen_jump_schedule`) Monte-Carlo over
  random secp256k1 inputs and emit per-step register-width bounds (the observed
  per-step extremes over a large sample, no additive margin -- the tail is driven
  down by sample count) as committed `*_schedule.rs` constants. This turns
  worst-case qubit
  sizing (always 257 bits) into tight per-step bounds, the main lever holding the
  divstep / dialog peak down.

- **Inline contracts + generic uncompute + streaming.** `contract_check` /
  `contract_capture`+`pop_and_check` (ghost-aware, 64-shot) for per-shot
  invariants; `emit_reverse_since(mark)` generically uncomputes any gate block
  (with alloc/dealloc id-remapping); `CIRC_OPS_CAP` streaming keeps metrics exact
  on multi-hundred-million-op circuits while bounding memory; an RSS watchdog +
  `RLIMIT_AS` guard make OOM a clean panic with section context.

- **Assertion caps as a design tool.** `CIRC_ASSERT_MAX_QUBIT_PEAK` fires the
  instant live qubits first cross the cap (not at the end), and
  `CIRC_ASSERT_MAX_OPS` prints a top-8 per-section cost breakdown -- both
  drop into the debugger under `DEBUG_ON_FAIL=1`.

---

# Detailed inventory

The sections below are the per-component inventories, citing the relevant files
and symbols.

---

## circuit.rs Runtime Features

Source file:
- `trailmix/src/circuit.rs` (~4800 lines)

---

### The `Circuit` Type and Op Model

#### `Op` enum

`Op` is a compact 16-byte enum (vs 40-50 bytes for `Vec<String>`) covering every
kickmix (kmx) instruction:

| Variant | Meaning |
|---|---|
| `Register(u32)` | Declare an output register |
| `AppendQubit(u32, u32)`, `AppendBit(u32, u32)` | Bind a qubit/bit into an output register |
| `X(u32)`, `Z(u32)` | Pauli X/Z |
| `Cx(u32,u32)`, `Cz(u32,u32)` | Controlled-X / Controlled-Z |
| `Ccx(u32,u32,u32)`, `Ccz(u32,u32,u32)` | Toffoli / doubly-controlled-Z |
| `Swap(u32,u32)` | Physical SWAP |
| `Hmr(u32,u32)` | Hadamard-measure-reset (HMR): `q -> 0`, random bit stored in classical bit |
| `R(u32)` | Reset: asserts qubit is |0>, deallocates it |
| `Neg` | Global phase flip |
| `PushCondition(u32)`, `PopCondition` | Gate a block of ops on a classical bit |
| `BitInvert(u32)`, `BitStore0(u32)`, `BitStore1(u32)` | Classical bit ops |

`Op::kmx_string()` renders any op as one line of kmx text.
`Op::touched_qubits()` is a zero-allocation iterator over operands,
used by the strict-dealloc and redundant-op machinery.

#### Type-safe wrappers

- **`Qubit(u32)`** -- module-private; never escapes `circuit.rs`.
- **`Cbit(pub u32)`** -- public classical-bit handle.
- **`CReg = [Cbit]`** -- slice alias for classical registers.
- **`QReg`** -- owning single-qubit handle. NOT `Copy`/`Clone` (linear
  type). When dropped, it queues its qubit id onto `Circuit::pending_frees` via
  an `Rc<RefCell<Vec<u32>>>` shared with the circuit; the free fires at the NEXT
  gate emission (or explicit `flush_pending_frees`). The raw `u32` qubit id is
  a private field -- no external code can construct or read it.
- **`SharedQReg`** -- `Rc<QReg>` for state-machine storage trees
  that need shared ownership without lifetime parameters. Drop is deferred until
  the last clone drops.
- **`BorrowedQReg<'a>`** -- `Owned(QReg) | Borrowed(&'a QReg)`:
  lets a single function signature serve both consuming and non-consuming callers.

The `Circuit.ops: Vec<Option<Op>>` buffer uses `None` slots as
tombstones left by the redundant-op eliminator. Absolute op indices remain
stable across elisions.

---

### Qubit Allocator

#### Allocation

`alloc_qubit(name)`:
1. Drains `pending_frees` first (so any QReg-drop fires BEFORE the new alloc
   advances `last_alloc_op_idx`).
2. Pops from `free_qubits: BTreeSet<u32>` (lowest id first, dense reuse) or
   increments `next_qubit`.
3. Zeroes the sim slot and records a `QubitAllocEvent` in `qubit_alloc_log`.
4. Resets `last_touched_op[q]` to `None` (untouched-alloc panic if freed
   without a gate touch).
5. Updates `last_alloc_op_idx` (the retention-check cutoff).
6. Fires `maybe_assert_max_qubit_peak` immediately if the new live count exceeds
   the cap.

Public surface (all backed by `alloc_qubit`):
- `alloc_qreg(name) -> QReg`
- `alloc_qreg_bits(name, n) -> Vec<QReg>`
- `alloc_shared_qreg(name) -> SharedQReg`
- `alloc_input_qreg[_bits]` variants -- also mark the
  qubit/bit as a fresh F2 atom in the phase tracker.
- `alloc_input_qreg_bits_with_lanes(name, n, lanes)` -- atomically
  allocates + loads 64-shot lane values; the ONLY clean init-time API.
- `alloc_qubit_fresh(name)` -- skips the free-pool (for registers
  that must not alias previously-freed state).

#### Deallocation and strict-dealloc check

`free_qubit(q)`:
1. Double-free guard.
2. **Wasteful-retention check**: panics if `last_touched_op[q] < last_alloc_op_idx`
   (the qubit was idle across a newer allocation -- it should have been freed
   earlier to let the allocator reuse its slot).
3. **`prove_zero_raw(q)`**: asserts the qubit reads |0> on all 64 sim shots
   (R-on-nonzero panic under `DEBUG_ON_FAIL` attaches the debugger).
4. Inserts `q` back into `free_qubits`.

`zero_and_free(q: QReg)` -- the public API: calls `prove_zero_raw`
then emits `R(q)` then lets `QReg::drop` queue the free.

Other lifecycle helpers: `free_bit(b)`, `flush_pending_frees()`, `relabel_qreg()`
(renames without physically moving, for register role changes).

#### Peak tracking

Every `alloc_qubit` call computes `live = next_qubit - free_qubits.len()`.
When `live > peak_qubits`:
- `peak_qubits`, `peak_at_op`, `peak_section` are updated.
- `snapshot_peak_live()` records the live-qubit set and their tags
  for post-build breakdown.
- `section_peak[current_section]` is updated independently (per-section local
  peak).
- `live_series` appends `(op_idx, live)` for the timeline graph.

---

### The Op Elider

#### What it does

Every involutary gate (X, Z, CX, CZ, CCX, CCZ) is a candidate for
cancellation. When a gate `G` is about to be emitted and ALL of its operands
show the SAME prior gate as `last_op_on_qubit` (i.e. `G` has been the last
thing to touch every operand without interruption), the pair is algebraically
identity and `push_gate_op` elides them both: the prior op's slot becomes
`None` (tombstone), the current op is never pushed.

Operand ordering is normalized before comparison (CCX: sort controls; CZ/CCZ:
sort all operands) so `CCX(a,b,t)` and `CCX(b,a,t)` correctly
cancel.

#### Machinery

`ElideDelta` stores per-operand `(qid, prev_last_touched_op, prev_last_op_on_qubit)` captured before overwriting those fields. On elide, these are restored so other qubits' retention checks still point at the
correct prior touch.

`elide_deltas: HashMap<u64, ElideDelta>` -- keyed by op_idx;
aggressively pruned when any operand is touched by a different op (the entry
can no longer be elided). PushCondition/PopCondition/Neg also flush all
candidates since they change the effective condition mask.

Elisions cannot cross a streaming truncation boundary (prior_idx < ops_truncated check).

---

### Sections / Scopes

#### Flat sections

`set_section(s)` updates `current_section` and appends to
`section_marks: Vec<(usize, String)>`. Every gate increments
`executed_ops_by_section[current_section]`. `push_section(sub)` / `pop_section(prev)`
nest sections as `"{parent}/{sub}"`.

Optional env `PHASE_TRACE` panics at every `set_section` if `sim_phase != 0`,
giving a trip-wire for phase-leak bisection.

#### Lexical scopes

`enter_scope!(circ, "name")` (a macro) calls `enter_scope_at(name, file!(), line!())`. Each scope frame is appended to `scope_frames_log: Vec<ScopeFrameLog>` with parent pointer, file, line, start_op, and end_op. The stack is
`scope_stack: Vec<ScopeFrame>`. `exit_scope(push_seq)` closes
the frame.

#### Auto call-site capture (`#[track_caller]`)

Every `pub fn x/cx/ccx/...` and their `*_internal` helpers carry
`#[track_caller]`. `push_gate_op` calls
`intern_call_site(file, line)`, which lazily inserts a
`ScopeFrameLog` entry keyed by `(file, line, parent_scope_seq)`. This
is O(#call_sites) total, NOT O(#ops), so `scope_frames_log` stays small
while `op_scope: Vec<u32>` (one u32/op) records the innermost frame per gate.
The result: in `--release` builds with NO manual `enter_scope!` tags, the
debugger's `src <op>` command still resolves to the correct file:line of the
primitive that emitted the gate.

#### Profiler output

`section_peak[s]`, `executed_ops_by_section[s]`, and
`executed_toffoli_by_section[s]` are all keyed by section path.
The `maybe_assert_max_ops` panic prints a top-8 breakdown by exact
section and by first-component prefix, enabling instant attribution.

Tagged regions: `tag_region(name, qubits) -> usize` / `untag_region(idx)` record `TaggedRegion` entries for idle-stretch and
packing-opportunity analysis.

---

### The 64-shot Simulator

#### Design

`sim: Option<Vec<u64>>` -- each entry is a 64-shot bitmask for one
qubit; bit `s` is that qubit's value in shot `s`. All 64 shots run in parallel
via bitwise arithmetic -- the condition mask, XOR, AND are all 64 operations at
once. `sim_bits: Option<Vec<u64>>` is the parallel structure for
classical bits.

`sim_condition_stack: Vec<u32>`: `sim_condition_mask()`
returns AND of `sim_bits[b]` for all stacked bits (u64::MAX when empty).
Every gate applies: `qubit[t] ^= cond & qubit[c]` etc.

#### Gate sim examples

- X: `sim[q] ^= cond`
- Z: `sim_phase ^= cond & sim[q]`
- CX: `sim[t] ^= cond & sim[c]`
- CCX: `k = cond & sim[c1] & sim[c2]; sim[t] ^= k; executed_toffoli_shots += popcount(k)` (per-shot Toffoli accounting)
- HMR: `rng = sim_next_rng_u64(); sim_bits[b] = rng; sim_phase ^= sim[q] & rng; sim[q] = 0`
  -- HMR is forbidden inside a `push_condition` block (asserted).
- R: `sim_phase ^= sim[q] & rng & cond; if sim[q] != 0 { sim_phase_errors += 1 }; sim[q] = 0`
  -- a non-zero qubit under R produces a random phase kick, making R-on-nonzero
  detectable.

#### HMR PRNG

`sim_next_rng_u64()` -- a SplitMix64-style step on `(sim_hmr_counter, sim_hmr_seed)`.
Seed drawn from `thread_rng()` once per `Circuit::new()`. Deterministic per
counter but different every run (never seeded externally) so every run exercises
a different HMR-bit pattern.

#### Loading inputs

- `sim_load_reg_bytes(reg, bytes)` -- broadcasts one classical value to all 64 shots.
- `sim_load_reg_bytes_shot(reg, bytes, shot)` -- loads for ONE shot (per-shot variation).
- Both are init-time-only: they panic if any gate has already been emitted.
- `sim_load_bits_bytes[_shot]` -- same for classical bits.
- `alloc_input_qreg_bits_with_lanes(name, n, lanes)` -- the clean API: allocates
  AND loads 64-shot lanes in one call.
- `replicate_classical_to_lanes(bytes, n)` -- helper that broadcasts
  a single classical value into a `Vec<u64>` of `u64::MAX` or `0` lanes.

#### `destroy_sim`

Consumes the live simulator and returns a `DestroyedSimState`. Asserts no
pending ghosts remain, drains pending frees, then checks `Rc::strong_count`
to verify every non-output QReg was freed. Output QRegs are `detached = true`
so their drop is a no-op. `DestroyedSimState` exposes `qubit_mask`, `read_bit`,
`read_bit_shot`, `read_bytes`, `read_bytes_shot`, `is_zero`, `bit_len`,
`phase_mask`, `phase_error_count`, `phase_error_counts_by_tag`.

#### Live debugger checkpoints

Every `checkpoint_interval` (default 10M) ops, `push_gate_op` snapshots the
full sim state as a `TruncationSnapshot` in `live_checkpoints`. This lets
`Debugger::attach` start from the nearest checkpoint instead of replaying
from op 0, keeping attach time O(checkpoint_interval) rather than O(total_ops).

---

### Metrics

| Field | What it counts |
|---|---|
| `ccx_emitted` | Every `Op::Ccx` pushed (not elided); stable across streaming truncation |
| `ccz_emitted` | Same for `Op::Ccz` |
| `executed_toffoli_shots` | Sum of `popcount(fire_mask)` across all CCX/CCZ; divide by 64 for average Toffoli per shot (matches Google's "average executed Toffoli" accounting) |
| `executed_toffoli_by_section` | Per-section version of above |
| `executed_ops_by_section` | Per-section gate count |
| `total_ops()` | `ops_truncated + ops.len()` -- stable across streaming truncation |
| `op_count()` | Gate-only count in the RETAINED buffer (not total) |
| `ccx_count()` | CCX count in retained buffer only (not stable) |
| `ccx_breakdown()` | Counts `(selfwire, overlap, real)` CCXs -- non-real are bugs |
| `peak_qubits` | Max live at any point; `peak_at_op` and `peak_section` annotate it |
| `sim_phase_errors` | Count of R-on-nonzero events (phase kicks); per-section in `sim_phase_errors_by_tag` |

---

### Assertion Caps / Safety Nets

#### Caps

Three caps can be set via env var or programmatically:

1. **`CIRC_ASSERT_MAX_QUBIT_PEAK`**: default `DEFAULT_MAX_QUBIT_PEAK = 680`. Fires IMMEDIATELY when `live` first exceeds the limit -- not at end.
   The panic message says "live is a LOWER BOUND" and prints a tag-class histogram.
   Set to 0 to disable. Per-test override via `set_max_qubit_peak(limit)`
   which is shadowed by the env var.
2. **`CIRC_ASSERT_MAX_OPS`**: fires when `total_ops()` exceeds the limit.
   Panic message includes top-8 section breakdowns by exact section and prefix.
3. **`CIRC_ASSERT_MAX_QUBITS`**: instantaneous live-qubit limit (rarely used).

#### `DEBUG_ON_FAIL` hook

When `DEBUG_ON_FAIL=1`, every cap violation, contract failure, and wasteful-retention
panic:
1. Prints the diagnostic.
2. Calls `Debugger::attach(self)` to build the time-travel engine.
3. Calls `d.goto(target)` to position at the failing op.
4. Calls `d.repl()` to start the interactive debugger REPL.

This applies to: MAX_OPS, MAX_QUBIT_PEAK, MAX_QUBITS, contract_check,
contract_pop_and_check, and the strict-dealloc retention panic.

#### Memory guards

- `install_memory_rlimit_once()` -- on `Circuit::new()`, sets
  `RLIMIT_AS` to `CIRC_MEM_RLIMIT_MB` MiB (default 6000, `=0` disables; the sole
  approved `unsafe` block in the codebase). Ensures an allocator panic fires BEFORE
  the systemd SIGKILL.
- Memory watchdog: every 1024 ops reads `/proc/self/status` VmRSS
  and panics with section context if it exceeds `CIRC_MEM_WATCHDOG_MB` (default 6000 MB).
- `CIRC_NEXT_QUBIT_CAP`: default 10M; fires if `next_qubit` grows
  beyond it, detecting broken free-pool reclaim.

#### Streaming mode (`CIRC_OPS_CAP`)

When `ops.len() >= ops_cap` (default 100M), `push_gate_op` snapshots the current
sim state into `truncation_snapshot`, increments `ops_truncated`, clears
`ops`/`op_scope`/`elide_deltas`, and prunes `qubit_alloc_log` (keeping labels
for still-live qubits). Metrics (`ccx_emitted`, `executed_toffoli_shots`,
`executed_ops_by_section`) accumulate globally. `total_ops()` stays correct.
The `truncation_snapshot` lets the debugger replay the retained tail from the
correct sim state.

---

### Contracts: Inline Invariant Checking

#### `ContractSimView<'a>`

A restricted read-only view of the live simulator: `qubits`, `bits`, and
`ghosts` (pending spooky-pebble ghosts). Exposes:
- `read_u256_shot(reg, shot)` -- reads a multi-qubit register as a `BigUint` for one shot.
- `read_bit_shot(q, shot)` -- single qubit.
- `pending_ghost_count/ids/anchors/ghosts/ghost_value_shot` -- ghost-set accessors.

Ghost-aware contracts: after a windowed-tape sweep, a contract can assert
"exactly K ghosts pending" and check each ghost's per-shot tape bit against
a reference. This is the load-bearing invariant for the spooky discharge machinery.

#### `contract_check(label, F)`

Runs `F(view, shot)` for all 64 shots inline. First `Err` panics with
`CONTRACT [label] shot N: detail (section, op)`. Under `DEBUG_ON_FAIL`, attaches
the debugger at the failing op.

#### `contract_capture(label, pre)` + `contract_pop_and_check(label, post)`

Pre/post-condition pair across a block of code:
- `pre` runs inline, returns one `T` per shot; the `Vec<T>` is type-erased
  (`Box<dyn Any>`) and pushed onto `deferred_contracts`.
- `post` is called later; it receives the stored `&T` and current `ContractSimView`,
  returning `Err(msg)` on violation.
- Labels must match; mismatch panics. `DEBUG_ON_FAIL` attaches the debugger.

#### RAII `Capture<T>`

`contract_capture_handle(label, pre) -> Capture<T>` returns an
opaque handle with `update(circ, f)` and `check(circ, f)` methods. Drop
automatically removes the entry from the deferred stack. Used for long-lived
invariants that need to be rechecked mid-computation, not just at one post-point.

---

### Phase Tracking: `assert_phase_clean` + HMR Obligations

`phase: PhaseTracker` is an abstract-interpretation F2-polynomial
tracker. Every gate calls `phase.on_x/cx/ccx/hmr/r/...`. `HMR` introduces a
fresh atom for the random HMR bit and records the XOR obligation; phase-gating
ops (`z_if_bit`, `cz_if_bit`) discharge parts of that obligation.

`assert_phase_clean()` -- must be called at circuit teardown.
Panics if:
1. Any pending `Ghost` records exist (unresolved HMR obligation from `hmr_ghost`).
2. `phase.assert_clean()` fails (global phase polynomial non-zero or uncancelled
   HMR obligations).

`declare_and_of`, `declare_copy_of`, `declare_identity`, `declare_xor_of`,
`declare_xor_of_three`, `declare_choose_of` -- each verifies
the claim across all 64 sim shots, THEN injects the abstract fact into the
tracker. No blind injection.

`clear_and(t, a, b)` -- context-sensitive AND-ancilla uncompute: uses
MBU (HMR + cz_if_bit, 0 Toffoli) when outside a `push_condition`; falls back
to `ccx(a,b,t)` (1 Toffoli) inside one.

`PHASE_TRACE` env: asserts `sim_phase == 0` at every `set_section`
call, turning section boundaries into phase-check trip-wires.

---

### `emit_reverse_since`

`reverse_marker() -> usize` captures `ops.len()`. After a forward
block, `emit_reverse_since(start)` replays the block in reverse order, inverting
each gate (involutary gates are self-inverse). Handles internal alloc/dealloc
via an id-remap stack: each forward `R` (dealloc) reverses to a
fresh alloc; each forward `AppendQubit` (alloc) reverses to a dealloc.
`PushCondition`/`PopCondition` pairs are reconstructed by pre-pairing on the
forward pass. Panics on HMR, Swap, Neg (non-reversible in this
gadget). This lets composite primitives be generically uncomputed with zero
hand-mirroring.

---

### KMX Emission

#### `to_kmx() -> String`

Serializes `self.ops` to kmx text. Panics if `ops_truncated != 0` (the
retained buffer is only the tail; emitting it would produce a wrong circuit).

#### `write_kmx<W: io::Write>(w)` -- streaming serializer

Avoids materializing gigabytes of text in a single String. Also collapses
`PUSH_CONDITION if b<bit>` + single conditional-able op + `POP_CONDITION`
into the kickmix inline form `<op> ... if b<bit>` (one kmx instruction instead
of three), calling `inline_conditional(inner, bit)`. Only single-op
condition blocks collapse; multi-op blocks stay as three instructions.

#### `defragment(slots) -> Vec<QReg>`

After internal free+realloc migrates a register's qubits to scattered high ids,
`defragment` restores values to the canonical low-id block `[0, n)` via physical
SWAPs. Required because the zenodo fuzzer reads outputs from the SAME qubit ids
it wrote inputs to. Two-phase: (1) compact values at id >= n into lowest-free
slots, (2) sort via selection-swap. Relies on `free_qubits: BTreeSet` handing
out the lowest available id.

---

### Other Noteworthy Utilities

#### `emit_reverse_since` (see above -- generic uncomputation)

#### Classical bit convenience ops

`bit_xor_into`, `bit_copy`, `bit_or_into`, `bit_and_into`, `bit_swap` -- all
implemented as short PUSH_CONDITION / BIT_INVERT / BIT_STORE sequences, so
they track through the phase lattice and sim correctly.

`store_cbits_from_const(bits, val)` / `clear_cbits_const` --
load and unload a classical constant into a `CReg` without any qubit cost,
for use as read-only classical operands in arithmetic primitives.

#### `with_condition` / `with_conditions`

Closure-based PUSH/POP wrappers that make it syntactically impossible to
mis-pair push and pop (even across early returns).

`is_inside_push_condition()` -- boolean query so primitives can
select a push_condition-safe fallback construction (no R or HMR inside a
condition block).

#### `zero_check` and `cswap`

`zero_check(reg, result, anc)` -- OR-fan-in + invert using n-2 ancillae;
result = 1 iff all bits are 0.

`cswap(ctrl, a, b)` -- CX+CCX+CX decomposition (1 Toffoli). Basis for
`cond_right_shift` and `cond_left_shift`.

#### `debug_repl()`

Call directly on a fully-built circuit to enter the interactive time-travel
debugger REPL (`src`, `watch`, `rb`, `where`, `show reg`, `prof`, etc.).

#### Register dump hooks

`register_debug_dump(name, hook)` installs a closure invocable from the
debugger REPL as `dump <name> [args]`. The hook receives the `Debugger` at
current cursor + arg strings, returns text. Used for domain-specific
diagnostic dumps (e.g. printing the full pack layout at any op).

#### `current_rss_kib()`

Reads `/proc/self/status` VmRSS. Called by the memory watchdog every 1024 ops;
also callable by external profiling code.

#### Tag interning

`intern_tag(tag: String) -> Arc<str>` shares heap allocations for repeated
qubit tag strings (e.g. "carry", "cmp_ctrl_tmp"). At EC-add scale (~24M alloc
events, ~thousands of unique tags) this is a ~4x reduction in
`qubit_alloc_log` memory.

#### `CircuitDebugStats`

`debug_stats()` returns a snapshot of all debug-overhead fields:
`section_marks`, `qubit_alloc_log`, `scope_frames_log`, `op_scope` lengths and
byte costs. Used to monitor overhead growth during large builds.

#### `phase_summary()`, `phase_assert()`, `phase_assert_zero()`

Checkpointing helpers: print or panic on accumulated phase errors or non-zero
`sim_phase` at a named point, without waiting for end-of-circuit.

---

## Tracker: Phase Lattice + Ghost API

### Phase Lattice (`src/tracker/phase_lattice.rs`)

#### What it is

The phase lattice is a **correctness gate, not a lint**. It runs an O(1) abstract-interpretation step on every gate emission and every HMR, and `assert_phase_clean()` must pass before a circuit is considered correct. It catches precondition violations that the 64-shot value simulator alone cannot see -- for example, a qubit computed as `a AND b` being silently modified before its MBU phase discharge, which would invert the Z kick for some inputs without ever corrupting the value sim.

#### The `AbsVal` enum

Each qubit carries one abstract value:

| Variant | Meaning |
|---|---|
| `Zero` | Known |0> |
| `One` | Known |1> |
| `CopyOf(q, v)` | Equals qubit `q` at version `v`; stale if `q` is written |
| `AndOf(q1,v1, q2,v2)` | Equals `q1@v1 AND q2@v2`; the standard MBU pattern |
| `AndOf3(q1,v1, q2,v2, q3,v3)` | 3-way AND; for CCZ-gated MBU discharges |
| `XorOf(a, b)` | Depth-1 XOR of two sub-values |
| `XorOf3(a, b, c)` | Depth-1 three-term XOR; discharge order-insensitive |
| `ChooseOf(ctrl, a, b)` | Mux: `ctrl ? a : b`; version-pinned; no HMR discharge |
| `Anchor(id)` | Opaque equality class; always version-current; used by `declare_identity` and ghost discharge |
| `Top` | Unknown; any HMR on a `Top` qubit is an unconditional error |

Versions are monotonic per qubit (bumped on every write). A `CopyOf` or `AndOf` obligation becomes "stale" if any referenced qubit is modified between the `declare_*` call and the matching `z_if_bit` discharge -- the tracker detects this at `assert_clean` time (`val_versions_current`).

#### Transfer functions

Every gate has an `on_*` method that updates the lattice:

- `on_x(q)`: flips `Zero`<->`One`; anything else -> `Top`.
- `on_cx(c, q)`: if `q=Zero` the result is `CopyOf(c,v)`; if `q=CopyOf(c,v)` (same version) it cancels to `Zero`; XorOf chains cancel one level; else `Top`.
- `on_ccx(a, b, q)`: if `q=Zero` the result is `AndOf(a,va, b,vb)`; if already `AndOf(a,b)` it cancels to `Zero`; one level of XorOf simplification; else `Top`.
- `on_z/cz/ccz`: phase gates deposit a discharge contribution into the topmost HMR obligation on the condition stack (`discharge_to_cond`). They do NOT modify qubit values.
- `on_hmr(q, b)`: saves `qval(q)` as `Obligation.val` keyed by the classical bit `b`, then writes `val[q] = Zero`. Forbidden inside a `push_condition` block.
- `on_r(q)`: if `val[q]` is not Zero, records an R-on-nonzero event (reported at `assert_clean`), then writes Zero. This catches zenodo's `phase ^= qubit & rng` semantic on non-zero qubits.

#### The HMR obligation model

`on_hmr` inserts an `Obligation { val, discharges: Vec<(AbsVal, bool, op_idx)>, ... }` into `self.obligations` keyed by the classical bit `b`. Every `on_z/cz/ccz` called under a `push_condition(b)` appends a discharge entry `(AbsVal, versions_current)`. The version-current flag is computed at deposit time: a discharge deposited after a referenced qubit is modified is marked stale and will not satisfy the obligation.

#### `prove_zero`

`prove_zero_raw(q)` reads the 64-shot sim mask for `q`. If any shot is nonzero it panics -- with a `DEBUG_ON_FAIL=1` hook that attaches the time-travel debugger at the exact op. On success, it calls `inject_zero_unchecked`, overwriting the abstract value with `Zero` so downstream `R`/free does not flag a false positive. This is the **only** mechanism to inject `Zero` from outside the transfer functions.

#### `assert_phase_clean` / `assert_clean`

Called at circuit end. Reports three failure modes:
1. **Direct phase**: a `Z/CZ/NEG` was emitted outside any `push_condition` block (`direct_phase_nonzero`).
2. **R-on-nonzero**: any `on_r` call on a non-Zero qubit.
3. **Unmatched obligations**: for each HMR obligation, attempts structural cancellation (pair-cancel identical discharges, then single match, then `XorOf` two-leaf match, then `XorOf3` three-leaf permutation match via brute-force over 3! orderings). Obligations that do not reduce to clean are reported with section, `hmr_op_idx`, and discharge summary.

#### The `declare_*` API

All `declare_*` methods are **sound fact injection**: each public wrapper in `Circuit` first asserts the claimed identity across all 64 sim shots, then calls the internal `_unchecked` variant. Direct calls to `_unchecked` from outside `phase_lattice.rs`/`circuit.rs` are a soundness bug.

| Public API | What it injects | Sim check |
|---|---|---|
| `declare_identity(q_a, q_b)` | `Anchor(fresh_id)` on both | `sim_mask(q_a) == sim_mask(q_b)` |
| `declare_copy_of(q, source)` | `CopyOf(source, ver)` on `q` | masks equal |
| `declare_and_of(q, a, b)` | `AndOf(a,b)` on `q` | `q_mask == a_mask & b_mask` |
| `declare_and3_of(q, a, b, c)` | `AndOf3(a,b,c)` on `q` | `q_mask == a_mask & b_mask & c_mask` |
| `declare_xor_of(target, q1, q2)` | `XorOf(CopyOf(q1,v1), CopyOf(q2,v2))` | `target_mask == q1_mask ^ q2_mask` |
| `declare_xor_of_three(target, q1,q2,q3)` | `XorOf3(...)` | XOR of three masks |
| `declare_choose_of(target, ctrl, a, b)` | `ChooseOf(ctrl,a,b)` | mux of masks |
| `mbu_free_copy_of` | sets source to `CopyOf` then HMRs | same version required at discharge |

Why these matter: without a `declare_*` call, the tracker sees `Top` for any qubit not reachable by transfer functions, and HMR of a `Top` qubit is an unconditional error.

#### Ghost-anchor accessors for deferred discharge

Two internal accessors support the Ghost API:
- `anchor_qubit_and_get_id(q)`: writes `val[q] = Anchor(fresh_id)` immediately before `on_hmr` is called; the obligation records `Anchor(id)` rather than a version-tagged pair, so it stays valid across arbitrary intervening ops (since `Anchor` is always version-current).
- `re_anchor_for_resolve(r, id)`: at discharge time, writes `val[r] = Anchor(id)` so the next `on_z(r)` under the bit's condition deposits the matching `Anchor(id)` and the obligation structurally resolves.

---

### Ghost API (`src/tracker/ghost.rs`)

#### What a Ghost represents

A `Ghost` is a **deferred HMR phase obligation**: the receipt produced when a qubit is measurement-uncomputed during a forward pass, whose phase cancellation is deferred to a later reverse pass. It is `#[must_use]`, `!Clone`, `!Copy`. Dropping without resolve panics.

Fields (all `pub(crate)`):
- `id: u64` -- sequential identifier, used as bookkeeping key in `Circuit::pending_ghosts`.
- `bit: Cbit` -- the random classical bit allocated at HMR time; lives until `resolve_ghost` frees it.
- `anchor_id: u64` -- the shared `Anchor(id)` that ties the HMR obligation to the discharge target, regardless of version.
- `mask_at_hmr: u64` -- 64-shot bitmask of the HMR'd qubit's value at creation time; `resolve_ghost` sim-verifies the discharge register matches this exactly.
- `hmr_section: String`, `hmr_op_idx: usize`, `hmr_caller: &'static Location` -- diagnostics; `DEBUG_ON_FAIL=1` prints these on drop-without-resolve and `goto hmr_op_idx` locates the origin in the debugger.
- `consumed: bool` -- set by `resolve_ghost`/`close_ghost` before the Ghost is dropped; if false and not unwinding, Drop panics.
- `acc_xor: u64` -- running XOR of discharge-term sim masks for the multi-term `ghost_xor_*`/`close_ghost` path; must equal `mask_at_hmr` at `close_ghost`.

#### The ghost-event log and pending-ghost table

`Circuit::hmr_ghost` pushes a `GhostEvent { op_idx, create:true, id, anchor_id, mask_at_hmr, bit_raw, section }` to `self.ghost_event_log`. `resolve_ghost` pushes a matching `create:false` event. This log is replayed by the debugger's `ghosts`/`gh` command to reconstruct the pending-ghost set at any op cursor -- which is what enables chasing ghost-discharge desync in windowed-tape sweeps.

`Circuit::pending_ghosts: Vec<GhostRecord>` mirrors the diagnostic fields of each live Ghost so the circuit-level Drop check can report them even if the Ghost was leaked via `std::mem::forget`.

#### Creation: `Circuit::hmr_ghost`

1. Assert condition stack is empty.
2. Snapshot `mask = sim_get_mask(q)` before zeroing.
3. Call `phase.anchor_qubit_and_get_id(q)` -- writes `val[q] = Anchor(id)`.
4. Allocate `bit = alloc_bit()`.
5. Call `hmr(q, bit)` -- obligation records `val = Anchor(id)`, writes `val[q] = Zero`.
6. Call `phase.set_obligation_hmr_mask(bit, mask)` -- stores the 64-shot mask on the obligation for multi-term discharge verification.
7. Push `GhostEvent` (create), push `GhostRecord` to `pending_ghosts`, return `Ghost`.

#### Resolution: `Circuit::resolve_ghost`

1. Assert condition stack empty.
2. Sim-verify `sim_get_mask(r) == g.mask_at_hmr`; on mismatch: print diff + attach debugger + panic.
3. Call `phase.re_anchor_for_resolve(r, anchor_id)` -- writes `val[r] = Anchor(id)`.
4. Call `z_if_bit(r, g.bit)` -- under `push_condition(bit)`, `on_z(r)` deposits `Anchor(id)` into the obligation's discharges; `on_free_bit` then sees `obligation_is_clean` (one Anchor match) and removes it.
5. Free `g.bit`. Remove `GhostRecord` from `pending_ghosts`. Mark `g.consumed = true`.

#### Multi-term discharge: `ghost_xor_*` / `close_ghost`

For deferred phases that cancel as a sum of terms (e.g. borrowed-dirty adder where a vented carry's phase = `Z(dirty@v1) XOR Z(dirty@v2)`):
- `ghost_xor_z(g, r)`: emits `z_if_bit(r, g.bit)`, XORs `sim_get_mask(r)` into both `g.acc_xor` and `obligation.discharge_xor`.
- `ghost_xor_cz(g, r1, r2)` / `ghost_xor_ccz(g, r1, r2, r3)`: same but for AND terms.
- `close_ghost(g)`: calls `phase.resolve_masked_obligation(bit)` which checks `obligation.discharge_xor == obligation.hmr_mask`; on mismatch: DEBUG_ON_FAIL attach + panic. On success, frees `bit`, removes bookkeeping, marks consumed.

The sim-mask check in `close_ghost` replaces structural matching: it verifies that the emitted Z/CZ/CCZ terms reproduce the vented value on all 64 shots for any random HMR bit, so the kickback cancels unconditionally.

#### `destroy_sim_ghosts`

For forward-only cost-measurement fragments: hands over undischarged ghosts explicitly. Calls `phase.assert_clean_except(ghost_bits)` to verify there are no other hidden obligations, then marks all handed-over ghosts consumed. This is the honest, accounted-for way to measure peak/Toffoli of a forward pass without leaking phase obligations.

#### Why this matters for the spooky-Kaliski circuits

The Ghost API is what enables "spooky quadratic discharge": the forward Kaliski pass vents ~B ancillae per window via `hmr_ghost`, accumulating a tape of `Ghost` receipts. The reverse pass recomputes each vented value from the (restored) live registers and calls `resolve_ghost`, phase-cancelling in O(B) qubits instead of the O(n) that a full reverse uncompute would require. The pending-ghost table + event log lets the debugger (`gh` command) show exactly which ghosts are open at any point in the op stream, turning discharge-desync bugs into a pinpointable mismatch between `mask_at_hmr` and the recomputed register mask.

---

## Time-Travel Debugger (`src/tracker/debugger/`)

The time-travel debugger is the primary forensic tool for the quantum
circuit simulator. It attaches to any built `Circuit`, replays the full
op stream gate-by-gate using the same transfer functions as the in-process
sim, and drops into an interactive REPL at any failure point. It supports
both forward and backward movement, named-register inspection, profiling,
and ghost-pebble tracking -- all referencing the same global op indices
used by panic messages.

---

### Core mechanism: delta-log backward stepping

**Data structure**: `SimState` holds the 64-shot parallel
sim -- `qubits: Vec<u64>` (one `u64` per qubit, 64 parallel shots packed
as bits), `bits: Vec<u64>` (classical bits, same encoding), `phase: u64`
(one phase bit per shot), `cond_stack: Vec<u32>`, `hmr_counter: u64`, and
`r_on_nonzero_events: u64`.

**Two-tier undo**:
- Full state checkpoints every `checkpoint_interval` ops (default 10M) -- coarse anchors for long-range jumps.
- A bounded `VecDeque<Delta>` ring-buffer (`delta_log_cap` = 500K) covering the window `[cursor - delta_log.len(), cursor)`. Each
  `Delta` stores minimal pre-op state -- self-inverse ops
  (X, CX, CCX, Z, CZ, CCZ, SWAP, NEG) store only `Delta::SelfInverse`
  and are reversed by re-applying the op; HMR, R, PushCond, PopCond, and
  BitStore ops record the pre-op values they overwrite.

**`goto(target_global)` routing**: If forward, steps via
checkpoints when the gap exceeds the delta-log capacity; otherwise
serial-steps forward. If backward and the target is within `delta_log.len()`,
pops deltas in O(cursor - target). If the target is beyond the log window,
falls back to `restore_snapshot_and_replay` -- snaps to the nearest
checkpoint <= target and forward-replays from there.
`step(n)` / `back(n)` are thin wrappers.

**Op-index offset model**: The debugger stores a local
`cursor` (0..=ops.len()) plus `ops_start_idx` -- the global index of the
first retained op (equals `ops_truncated` when streaming truncation is
active, 0 otherwise). All user-facing APIs and printed op indices translate
via `cursor() = cursor + ops_start_idx` so debugger output
aligns with the `op #N` values in panic messages. The valid replay range
is printed as `range=[lo..hi)` by the `where` command.

**Attach moves, not clones**: `Debugger::attach(&mut circ)`
uses `std::mem::take` on `circ.ops`, `section_marks`, `op_scope`,
`scope_frames_log`, `qubit_alloc_log`, `bit_alloc_log`, `ghost_event_log`,
and `dump_hooks` to avoid the transient ~5 GiB double-peak that a clone of
a 100M-op Vec would cause. The circuit is effectively gutted after attach;
the debugger owns the op stream. Live checkpoints captured during emission
are transferred to `self.checkpoints`.

**HMR/R determinism**: The debugger seeds its RNG with the circuit's
`initial_hmr_seed` and uses a counter-based hash (`rng_u64`) so every forward/backward step produces the same random
bits as the original emission run -- making replay bitwise identical to
what `prove_zero` observed.

---

### Auto-attach: `DEBUG_ON_FAIL=1`

The hook is installed in two places:
- `prove_zero` in `phase_lattice.rs` -- fires when the circuit's phase or
  ancilla check fails.
- `contract_pop_and_check` in `circuit.rs` -- fires when a contract
  postcondition diff is nonzero.

Both sites call `Debugger::attach(self)`, jump to the failing op, then
call `repl()`. The REPL drops in at the failing position so `where`
immediately shows context and the very first `src <op>` command maps the
failing op to file:line.

`run_8g_scope.sh` auto-disables `CIRC_WALL_TIME_LIMIT_SEC` when
`DEBUG_ON_FAIL=1` is set, so the REPL can sit at the prompt indefinitely.

For gate-level predicates not yet wired (declare_and_of, r_on_nonzero,
etc.), the pattern to add is:
```rust
if std::env::var("DEBUG_ON_FAIL").is_ok() {
    Debugger::attach(self).goto(self.ops.len()); repl();
}
```

---

### REPL: every command

The REPL reads lines from stdin, dispatches via
`run_command`, writes output, and flushes per command --
enabling non-interactive FIFO driving. The prompt `(dbg) ` has no trailing
newline. Commands:

#### Navigation

**`s` / `step [n]`**: Advance `n` ops forward (default 1).
Prints `where_line()` after moving.

**`b` / `back [n]`**: Rewind `n` ops via delta-log
(O(n) for recent ops, snapshot+replay for older). Prints `where_line()`.

**`n` / `next`**: Advance to the start of the NEXT
section boundary. Uses `section_marks` to find the next `op_idx > cursor`. Useful for skipping over a whole subsection at once.

**`c` / `continue`**: Run forward until a breakpoint
fires or the end is reached. Reports which breakpoint triggered.

**`rc` / `rcontinue` / `rb` / `run-back`**: run backward
until a breakpoint fires or op 0 is reached. Combined with `watch`,
it finds the exact op that last modified an invariant without manually
bisecting. Returns `rev-break: <bp>` on match,
`(hit op 0 without match)` otherwise.

**`g` / `goto <idx>`**: Jump to a specific global op
index. Also accepts `g @<section-name>` to jump to the start of a named
section (looks up `section_marks` by name).

#### Inspection

**`w` / `where`**: Print cursor (global op index / total),
current section name, `phase` (64-bit hex mask), `r-nonzero` count, and
`range=[lo..hi)`. Also prints the scope chain (function call stack) at the
cursor position.

**`src` / `source [idx]`**: Map any op index to its
**file:line call site** by walking the `scope_frames_log`. Every gate
emission auto-interns its `#[track_caller]` location (no manual
`enter_scope!` needed; see test `src_resolves_file_line_without_manual_enter_scope`). Prints the full scope chain innermost to root -- each frame
shows `function_name at file:line`. This is the first command to run at
any failure: `src <failing-op>` immediately tells you which code emitted
the offending gate. Handles streaming truncation gracefully with a note when
the requested op is below the retained tail.

**`l` / `list [n]`**: Show a window of `n` ops (default 10)
on each side of the cursor. Marks section boundaries with `[section-name]`
banners and the cursor position with `>>`. Op names include resolved qubit
tags (not raw IDs) via `format_op_named`.

**`p` / `show` + sub-commands** (`print_expr`):

- **`p q<N>[.s<S>]`**: Print qubit N's 64-shot mask as hex, or bit in shot S.
  Also accepts a tag label: `p det_sign` resolves the label to the most
  recent qubit ID via `qubit_id_from_tag` which does exact
  match first, then suffix match (so `det_sign` matches
  `divstep.outer_12/det_sign`).
- **`p b<N>[.s<S>]`**: Print classical bit N's mask. Also accepts cbit tag labels.
- **`p phase`**: Print `sim_phase` as hex plus a list of which shots have
  the phase bit set.
- **`p section`**: Print current section name.
- **`p reg <start> <n> [shot<S>]`**: Print `n` contiguous qubits starting
  at raw qubit id `start` as little-endian hex for shot S (default 0).
  Good for inspecting packed register values.
- **`p qreg <label>[:be]`**: Print a **scattered** multi-bit quantum
  register whose bits are allocated as `<label>[0]`, `<label>[1]`, etc.
  (not necessarily contiguous in qubit ID space). Walks `qubit_alloc_log`
  to resolve each index, assembles a hex integer. `:be` suffix reverses
  bit order (label[0] = MSB). Optional `shot<S>` selects which of the 64
  parallel shots to read. Handles dynamic-width registers
  that grow/shrink across the circuit.
- **`p creg <label>[:be]`**: Same but for classical-bit registers
  (`bit_alloc_log`), reading shot 0.

**`tag q<N>` / `tag <N>` / `tag <label>`**: Resolve a
qubit ID to its current tag, or a label to a qubit ID, at the current
cursor. Qubit IDs are reused across alloc/free cycles, so the tag at the
failure point may differ from the tag at attach -- this command makes the
current mapping explicit.

**`ghosts` / `gh`**: List the spooky-pebble ghosts **pending**
at the current cursor. Reconstructed by replaying `ghost_event_log` up to
the cursor: a `create` event adds a ghost, a `resolve`
event removes it. Output shows each ghost's ID, anchor
qubit ID, classical bit, 64-shot tape mask, create-site op index, and
section name. Used in combination with `rb`+`watch` to chase ghost-discharge
desync in windowed-tape sweeps.

#### Breakpoints

**`break op <idx>`**: Fire when the cursor reaches that global
op index.

**`break section <name>`**: Fire on entering the named
section (matches `section_marks` entries).

**`break phase`**: Fire at the first op where `sim_phase` goes
from 0 to nonzero.

**`break r-nonzero`**: Fire at the first R-on-non-zero event
(prove_zero precondition violation).

**`watch <q-or-label>` / `break <q-or-label>`**:
Set a `QubitChange` breakpoint on a qubit. The qubit can be specified as
`q<N>`, a bare integer, or a tag label (resolved via `qubit_id_from_tag`).
Records the qubit's current value as `last`; fires when the value
next differs from `last` in either direction (forward or backward walk).

**`watch <q-or-label> = <mask>`**: Set a `QubitValue` breakpoint that
fires when the qubit's 64-shot mask equals `mask` and it wasn't equal
before the step. Mask is decimal, `0x`-prefixed hex, or `all` (=
`u64::MAX`). Useful for "when does qubit q become fully set?" queries.

**`breakpoints` / `bp`**: List all active breakpoints
with their list indices.

**`clear <idx>`**: Remove breakpoint by list index.

#### The `rb`/`watch` workflow

This is the canonical debugging recipe for any "wrong bit / wrong value"
failure. The `run_backward_until_break` engine walks
backward one op at a time via `back(1)`, snapshotting qubit values before
each step and checking after whether any `QubitChange` or `QubitValue`
breakpoint fired. It also checks `Op` breakpoints on the current cursor.
Combined with `watch`:

1. Attach at failure: `DEBUG_ON_FAIL=1 ./scripts/run_8g_scope.sh cargo test ...`
2. `src <failing-op>` -- map to file:line immediately.
3. Identify the wrong qubit from the diff (e.g. `diff = 0x400` = bit 10 wrong).
4. `watch q<N>` or `watch <label>` -- sets `QubitChange` from current value.
5. `rb` -- walks backward until the qubit's value changes. Reports the exact
   op that last touched it. That op's `src` gives the bug site.

Multiple watches can be active simultaneously; the first to fire reveals
which side of a boundary holds the bug.

---

### Profiler: `prof` command

The profiler has three data sources selectable as a first argument:

**`prof whole ...`** (default): Whole-circuit op/Toffoli cost by section,
precomputed at attach time from `circ.executed_ops_by_section` and
`circ.executed_toffoli_by_section`. Toffoli counts are
the sum across 64 shots; displayed as per-shot averages (divided by 64). Rows default-sorted by ops; `tof` keyword re-sorts by Toffoli.

**`prof cursor ...`**: Tracks ops/Toffoli for ops between op 0 and the
current cursor only, updated incrementally during forward/backward
stepping. Starts empty at op 0; useful for "how much
did this one section cost?" -- navigate to the section start with `goto
@section`, read cursor profile, navigate to end, compare.

**`prof peak ...`**: Per-section qubit-count breakdown at the circuit's
peak. Drawn from `circ.peak_live_tags` captured during
emission; strips array-index suffixes to group by register class (e.g.
`pack[0]`, `pack[1]` --> `pack[]`). Shows qubit counts and percentages.
Sorted by qubit count; `q`/`qubits` metric keyword is accepted.

**Filter sub-commands** (documented in the REPL `HELP` text):
- `top [n]`: Top `n` rows by primary sort metric (default 20).
- `exact <name> [n]`: Only the section with this exact name.
- `prefix <prefix> [n]`: All sections whose name starts with `prefix`.
- `contains <substr> [n]`: Substring match anywhere in the name.
- `current [n]`: Current section and all its children (whole/cursor only).
- `split <prefix|current> [n]`: Aggregate children of `prefix` by their
  immediate child name -- produces one row per direct child, with that
  child's subtree summed. Equivalent to one level of drill-down without
  listing every leaf.

These compose: `prof cursor tof prefix v4.divstep 10` -- top 10
Toffoli-sorted sections inside `v4.divstep`, from the cursor window only.

---

### Region analysis: `analyze_regions` / `find_packing_opportunities`

These are programmatic APIs (not REPL commands). Given a
built circuit, `analyze_regions` builds per-tagged-region liveness stats:
qubit count, alive op window, ops touching the region vs total ops in window,
and idle stretches (runs of >= 10K consecutive ops that don't touch any of
the region's qubits). `find_packing_opportunities` cross-references all
pairs (A, B) to find regions where A is alive-but-idle while B is active --
candidates for qubit aliasing or delayed alloc/early free. Used offline to
find packing wins.

---

### Custom dump hooks: `dump <name> [args]`

`DumpHook`: `Box<dyn Fn(&Debugger, &[&str]) -> String + Send + Sync>`.
Registered via `circ.dump_hooks` (moved into the debugger at attach).
REPL command `dump <name> [args]` calls the hook with a
`&Debugger` (giving it access to `qubit()`, `cursor()`, `section_marks_iter()`,
`qubit_name_at()`, and `read_tagged_reg()`) plus any trailing arguments.
`dump` with no name lists registered hook names. Allows circuit-specific
custom state pretty-printers without modifying the debugger itself.
`read_tagged_reg` is the hook-friendly API for reading a
dynamic-width register by label -- stops at the first index whose tag is
no longer live.

---

### Rendering at time-travel

At any cursor position the debugger can reconstruct:
- **Current section**: binary-searched from `section_marks` (sorted by op
  index) in O(log M) per lookup.
- **Scope chain**: `op_scope[local_cursor]` indexes into `scope_frames_log`
  whose frames chain via `parent` pointers. Printed by
  `where` (innermost to root names only) and `src` (with file:line).
- **Qubit/cbit tags at any op**: `qubit_name_at(qid, op_idx)` and
  `cbit_name_at(bid, op_idx)` walk `qubit_alloc_log` / `bit_alloc_log` for
  the most recent alloc event at or before the requested op.
  The `format_op_named` formatter calls this for every qubit in every listed
  op, so `list` always shows human-readable register names even in the
  middle of time-travel. Tags follow alloc/free cycles correctly (a qubit
  reused three times shows the tag appropriate to that cursor's allocation).
- **Pending ghosts**: `pending_ghosts_at_cursor()` replays `ghost_event_log`
  up to cursor in a single linear scan.
- **Cursor-mode profile**: updated incrementally on every `forward_one` and
  `back_one_via_log` step, so `prof cursor` always reflects
  exactly the ops between the snapshot baseline and current cursor.

---

### Non-interactive FIFO driving

The REPL is scriptable without modification. Because the REPL flushes
stdout after every command and reads from stdin line-by-line,
a FIFO pair works as a non-interactive driver:

```
TMPD=$(mktemp -d)
mkfifo "$TMPD/in"
touch "$TMPD/out"
sleep 99999 > "$TMPD/in" &        # writer-hold (run_in_background)
DEBUG_ON_FAIL=1 ./scripts/run_8g_scope.sh cargo test ... \
    < "$TMPD/in" > "$TMPD/out" 2>&1 &
## monitor until attached or exited
echo "watch q905" > "$TMPD/in"
echo "rb"         > "$TMPD/in"
echo "where"      > "$TMPD/in"
echo "quit"       > "$TMPD/in"
```

The writer-hold (`sleep 99999 > "$TMPD/in"`) keeps the FIFO open so
`echo cmd > fifo` never blocks. Always check `dbg_alive()` (grep the
output file for exit markers) before each write -- if the test process
died, the FIFO has no reader and subsequent writes block forever.
Use the Monitor tool for indefinite waits; use `wc -l` polling only for
sub-second expected waits.

---

### Tests

The test suite covers:
- **Differential replay** (`differential_debugger_matches_sim`):
  200 random circuits, every qubit/bit/phase verified to match the live sim
  after replaying to end.
- **Regression: gates before set_section**: verifies
  `initial_sim_state` is captured before the first gate, not at first
  `set_section`.
- **Round-trip step/back** (`round_trip_step_back`): forward
  to midpoint, save state, advance to end, goto midpoint, compare.
- **Delta-log ring drop** (`delta_log_ring_drop_recovers_via_snapshot`): forces ring drops with a small cap (8), verifies snapshot
  fallback restores identical state.
- **Phase breakpoint** (`phase_breakpoint_fires_at_neg`):
  confirms `PhaseNonzero` fires exactly at the first `neg()` op.
- **Section breakpoint** (`section_breakpoint_fires`).
- **Delta-vs-snapshot identity** (`delta_back_matches_snapshot_replay`): walks every op variant forward then back via delta-log and
  compares to snapshot-only replay state at each position.
- **Profiler queries** (`profiler_supports_exact_prefix_current_and_split_queries`; `cursor_profiler_tracks_step_back_and_goto`;
  `peak_profiler_supports_top_exact_prefix_and_contains`):
  all profiler filter sub-commands with whole/cursor/peak modes.
- **`src` resolves file:line without manual enter_scope**
  (`src_resolves_file_line_without_manual_enter_scope`):
  the critical regression test that ensures auto-caller-tracking works
  on every gate, making `src` immediately useful in real circuit runs.
