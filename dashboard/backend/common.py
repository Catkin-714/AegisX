"""
common.py — AegisX 共享工具模块

提供: PRG (AES-CTR), fmod, TCP 通信辅助
所有 dashboard 后端和 party.py 统一使用此模块。
"""
import struct, hashlib, socket, json

L_U64 = 2**64
MOD = 256.0
SIGN_SCALE = 2**20
GELU_COEF = 1.702

# ── PRG (AES-CTR 优先，降级 hashlib) ──
try:
    from Crypto.Cipher import AES
    class PRG:
        """AES-CTR 同步伪随机数生成器，与 Rust prg.rs 一致"""
        def __init__(self, seed: bytes):
            self.seed = seed; self.counter = 0
        def next(self, ring=L_U64):
            n = struct.pack('>Q', self.counter) + b'\x00' * 8
            cipher = AES.new(self.seed, AES.MODE_CTR, nonce=n[:8], initial_value=n[8:])
            v = int.from_bytes(cipher.encrypt(b'\x00' * 8), 'big')
            self.counter += 1; return v % ring
        def full(self): return self.next(L_U64)
        def f64(self): return self.next(2**53) / float(2**53)
        def real(self, high): return self.f64() * high
        def batch(self, n, ring=L_U64):
            """一次 AES-CTR 调用生成 n 个随机数（~n× 提速）
            注意: 不要在同一实例上混用 batch() 和 next()/full()/f64()/real()，
            因为 counter 推进速度不同。批量操作用 batch()，逐次操作用 next()。
            """
            iv = struct.pack('>Q', self.counter) + b'\x00' * 8
            cipher = AES.new(self.seed, AES.MODE_CTR, nonce=iv[:8], initial_value=iv[8:])
            ks = cipher.encrypt(b'\x00' * (n * 8))
            result = [int.from_bytes(ks[i*8:(i+1)*8], 'big') % ring for i in range(n)]
            self.counter += n
            return result
    _PRG_CLS = PRG
except ImportError:
    class _HashPRG:
        """hashlib 降级 PRG (无 pycryptodome 时使用)"""
        def __init__(self, seed: bytes):
            self.seed = seed; self.counter = 0
        def next(self, ring=L_U64):
            d = self.counter.to_bytes(8, 'big') + b'\x00' * 8 + self.seed
            v = int.from_bytes(hashlib.sha256(d).digest()[:8], 'big')
            self.counter += 1; return v % ring
        def full(self): return self.next(L_U64)
        def f64(self): return self.next(2**53) / float(2**53)
        def real(self, high): return self.f64() * high
        def batch(self, n, ring=L_U64):
            """每 SHA-256 调用产出 4 个随机数（~4x 提速）
            注意: batch() 与 next() 的 counter 推进速度不同，
            同一 PRG 实例上不要混用这两个方法。
            """
            result = []
            for _ in range(0, n, 4):
                d = self.counter.to_bytes(8, 'big') + b'\x00' * 8 + self.seed
                h = hashlib.sha256(d).digest()
                for j in range(4):
                    if len(result) >= n: break
                    result.append(int.from_bytes(h[j*8:(j+1)*8], 'big') % ring)
                self.counter += 1
            return result
    PRG = _HashPRG

# ── 浮点取模 (Rust/Python 一致) ──
def fmod(a: float, m: float = MOD) -> float:
    """浮点取模，结果始终非负 (与 Python % 和 Rust fmod 一致)"""
    r = a % m
    return r + m if r < 0 else r

# ── TCP 辅助 ──
SHARED_SEED = bytes(range(16))  # 演示用固定种子

def send_msg(sock: socket.socket, data: dict):
    """发送: 4字节大端长度 + JSON"""
    m = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack('>I', len(m)) + m)

def recv_msg(sock: socket.socket) -> dict:
    """接收: 读4字节长度 → 读JSON"""
    lb = b''
    while len(lb) < 4:
        c = sock.recv(4 - len(lb))
        if not c: raise ConnectionError('Connection closed')
        lb += c
    length = struct.unpack('>I', lb)[0]
    db = b''
    while len(db) < length:
        c = sock.recv(length - len(db))
        if not c: raise ConnectionError('Connection closed')
        db += c
    return json.loads(db.decode('utf-8'))
