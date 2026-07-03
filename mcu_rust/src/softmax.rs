//! Π_softmax — MCU 安全 Softmax 协议
//! 对标 Python `softmax.py`
//!
//! 流程: k 路并行 Π_exp → 掩码求和(分母公开) → 本地相除
//! 通信: k 路指数(可并行) + 掩码求和 ≈ 6 轮

use crate::exponential;
use crate::mock_comm::{MockCommHP, MockCommParty};
use crate::prg::PrgSync;
use serde_json::json;

pub const MOD: f64 = exponential::MOD;

/// P0/P1: 输入 shares = [[x_1]_i, ...]，返回 [softmax(x_m)]_i
pub fn softmax(
    party_id: u8,
    prg: &mut PrgSync,
    shares: &[f64],
    m: usize,
    comm: &MockCommParty,
) -> f64 {
    let k = shares.len();

    // 1. k 路指数
    let mut exp_shares = Vec::with_capacity(k);
    for &s in shares {
        exp_shares.push(exponential::exp(party_id, prg, s, comm));
    }

    // 2. 掩码求和
    let t = prg.next_real(MOD);
    let et = t.exp();
    let p_i: f64 = exp_shares.iter().sum();
    comm.send_to_hp(json!({"u": et * p_i}));
    let d_pub = comm.recv_from_hp()["D"].as_f64().unwrap();

    // 3. 本地相除
    exp_shares[m] * et / d_pub
}

// ── HP ──

/// HP: 协助 k 路 softmax
pub fn serve_softmax(asprg: &mut PrgSync, comm: &MockCommHP, k: usize) {
    // 1. 协助 k 路指数
    for _ in 0..k {
        exponential::serve_exp(asprg, comm);
    }

    // 2. 聚合掩码分母并广播
    let u0 = comm.recv_from_p0()["u"].as_f64().unwrap();
    let u1 = comm.recv_from_p1()["u"].as_f64().unwrap();
    let d_pub = u0 + u1;
    comm.send_to_p0(json!({"D": d_pub}));
    comm.send_to_p1(json!({"D": d_pub}));
}

// ── 测试 ──

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock_comm::make_mock_comm;

    fn plaintext_softmax(xs: &[f64]) -> Vec<f64> {
        let mx = xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let exps: Vec<f64> = xs.iter().map(|v| (v - mx).exp()).collect();
        let s: f64 = exps.iter().sum();
        exps.iter().map(|e| e / s).collect()
    }

    #[test]
    fn test_softmax_precision() {
        let shared_seed: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();
        let hp_seed: [u8; 16] = (16u8..32).collect::<Vec<_>>().try_into().unwrap();
        let n_tests = 20;
        let k = 6;

        let mut max_err = 0.0f64;
        let mut sum_err = 0.0f64;
        let mut count = 0;

        for t in 0..n_tests {
            // 确定性输入
            let xs: Vec<f64> = (0..k)
                .map(|j| ((t * k + j) as f64 - (n_tests * k / 2) as f64) * 0.3)
                .collect();
            let xs0: Vec<f64> = xs.iter().map(|v| v * 0.6).collect();
            let xs1: Vec<f64> = xs.iter().zip(&xs0).map(|(v, v0)| v - v0).collect();
            let expected = plaintext_softmax(&xs);

            for m in 0..k {
                let xs0_m = xs0.clone();
                let xs1_m = xs1.clone();
                let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

                let (s0, s1) = std::thread::scope(|s| {
                    let mut prg0 = PrgSync::new(&shared_seed);
                    let mut prg1 = PrgSync::new(&shared_seed);
                    let mut asprg = PrgSync::new(&hp_seed);
                    let t0 = s.spawn(move || softmax(0, &mut prg0, &xs0_m, m, &comm_p0));
                    let t1 = s.spawn(move || softmax(1, &mut prg1, &xs1_m, m, &comm_p1));
                    serve_softmax(&mut asprg, &comm_hp, k);
                    (t0.join().unwrap(), t1.join().unwrap())
                });

                let result = s0 + s1;
                let err = (result - expected[m]).abs();
                max_err = max_err.max(err);
                sum_err += err;
                count += 1;
            }
        }

        let avg = sum_err / count as f64;
        println!("Softmax: count={count}, avg_err={avg:.3e}, max_err={max_err:.3e}");
        assert!(max_err < 1e-4, "max error too large: {max_err:.3e}");
    }
}
