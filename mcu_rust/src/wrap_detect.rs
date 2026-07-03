//! Wrap 检测子协议 — 对标 Python `wrap_detect.py`
//!
//! 目标: 给定秘密 x = x0 + x1、公开掩码 r、模数 M，
//! 计算 w = floor((x + r) / M) ∈ {-1, 0, 1}
//!
//! 无状态设计: 所有方法显式传入 &mut PrgSync，保证 counter 跨协议连续。

use crate::mock_comm::{MockCommHP, MockCommParty};
use crate::prg::PrgSync;
use serde_json::json;

pub const MOD: f64 = 256.0;
const SIGN_SCALE: f64 = (1u64 << 20) as f64;

/// 安全判断 x >= threshold → 1 / 0（P0/P1 调用）
fn sign_ge(party_id: u8, prg: &mut PrgSync, share_x: f64, threshold: f64, comm: &MockCommParty) -> i32 {
    let z_i = share_x - if party_id == 0 { threshold } else { 0.0 };
    let alpha = 1.0 + prg.next_real(SIGN_SCALE);
    comm.send_to_hp(json!({"za": alpha * z_i}));
    comm.recv_from_hp()["bit"].as_i64().unwrap() as i32
}

/// P0/P1: 返回 w = floor((x + r) / M)
pub fn wrap(party_id: u8, prg: &mut PrgSync, share_x: f64, r: f64, comm: &MockCommParty) -> i32 {
    let ge_hi = sign_ge(party_id, prg, share_x, MOD - r, comm);
    let ge_lo = sign_ge(party_id, prg, share_x, -r, comm);
    let c_hi = ge_hi;
    let c_lo = 1 - ge_lo;
    c_hi - c_lo
}

// ── HP ──

/// HP 处理一次符号比较
pub fn serve_sign(comm: &MockCommHP) {
    let za0 = comm.recv_from_p0()["za"].as_f64().unwrap();
    let za1 = comm.recv_from_p1()["za"].as_f64().unwrap();
    let bit = if za0 + za1 >= 0.0 { 1 } else { 0 };
    comm.send_to_p0(json!({"bit": bit}));
    comm.send_to_p1(json!({"bit": bit}));
}

/// HP 处理一次完整 wrap 检测（两次符号比较）
pub fn serve_wrap(comm: &MockCommHP) {
    serve_sign(comm);
    serve_sign(comm);
}

// ── 测试 ──

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock_comm::make_mock_comm;

    #[test]
    fn test_wrap_detection() {
        let shared_seed: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();

        let cases = [
            (100.0, 50.0, 0),
            (200.0, 100.0, 1),
            (-30.0, 10.0, -1),
            (-300.0, 100.0, -1),
            (255.0, 100.0, 1),
            (0.0, 0.0, 0),
            (50.0, 206.0, 1), // x+r=256=M
            (-255.0, 254.0, -1),
        ];

        for (i, &(x, r, expected)) in cases.iter().enumerate() {
            let x0 = x * 0.3;
            let x1 = x - x0;

            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

            let w = std::thread::scope(|s| {
                let mut prg0 = PrgSync::new(&shared_seed);
                let mut prg1 = PrgSync::new(&shared_seed);
                let t0 = s.spawn(move || wrap(0, &mut prg0, x0, r, &comm_p0));
                let t1 = s.spawn(move || wrap(1, &mut prg1, x1, r, &comm_p1));
                serve_wrap(&comm_hp);
                (t0.join().unwrap(), t1.join().unwrap())
            });

            assert_eq!(w.0, w.1, "case {i}: mismatch");
            assert_eq!(w.0, expected, "case {i}: x={x}, r={r}, w={}, expected {expected}", w.0);
        }
    }

    #[test]
    fn test_wrap_edge_cases() {
        let seed: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();

        // |x| >> M should produce w = -1 or 1 correctly
        let cases = [
            (-1000.0, 10.0, -1),  // x+r = -990 < 0
            (1000.0, 10.0, 1),    // x+r = 1010 > 256
            (-500.0, 600.0, 0),   // x+r = 100 in [0, 256)
            (200.0, 100.0, 1),    // x+r = 300 > 256
        ];
        for (i, &(x, r, expected)) in cases.iter().enumerate() {
            let x0 = x * 0.5; let x1 = x - x0;
            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();
            let w = std::thread::scope(|s| {
                let mut p0 = PrgSync::new(&seed);
                let mut p1 = PrgSync::new(&seed);
                let t0 = s.spawn(move || wrap(0, &mut p0, x0, r, &comm_p0));
                let t1 = s.spawn(move || wrap(1, &mut p1, x1, r, &comm_p1));
                serve_wrap(&comm_hp);
                (t0.join().unwrap(), t1.join().unwrap())
            });
            assert_eq!(w.0, expected, "edge case {i}: x={x}, r={r}, expected {expected}");
        }
    }
}
