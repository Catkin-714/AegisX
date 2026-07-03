"""
benchmark.py — Rust vs Python MPC 乘法性能对比

用法:
    venv\Scripts\python.exe benchmark.py
"""
import time, threading, socket, struct, json, hashlib, subprocess, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
L = 2**64; HOST = '127.0.0.1'; PORT = 9000

class PRG:
    def __init__(self, s): self.s = s; self.c = 0
    def n(self):
        d = self.c.to_bytes(8,'big')+b'\x00'*8+self.s
        v = int.from_bytes(hashlib.sha256(d).digest()[:8],'big')
        self.c += 1; return v % L

def _send(s,d):
    m=json.dumps(d).encode(); s.sendall(struct.pack('>I',len(m))+m)
def _recv(s):
    lb=b'';
    while len(lb)<4:
        c=s.recv(4-len(lb))
        if not c: raise ConnectionError
        lb+=c
    l=struct.unpack('>I',lb)[0]; db=b''
    while len(db)<l:
        c=s.recv(l-len(db))
        if not c: raise ConnectionError
        db+=c
    return json.loads(db.decode('utf-8'))

def main():
    print('=' * 60)
    print('  AegisX MPC Performance Benchmark')
    print('=' * 60)
    print()

    # Start Rust HP (先清理残留)
    exe = os.path.join(BASE, 'mcu_rust', 'target', 'release', 'mcu_hp.exe')
    if not os.path.exists(exe):
        exe = exe.replace('release', 'debug')
    subprocess.run(['taskkill', '/F', '/IM', 'mcu_hp.exe'],
        capture_output=True, timeout=5)
    time.sleep(0.8)  # 等待 TIME_WAIT 释放
    hp = subprocess.Popen([exe, '--mode', 'hp'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)

    results = {}
    try:
        # ── 1. Rust TCP batch ──
        print('[1/3] Rust TCP batch (256 muls, 1 round-trip)...')
        n_batch, runs = 256, 20
        t_total = 0
        for _ in range(runs):
            c0 = socket.socket(); c0.connect((HOST,PORT)); _send(c0,{'role':'p0'})
            c1 = socket.socket(); c1.connect((HOST,PORT)); _send(c1,{'role':'p1'})
            p0, p1 = PRG(bytes(range(16))), PRG(bytes(range(16)))
            mxs0 = [(i*11111)%L for i in range(n_batch)]
            mys0 = [(i*22222)%L for i in range(n_batch)]
            mxs1 = [((i*12345)%L - (i*11111)%L)%L for i in range(n_batch)]
            mys1 = [((i*67890)%L - (i*22222)%L)%L for i in range(n_batch)]
            start = time.time()
            r = {}
            def b0():
                rx = [p0.n() for _ in range(n_batch)]; ry = [p0.n() for _ in range(n_batch)]
                _send(c0,{'op':'mul_batch','mx':[(mxs0[j]+rx[j])%L for j in range(n_batch)],
                    'my':[(mys0[j]+ry[j])%L for j in range(n_batch)]})
                sh = _recv(c0)['shares']
                r['p0'] = [(sh[j]-(mxs0[j]*ry[j]+mys0[j]*rx[j]+rx[j]*ry[j]))%L for j in range(n_batch)]
                _send(c0,{'op':'done'})
            def b1():
                rx = [p1.n() for _ in range(n_batch)]; ry = [p1.n() for _ in range(n_batch)]
                _send(c1,{'op':'mul_batch','mx':[mxs1[j]%L for j in range(n_batch)],
                    'my':[mys1[j]%L for j in range(n_batch)]})
                sh = _recv(c1)['shares']
                r['p1'] = [(sh[j]-(mxs1[j]*ry[j]+mys1[j]*rx[j]))%L for j in range(n_batch)]
                _send(c1,{'op':'done'})
            t0 = threading.Thread(target=b0); t1 = threading.Thread(target=b1)
            t0.start(); t1.start(); t0.join(); t1.join()
            t_total += time.time()-start
            c0.close(); c1.close()
        avg = t_total/runs
        results['Rust TCP batch'] = (avg, n_batch, n_batch/avg)

        # ── 2. Rust TCP single ──
        print('[2/3] Rust TCP single mul...')
        c0 = socket.socket(); c0.connect((HOST,PORT)); _send(c0,{'role':'p0'})
        c1 = socket.socket(); c1.connect((HOST,PORT)); _send(c1,{'role':'p1'})
        p0, p1 = PRG(bytes(range(16))), PRG(bytes(range(16)))
        n_single = 64
        start = time.time()
        for i in range(n_single):
            x=(i*12345)%L; y=(i*67890)%L
            x0=(i*11111)%L; x1=(x-x0)%L; y0=(i*22222)%L; y1=(y-y0)%L
            r2 = {}
            def s0():
                rx,ry=p0.n(),p0.n()
                _send(c0,{'op':'mul','mx':(x0+rx)%L,'my':(y0+ry)%L})
                si=_recv(c0)['share']; r2['p0']=(si-(x0*ry+y0*rx+rx*ry))%L
            def s1():
                rx,ry=p1.n(),p1.n()
                _send(c1,{'op':'mul','mx':x1%L,'my':y1%L})
                si=_recv(c1)['share']; r2['p1']=(si-(x1*ry+y1*rx))%L
            t0=threading.Thread(target=s0); t1=threading.Thread(target=s1)
            t0.start(); t1.start(); t0.join(); t1.join()
        elapsed = time.time()-start
        _send(c0,{'op':'done'}); _send(c1,{'op':'done'})
        c0.close(); c1.close()
        results['Rust TCP single'] = (elapsed, n_single, n_single/elapsed)

        # ── 3. Python mock_comm (复用通道) ──
        print('[3/3] Python mock_comm (reusing channels)...')
        sys.path.insert(0, BASE)
        from mcu_core.prg_sync import PRGSync as PyPRG
        from mcu_core.mock_comm import make_mock_comm
        from mcu_core.protocols.multiply import MultiplyParty as PyMul, MultiplyHP as PyMHP
        shared = bytes(range(16)); hp_p0 = bytes(range(16,32)); hp_p1 = bytes(range(32,48))
        n_py = 256
        pprg0, pprg1 = PyPRG(shared), PyPRG(shared)
        ahp0, ahp1 = PyPRG(hp_p0), PyPRG(hp_p1)
        cp0, cp1, chp = make_mock_comm()
        mp0 = PyMul(0, pprg0, cp0); mp1 = PyMul(1, pprg1, cp1)
        mhp = PyMHP(ahp0, ahp1, chp)

        start = time.time()
        for i in range(n_py):
            x=(i*12345)%L; y=(i*67890)%L
            x0=(i*11111)%L; x1=(x-x0)%L; y0=(i*22222)%L; y1=(y-y0)%L
            r3 = {}
            t0=threading.Thread(target=lambda:r3.__setitem__('p0',mp0.multiply(x0,y0)))
            t1=threading.Thread(target=lambda:r3.__setitem__('p1',mp1.multiply(x1,y1)))
            t0.start(); t1.start(); mhp.handle_multiply(); t0.join(); t1.join()
        elapsed = time.time()-start
        results['Python mock_comm (reuse)'] = (elapsed, n_py, n_py/elapsed)

    finally:
        hp.terminate()

    # Print results
    print()
    print(f'{"Method":<25} {"Muls":<8} {"Time":<12} {"Throughput":<18} {"Latency"}')
    print('-' * 80)
    for name, (t, n, rate) in results.items():
        lat = t/n*1000
        print(f'{name:<25} {n:<8} {t*1000:>6.1f} ms   {rate:>8.0f} mul/s   {lat:>6.2f} ms/mul')

    print()
    rust_batch = results.get('Rust TCP batch', (0,0,0))
    py_mock = results.get('Python mock_comm', (0,0,0))
    if py_mock[2] > 0:
        speedup = rust_batch[2] / py_mock[2]
        print(f'  Rust batch vs Python mock_comm speedup: {speedup:.0f}x')
    print(f'  Key: batch mode eliminates TCP round-trip overhead')
    print(f'  Rust HP = AES-CTR hardware-accelerated PRG')
    print(f'  Python  = SHA-256 software PRG + queue overhead')

if __name__ == '__main__':
    main()
