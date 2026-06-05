# Estimating FT quantum-computer "size": metrics + the qubit/Toffoli exchange rate

Research note, 2026-06-02. Primary question: when shrinking logical-qubit
count, how much Toffoli blowup is tolerable? Background: how the surface-code
literature actually scores "machine size" (vs the naive qubits x Toffoli
product). All quantitative claims carry fetchable arXiv URLs.

================================================================================
## 0. THE ANSWER: qubit <-> Toffoli exchange rate
================================================================================

Cost currency = physical SPACETIME VOLUME:
    C ~ Q_tot * phys_per_logical(d) * runtime_cycles
where Q_tot = logical footprint (data + ancilla + magic-state region),
phys_per_logical ~ 2(d+1)^2, and runtime depends on regime:

  - VOLUME-LIMITED (few magic-state factories, i.e. a space-minimized design):
      runtime ~ T_count * (~d cycles/Toffoli) / n_factories
      With n_factories fixed: runtime ~ T_count.
      => C ~ Q * T_count.   The PRODUCT is the local iso-cost curve.
      Iso-cost d(Q*T)=0 => dT/T = -dQ/Q.
      Finite: T_new/T_old = Q_old/Q_new = 1 / (qubit shrink factor).

  - REACTION-LIMITED (many factories / lots of spare area):
      runtime ~ T_depth * t_react   (t_react ~ 10 cycles, 10us/1us)
      independent of Q and of Toffoli COUNT.
      => C ~ Q * T_depth. Count is nearly free; depth and Q are what you pay.

A space-minimized EC inversion is VOLUME-LIMITED. Confirmation: Gidney 2025
RSA design explicitly ACCEPTED longer runtime by using FEWER magic-state
factories to shrink the footprint (arXiv:2505.15917) -- that is the
volume-limited regime by construction. Quick test for which regime: you are
volume-limited while  n_factories < (T_count/T_depth) * d/10. With n_fact=1..4
this holds unless Toffoli-depth ~ Toffoli-count.

### Bottom line
Break-even tolerable Toffoli blowup = RECIPROCAL of the qubit shrink:
  - halve qubits (s=0.5)      -> up to ~2x   Toffolis is free
  - -10% qubits (s=0.9)       -> up to ~+11% Toffolis
  - shrink qubits 10x         -> up to 10x   Toffolis
That reciprocal is a CEILING, and three effects only ever lower it (in this
regime):

  1. TOFFOLI-DEPTH is the trap. The reciprocal rule holds only if the
     qubit-saving trick is depth-NEUTRAL. Most qubit-reduction tricks
     (recompute/uncompute, windowing, fewer ancillae -> more sequential
     recompute) inflate depth. Enough depth growth -> fall to the reaction
     floor where iso-cost is Q*T_depth and the depth blowup is NOT refundable
     by the qubit savings. Rule: "free up to reciprocal Toffolis" ONLY if
     Toffoli-depth stays roughly flat. If it doubles depth, assume the savings
     are eaten.

  2. MAGIC-STATE-REGION FLOOR. Shrinking DATA qubits does not shrink the
     factory/cultivation area. Once data qubits ~ magic-state area, further
     data cuts barely move Q_tot -- you keep paying Toffolis but stop saving
     qubits. Diminishing returns well before Q -> 0.

  3. d ~ log(volume) is second order. A volume-flat trade keeps d flat; only
     matters if volume moves > ~10x (then d ticks 1-2, small (d+1)^2*d penalty).

### Practical verdict
  - cut qubits 2x for +50% Toffolis, depth-neutral  -> CLEAR WIN
  - cut qubits 20% but 3x the Toffolis              -> CLEAR LOSS (cap ~1.25x)
  - cut qubits 2x but also 2x Toffoli-DEPTH         -> break-even at best / loss
This is why Gidney pursued qubit reduction AND a 100x Toffoli-count cut
SIMULTANEOUSLY (residue arithmetic) rather than trading one for the other.

Reconciliation with "the product is a bad metric": the product is bad as an
ABSOLUTE cross-architecture figure of merit (it ignores parallelism, routing,
the space-time tradeoff continuum). But its GRADIENT is locally valid for a
small perturbation around a fixed space-minimized operating point -- which is
exactly the "should I trade these qubits for those Toffolis" question. Bad
absolute scalar, usable local exchange rate.

ACTION ITEM: get the real Toffoli-DEPTH of the EC-inversion circuit. That
single number decides volume- vs reaction-limited and turns the "reciprocal
ceiling" into a hard exchange rate.

================================================================================
## 1. Why qubits x Toffoli (the product) is weak -- but not meaningless
================================================================================

It IS "circuit volume." Litinski & Nickerson (PsiQuantum), "Active Volume,"
arXiv:2211.15465: "the cost of a quantum computation is determined by the
circuit volume, i.e., the number of qubits multiplied by the number of
non-Clifford gates ... idling logical qubits have the same cost as logical
qubits that participate." Their thesis: "For quantum computations with
thousands of logical qubits, the active volume can be orders of magnitude
lower than the circuit volume." (3-0 verified.) Toffoli ~ 2T, so qubits*Toffoli
is the same family. The product is the pessimistic "everything idles at full
price" upper bound; real machines beat it by 1-3 orders of magnitude.

Continuous space-time tradeoff => one scalar cannot capture it. Litinski,
"A Game of Surface Codes," arXiv:1808.02892 (Quantum 3, 128, 2019): one FIXED
logical computation (100 qubits, T-count 10^8, T-depth 10^6) runs in 4 hours
on 55,000 qubits, 22 min on 120,000, or 1 second on 330,000,000 qubits --
~4 orders of magnitude of physical-qubit variation for the SAME circuit, at
phys error 1e-4, 1us cycle.
Two refuted misconceptions:
  - "Toffoli count is the dominant runtime metric" -- FALSE. Runtime has a hard
    reaction floor: time >= measurement_depth * reaction_time. Count sets total
    work; DEPTH sets the runtime floor. (Fowler, "Time-optimal quantum
    computation," arXiv:1210.4626.)
  - "Magic-state distillation dominates cost" -- FALSE post-cultivation (sec 3).

Practitioners therefore report a PAIR + a depth: logical-qubit count AND
Toffoli/T count (un-multiplied) + Toffoli/T DEPTH (runtime). The repo's
1191q/2.755M-tof tracking and Google's <1175q/<2.7M-tof target are both stated
this way --
correct. Only the product-as-one-scalar is the weak object.

================================================================================
## 2. The right currency: spacetime volume, with d folded in
================================================================================

Native unit = BLOCK = one logical qubit for one logical timestep.
FLASQ (arXiv:2511.08508, Google Quantum AI, Nov 2025):
  block = 2(d+1)^2 physical qubits * d cycles.
  per-cycle logical error p_cyc = c_cyc * Lambda^(-(d+1)/2),
     c_cyc ~ 0.03, Lambda = p_th/p_phys, threshold p_th ~ 0.01.
  total logical error < target + exponential suppression in d  =>  d ~ log(volume).
So d is DERIVED from total spacetime volume, then multiplies back in
(logarithmically). You cannot read physical size off logical gate counts alone;
it depends on the error budget and architecture. Aggregate units: physical
qubit-cycles / qubit-hours / "megaqubitdays."
================================================================================
## 3. Recent shifts -- constants, not the currency
================================================================================

MAGIC STATE CULTIVATION (Gidney, Shutty, Jones, arXiv:2409.17595, "growing T
states as cheap as CNOT gates"): a T state "uses roughly the same number of
physical gates as a lattice-surgery CNOT," ~10x FEWER qubit-rounds, reaches
logical error 2e-9, and FITS IN A SINGLE surface-code patch for d>=7 (killing
factory routing overhead). This is why "distillation dominates" is now false.
Caveat: cultivation has an error FLOOR (~2e-9 at 1e-3 noise); deeper algorithms
still feed it into one distillation round. "Further distillation may never be
needed" is a hedge.

FLASQ estimates spacetime volume directly by "fluidly" reallocating ancilla
space/time while enforcing measurement-depth + reaction-time constraints.
"circuit depth or T-count ... fail to capture critical overheads, such as the
spacetime cost of Clifford operations and routing." Headline: cultivation +
walking codes + QEC/QEM hybrid cut BOTH space and time > 10x for a 2D-TFIM sim;
predicted depth within ~25% of a hand-optimized compilation. Same logical
T-count, ~10x different physical size -- gate count alone is a poor size
predictor.
ACTIVE VOLUME beats circuit volume by not charging idle qubits full price --
but REQUIRES non-local connectivity (photonic interconnect, atom shuttling).
The strong "cost independent of qubit count" form does not hold; rely only
on the weaker claim (orders of magnitude below circuit volume at
thousands of qubits).

Historical factory calibration: Gidney-Fowler catalyzed CCZ factory
(arXiv:1812.01238) = 12d x 6d footprint, one |CCZ> per 5.5d cycles; old |T>
factory = 12d x 8d x 6.5d; T-factory spacetime volume ~"two orders of magnitude
larger than a CNOT." Superseded as cheapest option by cultivation.

================================================================================
## 4. Google vs Oratomic -- the physical:logical ratio is the swing factor
================================================================================

GOOGLE (superconducting surface code): Gidney 2025, "How to factor 2048 bit RSA
integers with less than a million noisy qubits," arXiv:2505.15917.
  - < 1,000,000 physical qubits, < 1 week, RSA-2048.
  - square grid NN, 0.1% gate error, 1us cycle, 10us reaction.
  - uses magic state cultivation + approximate residue arithmetic + yoked
    surface codes. Runtime INCREASED vs 2019 "because of performing more
    Toffoli gates and using fewer magic state factories" (= space-time tradeoff
    as a deliberate choice).
  - reduced Toffoli count "by over 100x compared to Chevignard+Fouque+
    Schrottenloher 2024" <-- the SAME Schrottenloher arithmetic line as our
    schrottenloher_status.md work. Worth mining for technique transfer.
  - vs Gidney-Ekera 2019 (arXiv:1905.09749): 20,000,000 qubits, 8 hours.
  - ECC whitepaper (Gidney/Babbush/Boneh/Drake, "Quantum Threat to Elliptic
    Curve Cryptocurrencies"): ECC-256 < 500k physical / 1200-1450 LOGICAL
    qubits -- the source of our ~1175q logical target.

ORATOMIC (neutral atoms): Cain, Xu, King, Picard, Levine, Endres, Preskill,
Huang, Bluvstein, "Shor's algorithm is possible with as few as 10,000
reconfigurable atomic qubits," arXiv:2603.28627.
  - as few as 10,000 atomic qubits (space-min) to 26,000 (P-256 discrete log,
    time-efficient, "a few days"); RSA-2048 runtime 1-2 orders longer.
  - long-range/high-rate connectivity via atom shuttling. Exact code family
    (qLDPC / bivariate-bicycle / transversal surface) NOT named in the abstract;
    secondary coverage says qLDPC/transversal -- treat as "long-range high-rate,
    not pinned from abstract."

The crux: physical:logical exchange rate. Surface code ~ 2(d+1)^2 (hundreds-to-
thousands x). High-rate/neutral-atom claims ~10x (and recent QuEra/Harvard/MIT
sims claim ~2 physical per logical -- secondary, unverified here). When the
ratio drops 100-1000x, LOGICAL-QUBIT count suddenly dominates relative to
Toffoli count, and the whole (q,tof) optimization weighting shifts WITH the
architecture. Comparison writeup: murmurationstwo.substack.com/p/
my-takeaways-from-googles-and-oratomics (blog; used only to locate primaries).

================================================================================
## 5. Tooling + open items
================================================================================

- Azure Quantum Resource Estimator (learn.microsoft.com/azure/quantum/
  intro-to-resource-estimation): logical circuit + qubit/error model ->
  physical qubits, runtime, code distance. Practical way to turn our
  (q, tof, depth) into physical/spacetime estimates under varied assumptions.
- Physical-level pipeline (arXiv:2511.20947, Nov 2025) argues even
  spacetime-volume counting is an abstraction above true physical sim
  (medium-confidence, single source). Bounds how far ANY purely-logical metric
  predicts physical cost -- but for RANKING two candidate logical circuits
  (what we care about) the abstraction is usually fine.

OPEN:
- Need EC-inversion Toffoli-DEPTH to fix the regime and sharpen the exchange
  rate (sec 0 action item).
- Exact Oratomic code family + the ~2-phys-per-logical QuEra/Harvard/MIT claim
  unverified; chase primaries before relying on them.

### Key citations
  2211.15465  Active Volume (circuit volume = the product)
  1808.02892  A Game of Surface Codes (space-time tradeoff)
  2511.08508  FLASQ cost model (spacetime volume; d-folding)
  2409.17595  Magic state cultivation
  1812.01238  Catalyzed CCZ factory
  1210.4626   Time-optimal quantum computation (reaction limit)
  2505.15917  Gidney 2025, RSA < 1M qubits
  1905.09749  Gidney-Ekera 2019, RSA 20M qubits / 8h
  2603.28627  Cain et al., Shor's with ~10k atomic qubits (Oratomic)
  2511.20947  Physical-level compilation pipeline
