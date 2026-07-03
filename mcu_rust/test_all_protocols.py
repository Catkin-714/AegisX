"""
test_all_protocols.py — Python 调 Rust 全协议验证 + 交叉对比

用法:
  cd mcu_rust
  ..\\venv\\Scripts\\python.exe test_all_protocols.py
"""
import subprocess
import os
import sys

def run_rust(mode: str) -> str:
    exe = os.path.join(os.path.dirname(__file__), "target", "debug", "mcu_hp.exe")
    result = subprocess.run([exe, "--mode", mode], capture_output=True, text=True)
    return result.stdout

def main():
    print("=" * 60)
    print("  AegisX Rust Protocol Suite")
    print("  Cross-Validation: Python <-> Rust")
    print("=" * 60)
    print()

    # 1. Rust 单元测试
    print("[1/4] Rust unit tests...")
    r = subprocess.run(["cargo", "test"], cwd=os.path.dirname(__file__),
                       capture_output=True, text=True)
    if "test result: ok" in r.stdout and "0 failed" in r.stdout:
        print("  [PASS] All unit tests passed")
    else:
        print("  [FAIL]")
        print(r.stdout[-500:])
        return 1

    # 2. Rust protocol-test 模式
    print("[2/4] Rust protocol-test mode...")
    out = run_rust("protocol-test")
    print(out)
    if "ALL PASSED" not in out:
        print("  [FAIL]")
        return 1

    # 3. Rust mul test
    print("[3/4] Rust mul test...")
    out = run_rust("test")
    if "ALL PASSED" in out:
        print("  [PASS]")
    else:
        print("  [FAIL]")
        return 1

    # 4. Python <-> Rust HP TCP integration
    print("[4/4] Python P0/P1 <-> Rust HP TCP...")
    test_script = os.path.join(os.path.dirname(__file__), "test_rust_hp.py")
    r = subprocess.run(
        [os.path.join(os.path.dirname(__file__), "..", "venv", "Scripts", "python.exe"),
         test_script],
        capture_output=True, text=True
    )
    print(r.stdout)
    if "ALL TESTS PASSED" not in r.stdout:
        print("  [FAIL]")
        return 1

    print()
    print("=" * 60)
    print("  ALL CROSS-VALIDATIONS PASSED")
    print("")
    print("  Rust MCU Protocol Suite:")
    print("    Pi_mul    — Z_{2^64} 安全乘法")
    print("    Pi_exp    — 安全指数 (e^x)")
    print("    Pi_softmax — 安全 Softmax")
    print("    Pi_gelu   — 安全 GeLU")
    print("")
    print("  Python P0/P1  <->  Rust HP TCP  : OK")
    print("  Python PRG    <->  Rust PRG      : OK")
    print("=" * 60)
    return 0

if __name__ == '__main__':
    exit(main())
