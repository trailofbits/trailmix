/// This file contains code for performing elliptic curve point arithmetic.
/// Note: only supports curves in weierstrass form.
/// Note: only supports curves with a prime modulus less than pow(2, 256).


use ruint::aliases::U256;

/// Elliptic curve parameters, including the generator and its order.
/// A point (x, y) is on the curve if it satisfies y*y = x*x*x + a*x + b (mod modulus).
/// The point (gx, gy) is a generator with a known order for the curve.
#[derive(Clone, Debug, PartialEq)]
pub struct WeierstrassEllipticCurve {
    pub a: U256,
    pub b: U256,
    pub gx: U256,
    pub gy: U256,
    pub modulus: U256,
    pub order: U256,
}

/// Computes a - b (mod m).
pub fn sub_mod(a: U256, b: U256, m: U256) -> U256 {
    let a_m = a % m;
    let b_m = b % m;
    if a_m >= b_m {
        a_m - b_m
    } else {
        m - (b_m - a_m)
    }
}

impl WeierstrassEllipticCurve {
    pub fn is_on_curve(&self, x: U256, y: U256) -> bool {
        if x.is_zero() && y.is_zero() {
            return true; // Point at infinity
        }
        let lhs = y.mul_mod(y, self.modulus);
        let rhs = x
            .mul_mod(x, self.modulus)
            .mul_mod(x, self.modulus)
            .add_mod(self.a.mul_mod(x, self.modulus), self.modulus)
            .add_mod(self.b, self.modulus);
        lhs == rhs
    }

    pub fn discriminant(&self) -> U256 {
        // -16*(4a^3 + 27b^2) mod m
        let a3 = self.a.mul_mod(self.a, self.modulus).mul_mod(self.a, self.modulus);
        let b2 = self.b.mul_mod(self.b, self.modulus);
        let inner = U256::from(4)
            .mul_mod(a3, self.modulus)
            .add_mod(U256::from(27).mul_mod(b2, self.modulus), self.modulus);
        let sixteen = U256::from(16) % self.modulus;
        sub_mod(U256::ZERO, sixteen.mul_mod(inner, self.modulus), self.modulus)
    }

    pub fn verify(&self) {
        assert!(self.modulus > U256::from(3), "Modulus too small");
        assert!(!self.discriminant().is_zero(), "Discriminant is zero");
        assert!(self.is_on_curve(self.gx, self.gy), "Generator not on curve");
        
        let (ox, oy) = self.mul(self.gx, self.gy, self.order);
        assert!(ox.is_zero() && oy.is_zero(), "Generator order is wrong");
    }

    pub fn add(&self, x1: U256, y1: U256, x2: U256, y2: U256) -> (U256, U256) {
        if x1.is_zero() && y1.is_zero() { return (x2, y2); }
        if x2.is_zero() && y2.is_zero() { return (x1, y1); }

        if x1 == x2 {
            if y1.add_mod(y2, self.modulus).is_zero() {
                return (U256::ZERO, U256::ZERO);
            } else {
                // lambda = (3x1^2 + a) / 2y1
                let num = x1.mul_mod(x1, self.modulus).mul_mod(U256::from(3), self.modulus).add_mod(self.a, self.modulus);
                let den = y1.mul_mod(U256::from(2), self.modulus);
                let den_inv = den.inv_mod(self.modulus).expect("Denominator not invertible in doubling");
                let lambda = num.mul_mod(den_inv, self.modulus);
                let x3 = sub_mod(lambda.mul_mod(lambda, self.modulus), x1.mul_mod(U256::from(2), self.modulus), self.modulus);
                let y3 = sub_mod(lambda.mul_mod(sub_mod(x1, x3, self.modulus), self.modulus), y1, self.modulus);
                return (x3, y3);
            }
        }

        // lambda = (y2 - y1) / (x2 - x1)
        let num = sub_mod(y2, y1, self.modulus);
        let den = sub_mod(x2, x1, self.modulus);
        let den_inv = den.inv_mod(self.modulus).expect("Denominator not invertible in addition");
        let lambda = num.mul_mod(den_inv, self.modulus);
        let x3 = sub_mod(sub_mod(lambda.mul_mod(lambda, self.modulus), x1, self.modulus), x2, self.modulus);
        let y3 = sub_mod(lambda.mul_mod(sub_mod(x1, x3, self.modulus), self.modulus), y1, self.modulus);
        (x3, y3)
    }

    pub fn mul(&self, x: U256, y: U256, n: U256) -> (U256, U256) {
        let mut res = (U256::ZERO, U256::ZERO);
        let mut base = (x, y);
        let mut exp = n;
        while !exp.is_zero() {
            if exp.bit(0) {
                res = self.add(res.0, res.1, base.0, base.1);
            }
            base = self.add(base.0, base.1, base.0, base.1);
            exp >>= 1;
        }
        res
    }
}
