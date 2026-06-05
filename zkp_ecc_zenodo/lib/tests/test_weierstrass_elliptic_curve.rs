use ruint::aliases::U256;

use zkp_ecc_lib::weierstrass_elliptic_curve::WeierstrassEllipticCurve;

#[cfg(test)]
mod weierstrass_elliptic_curve_tests {
    use super::*;

    #[test]
    fn test_secp256k1_arithmetic() {
        let curve = WeierstrassEllipticCurve {
            modulus: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16).unwrap(),
            a: U256::from(0),
            b: U256::from(7),
            gx: U256::from_str_radix("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16).unwrap(),
            gy: U256::from_str_radix("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16).unwrap(),
            order: U256::from_str_radix("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16).unwrap(),
        };
        curve.verify();

        let x1 = U256::from_str_radix("34179685888554155755839781063929600280404842489758242293688176408896338330160", 10).unwrap();
        let y1 = U256::from_str_radix("115032417360155650845602239133487143929079591511167044308608186044351128872956", 10).unwrap();
        let x2 = U256::from_str_radix("112941813065185284636179834410886220083022768386350425906133653860689564924441", 10).unwrap();
        let y2 = U256::from_str_radix("25616454461046262208909136549316241511440878886716458491094212409916288867506", 10).unwrap();
        let x3 = U256::from_str_radix("44526440932387464589154835875351320819776816161856811868894932119120549074642", 10).unwrap();
        let y3 = U256::from_str_radix("41980934615728080552191611489205209889920921445773709176816577019517115724061", 10).unwrap();
        let x4 = U256::from_str_radix("97553936078686945997560491851858714374006000272409909097366165221474118799450", 10).unwrap();
        let y4 = U256::from_str_radix("85315618976048794194744942360848430326483620314346177154556566691090953236568", 10).unwrap();
        assert!(curve.add(x1, y1, x2, y2) == (x3, y3));
        assert!(curve.add(x1, y1, x1, y1) == (x4, y4));
    }
}
