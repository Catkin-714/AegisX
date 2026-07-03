//! Π_gelu — MCU 安全 GeLU 协议（含 Π_sigmoid）
//! 对标 Python `gelu.py`
//!
//! GeLU(x) = x · sigmoid(1.702·x)
//! Sigmoid(z) = e^z / (1 + e^z)
//!
//! 通信: Sigmoid ≈ 6 轮 + 实数乘法 2 轮 ≈ 8 轮

use crate::exponential;
use crate::mock_comm::{MockCommHP, MockCommParty};
use crate::prg::PrgSync;
use serde_json::json;

pub const MOD: f64 = exponential::MOD;
const GELU_COEF: f64 = 1.702;

// ═══════════════════════════════════════════════════════════════
// Π_sigmoid
// ═══════════════════════════════════════════════════════════════

/// P0/P1: 输入 [z]_i → 输出 [sigmoid(z)]_i
pub fn sigmoid(party_id: u8, prg: &mut PrgSync, share_z: f64, comm: &MockCommParty) -> f64 {
    // 1. 指数
    let e_i = exponential::exp(party_id, prg, share_z, comm);

    // 2. 分母份额: 1 + e^z（常数 1 仅 P0 承担）
    let d_i = e_i + if party_id == 0 { 1.0 } else { 0.0 };

    // 3. 掩码求和
    let t = prg.next_real(MOD);
    let et = t.exp();
    comm.send_to_hp(json!({"u": et * d_i}));
    let d_pub = comm.recv_from_hp()["D"].as_f64().unwrap();

    // 4. 本地相除
    e_i * et / d_pub
}

/// HP: 协助一次 sigmoid
pub fn serve_sigmoid(asprg: &mut PrgSync, comm: &MockCommHP) {
    exponential::serve_exp(asprg, comm);
    let u0 = comm.recv_from_p0()["u"].as_f64().unwrap();
    let u1 = comm.recv_from_p1()["u"].as_f64().unwrap();
    let d_pub = u0 + u1;
    comm.send_to_p0(json!({"D": d_pub}));
    comm.send_to_p1(json!({"D": d_pub}));
}

// ═══════════════════════════════════════════════════════════════
// Π_gelu
// ═══════════════════════════════════════════════════════════════

/// P0/P1: 输入 [x]_i → 输出 [GeLU(x)]_i
pub fn gelu(party_id: u8, prg: &mut PrgSync, share_x: f64, comm: &MockCommParty) -> f64 {
    // 1. 本地缩放
    let scaled = GELU_COEF * share_x;

    // 2. Sigmoid
    let sig_i = sigmoid(party_id, prg, scaled, comm);

    // 3. 实数域安全乘法: x · sigmoid
    let r_a = prg.next_real(MOD);
    let r_b = prg.next_real(MOD);

    if party_id == 0 {
        comm.send_to_hp(json!({"ma": share_x + r_a, "mb": sig_i + r_b}));
    } else {
        comm.send_to_hp(json!({"ma": share_x, "mb": sig_i}));
    }

    let s_i = comm.recv_from_hp()["s"].as_f64().unwrap();

    let correction = if party_id == 0 {
        share_x * r_b + sig_i * r_a + r_a * r_b
    } else {
        share_x * r_b + sig_i * r_a
    };

    s_i - correction
}

/// HP: 协助一次 gelu
pub fn serve_gelu(asprg: &mut PrgSync, comm: &MockCommHP) {
    // 1. 协助 sigmoid
    serve_sigmoid(asprg, comm);

    // 2. 实数乘法
    let m0 = comm.recv_from_p0();
    let m1 = comm.recv_from_p1();
    let ma = m0["ma"].as_f64().unwrap() + m1["ma"].as_f64().unwrap();
    let mb = m0["mb"].as_f64().unwrap() + m1["mb"].as_f64().unwrap();
    let product = ma * mb;

    let u = asprg.next_f64();
    let s0 = u * product;
    let s1 = product - s0;
    comm.send_to_p0(json!({"s": s0}));
    comm.send_to_p1(json!({"s": s1}));
}

// ── 测试 ──

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock_comm::make_mock_comm;

    fn plaintext_sigmoid(z: f64) -> f64 {
        1.0 / (1.0 + (-z).exp())
    }

    fn plaintext_gelu(x: f64) -> f64 {
        x * plaintext_sigmoid(GELU_COEF * x)
    }

    fn shared_seed() -> [u8; 16] {
        (0u8..16).collect::<Vec<_>>().try_into().unwrap()
    }
    fn hp_seed() -> [u8; 16] {
        (16u8..32).collect::<Vec<_>>().try_into().unwrap()
    }

    #[test]
    fn test_sigmoid_precision() {
        let n = 100;
        let mut max_err = 0.0f64;
        let mut sum_err = 0.0f64;

        for i in 0..n {
            let z = ((i as f64) - 50.0) * 0.16; // [-8, 8)
            let z0 = z * 0.7;
            let z1 = z - z0;
            let expected = plaintext_sigmoid(z);

            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

            let (s0, s1) = std::thread::scope(|s| {
                let mut prg0 = PrgSync::new(&shared_seed());
                let mut prg1 = PrgSync::new(&shared_seed());
                let mut asprg = PrgSync::new(&hp_seed());
                let t0 = s.spawn(move || sigmoid(0, &mut prg0, z0, &comm_p0));
                let t1 = s.spawn(move || sigmoid(1, &mut prg1, z1, &comm_p1));
                serve_sigmoid(&mut asprg, &comm_hp);
                (t0.join().unwrap(), t1.join().unwrap())
            });

            let err = (s0 + s1 - expected).abs();
            max_err = max_err.max(err);
            sum_err += err;
        }

        let avg = sum_err / n as f64;
        println!("Sigmoid: n={n}, avg_err={avg:.3e}, max_err={max_err:.3e}");
        assert!(max_err < 1e-4, "max error: {max_err:.3e}");
    }

    #[test]
    fn test_gelu_precision() {
        let n = 200;
        let mut max_err = 0.0f64;
        let mut sum_err = 0.0f64;

        for i in 0..n {
            let x = ((i as f64) - 100.0) * 0.05; // [-5, 5)
            let x0 = x * 0.7;
            let x1 = x - x0;
            let expected = plaintext_gelu(x);

            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

            let (g0, g1) = std::thread::scope(|s| {
                let mut prg0 = PrgSync::new(&shared_seed());
                let mut prg1 = PrgSync::new(&shared_seed());
                let mut asprg = PrgSync::new(&hp_seed());
                let t0 = s.spawn(move || gelu(0, &mut prg0, x0, &comm_p0));
                let t1 = s.spawn(move || gelu(1, &mut prg1, x1, &comm_p1));
                serve_gelu(&mut asprg, &comm_hp);
                (t0.join().unwrap(), t1.join().unwrap())
            });

            let err = (g0 + g1 - expected).abs();
            max_err = max_err.max(err);
            sum_err += err;
        }

        let avg = sum_err / n as f64;
        println!("GeLU: n={n}, avg_err={avg:.3e}, max_err={max_err:.3e}");
        assert!(avg < 1e-3, "average error: {avg:.3e}");
    }
}
