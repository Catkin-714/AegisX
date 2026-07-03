"""
mcu_tcp_client.py — Python TCP 客户端库：调用 Rust HP 全协议

与 party.py 和 infer_engine.py 使用相同的 common.PRG 和通信函数。
"""
import socket, time, math, threading, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'backend'))
from common import PRG, fmod, send_msg as _send, recv_msg as _recv, SHARED_SEED, L_U64, MOD, SIGN_SCALE, GELU_COEF

HOST = '127.0.0.1'; PORT = 9000

def connect(role):
    for _ in range(30):
        try:
            s = socket.socket(); s.connect((HOST, PORT))
            _send(s, {'role': role}); return s
        except: time.sleep(0.15)
    raise ConnectionError(f"Can't connect as {role}")

def parallel(f0, f1):
    r = {}
    t0 = threading.Thread(target=lambda: r.__setitem__(0, f0()))
    t1 = threading.Thread(target=lambda: r.__setitem__(1, f1()))
    t0.start(); t1.start(); t0.join(); t1.join()
    return r[0], r[1]

def session_done(c0, c1):
    _send(c0, {'op': 'done'}); _send(c1, {'op': 'done'})

# ── 协议客户端 ──

def _exp_inner(c, pid, prg, sx):
    """exp 内部版: HP 已进入子协议, 无 op"""
    rv = prg.real(MOD); mi = fmod(sx+rv) if pid == 0 else fmod(sx)
    _send(c, {'m': mi}); si = _recv(c)['s']
    bits = []
    for th in [MOD-rv, -rv]:
        zi = sx - th if pid == 0 else sx
        _send(c, {'za': (1.0 + prg.real(SIGN_SCALE)) * zi})
        bits.append(_recv(c)['bit'])
    return si * math.exp((bits[0] - (1 - bits[1])) * MOD - rv)

def mul_pair(c0, c1, x=12345, y=67890):
    x0, x1 = 999999, (x-999999)%L_U64; y0, y1 = 888888, (y-888888)%L_U64
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)
    def f(pid, c, sx, sy, px):
        rx, ry = px.full(), px.full()
        _send(c, {'op':'mul','mx':(sx+rx)%L_U64 if pid==0 else sx%L_U64,
                  'my':(sy+ry)%L_U64 if pid==0 else sy%L_U64})
        si = _recv(c)['share']
        corr = (sx*ry+sy*rx+rx*ry)%L_U64 if pid==0 else (sx*ry+sy*rx)%L_U64
        return (si-corr)%L_U64
    r0, r1 = parallel(lambda: f(0,c0,x0,y0,p0), lambda: f(1,c1,x1,y1,p1))
    return (r0+r1)%L_U64

def exp_pair(c0, c1, xv=1.5):
    x0, x1 = xv*0.7, xv*0.3
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)
    def f(pid, c, sx, px):
        rv = px.real(MOD); mi = fmod(sx+rv) if pid==0 else fmod(sx)
        _send(c, {'op':'exp','m':mi}); si = _recv(c)['s']
        bits = []
        for th in [MOD-rv, -rv]:
            zi = sx-th if pid==0 else sx
            _send(c, {'za':(1.0+px.real(SIGN_SCALE))*zi})
            bits.append(_recv(c)['bit'])
        return si * math.exp((bits[0]-(1-bits[1]))*MOD-rv)
    r0, r1 = parallel(lambda: f(0,c0,x0,p0), lambda: f(1,c1,x1,p1))
    return r0+r1

def softmax_pair(c0, c1, xs=[1.0,-1.5,0.3], m_idx=0):
    k = len(xs); xs0 = [v*0.7 for v in xs]; xs1 = [xs[i]-xs0[i] for i in range(k)]
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)
    def f(pid, c, sxs, px):
        _send(c, {'op':'softmax','k':k})
        es = [_exp_inner(c, pid, px, s) for s in sxs]
        t_val = px.real(MOD); et = math.exp(t_val)
        _send(c, {'u':et*sum(es)}); d = _recv(c)['D']
        return es[m_idx]*et/d
    r0, r1 = parallel(lambda: f(0,c0,xs0,p0), lambda: f(1,c1,xs1,p1))
    return r0+r1

def gelu_pair(c0, c1, xv=0.5):
    x0, x1 = xv*0.7, xv*0.3
    p0, p1 = PRG(SHARED_SEED), PRG(SHARED_SEED)
    def f(pid, c, sx, px):
        scaled = GELU_COEF*sx; _send(c, {'op':'gelu'})
        ei = _exp_inner(c, pid, px, scaled)
        di = ei + (1.0 if pid==0 else 0)
        t_val = px.real(MOD); et = math.exp(t_val)
        _send(c, {'u':et*di}); d_pub = _recv(c)['D']; sig_i = ei*et/d_pub
        ra, rb = px.real(MOD), px.real(MOD)
        _send(c, {'ma':sx+ra if pid==0 else sx, 'mb':sig_i+rb if pid==0 else sig_i})
        si = _recv(c)['s']
        corr = sx*rb+sig_i*ra+(ra*rb if pid==0 else 0)
        return si-corr
    r0, r1 = parallel(lambda: f(0,c0,x0,p0), lambda: f(1,c1,x1,p1))
    return r0+r1
