//! Π_mul — MCU 安全乘法协议（2 轮通信）
//!
//! 所有算术在 Z_{2^64} 整数环上，使用 u64 wrapping 操作，
//! 与 Python `party.py` / `multiply.py` 中 `L = 2**64` 完全一致。

use crate::mock_comm::{MockCommHP, MockCommParty};
use crate::prg::PrgSync;
use serde_json::json;

// ── Z_{2^64} 环上的算术（wrapping = 自动 mod 2^64）──

fn add_mod(a: u64, b: u64) -> u64 { a.wrapping_add(b) }
fn sub_mod(a: u64, b: u64) -> u64 { a.wrapping_sub(b) }
fn mul_mod(a: u64, b: u64) -> u64 { a.wrapping_mul(b) }

// ── P0 / P1 角色 ──

pub struct MultiplyParty {
    pub party_id: u8,
    prg0: PrgSync,
}

impl MultiplyParty {
    pub fn new(party_id: u8, prg0: PrgSync) -> Self {
        assert!(party_id == 0 || party_id == 1);
        MultiplyParty { party_id, prg0 }
    }

    /// 执行一次安全乘法，返回本方持有的 `[x*y]` 份额
    pub fn multiply(&mut self, share_x: u64, share_y: u64, comm: &MockCommParty) -> u64 {
        // 公开掩码（P0/P1 的 PRG0 同种子 → 同 r_x, r_y）
        let r_x = self.prg0.next_full();
        let r_y = self.prg0.next_full();

        // Step 1: Mask + Send
        if self.party_id == 0 {
            comm.send_to_hp(json!({
                "id": 0,
                "mx": add_mod(share_x, r_x),
                "my": add_mod(share_y, r_y),
            }));
        } else {
            comm.send_to_hp(json!({
                "id": 1,
                "mx": share_x,
                "my": share_y,
            }));
        }

        // Step 2: Receive share from HP
        let msg = comm.recv_from_hp();
        let s_i = msg["share"].as_u64().expect("share must be u64");

        // Step 3: Unmask
        let correction = if self.party_id == 0 {
            // P0: x0*r_y + y0*r_x + r_x*r_y
            add_mod(
                add_mod(mul_mod(share_x, r_y), mul_mod(share_y, r_x)),
                mul_mod(r_x, r_y),
            )
        } else {
            // P1: x1*r_y + y1*r_x
            add_mod(mul_mod(share_x, r_y), mul_mod(share_y, r_x))
        };

        sub_mod(s_i, correction)
    }
}

// ── HP 角色 ──

pub struct MultiplyHP {
    asprg_p0: PrgSync,
    #[allow(dead_code)]
    asprg_p1: PrgSync, // 后续 exp/softmax/gelu 协议使用
}

impl MultiplyHP {
    pub fn new(asprg_p0: PrgSync, asprg_p1: PrgSync) -> Self {
        MultiplyHP { asprg_p0, asprg_p1 }
    }

    pub fn handle_multiply(&mut self, comm: &MockCommHP) {
        let msg0 = comm.recv_from_p0();
        let msg1 = comm.recv_from_p1();

        let mx = add_mod(
            msg0["mx"].as_u64().expect("mx0"),
            msg1["mx"].as_u64().expect("mx1"),
        );
        let my = add_mod(
            msg0["my"].as_u64().expect("my0"),
            msg1["my"].as_u64().expect("my1"),
        );

        let product = mul_mod(mx, my);
        let s0 = self.asprg_p0.next_full();
        let s1 = sub_mod(product, s0);

        comm.send_to_p0(json!({"share": s0}));
        comm.send_to_p1(json!({"share": s1}));
    }
}

// ── 测试 ──

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mock_comm::make_mock_comm;

    fn seeds() -> ([u8; 16], [u8; 16], [u8; 16]) {
        let s0: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();
        let s1: [u8; 16] = (16u8..32).collect::<Vec<_>>().try_into().unwrap();
        let s2: [u8; 16] = (32u8..48).collect::<Vec<_>>().try_into().unwrap();
        (s0, s1, s2)
    }

    fn run_mpc_mul(x: u64, y: u64) -> u64 {
        let (shared, hp_p0, hp_p1) = seeds();
        let x0: u64 = 999999;
        let x1 = sub_mod(x, x0);
        let y0: u64 = 888888;
        let y1 = sub_mod(y, y0);

        let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

        let mut p0 = MultiplyParty::new(0, PrgSync::new(&shared));
        let mut p1 = MultiplyParty::new(1, PrgSync::new(&shared));
        let mut hp = MultiplyHP::new(PrgSync::new(&hp_p0), PrgSync::new(&hp_p1));

        let t0 = std::thread::spawn(move || p0.multiply(x0, y0, &comm_p0));
        let t1 = std::thread::spawn(move || p1.multiply(x1, y1, &comm_p1));
        hp.handle_multiply(&comm_hp);

        add_mod(t0.join().unwrap(), t1.join().unwrap())
    }

    #[test]
    fn test_single() {
        let x = 12345u64;
        let y = 67890u64;
        assert_eq!(run_mpc_mul(x, y), mul_mod(x, y));
    }

    #[test]
    fn test_random_5() {
        for i in 0u64..5 {
            let xi = i.wrapping_mul(123456789).wrapping_add(987654321);
            let yi = i.wrapping_mul(987654321).wrapping_add(123456789);
            assert_eq!(run_mpc_mul(xi, yi), mul_mod(xi, yi),
                "test {i}: {xi} x {yi}");
        }
    }

    #[test]
    fn test_large_values() {
        let x = u64::MAX / 2 + 12345;
        let y = u64::MAX / 3 + 67890;
        assert_eq!(run_mpc_mul(x, y), mul_mod(x, y),
            "large: {x} x {y}");
    }

    #[test]
    fn test_zero_and_edge() {
        assert_eq!(run_mpc_mul(0, 12345), 0, "zero * anything = 0");
        assert_eq!(run_mpc_mul(12345, 0), 0, "anything * zero = 0");
        assert_eq!(run_mpc_mul(0, 0), 0, "zero * zero = 0");
        assert_eq!(run_mpc_mul(u64::MAX, 1), u64::MAX, "MAX * 1 = MAX");
        assert_eq!(run_mpc_mul(1, u64::MAX), u64::MAX, "1 * MAX = MAX");
    }

    #[test]
    fn test_wrapping_overflow() {
        // 确保 wrapping 算术正确: 2^32 * 2^32 = 2^64 wraps to 0
        let x = 1u64 << 32;
        let y = 1u64 << 32;
        assert_eq!(run_mpc_mul(x, y), 0, "2^32 * 2^32 wraps to 0 in Z_2^64");
    }
}
