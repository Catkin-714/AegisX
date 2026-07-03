//! 模拟通信层 — 基于 `std::sync::mpsc` channel
//!
//! 对标 Python `mcu_core/mock_comm.py`。
//! 用于单进程内三方协议测试，无需实际网络连接。

use std::sync::mpsc::{channel, Receiver, Sender};

/// 消息类型：所有协议消息统一用 serde_json::Value
pub type Msg = serde_json::Value;

// ── P0 / P1 通信接口 ──

/// P0 或 P1 的模拟通信对象
pub struct MockCommParty {
    /// HP → 本方的消息队列
    my_inbox: Receiver<Msg>,
    /// 本方 → HP 的消息队列
    hp_inbox: Sender<Msg>,
}

impl MockCommParty {
    pub fn send_to_hp(&self, msg: Msg) {
        self.hp_inbox.send(msg).expect("HP inbox full");
    }

    pub fn recv_from_hp(&self) -> Msg {
        self.my_inbox.recv().expect("my inbox empty")
    }
}

// ── HP 通信接口 ──

/// HP 的模拟通信对象
pub struct MockCommHP {
    from_p0: Receiver<Msg>,
    from_p1: Receiver<Msg>,
    to_p0: Sender<Msg>,
    to_p1: Sender<Msg>,
}

impl MockCommHP {
    pub fn recv_from_p0(&self) -> Msg {
        self.from_p0.recv().expect("from_p0 empty")
    }

    pub fn recv_from_p1(&self) -> Msg {
        self.from_p1.recv().expect("from_p1 empty")
    }

    pub fn send_to_p0(&self, msg: Msg) {
        self.to_p0.send(msg).expect("to_p0 full");
    }

    pub fn send_to_p1(&self, msg: Msg) {
        self.to_p1.send(msg).expect("to_p1 full");
    }
}

// ── 工厂函数 ──

/// 创建三方模拟通信对象
///
/// 返回 `(comm_p0, comm_p1, comm_hp)`
pub fn make_mock_comm() -> (MockCommParty, MockCommParty, MockCommHP) {
    let (to_hp_p0, from_p0) = channel(); // P0 → HP
    let (to_hp_p1, from_p1) = channel(); // P1 → HP
    let (to_p0_tx, to_p0_rx) = channel(); // HP → P0
    let (to_p1_tx, to_p1_rx) = channel(); // HP → P1

    let comm_p0 = MockCommParty {
        my_inbox: to_p0_rx,
        hp_inbox: to_hp_p0,
    };
    let comm_p1 = MockCommParty {
        my_inbox: to_p1_rx,
        hp_inbox: to_hp_p1,
    };
    let comm_hp = MockCommHP {
        from_p0,
        from_p1,
        to_p0: to_p0_tx,
        to_p1: to_p1_tx,
    };

    (comm_p0, comm_p1, comm_hp)
}
