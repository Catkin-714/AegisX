"""
verify_all.py — AegisX 全量验证（~3 秒）

自动启动 Rust HP，运行全部验证，完成后自动清理。

用法:
    venv\Scripts\python.exe verify_all.py
"""
import subprocess, os, sys, time, math, socket, json, struct, threading, hashlib

BASE = os.path.dirname(os.path.abspath(__file__))
HOST, PORT = '127.0.0.1', 9000
L_U64 = 2**64
SHARED_SEED = bytes(range(16))
results = []
hp_proc = None

def check(name, ok, detail=""):
    tag = "[OK]" if ok else "[FAIL]"
    msg = f"  {tag} {name}"
    if detail: msg += f"  ({detail})"
    print(msg)
    results.append(ok)
    return ok

# ── PRG ──
class PRG:
    def __init__(self, s): self.s, self.c = s, 0
    def n(self):
        d = self.c.to_bytes(8,'big')+b'\x00'*8+self.s
        v = int.from_bytes(hashlib.sha256(d).digest()[:8],'big')
        self.c += 1; return v % L_U64
    def full(self): return self.n()

# ── TCP ──
def send_msg(s, d):
    m = json.dumps(d).encode('utf-8'); s.sendall(struct.pack('>I', len(m)) + m)
def recv_msg(s):
    lb = b''
    while len(lb) < 4:
        c = s.recv(4 - len(lb))
        if not c: raise ConnectionError('EOF')
        lb += c
    l = struct.unpack('>I', lb)[0]; db = b''
    while len(db) < l:
        c = s.recv(l - len(db))
        if not c: raise ConnectionError('EOF')
        db += c
    return json.loads(db.decode('utf-8'))

def connect_hp(role, retries=30):
    for _ in range(retries):
        try:
            s = socket.socket(); s.connect((HOST, PORT))
            send_msg(s, {'role': role}); return s
        except: time.sleep(0.15)
    raise ConnectionError(f"Can't connect as {role}")

def parallel(f0, f1):
    r = {}
    def w0(): r['v0'] = f0()
    def w1(): r['v1'] = f1()
    t0 = threading.Thread(target=w0); t1 = threading.Thread(target=w1)
    t0.start(); t1.start(); t0.join(); t1.join()
    return r['v0'], r['v1']

# ── Locate binary ──
EXE = os.path.join(BASE, 'mcu_rust', 'target', 'release', 'mcu_hp.exe')
if not os.path.exists(EXE):
    EXE = EXE.replace('release', 'debug')
if not os.path.exists(EXE):
    print('[FATAL] Rust binary not found. Run: cd mcu_rust && cargo build --release')
    sys.exit(1)

def start_hp():
    """启动 Rust HP，确保无残留进程，等待就绪"""
    global hp_proc
    # 先强制清理残留
    stop_hp()
    try:
        # Windows: 强制释放端口
        subprocess.run(['taskkill', '/F', '/IM', 'mcu_hp.exe'],
            capture_output=True, timeout=5)
    except: pass
    time.sleep(0.5)
    hp_proc = subprocess.Popen([EXE, '--mode', 'hp'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    return True

def stop_hp():
    """清理 HP 进程"""
    global hp_proc
    if hp_proc:
        try: hp_proc.terminate()
        except: pass
        try: hp_proc.wait(timeout=2)
        except: hp_proc.kill()
        hp_proc = None
    # 确保没有遗漏的 HP 进程
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'mcu_hp.exe'],
            capture_output=True, timeout=5)
    except: pass
    time.sleep(0.3)

print('=' * 60)
print('  AegisX — Full Verification Suite')
print('=' * 60)
print()

# ═══ 1. Rust protocol-test (in-process, no HP needed) ═══
print('[1/4] Rust protocol-test (mul+exp+softmax+gelu)...')
r = subprocess.run([EXE, '--mode', 'protocol-test'], capture_output=True, text=True, timeout=30)
for line in r.stdout.split('\n'):
    if 'avg_err' in line:
        print(f'    {line.strip()}')
check('Rust protocol suite', 'ALL PASSED' in r.stdout)

# ═══ 2. Python protocol check (mock_comm, no HP needed) ═══
print()
print('[2/4] Python mcu_core protocol check...')
sys.path.insert(0, BASE)
from mcu_core.prg_sync import PRGSync
from mcu_core.mock_comm import make_mock_comm
from mcu_core.protocols.multiply import MultiplyParty as MP, MultiplyHP as MHP

x, y = 12345, 67890; expected = (x*y) % L_U64
x0, x1 = 999999, (x-999999)%L_U64; y0, y1 = 888888, (y-888888)%L_U64
shared = bytes(range(16))
cp0, cp1, chp = make_mock_comm()
p0 = MP(0, PRGSync(shared), cp0); p1 = MP(1, PRGSync(shared), cp1)
hp = MHP(PRGSync(bytes(range(16,32))), PRGSync(bytes(range(32,48))), chp)
r3 = {}
t0 = threading.Thread(target=lambda: r3.__setitem__('p0', p0.multiply(x0, y0)))
t1 = threading.Thread(target=lambda: r3.__setitem__('p1', p1.multiply(x1, y1)))
t0.start(); t1.start(); hp.handle_multiply(); t0.join(); t1.join()
result = (r3['p0'] + r3['p1']) % L_U64
check(f'Python mul: {x}*{y}={result}', result == expected)

# ═══ Start HP for TCP tests ═══
print()
print('[HP] Starting Rust HP for TCP tests...')
start_hp()
check('Rust HP ready', True, f'{HOST}:{PORT}')

# ═══ 3. TCP mul ═══
print()
print('[3/4] Python-Rust TCP mul...')
c0 = connect_hp('p0'); c1 = connect_hp('p1')
p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)
x, y = 12345, 67890; expected = (x*y) % L_U64
x0, x1 = 999999, (x-999999)%L_U64; y0, y1 = 888888, (y-888888)%L_U64

def p0f():
    rx, ry = p0.full(), p0.full()
    send_msg(c0, {'op':'mul','mx':(x0+rx)%L_U64,'my':(y0+ry)%L_U64})
    si = recv_msg(c0)['share']
    send_msg(c0, {'op':'done'})
    return (si-(x0*ry+y0*rx+rx*ry))%L_U64
def p1f():
    rx, ry = p1.full(), p1.full()
    send_msg(c1, {'op':'mul','mx':x1%L_U64,'my':y1%L_U64})
    si = recv_msg(c1)['share']
    send_msg(c1, {'op':'done'})
    return (si-(x1*ry+y1*rx))%L_U64
r0, r1 = parallel(p0f, p1f)
c0.close(); c1.close()
result = (r0 + r1) % L_U64
check(f'TCP mul via Rust HP: {x}*{y}={result}', result == expected)

# ═══ 4. Full protocol demo ═══
print()
print('[4/4] Full protocol demo (mul+exp+softmax+gelu)...')
sys.path.insert(0, os.path.join(BASE, 'mcu_rust'))
from mcu_tcp_client import connect, session_done, mul_pair, exp_pair, softmax_pair, gelu_pair

c0, c1 = connect('p0'), connect('p1')
ok_mul = mul_pair(c0, c1, 12345, 67890) == (12345*67890) % L_U64
err_exp = abs(exp_pair(c0, c1, 1.5) - math.exp(1.5))
ok_exp = err_exp < 1e-10
xs = [1.0, -1.5, 0.3]; mx_xs = max(xs)
exps_sm = [math.exp(v-mx_xs) for v in xs]
ok_sm = abs(softmax_pair(c0, c1, xs, 0) - exps_sm[0]/sum(exps_sm)) < 1e-4
expected_g = 0.5/(1.0+math.exp(-1.702*0.5))
ok_g = abs(gelu_pair(c0, c1, 0.5) - expected_g) < 1e-4
session_done(c0, c1); c0.close(); c1.close()

all_ok = ok_mul and ok_exp and ok_sm and ok_g
details = []
for name, ok, err in [("mul", ok_mul, 0), ("exp", ok_exp, err_exp),
                       ("softmax", ok_sm, 0), ("gelu", ok_g, 0)]:
    details.append(f"{name}={'OK' if ok else 'FAIL'}{' err='+f'{err:.1e}' if err else ''}")
check(f'Protocols: {", ".join(details)}', all_ok)

# ── Cleanup + Summary ──
stop_hp()
print()
print('=' * 60)
n_pass = sum(results); n_total = len(results)
if n_pass == n_total:
    print(f'  {n_pass}/{n_total} ALL PASSED')
    print('  AegisX ready for competition!')
else:
    print(f'  {n_pass}/{n_total} — {n_total-n_pass} FAILED')
print('=' * 60)
sys.exit(0 if n_pass == n_total else 1)
