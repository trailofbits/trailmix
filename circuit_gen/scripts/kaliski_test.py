import random


def slow_inv(x, p):
    p_2 = p-2
    ret = 1
    x_shifted = x
    while p_2 > 0:
        if (p_2 % 2) == 1:
            ret = (ret*x_shifted) % p
        p_2 >>= 1
        x_shifted = (x_shifted*x_shifted) % p
    return ret


def trailing_zeros(x):
    return (x & -x).bit_length() - 1


P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
inv_2 = slow_inv(2, P)

assert (inv_2 << 1) == (P+1)


def windowed_shift_down(W, x, s, N=257):
    s_bits = [(s >> i) & 1 != 0 for i in range(N.bit_length()+1)]
    assert s == sum(((b << i) for i, b in enumerate(s_bits)))
    assert W < N
    assert s < W and s >= 0
    assert x & ((1 << s)-1) == 0
    # treat it as bits to illustrate the algorithm
    x_bits = []
    for _ in range(N):
        x_bits.append(x & 1)
        x >>= 1

    for (k, b) in enumerate(s_bits):
        k = (1 << k)
        for i in range(N):
            if b and i + k < W:  # use unary iter here
                x_bits[i], x_bits[i+k] = x_bits[i+k], x_bits[i]

    return sum((b << i) for i, b in enumerate(x_bits))


def windowed_shift_up(W, x, s, N=257):
    s_bits = [(s >> i) & 1 != 0 for i in range(N.bit_length()+1)]
    assert s == sum(((b << i) for i, b in enumerate(s_bits)))
    assert W < N
    assert s < W and s >= 0
    assert (x >> (W-s)) & ((1 << s)-1) == 0
    # treat it as bits to illustrate the algorithm
    x_bits = []
    for _ in range(N):
        x_bits.append(x & 1)
        x >>= 1

    for (k, b) in enumerate(s_bits):
        k = (1 << k)
        for i in range(N, 0, -1):
            if b and k <= i < W:  # use unary iter here
                x_bits[i], x_bits[i-k] = x_bits[i-k], x_bits[i]

    return sum((b << i) for i, b in enumerate(x_bits))


for _ in range(100):
    N = random.randrange(250, 300)

    W = random.randrange(1, N)
    hi = random.randrange(1 << (N-W))
    s = random.randrange(W)

    lo = random.randrange(1 << (W-s)) << s
    x = lo + (hi << W)
    x_new = windowed_shift_down(W, x, s, N)
    x_expected = (lo >> s) + (hi << W)
    assert x_new == x_expected, \
        f"{x_new:x} != {x_expected:x}, W={W:x}, hi={hi:x}, lo={lo:x},"\
        + f" s={s:x} N={N}"
    x_round_trip = windowed_shift_up(W, x_new, s, N)
    assert x_round_trip == x, \
        f"{x_round_trip:x} != {x:x}, W={W:x}, hi={hi:x}, lo={lo:x}, s={s:x}"\
        + f"N={N}"


for _ in range(100):
    W = random.randrange(1, 257)
    hi = random.randrange(1 << (257-W))
    s = random.randrange(W)

    lo = random.randrange(1 << (W-s)) << s
    x = lo + (hi << W)
    x_new = windowed_shift_down(W, x, s)
    x_expected = (lo >> s) + (hi << W)
    assert x_new == x_expected, \
        f"{x_new:x} != {x_expected:x}, W={W:x}, hi={hi:x}, lo={lo:x}, s={s:x}"


# def kaliski_phase1_packed(x):
#     assert x < P and x > 0

#     pad = 24
#     W = 256
#     L = P
#     R = x

#     k = 0
#     pow_k = 1

#     parity = False
#     shifts = 0
#     iters = 0
#     max_ctz = 0

#     ctz = trailing_zeros(R)
#     max_ctz = max(max_ctz, ctz)

#     windowed_shift_down(W, R, ctz)
#     k += ctz
#     pow_k = ((1 << ctz)*pow_k) % P

#     u, r, v, s = v, s, u, r
#     parity = not parity

#     L += R

#     while W != 0:

#         assert (L & 1) == 1

#         ctz = trailing_zeros(R)
#         max_ctz = max(max_ctz, ctz)
#         assert ctz > 0

#         windowed_shift_up(W, R, ctz)
#         W -= ctz
#         k += ctz
#         pow_k = ((1 << ctz)*pow_k) % P
#         shifts += 1


#         if u > v:
#             u, r, v, s = v, s, u, r
#             parity = not parity

#         v -= u
#         s += r
#         k += 1

#         pow_k = (2*pow_k) % P

#         iters += 1

#     print(f"{shifts} shifts, k={k}, {iters} iters, max ctz {max_ctz}")

#     assert u == 1
#     if r >= P:
#         r -= P
#     assert r < P
#     ret = (r if parity else P-r)
#     assert (ret*x) % P == pow_k % P
#     return (ret, k)



schedule = {}

def update_schedule(i,u,v,r,s):
    u = u.bit_length()
    v = v.bit_length()
    r = r.bit_length()
    s = s.bit_length()

    if i not in schedule:
        schedule[i] = {'u':{},'v':{},'r':{},'s':{}}
    for (k,v) in [('u',u),('v',v),('r',r),('s',s)]:
        if v not in schedule[i][k]:
            schedule[i][k][v] = 0
        schedule[i][k][v] += 1

def get_p999(hist):
    tot = sum(hist.values())
    cum = 0
    for (i,count) in sorted(list(hist.items())):
        if (cum + count) >= 0.999*tot:
            return i
        cum += count
    return max(hist)

def pz_small_step_dialog(x):
    sgn = (x > P//2)
    if sgn: x = P-x

    A, B = P,x
    a, b = 0,1

    div_leftward = True


    i = 0

    dialog = []

    s = 0

    while A != 0 or s != 0:
        update_schedule(i,A,B,0,0)
        i += 1
        # print(A,B,s)
        # print(A,B,a,b)
        # print(s_div,div_leftward,div_active)
        # print(s_mul,mul_active)

        dialog.append(A >= B)
        if A >= B:
            A -= B
        elif div_leftward:
            div_leftward = False

        if div_leftward:
            B <<= 2
            s += 2
        elif s == 0:
            if A != 0:
                A,B = B,A
                div_leftward = True
        else:
            B >>= 1
            s -= 1
            if s == 0 and A == 0:
                dialog.append(False)
    assert s == 0

    # print(len(dialog))
    # assert i == len(dialog)

    s = 0
    parity = True
    leftward = True
    for l in dialog:
        # print(a,b,s)
        if l:
            a += b
        elif leftward:
            leftward = False

        if leftward:
            s += 2
            b <<= 2
        elif s == 0:
            a,b = b,a
            leftward = True
            parity = not parity
        else:
            s -= 1
            b >>= 1
    assert leftward == True
    assert s == 0

    assert A == 0 and B == 1 and b == P, \
            f"A {A} B {B} a {a} b {b}"
    if parity:
        a = P-a
    assert (a*x)%P == 1, f"{a}*{x}"
    if sgn:
        a = P-a
    return a


def pz_small_step(x):
    sgn = (x > P//2)
    if sgn: x = P-x

    A, B = P,x
    a, b = 0,1

    q_div, q_mul = 0,0
    mul_active = False
    mul_leftward = True

    s_div,s_mul = 0,0
    div_active = True
    div_leftward = True

    parity = True

    i = 0

    while div_active or mul_active:
        update_schedule(i,A,B,a,b)
        i += 1
        # print(A,B,a,b)
        # print(s_div,div_leftward,div_active)
        # print(s_mul,mul_active)

        if A >= B:
            A -= B
            q_div += (1<<s_div)
            if div_leftward:
                s_div += 1
                B <<= 1
            elif s_div == 0:
                div_active = False
                div_leftward = True
            else:
                s_div -= 1
                B >>= 1
        elif div_leftward:
            div_leftward = False
            if s_div != 0:
                s_div -= 1
                B >>= 1
        elif s_div != 0:
            s_div -= 1
            B >>= 1
        else:
            div_active = False
            div_leftward = False

        if not div_active and not mul_active and q_div != 0:
            assert q_mul == 0
            assert A < B
            q_div,q_mul = q_mul,q_div
            if A != 0:
                A,B = B,A

            mul_active = True
            div_active = True
            div_leftward = True

        if mul_active:
            if q_mul != 0:
                do_mul = (q_mul&1)
                q_mul ^= do_mul
                if do_mul != 0:
                    a += b
                do_mul ^= (a >= b)
                q_mul >>= 1
                s_mul += 1
                b <<= 1
            elif s_mul != 0:
                s_mul -= 1
                b >>= 1
            else:
                a,b = b,a
                parity = not parity

                mul_active = False

        if not div_active and not mul_active and q_div != 0:
            assert q_mul == 0
            assert A < B
            q_div,q_mul = q_mul,q_div
            if A != 0:
                A,B = B,A

            mul_active = True
            div_active = True
            div_leftward = True

    assert A == 0 and B == 1 and b == P, \
            f"A {A} B {B} b {b}"
    if parity:
        a = P-a
    assert (a*x)%P == 1
    if sgn:
        a = P-a
    return a


def pz_big_step(x):
    sgn = (x > P//2)
    if sgn: x = P-x

    A, B = P,x
    a, b = 0,1

    q_div, q_mul = 0,0
    mul_active = False
    mul_leftward = True

    s_div,s_mul = 0,0
    div_active = True

    parity = True

    i = 0

    # for _ in range(470):
    while div_active or mul_active:
        # print(A,B,a,b,q_div,q_mul)
        update_schedule(i,A,B,a,b)
        i += 1

        s = A.bit_length()-B.bit_length()

        offset = False
        if s >= 0:
            B <<= s
            assert A.bit_length() == B.bit_length()
            offset = (A < B)
        if offset:
            s -= 1
            if s >= 0:
                B >>= 1
        if s >= 0 and A >= B:
            offset ^= (A.bit_length() != B.bit_length())
            assert offset == 0
            A -= B
            B >>= s
            assert q_div&((1<<(s+1))-1) == 0
            q_div ^= (1<<s)
            s -= trailing_zeros(q_div)
            assert s == 0
        else:
            assert s <= 0
            if offset:
                s += 1
            offset ^= (s >= 0 and A < B)
            s -= A.bit_length()-B.bit_length()
            assert s == 0 and offset == 0, f"{s} {offset}"

            div_active = False

        if not div_active and not mul_active and q_div != 0:
            assert q_mul == 0
            assert A < B
            q_div,q_mul = q_mul,q_div
            assert q_mul != 0
            if A != 0:
                A,B = B,A
                assert B < A

            mul_active = True
            div_active = True

        if mul_active:
            if q_mul != 0:
                s = trailing_zeros(q_mul)
                assert (q_mul&(1<<s)) == (1<<s)
                q_mul ^= (1<<s)
                b <<= s

                a += b

                o = (a.bit_length() != b.bit_length())
                if o:
                    b <<= 1
                    s += 1
                assert a.bit_length() == b.bit_length(), \
                        f"{a.bit_length()} {b.bit_length()} {a:x} {b:x}"

                o ^= (a < b)

                assert o == 0

                b >>= s
                s -= a.bit_length()-b.bit_length()
                assert s == 0 , f"{s} {a:x}, {b:x}"
            if q_mul == 0:
                a,b = b,a
                assert a < b
                parity = not parity

                mul_active = False

        if not div_active and not mul_active and q_div != 0:
            assert q_mul == 0
            assert A < B
            q_div,q_mul = q_mul,q_div
            assert q_mul != 0
            if A != 0:
                A,B = B,A

            mul_active = True
            div_active = True

    assert A == 0 and B == 1 and b == P, \
            f"A {A} B {B} b {b}"
    if parity:
        a = P-a
    assert (a*x)%P == 1
    if sgn:
        a = P-a
    return a


def pz_big_step_v2(x_orig, n_iters = 350):
    """Return the convergence iter (first idle step: A=0,B=1,q_div=0,q_mul=0)."""
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q_div, q_mul = 0, 0
    i = 0
    parity = True
    tape_len = 0
    for _ in range(n_iters):
        update_schedule(i,A,B,ca,cb)
        i += 1

        active = not (A == 0 and B == 1 and q_div == 0 and q_mul == 0)

        s = A.bit_length() - B.bit_length()
        offset = False
        if active:
            if s >= 0:
                B <<= s
                assert A.bit_length() == B.bit_length()
                offset = (A < B)
            if offset:
                s -= 1
                if s >= 0:
                    B >>= 1
            if s >= 0:
                offset ^= (A.bit_length() != B.bit_length())
                assert A >= B
                A -= B
                B >>= s
                q_div ^= (1 << s)
                s -= trailing_zeros(q_div)
                assert offset == 0 and s == 0, f"{offset} {s}"
            else:
                if offset:
                    s += 1
                offset ^= (s >= 0 and A < B)
                s -= A.bit_length()-B.bit_length()
                assert offset == 0 and s == 0, f"{offset} {s}"
        else:
            s += 1

        assert offset == 0 and s == 0, f"{offset} {s}"

        if active:
            if A < B and q_div != 0 and q_mul == 0:
                tape_len += 5 + q_div.bit_length()
                q_div, q_mul = q_mul, q_div
                if A != 0:
                    A, B = B, A
            if q_mul != 0:
                s2 = trailing_zeros(q_mul)
                q_mul ^= (1 << s2)
                cb <<= s2
                ca = ca + cb
                o = (ca.bit_length() != cb.bit_length())
                if o:
                    cb <<= 1
                    s2 += 1
                cb >>= s2
                if q_mul == 0:
                    ca, cb = cb, ca
                    parity = not parity

    print(tape_len)

    assert A == 0 and B == 1 and cb == P, \
            f"A {A} B {B} b {cb}"
    if parity:
        ca = P-ca
    assert (ca*x)%P == 1
    if sgn:
        ca = P-ca
    return ca

def pz_big_step_v3(x_orig, n_iters = 520):
    """Return the convergence iter (first idle step: A=0,B=1,q_div=0,q_mul=0)."""
    sgn = x_orig > P // 2
    x = P - x_orig if sgn else x_orig
    A, B = P, x
    ca, cb = 0, 1
    q = 0
    i = 0
    parity = True
    # while not (A == 0 and B == 1 and q == 0):
    for _ in range(n_iters):
        # print(A,B,ca,cb,q)
        update_schedule(i,A,B,ca,cb)


        i += 1

        active = not (A == 0 and B == 1 and q == 0)

        offset = False
        if active:
            if A >= B:
                s = A.bit_length() - B.bit_length()
                B <<= s
                assert A.bit_length() == B.bit_length()
                offset = (A < B)
                if offset:
                    s -= 1
                    if s >= 0:
                        B >>= 1
                if s >= 0:
                    offset ^= (A.bit_length() != B.bit_length())
                    assert A >= B
                    A -= B
                    B >>= s
                    q ^= (1 << s)
                    s -= trailing_zeros(q)
                    assert offset == 0 and s == 0, f"{offset} {s}"
            else:

                s2 = trailing_zeros(q)
                q ^= (1 << s2)
                cb <<= s2
                ca = ca + cb
                o = (ca.bit_length() != cb.bit_length())
                if o:
                    cb <<= 1
                    s2 += 1
                cb >>= s2
            if q == 0 and A != 0:
                A,B = B,A
                ca, cb = cb, ca
                parity = not parity


    assert A == 0 and B == 1 and ca == P, \
            f"A {A} B {B} a {ca} b {cb}"
    if not parity:
        cb = P-cb
    assert (cb*x)%P == 1
    if sgn:
        cb = P-cb
    return cb



def bin_eea(x):
    assert x < P and x > 0

    u, v = P, x
    r, s = 0, 1

    pack_bound = max(r.bit_length(),s.bit_length()) + max(u.bit_length(),v.bit_length())

    parity = False
    shifts = 0
    iters = 0
    max_ctz = 0

    update_schedule(iters,u,v,r,s)

    while v != 0:
        print(u,v,r,s)
        assert (u & 1) == 1
        assert ((r*x)) % P == ((u if parity else -u)) % P
        assert ((s*x)) % P == ((-v if parity else v)) % P


        # print(u.bit_length(), r.bit_length(), v.bit_length(),
        #       s.bit_length(), trailing_zeros(r), trailing_zeros(s))

        if (v&1) == 1 and u > v:
            u,v = v,u
            r,s = s,r
            parity = not parity
            assert ((r*x)) % P == ((u if parity else -u)) % P
            assert ((s*x)) % P == ((-v if parity else v)) % P
            v -= u
            s += r
        elif (v&1) == 1:
            v -= u
            s += r
            assert ((r*x)) % P == ((u if parity else -u)) % P
            assert ((s*x)) % P == ((-v if parity else v)) % P

        assert (v&1) == 0

        v >>= 1
        s <<= 1


        update_schedule(iters,u,v,r,s)

        iters += 1

    # print(f"{shifts} shifts, k={k}, {iters} iters, max ctz {max_ctz}, max "
    #       + f"pack {pack_bound} swaps {swaps} ctz_avg {ctz_avg}")

    assert u == 1
    ret = (r if parity else P-r)
    assert (ret*x) % P == 1
    return (ret)

def kaliski_phase1(x):
    assert x < P and x > 0

    u, v = P, x
    r, s = 0, 1

    pack_bound = max(r.bit_length(),s.bit_length()) + max(u.bit_length(),v.bit_length())

    k = 0
    pow_k = 1

    parity = False
    shifts = 0
    iters = 0
    max_ctz = 0

    ctz = trailing_zeros(v)
    max_ctz = max(max_ctz, ctz)

    v >>= ctz
    r <<= ctz
    k += ctz
    pow_k = ((1 << ctz)*pow_k) % P

    if u > v:
        u, r, v, s = v, s, u, r
        parity = not parity

    v -= u
    s += r
    swaps = 0
    ctz_tot = ctz

    update_schedule(iters,u,v,r - trailing_zeros(r),s-trailing_zeros(s))

    while v != 0:
        assert (u & 1) == 1
        assert ((r*x)) % P == ((u if parity else -u)*pow_k) % P
        assert ((s*x)) % P == ((-v if parity else v)*pow_k) % P


        # print(u.bit_length(), r.bit_length(), v.bit_length(),
        #       s.bit_length(), trailing_zeros(r), trailing_zeros(s))

        ctz = min(4,trailing_zeros(v))
        max_ctz = max(max_ctz, ctz)
        assert ctz >= 0


        v >>= ctz
        r <<= ctz
        k += ctz
        pow_k = ((1 << ctz)*pow_k) % P
        shifts += 1
        ctz_tot += ctz

        update_schedule(iters,u,v,r - trailing_zeros(r),s-trailing_zeros(s))

        # assert v.bit_length() + s.bit_length() <= 257
        assert v.bit_length() + r.bit_length() <= 257
        assert u.bit_length() + s.bit_length() <= 257

        if (v & 1) == 1:
            if u > v:
                u, r, v, s = v, s, u, r
                parity = not parity
                swaps += 1
            v -= u
            s += r


        pack_bound = max(pack_bound,max(r.bit_length(),s.bit_length()) +
                         max(u.bit_length(),v.bit_length()))

        # print(u.bit_length(),r.bit_length(),v.bit_length(),s.bit_length())
        assert v.bit_length() + r.bit_length() <= 257

        iters += 1

    ctz_avg = ctz_tot/iters

    # print(f"{shifts} shifts, k={k}, {iters} iters, max ctz {max_ctz}, max "
    #       + f"pack {pack_bound} swaps {swaps} ctz_avg {ctz_avg}")

    assert u == 1
    if r >= P:
        r -= P
    assert r < P
    ret = (r if parity else P-r)
    assert (ret*x) % P == pow_k % P
    return (ret, k)


def kaliski_phase2(r, k):
    while k > 0:
        if (r & 1) == 0:
            r >>= 1
        else:
            r = (r+P) >> 1
        k -= 1
    return r


def mod_inv(x):
    # return kaliski_phase2(*kaliski_phase1(x))
    # return pz_big_step(x)
    # return pz_big_step_v2(x)
    # return pz_big_step_v3(x)
    # return bin_eea(x)
    # return pz_small_step(x)
    return pz_small_step_dialog(x)


for _ in range(10000):
    x = random.randrange(1, P)
    x_inv = mod_inv(x)
    assert x_inv > 0 and x_inv < P, f"expected 0 < {x_inv} < P"
    prod = (x*x_inv) % P
    assert prod == 1, f"{x}*{x_inv} == {prod} (expected 1)"

max_size = 0

for (i,hist) in sorted(list(schedule.items())):
    u = get_p999(hist['u'])
    v = get_p999(hist['v'])
    r = get_p999(hist['r'])
    s = get_p999(hist['s'])

    size = u+v+r+s
    print(i,u,v,r,s,size)
    max_size = max(max_size,size)
print(f"max size: {max_size}")

