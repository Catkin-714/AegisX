//! Π_exp — MCU 安全指数协议
//! 对标 Python `exponential.py`
//!
//! 恒等式: e^x = e^((x+r) mod M) · e^(w·M - r)
//! 通信: 指数约 1 轮 + wrap 检测 2 轮 ≈ 3-4 轮

use crate::mock_comm::{MockCommHP, MockCommParty};
use crate::prg::PrgSync;
use crate::wrap_detect;
use serde_json::json;

pub const MOD: f64 = 256.0;

/// f64 取模（行为与 Python `%` 一致：结果始终非负）
fn fmod(a: f64, m: f64) -> f64 {
    let r = a % m;
    if r < 0.0 { r + m } else { r }
}

/// P0/P1: 输入 [x]_i → 输出 [e^x]_i
pub fn exp(party_id: u8, prg: &mut PrgSync, share_x: f64, comm: &MockCommParty) -> f64 {
    // 掩码 r（两方 PRG0 同步）
    let r = prg.next_real(MOD);

    // 第 1 轮：发送掩码份额
    let m_i = if party_id == 0 {
        fmod(share_x + r, MOD)
    } else {
        fmod(share_x, MOD)
    };
    comm.send_to_hp(json!({"m": m_i}));

    // 接收 e^R 份额
    let s_i = comm.recv_from_hp()["s"].as_f64().unwrap();

    // 第 2-3 轮：Wrap 检测
    let w = wrap_detect::wrap(party_id, prg, share_x, r, comm) as f64;

    // 去掩码
    let correction = (w * MOD - r).exp();
    s_i * correction
}

// ── HP ──

/// HP: 协助一次指数运算
pub fn serve_exp(asprg: &mut PrgSync, comm: &MockCommHP) {
    // 第 1 轮：聚合掩码值
    let m0 = comm.recv_from_p0()["m"].as_f64().unwrap();
    let m1 = comm.recv_from_p1()["m"].as_f64().unwrap();
    let r_val = fmod(m0 + m1, MOD);
    let e_val = r_val.exp();

    // 拆成正份额
    let u = asprg.next_f64();
    let s0 = u * e_val;
    let s1 = e_val - s0;
    comm.send_to_p0(json!({"s": s0}));
    comm.send_to_p1(json!({"s": s1}));

    // 第 2-3 轮：协助 wrap 检测
    wrap_detect::serve_wrap(comm);
}

// ── 测试 ──

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock_comm::make_mock_comm;

    #[test]
    fn test_exp_precision() {
        let shared_seed: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();
        let hp_seed: [u8; 16] = (16u8..32).collect::<Vec<_>>().try_into().unwrap();

        let n = 200;
        let mut sum_err = 0.0f64;
        let mut max_err = 0.0f64;

        for i in 0..n {
            let x = ((i as f64) - 100.0) * 0.1; // [-10, 10)
            let x0 = x * 0.7;
            let x1 = x - x0;
            let expected = x.exp();

            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

            let (e0, e1) = std::thread::scope(|s| {
                let mut prg0 = PrgSync::new(&shared_seed);
                let mut prg1 = PrgSync::new(&shared_seed);
                let mut asprg = PrgSync::new(&hp_seed);
                let t0 = s.spawn(move || exp(0, &mut prg0, x0, &comm_p0));
                let t1 = s.spawn(move || exp(1, &mut prg1, x1, &comm_p1));
                serve_exp(&mut asprg, &comm_hp);
                (t0.join().unwrap(), t1.join().unwrap())
            });

            let result = e0 + e1;
            let err = (result - expected).abs();
            sum_err += err;
            max_err = max_err.max(err);
        }

        let avg = sum_err / n as f64;
        println!("Exp: n={n}, avg_err={avg:.3e}, max_err={max_err:.3e}");
        assert!(avg < 1e-4, "average error too large: {avg:.3e}");
    }
}
