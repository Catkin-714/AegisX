"""
rust_verify.py — 通过 TCP 调 Rust HP 验证协议正确性

不管理 HP 生命周期（由 start_dashboard.bat 或 infer_engine._get_rust_hp() 负责）。
HP 未运行时返回 available: false。
"""
import socket, time, os, threading
from common import PRG, send_msg as _send, recv_msg as _recv, SHARED_SEED, L_U64

HOST = '127.0.0.1'
PORT_HP = 9000


def _hp_online():
    """检测 HP 是否在运行"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect((HOST, PORT_HP))
        s.close()
        return True
    except Exception:
        return False


def _connect(role):
    for _ in range(20):
        try:
            s = socket.socket(); s.connect((HOST, PORT_HP))
            _send(s, {'role': role}); return s
        except: time.sleep(0.15)
    raise ConnectionError(f"Can't connect as {role}")


def run_rust_mul_verification(x=12345, y=67890):
    """通过 TCP 调用已运行的 Rust HP 完成一次乘法并验证"""
    if not _hp_online():
        return {"available": False, "message": "Rust HP not running on port 9000"}

    expected = (x * y) % L_U64
    x0, x1 = 999999 % L_U64, (x - 999999) % L_U64
    y0, y1 = 888888 % L_U64, (y - 888888) % L_U64

    c0 = _connect('p0'); c1 = _connect('p1')
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)

    results = {}
    def do_p0():
        rx, ry = p0.full(), p0.full()
        _send(c0, {'op':'mul','mx':(x0+rx)%L_U64,'my':(y0+ry)%L_U64})
        si = _recv(c0)['share']
        results['p0'] = (si-(x0*ry+y0*rx+rx*ry))%L_U64
        _send(c0, {'op':'done'})
    def do_p1():
        rx, ry = p1.full(), p1.full()
        _send(c1, {'op':'mul','mx':x1%L_U64,'my':y1%L_U64})
        si = _recv(c1)['share']
        results['p1'] = (si-(x1*ry+y1*rx))%L_U64
        _send(c1, {'op':'done'})

    t0 = threading.Thread(target=do_p0); t1 = threading.Thread(target=do_p1)
    t0.start(); t1.start(); t0.join(); t1.join()
    c0.close(); c1.close()

    result = (results['p0'] + results['p1']) % L_U64
    return {
        "available": True,
        "verified": result == expected,
        "x": x, "y": y,
        "expected": expected,
        "rust_result": result,
        "p0_share": results['p0'],
        "p1_share": results['p1'],
    }


def run_rust_perf_benchmark(n_muls=64):
    """测量 Rust HP 吞吐量"""
    if not _hp_online():
        return {"available": False}

    c0 = _connect('p0'); c1 = _connect('p1')
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)

    start = time.time()
    for _ in range(min(n_muls, 128)):
        xi, yi = 12345, 67890
        x0i, x1i = 999999, (xi-999999)%L_U64
        y0i, y1i = 888888, (yi-888888)%L_U64
        results = {}
        def p0f():
            rx, ry = p0.full(), p0.full()
            _send(c0, {'op':'mul','mx':(x0i+rx)%L_U64,'my':(y0i+ry)%L_U64})
            si = _recv(c0)['share']
            results['p0'] = (si-(x0i*ry+y0i*rx+rx*ry))%L_U64
        def p1f():
            rx, ry = p1.full(), p1.full()
            _send(c1, {'op':'mul','mx':x1i%L_U64,'my':y1i%L_U64})
            si = _recv(c1)['share']
            results['p1'] = (si-(x1i*ry+y1i*rx))%L_U64
        t0 = threading.Thread(target=p0f); t1 = threading.Thread(target=p1f)
        t0.start(); t1.start(); t0.join(); t1.join()

    elapsed = time.time() - start
    _send(c0, {'op':'done'}); _send(c1, {'op':'done'})
    c0.close(); c1.close()

    return {
        "available": True,
        "n_muls": n_muls,
        "elapsed_sec": round(elapsed, 3),
        "muls_per_sec": round(n_muls / elapsed, 1),
        "ms_per_mul": round(elapsed / n_muls * 1000, 1),
    }
