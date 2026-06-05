import random
import sys

_, bits, shots = sys.argv
bits = int(bits)
shots = int(shots)
n = 1 << bits

for _ in range(shots):
    a = random.randrange(n)
    b = random.randrange(n)
    print(a, b, '->', (a + b) % n, b)
