//! TCP 通信层 — 与 Python `mcu_core/comm.py` 完全兼容
//!
//! 消息格式: 4 字节大端长度前缀 + UTF-8 JSON 载荷
//!
//! ```python
//! # Python 侧（comm.py）:
//! length = struct.pack('>I', len(msg))   # 4 字节大端
//! sock.sendall(length + msg)
//! ```

use serde_json::Value as Msg;
use std::io::{Read, Write};
use std::net::TcpStream;

/// 发送消息：4 字节大端长度 + JSON
pub fn send_msg(stream: &mut TcpStream, msg: &Msg) -> std::io::Result<()> {
    let json = serde_json::to_string(msg).unwrap();
    let bytes = json.as_bytes();
    let len = bytes.len() as u32;
    stream.write_all(&len.to_be_bytes())?;
    stream.write_all(bytes)?;
    stream.flush()?;
    Ok(())
}

/// 接收消息：读 4 字节长度 → 读载荷 → 解析 JSON
pub fn recv_msg(stream: &mut TcpStream) -> std::io::Result<Msg> {
    // 读 4 字节长度前缀（大端）
    let mut len_buf = [0u8; 4];
    stream.read_exact(&mut len_buf)?;
    let len = u32::from_be_bytes(len_buf) as usize;

    // 读载荷
    let mut buf = vec![0u8; len];
    stream.read_exact(&mut buf)?;

    // 解析 JSON
    let msg: Msg = serde_json::from_slice(&buf)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

    Ok(msg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{TcpListener, TcpStream};
    use std::thread;

    #[test]
    fn test_send_recv_roundtrip() {
        // 启动一个临时 TCP 服务器
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();

        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let msg = recv_msg(&mut stream).unwrap();
            // 回显
            send_msg(&mut stream, &msg).unwrap();
        });

        let mut client = TcpStream::connect(addr).unwrap();
        let sent = serde_json::json!({
            "op": "mul",
            "mx": 12345u64,
            "my": 67890u64
        });
        send_msg(&mut client, &sent).unwrap();
        let received = recv_msg(&mut client).unwrap();

        assert_eq!(sent, received);

        handle.join().unwrap();
    }
}
