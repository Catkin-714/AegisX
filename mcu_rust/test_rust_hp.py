"""
test_rust_hp.py — Rust HP 替换验证: Python P0/P1 <-> Rust HP TCP 三方 MPC 乘法

用法:
  cd mcu_rust
  ..\\venv\\Scripts\\python.exe test_rust_hp.py
"""
import subprocess
import socket
import struct
import json
import time
import sys
import os
import threading

L = 2**64
L_SIGNED = 2**63
HOST = '127.0.0.1'
PORT_HP = 9000
SHARED_SEED = bytes(range(16))

# ── PRG（优先用 pycryptodome AES-CTR，降级用 hashlib）──
try:
    from Crypto.Cipher import AES
    class PRGSync:
        def __init__(self, seed: bytes):
            self.seed = seed
            self.counter = 0
        def next(self, ring: int = L) -> int:
            nonce = struct.pack('>Q', self.counter) + b'\x00' * 8
            cipher = AES.new(self.seed, AES.MODE_CTR, nonce=nonce[:8],
                             initial_value=nonce[8:])
            rand_bytes = cipher.encrypt(b'\x00' * 8)
            self.counter += 1
            return int.from_bytes(rand_bytes, 'big') % ring
except ImportError:
    import hashlib
    class PRGSync:
        def __init__(self, seed: bytes):
            self.seed = seed
            self.counter = 0
        def next(self, ring: int = L) -> int:
            data = self.counter.to_bytes(8, 'big') + b'\x00' * 8 + self.seed
            h = hashlib.sha256(data).digest()
            val = int.from_bytes(h[:8], 'big')
            self.counter += 1
            return val % ring


# ── TCP 通信 ──
def send_msg(sock: socket.socket, data: dict):
    msg = json.dumps(data).encode('utf-8')
    length = struct.pack('>I', len(msg))
    sock.sendall(length + msg)

def recv_msg(sock: socket.socket) -> dict:
    raw_len = _recv_exact(sock, 4)
    length = struct.unpack('>I', raw_len)[0]
    raw_data = _recv_exact(sock, length)
    return json.loads(raw_data.decode('utf-8'))

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError('Connection closed')
        data += chunk
    return data


# ── 连接 HP ──
def connect_to_hp(role: str) -> socket.socket:
    for _ in range(20):
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect((HOST, PORT_HP))
            send_msg(conn, {'role': role})
            return conn
        except ConnectionRefusedError:
            time.sleep(0.3)
    raise ConnectionError(f"Cannot connect to HP as {role}")


# ── P0 / P1 协议客户端 ──
def run_p0(conn: socket.socket, x0, y0, r_x, r_y):
    send_msg(conn, {
        'op': 'mul',
        'mx': (x0 + r_x) % L,
        'my': (y0 + r_y) % L
    })
    msg = recv_msg(conn)
    s0 = msg['share']
    correction = (x0 * r_y + y0 * r_x + r_x * r_y) % L
    result0 = (s0 - correction) % L
    send_msg(conn, {'op': 'done'})
    return result0


def run_p1(conn: socket.socket, x1, y1, r_x, r_y):
    send_msg(conn, {
        'op': 'mul',
        'mx': x1 % L,
        'my': y1 % L
    })
    msg = recv_msg(conn)
    s1 = msg['share']
    correction = (x1 * r_y + y1 * r_x) % L
    result1 = (s1 - correction) % L
    send_msg(conn, {'op': 'done'})
    return result1


def do_mpc_mul(x, y, x0, y0, x1, y1):
    """一次完整的三方 MPC 乘法（P0 + P1 连接 Rust HP）"""
    prg = PRGSync(SHARED_SEED)
    r_x = prg.next(L)
    r_y = prg.next(L)

    conn_p0 = connect_to_hp('p0')
    conn_p1 = connect_to_hp('p1')

    results = {}
    def p0_fn():
        results['p0'] = run_p0(conn_p0, x0, y0, r_x, r_y)
    def p1_fn():
        results['p1'] = run_p1(conn_p1, x1, y1, r_x, r_y)

    t0 = threading.Thread(target=p0_fn)
    t1 = threading.Thread(target=p1_fn)
    t0.start(); t1.start()
    t0.join(); t1.join()

    conn_p0.close()
    conn_p1.close()

    return (results['p0'] + results['p1']) % L


# ── 主测试 ──
def main():
    print("=" * 60)
    print("  Rust HP Replacement Test")
    print("  P0/P1 (Python) <--> HP (Rust mcu_hp.exe)")
    print("=" * 60)
    print()

    # 1. 启动 Rust HP（只需一次，会话循环保持存活）
    exe = os.path.join(os.path.dirname(__file__), "target", "debug", "mcu_hp.exe")
    if not os.path.exists(exe):
        exe = os.path.join(os.path.dirname(__file__), "target", "release", "mcu_hp.exe")
    if not os.path.exists(exe):
        print(f"[ERROR] Rust binary not found at {exe}")
        print("        Run: cargo build")
        return 1

    print(f"[TEST] Starting Rust HP: {exe}")
    hp_proc = subprocess.Popen(
        [exe, "--mode", "hp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(0.5)

    all_pass = True
    try:
        # ── 单组验证 ──
        x, y = 12345, 67890
        expected = (x * y) % L
        x0, x1 = 999999, (x - 999999) % L
        y0, y1 = 888888, (y - 888888) % L

        print(f"[TEST] Single: {x} x {y} = ?")
        result = do_mpc_mul(x, y, x0, y0, x1, y1)
        print(f"[TEST]   P0 share + P1 share = {result}")
        print(f"[TEST]   Expected = {expected}")
        if result == expected:
            print(f"[TEST]   >>> PASS <<<")
        else:
            print(f"[TEST]   >>> FAIL <<<")
            all_pass = False
        print()

        # ── 批量随机测试（HP 持续运行，每轮重连）──
        print("[TEST] Batch: 5 random pairs...")
        import random
        for i in range(5):
            xi = random.randint(0, 10**9)
            yi = random.randint(0, 10**9)
            exp = (xi * yi) % L
            xi0 = random.randint(0, L_SIGNED - 1)
            xi1 = (xi - xi0) % L
            yi0 = random.randint(0, L_SIGNED - 1)
            yi1 = (yi - yi0) % L

            ri = do_mpc_mul(xi, yi, xi0, yi0, xi1, yi1)
            status = "[OK]" if ri == exp else "[FAIL]"
            if ri != exp:
                all_pass = False
            print(f"  {status} {xi} x {yi} = {ri}")

        print()

    finally:
        # 读 Rust HP 日志
        hp_proc.terminate()
        try:
            hp_out, _ = hp_proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            hp_proc.kill()
            hp_out, _ = hp_proc.communicate()
        if hp_out:
            print("--- Rust HP Log ---")
            print(hp_out)

    if all_pass:
        print("=" * 60)
        print("  ALL TESTS PASSED")
        print("  Rust HP fully replaces Python HP!")
        print("=" * 60)
        return 0
    else:
        print("=" * 60)
        print("  SOME TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    exit(main())
