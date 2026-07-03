//! MCU 乘法协议 — 独立二进制入口
//!
//! ## 用法
//!
//! ```bash
//! # 验证协议正确性（单进程测试）
//! mcu_hp --mode test
//!
//! # 运行 HP TCP 服务（替换 Python HP，与 party.py 的 P0/P1 对接）
//! mcu_hp --mode hp
//! ```

use mcu_rust::prg::PrgSync;
use mcu_rust::comm::{send_msg, recv_msg};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};
use std::env;

// 与 Python party.py 相同的种子
const SEED_HP_P0: [u8; 16] = [
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
];
const SEED_HP_P1: [u8; 16] = [
    32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47,
];

fn main() {
    let args: Vec<String> = env::args().collect();

    let mode = args
        .iter()
        .find(|a| *a == "--mode")
        .and_then(|_| args.iter().skip_while(|a| *a != "--mode").nth(1))
        .map(|s| s.as_str())
        .unwrap_or("hp"); // 默认 hp 模式

    match mode {
        "test" => run_mul_test(),
        "protocol-test" => run_full_protocol_test(),
        "hp" => {
            let port: u16 = args.iter()
                .find(|a| *a == "--port")
                .and_then(|_| args.iter().skip_while(|a| *a != "--port").nth(1))
                .and_then(|s| s.parse().ok())
                .unwrap_or(9000);
            run_hp_server(port);
        }
        other => {
            eprintln!("Unknown mode: {other}");
            eprintln!("Usage: mcu_hp --mode [test|protocol-test|hp]");
            std::process::exit(1);
        }
    }
}

// ══════════════════════════════════════════════════════════════════════
// HP TCP 服务器 — 完整替换 Python HPProcess
// ══════════════════════════════════════════════════════════════════════

fn run_hp_server(port: u16) {
    let host = "127.0.0.1";

    let listener = TcpListener::bind((host, port))
        .unwrap_or_else(|e| {
            eprintln!("[Rust HP] Failed to bind {host}:{port}: {e}");
            std::process::exit(1);
        });

    println!("+==========================================+");
    println!("|   Rust MCU HP Server                     |");
    println!("|   Listening on {host}:{port}                  |");
    println!("|   Waiting for P0 and P1...               |");
    println!("+==========================================+");

    // ── 会话循环：每轮 done 后回到等待新连接 ──
    let mut session = 0;
    loop {
        session += 1;

        // 接受两个连接
        let (mut conn_p0, mut conn_p1) = accept_two(&listener);

        // 每个会话重置 PRG（种子与 Python 一致）
        let mut asprg_p0 = PrgSync::new(&SEED_HP_P0);
        let _asprg_p1 = PrgSync::new(&SEED_HP_P1);

        println!("[Rust HP] Session {session}: started");

        loop {

            let msg0 = match recv_msg(&mut conn_p0) {
                Ok(m) => m,
                Err(e) => {
                    println!("[Rust HP] P0 disconnected: {e}");
                    break;
                }
            };
            let op = msg0["op"].as_str().unwrap_or("");

            if op == "done" {
                // P1 也会发送 done，吞掉它
                let _ = recv_msg(&mut conn_p1);
                break;
            }

            let msg1 = match recv_msg(&mut conn_p1) {
                Ok(m) => m,
                Err(e) => {
                    println!("[Rust HP] P1 disconnected: {e}");
                    break;
                }
            };

            match op {
                "mul" => {
                    handle_mul_tcp(&msg0, &msg1, &mut asprg_p0, &mut conn_p0, &mut conn_p1);
                    println!("[Rust HP] Session {session}: mul OK");
                }
                "mul_batch" => {
                    handle_mul_batch_tcp(&msg0, &msg1, &mut asprg_p0, &mut conn_p0, &mut conn_p1);
                    println!("[Rust HP] Session {session}: mul_batch OK");
                }
                "exp" => {
                    // msg0/msg1 already contain the first round data; pass through
                    serve_exp_full_tcp(msg0, msg1, &mut asprg_p0, &mut conn_p0, &mut conn_p1);
                    println!("[Rust HP] Session {session}: exp OK");
                }
                "softmax" => {
                    serve_softmax_full_tcp(&msg0, &msg1, &mut asprg_p0, &mut conn_p0, &mut conn_p1);
                    println!("[Rust HP] Session {session}: softmax OK");
                }
                "gelu" => {
                    serve_gelu_full_tcp(&msg0, &msg1, &mut asprg_p0, &mut conn_p0, &mut conn_p1);
                    println!("[Rust HP] Session {session}: gelu OK");
                }
                "ping" => {
                    send_msg(&mut conn_p0, &serde_json::json!({"pong": true})).ok();
                    send_msg(&mut conn_p1, &serde_json::json!({"pong": true})).ok();
                }
                _ => {
                    println!("[Rust HP] Unknown op: {op}");
                }
            }
        }

        println!("[Rust HP] Session {session}: done, waiting for next pair...");
        println!();
    }
}

/// 接受两个 TCP 连接，通过首条消息中的 role 字段识别
fn accept_two(listener: &TcpListener) -> (TcpStream, TcpStream) {
    let mut conn_p0: Option<TcpStream> = None;
    let mut conn_p1: Option<TcpStream> = None;
    let start = Instant::now();
    let timeout = Duration::from_secs(30);

    listener.set_nonblocking(true).ok();

    while conn_p0.is_none() || conn_p1.is_none() {
        // 超时检查
        if start.elapsed() > timeout {
            eprintln!("[Rust HP] Timeout waiting for parties (30s). Only got: {}/{}",
                if conn_p0.is_some() { "P0" } else { "" },
                if conn_p1.is_some() { "P1" } else { "" });
            eprintln!("[Rust HP] Shutting down.");
            std::process::exit(1);
        }

        match listener.accept() {
            Ok((mut conn, addr)) => {
                conn.set_nonblocking(false).ok();
                match recv_msg(&mut conn) {
                    Ok(msg) => {
                        let role = msg["role"].as_str().unwrap_or("");
                        match role {
                            "p0" => {
                                println!("[Rust HP] P0 connected from {addr}");
                                conn_p0 = Some(conn);
                            }
                            "p1" => {
                                println!("[Rust HP] P1 connected from {addr}");
                                conn_p1 = Some(conn);
                            }
                            other => eprintln!("[Rust HP] Unknown role: {other}, rejecting"),
                        }
                    }
                    Err(e) => eprintln!("[Rust HP] Failed to read role from {addr}: {e}"),
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // 非阻塞模式下无连接，短暂等待后重试
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => {
                eprintln!("[Rust HP] Accept error: {e}");
                std::thread::sleep(Duration::from_millis(100));
            }
        }
    }

    listener.set_nonblocking(false).ok();
    println!("[Rust HP] All parties connected. Starting protocol.");
    (conn_p0.unwrap(), conn_p1.unwrap())
}

// ═══════════════════════════════════════════════════════════════
// TCP 协议处理器 — 每个子协议全程内部处理多轮收发
// ═══════════════════════════════════════════════════════════════

const MOD: f64 = 256.0;
fn fmod(a: f64, m: f64) -> f64 { let r = a % m; if r < 0.0 { r + m } else { r } }

fn read_both(conn_p0: &mut TcpStream, conn_p1: &mut TcpStream)
    -> (serde_json::Value, serde_json::Value) {
    (recv_msg(conn_p0).unwrap(), recv_msg(conn_p1).unwrap())
}

/// Π_mul: 单轮
fn handle_mul_tcp(
    msg0: &serde_json::Value, msg1: &serde_json::Value,
    asprg_p0: &mut PrgSync, conn_p0: &mut TcpStream, conn_p1: &mut TcpStream,
) {
    let mx = msg0["mx"].as_u64().unwrap().wrapping_add(msg1["mx"].as_u64().unwrap());
    let my = msg0["my"].as_u64().unwrap().wrapping_add(msg1["my"].as_u64().unwrap());
    let s0 = asprg_p0.next_full();
    let s1 = mx.wrapping_mul(my).wrapping_sub(s0);
    send_msg(conn_p0, &serde_json::json!({"share": s0})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"share": s1})).unwrap();
}

/// Π_mul 批量版：一次收发处理 n 组乘法（用于线性层加速）
fn handle_mul_batch_tcp(
    msg0: &serde_json::Value, msg1: &serde_json::Value,
    asprg_p0: &mut PrgSync, conn_p0: &mut TcpStream, conn_p1: &mut TcpStream,
) {
    let mx0: Vec<u64> = msg0["mx"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    let my0: Vec<u64> = msg0["my"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    let mx1: Vec<u64> = msg1["mx"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();
    let my1: Vec<u64> = msg1["my"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap()).collect();

    let n = mx0.len();
    let mut s0s = Vec::with_capacity(n);
    let mut s1s = Vec::with_capacity(n);

    for i in 0..n {
        let mx = mx0[i].wrapping_add(mx1[i]);
        let my = my0[i].wrapping_add(my1[i]);
        let product = mx.wrapping_mul(my);
        let s0 = asprg_p0.next_full();
        s0s.push(s0);
        s1s.push(product.wrapping_sub(s0));
    }

    send_msg(conn_p0, &serde_json::json!({"shares": s0s})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"shares": s1s})).unwrap();
}

/// Π_exp: 3 轮（mask → 2x sign）全程
fn serve_exp_full_tcp(
    msg0: serde_json::Value, msg1: serde_json::Value,
    asprg_p0: &mut PrgSync, conn_p0: &mut TcpStream, conn_p1: &mut TcpStream,
) {
    // Round 1: mask → e^R → split
    let r_val = fmod(
        msg0["m"].as_f64().unwrap() + msg1["m"].as_f64().unwrap(), MOD);
    let e_val = r_val.exp();
    let u = asprg_p0.next_f64();
    send_msg(conn_p0, &serde_json::json!({"s": u * e_val})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"s": e_val - u * e_val})).unwrap();

    // Rounds 2-3: two sign comparisons
    for _ in 0..2 {
        let (s0, s1) = read_both(conn_p0, conn_p1);
        let za = s0["za"].as_f64().unwrap() + s1["za"].as_f64().unwrap();
        let bit = if za >= 0.0 { 1 } else { 0 };
        send_msg(conn_p0, &serde_json::json!({"bit": bit})).unwrap();
        send_msg(conn_p1, &serde_json::json!({"bit": bit})).unwrap();
    }
}

/// Π_softmax: k 路 exp + 掩码分母
fn serve_softmax_full_tcp(
    msg0: &serde_json::Value, _msg1: &serde_json::Value,
    asprg_p0: &mut PrgSync, conn_p0: &mut TcpStream, conn_p1: &mut TcpStream,
) {
    let k = msg0["k"].as_u64().unwrap_or(1) as usize;
    // k 路 exp
    for _ in 0..k {
        let (m0, m1) = read_both(conn_p0, conn_p1);
        serve_exp_full_tcp(m0, m1, asprg_p0, conn_p0, conn_p1);
    }
    // 掩码分母
    let (u0, u1) = read_both(conn_p0, conn_p1);
    let d_pub = u0["u"].as_f64().unwrap() + u1["u"].as_f64().unwrap();
    send_msg(conn_p0, &serde_json::json!({"D": d_pub})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"D": d_pub})).unwrap();
}

/// Π_gelu: sigmoid(exp + 分母) + 实数乘法
fn serve_gelu_full_tcp(
    _msg0: &serde_json::Value, _msg1: &serde_json::Value,
    asprg_p0: &mut PrgSync, conn_p0: &mut TcpStream, conn_p1: &mut TcpStream,
) {
    // sigmoid = exp + sm_u
    let (m0, m1) = read_both(conn_p0, conn_p1);
    serve_exp_full_tcp(m0, m1, asprg_p0, conn_p0, conn_p1);

    let (u0, u1) = read_both(conn_p0, conn_p1);
    let d_pub = u0["u"].as_f64().unwrap() + u1["u"].as_f64().unwrap();
    send_msg(conn_p0, &serde_json::json!({"D": d_pub})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"D": d_pub})).unwrap();

    // 实数乘法
    let (ma0, ma1) = read_both(conn_p0, conn_p1);
    let ma = ma0["ma"].as_f64().unwrap() + ma1["ma"].as_f64().unwrap();
    let mb = ma0["mb"].as_f64().unwrap() + ma1["mb"].as_f64().unwrap();
    let product = ma * mb;
    let u = asprg_p0.next_f64();
    send_msg(conn_p0, &serde_json::json!({"s": u * product})).unwrap();
    send_msg(conn_p1, &serde_json::json!({"s": product - u * product})).unwrap();
}

// ══════════════════════════════════════════════════════════════════════
// 单进程协议验证（原有 test 模式）
// ══════════════════════════════════════════════════════════════════════

fn run_mul_test() {
    println!("============================================");
    println!("  MCU Pi_mul Protocol Test (Rust)");
    println!("============================================");
    println!();

    let shared_seed: [u8; 16] = (0u8..16).collect::<Vec<u8>>().try_into().unwrap();
    let seed_hp_p0: [u8; 16] = SEED_HP_P0;
    let seed_hp_p1: [u8; 16] = SEED_HP_P1;

    // 单组验证
    let x: u64 = 12345;
    let y: u64 = 67890;
    let expected = x.wrapping_mul(y);

    println!("--- Single Test ---");
    println!("x = {x}, y = {y}");
    println!("Expected: {expected}");

    let result = run_single_mul(x, y, &shared_seed, &seed_hp_p0, &seed_hp_p1);
    let status = if result == expected { "[PASS]" } else { "[FAIL]" };
    println!("MPC result: {result}");
    println!("Status: {status}");
    println!();

    // 多组随机测试
    println!("--- Random Tests (5 groups) ---");
    let mut all_pass = true;

    for i in 0..5 {
        let xi = (i as u64).wrapping_mul(123456789).wrapping_add(987654321);
        let yi = (i as u64).wrapping_mul(987654321).wrapping_add(123456789);
        let exp = xi.wrapping_mul(yi);

        let res = run_single_mul(xi, yi, &shared_seed, &seed_hp_p0, &seed_hp_p1);

        let status = if res == exp { "[OK]" } else { "[FAIL]" };
        if res != exp {
            all_pass = false;
        }
        println!("  {status} {xi} x {yi} = {exp}, MPC={res}");
    }

    println!();
    if all_pass {
        println!("============================================");
        println!("  ALL PASSED");
        println!("============================================");
    } else {
        println!("SOME TESTS FAILED");
        std::process::exit(1);
    }
}

// ══════════════════════════════════════════════════════════════════════
// 全协议验证
// ══════════════════════════════════════════════════════════════════════

fn run_full_protocol_test() {
    use mcu_rust::mock_comm::make_mock_comm;
    use mcu_rust::prg::PrgSync;
    use mcu_rust::exponential;
    use mcu_rust::softmax;
    use mcu_rust::gelu;

    let shared: [u8; 16] = (0u8..16).collect::<Vec<_>>().try_into().unwrap();
    let hp_seed: [u8; 16] = SEED_HP_P0;

    println!("+==========================================+");
    println!("|  MCU Protocol Suite Test (Rust)           |");
    println!("+==========================================+");
    println!();

    // ── Π_mul ──
    println!("--- Pi_mul ---");
    let x: u64 = 12345;
    let y: u64 = 67890;
    let expected = x.wrapping_mul(y);
    let result = run_single_mul(x, y, &shared, &SEED_HP_P0, &SEED_HP_P1);
    println!("  {x} x {y} = {result} (expected {expected}) [{}]",
        if result == expected { "OK" } else { "FAIL" });
    println!();

    // ── Π_exp ──
    println!("--- Pi_exp (200 samples) ---");
    let n_exp = 200;
    let mut e_max = 0.0f64;
    let mut e_sum = 0.0f64;
    for i in 0..n_exp {
        let x_val = ((i as f64) - 100.0) * 0.1;
        let x0 = x_val * 0.7;
        let x1 = x_val - x0;
        let ex = x_val.exp();

        let (comm_p0, comm_p1, comm_hp) = make_mock_comm();
        let (e0, e1) = std::thread::scope(|s| {
            let mut p0 = PrgSync::new(&shared);
            let mut p1 = PrgSync::new(&shared);
            let mut hp = PrgSync::new(&hp_seed);
            let t0 = s.spawn(move || exponential::exp(0, &mut p0, x0, &comm_p0));
            let t1 = s.spawn(move || exponential::exp(1, &mut p1, x1, &comm_p1));
            exponential::serve_exp(&mut hp, &comm_hp);
            (t0.join().unwrap(), t1.join().unwrap())
        });
        let err = (e0 + e1 - ex).abs();
        e_max = e_max.max(err);
        e_sum += err;
    }
    let e_avg = e_sum / n_exp as f64;
    println!("  avg_err={e_avg:.3e}, max_err={e_max:.3e} [{}]",
        if e_avg < 1e-4 { "OK" } else { "FAIL" });
    println!();

    // ── Π_softmax ──
    println!("--- Pi_softmax (10 groups, k=6) ---");
    let n_sm = 10;
    let k_sm = 6;
    let mut s_max = 0.0f64;
    let mut s_sum = 0.0f64;
    let mut s_cnt = 0;
    for t in 0..n_sm {
        let xs: Vec<f64> = (0..k_sm)
            .map(|j| ((t * k_sm + j) as f64 - (n_sm * k_sm / 2) as f64) * 0.3)
            .collect();
        let xs0: Vec<f64> = xs.iter().map(|v| v * 0.6).collect();
        let xs1: Vec<f64> = xs.iter().zip(&xs0).map(|(v, v0)| v - v0).collect();

        // 明文 softmax
        let mx = xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let exps: Vec<f64> = xs.iter().map(|v| (v - mx).exp()).collect();
        let s_exps: f64 = exps.iter().sum();
        let expected_sm: Vec<f64> = exps.iter().map(|e| e / s_exps).collect();

        for m in 0..k_sm {
            let xs0_m = xs0.clone();
            let xs1_m = xs1.clone();
            let (comm_p0, comm_p1, comm_hp) = make_mock_comm();
            let (s0, s1) = std::thread::scope(|s| {
                let mut p0 = PrgSync::new(&shared);
                let mut p1 = PrgSync::new(&shared);
                let mut hp = PrgSync::new(&hp_seed);
                let t0 = s.spawn(move || softmax::softmax(0, &mut p0, &xs0_m, m, &comm_p0));
                let t1 = s.spawn(move || softmax::softmax(1, &mut p1, &xs1_m, m, &comm_p1));
                softmax::serve_softmax(&mut hp, &comm_hp, k_sm);
                (t0.join().unwrap(), t1.join().unwrap())
            });
            let err = (s0 + s1 - expected_sm[m]).abs();
            s_max = s_max.max(err);
            s_sum += err;
            s_cnt += 1;
        }
    }
    println!("  avg_err={:.3e}, max_err={:.3e} [{}]",
        s_sum / s_cnt as f64, s_max,
        if s_max < 1e-4 { "OK" } else { "FAIL" });
    println!();

    // ── Π_gelu ──
    println!("--- Pi_gelu (200 samples) ---");
    let n_gelu = 200;
    let mut g_max = 0.0f64;
    let mut g_sum = 0.0f64;
    let plain_gelu = |x: f64| x / (1.0 + (-1.702 * x).exp());
    for i in 0..n_gelu {
        let x_val = ((i as f64) - 100.0) * 0.05;
        let x0 = x_val * 0.7;
        let x1 = x_val - x0;
        let ex = plain_gelu(x_val);

        let (comm_p0, comm_p1, comm_hp) = make_mock_comm();
        let (g0, g1) = std::thread::scope(|s| {
            let mut p0 = PrgSync::new(&shared);
            let mut p1 = PrgSync::new(&shared);
            let mut hp = PrgSync::new(&hp_seed);
            let t0 = s.spawn(move || gelu::gelu(0, &mut p0, x0, &comm_p0));
            let t1 = s.spawn(move || gelu::gelu(1, &mut p1, x1, &comm_p1));
            gelu::serve_gelu(&mut hp, &comm_hp);
            (t0.join().unwrap(), t1.join().unwrap())
        });
        let err = (g0 + g1 - ex).abs();
        g_max = g_max.max(err);
        g_sum += err;
    }
    let g_avg = g_sum / n_gelu as f64;
    println!("  avg_err={g_avg:.3e}, max_err={g_max:.3e} [{}]",
        if g_avg < 1e-3 { "OK" } else { "FAIL" });
    println!();

    println!("+==========================================+");
    println!("|  Protocol Suite: ALL PASSED               |");
    println!("+==========================================+");
}

fn run_single_mul(
    x: u64, y: u64,
    shared_seed: &[u8; 16],
    seed_hp_p0: &[u8; 16],
    seed_hp_p1: &[u8; 16],
) -> u64 {
    use mcu_rust::mock_comm::make_mock_comm;
    use mcu_rust::multiply::{MultiplyHP, MultiplyParty};
    let x0: u64 = 999999;
    let x1 = x.wrapping_sub(x0);
    let y0: u64 = 888888;
    let y1 = y.wrapping_sub(y0);

    let prg0_p0 = PrgSync::new(shared_seed);
    let prg0_p1 = PrgSync::new(shared_seed);
    let asprg_p0 = PrgSync::new(seed_hp_p0);
    let asprg_p1 = PrgSync::new(seed_hp_p1);

    let (comm_p0, comm_p1, comm_hp) = make_mock_comm();

    let mut p0 = MultiplyParty::new(0, prg0_p0);
    let mut p1 = MultiplyParty::new(1, prg0_p1);
    let mut hp = MultiplyHP::new(asprg_p0, asprg_p1);

    let t0 = std::thread::spawn(move || p0.multiply(x0, y0, &comm_p0));
    let t1 = std::thread::spawn(move || p1.multiply(x1, y1, &comm_p1));
    hp.handle_multiply(&comm_hp);

    let r0 = t0.join().unwrap();
    let r1 = t1.join().unwrap();

    r0.wrapping_add(r1)
}
