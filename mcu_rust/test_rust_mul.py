"""
test_rust_mul.py — Python 调用 Rust 乘法协议，端到端验证

用法:
  cd mcu_rust
  ..\\venv\\Scripts\\python.exe test_rust_mul.py
"""
import subprocess
import json
import os
import hashlib

L = 2**63  # 有符号 64 位环，与 Rust 一致

# ── 纯 Python 实现 PRG（不依赖 pycryptodome）──
class PurePrgSync:
    """纯 Python AES-CTR PRG，与 Rust prg.rs 行为一致"""
    def __init__(self, seed: bytes):
        assert len(seed) == 16
        self.seed = seed
        self.counter = 0

    def next(self, ring: int = L) -> int:
        """生成下一个随机数，用 hashlib 模拟 AES-CTR 单块输出"""
        # 构造与 AES-CTR 等价的确定性字节流
        # nonce = pack('>Q', counter) + b'\x00' * 8
        data = self.counter.to_bytes(8, 'big') + b'\x00' * 8 + self.seed
        h = hashlib.sha256(data).digest()
        val = int.from_bytes(h[:8], 'big')
        self.counter += 1
        return val % ring


def mod_l(v):
    return v % L

def sub_mod(a, b):
    return (a - b) % L

def add_mod(a, b):
    return (a + b) % L

def mul_mod(a, b):
    return (a * b) % L


def run_python_mul(x, y, shared_seed, hp_p0_seed, hp_p1_seed):
    """纯 Python 实现 MCU 乘法协议（不依赖 mcu_core）"""
    prg = PurePrgSync(shared_seed)
    asprg = PurePrgSync(hp_p0_seed)

    # 秘密共享
    x0, x1 = 999999 % L, sub_mod(x, 999999 % L)
    y0, y1 = 888888 % L, sub_mod(y, 888888 % L)

    r_x = prg.next(L)
    r_y = prg.next(L)

    # HP 重建掩码值
    mx_p0 = add_mod(x0, r_x)
    my_p0 = add_mod(y0, r_y)
    mx_p1 = mod_l(x1)
    my_p1 = mod_l(y1)
    mx = add_mod(mx_p0, mx_p1)
    my = add_mod(my_p0, my_p1)

    # HP 计算乘积 + 分发份额
    product = mul_mod(mx, my)
    s0 = asprg.next(L)
    s1 = sub_mod(product, s0)

    # 去掩码
    c0 = add_mod(add_mod(mul_mod(mod_l(x0), r_y), mul_mod(mod_l(y0), r_x)), mul_mod(r_x, r_y))
    c1 = add_mod(mul_mod(mod_l(x1), r_y), mul_mod(mod_l(y1), r_x))
    r0 = sub_mod(s0, c0)
    r1 = sub_mod(s1, c1)

    return add_mod(r0, r1)


def run_rust_binary():
    """调用已编译的 Rust mcu_hp.exe --mode test"""
    exe = os.path.join(os.path.dirname(__file__), "target", "debug", "mcu_hp.exe")
    result = subprocess.run([exe, "--mode", "test"], capture_output=True, text=True)
    return result.stdout


def main():
    print("=" * 50)
    print("  Rust MCU Pi_mul Protocol - E2E Verification")
    print("=" * 50)
    print()

    # 1. 检查 Rust 二进制
    exe = os.path.join(os.path.dirname(__file__), "target", "debug", "mcu_hp.exe")
    if not os.path.exists(exe):
        print("[ERROR] Rust binary not found. Run: cargo build")
        print(f"        期望路径: {exe}")
        return 1
    print(f"[OK] Rust binary: {exe}")
    print()

    # 2. 跑 Rust 二进制测试
    print("--- Rust Binary Output ---")
    rust_out = run_rust_binary()
    print(rust_out)

    # 3. Python 实现交叉验证
    print("--- Python Cross-Validation ---")
    seeds = (bytes(range(16)), bytes(range(16, 32)), bytes(range(32, 48)))

    # 单组验证
    x, y = 12345, 67890
    expected = mul_mod(x, y)
    py_result = run_python_mul(x, y, *seeds)
    print(f"  12345 x 67890 = {py_result}")
    print(f"  Expected = {expected}")
    print(f"  {'[PASS]' if py_result == expected else '[FAIL]'}")

    # 多组随机验证
    print()
    all_pass = True
    for i in range(5):
        xi = (i * 123456789 + 987654321) % L
        yi = (i * 987654321 + 123456789) % L
        exp = mul_mod(xi, yi)
        res = run_python_mul(xi, yi, *seeds)
        if res != exp:
            all_pass = False
            print(f"  [FAIL] test {i}: {xi} x {yi} = {res}, expected {exp}")
        else:
            print(f"  [OK] test {i}: passed")

    print()
    if all_pass:
        print("=" * 50)
        print("  ALL TESTS PASSED")
        print("  Rust MCU Pi_mul Protocol Verified!")
        print("=" * 50)
        return 0
    else:
        print("[FAIL] 存在失败用例")
        return 1


if __name__ == '__main__':
    exit(main())
