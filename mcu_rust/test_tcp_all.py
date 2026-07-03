"""
test_tcp_all.py — Rust HP TCP 全协议端到端验证
"""
import subprocess, socket, struct, json, time, threading, os, math, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'dashboard', 'backend'))
from common import PRG, fmod, send_msg as send, recv_msg as recv, L_U64, MOD, SIGN_SCALE

HOST='127.0.0.1'; PORT=9000
EXE=os.path.join(os.path.dirname(__file__),'target/release/mcu_hp.exe')
if not os.path.exists(EXE): EXE=EXE.replace('release','debug')

def parallel(f0,f1):
    r={}; t0=threading.Thread(target=lambda:r.__setitem__(0,f0()))
    t1=threading.Thread(target=lambda:r.__setitem__(1,f1()))
    t0.start(); t1.start(); t0.join(); t1.join()
    return r[0],r[1]

# ── Protocol client functions ──

def _exp_inner(c, pid, prg, sx):
    """Send/recv one exp through HP (HP already expects exp sub-msg)"""
    rv=prg.real(MOD)
    mi=fmod(sx+rv) if pid==0 else fmod(sx)
    send(c,{'m':mi})
    si=recv(c)['s']
    bits=[]
    for th in [MOD-rv, -rv]:
        zi=sx-(th if pid==0 else 0)
        send(c,{'za':(1.0+prg.real(SIGN_SCALE))*zi})
        bits.append(recv(c)['bit'])
    w=bits[0]-(1-bits[1])
    return si*math.exp(w*MOD-rv)

def mul_pair(c0,c1,x=12345,y=67890):
    x0,x1=999999,(x-999999)%L_U64; y0,y1=888888,(y-888888)%L_U64
    p0,p1=PRG(bytes(range(16))),PRG(bytes(range(16)))
    def f(pid,c,sx,sy,px):
        rx,ry=px.full(),px.full()
        if pid==0:
            send(c,{'op':'mul','mx':(sx+rx)%L_U64,'my':(sy+ry)%L_U64})
        else:
            send(c,{'op':'mul','mx':sx%L_U64,'my':sy%L_U64})
        si=recv(c)['share']
        if pid==0: corr=(sx*ry+sy*rx+rx*ry)%L_U64
        else: corr=(sx*ry+sy*rx)%L_U64
        return (si-corr)%L_U64
    r0,r1=parallel(
        lambda:f(0,c0,x0,y0,p0), lambda:f(1,c1,x1,y1,p1))
    return (r0+r1)%L_U64

def exp_pair(c0,c1,xv=1.5):
    x0,x1=xv*0.7,xv*0.3
    p0,p1=PRG(bytes(range(16))),PRG(bytes(range(16)))
    def f(pid,c,sx,px):
        rv=px.real(MOD); mi=fmod(sx+rv) if pid==0 else fmod(sx)
        send(c,{'op':'exp','m':mi}); si=recv(c)['s']
        bits=[]
        for th in [MOD-rv,-rv]:
            zi=sx-(th if pid==0 else 0)
            send(c,{'za':(1.0+px.real(SIGN_SCALE))*zi})
            bits.append(recv(c)['bit'])
        w=bits[0]-(1-bits[1])
        return si*math.exp(w*MOD-rv)
    r0,r1=parallel(
        lambda:f(0,c0,x0,p0), lambda:f(1,c1,x1,p1))
    return r0+r1

def softmax_pair(c0,c1,xs=[1.0,-1.5,0.3],m=0):
    k=len(xs); xs0=[v*0.7 for v in xs]; xs1=[xs[i]-xs0[i] for i in range(k)]
    p0,p1=PRG(bytes(range(16))),PRG(bytes(range(16)))
    def f(pid,c,sxs,px):
        send(c,{'op':'softmax','k':k})
        es=[]
        for s in sxs:
            es.append(_exp_inner(c,pid,px,s))
        t=px.real(MOD); et=math.exp(t)
        send(c,{'u':et*sum(es)}); d=recv(c)['D']
        return es[m]*et/d
    r0,r1=parallel(
        lambda:f(0,c0,xs0,p0), lambda:f(1,c1,xs1,p1))
    return r0+r1

def gelu_pair(c0,c1,xv=0.5):
    GELU_COEF=1.702; x0,x1=xv*0.7,xv*0.3
    p0,p1=PRG(bytes(range(16))),PRG(bytes(range(16)))
    def f(pid,c,sx,px):
        scaled=GELU_COEF*sx
        send(c,{'op':'gelu'})
        # exp
        e_i=_exp_inner(c,pid,px,scaled)
        # sm_u
        d_i=e_i+(1.0 if pid==0 else 0)
        t=px.real(MOD); et=math.exp(t)
        send(c,{'u':et*d_i}); d_pub=recv(c)['D']
        sig_i=e_i*et/d_pub
        # gelu_ma
        ra,rb=px.real(MOD),px.real(MOD)
        if pid==0: send(c,{'ma':sx+ra,'mb':sig_i+rb})
        else: send(c,{'ma':sx,'mb':sig_i})
        si=recv(c)['s']
        if pid==0: corr=sx*rb+sig_i*ra+ra*rb
        else: corr=sx*rb+sig_i*ra
        return si-corr
    r0,r1=parallel(
        lambda:f(0,c0,x0,p0), lambda:f(1,c1,x1,p1))
    return r0+r1

# ── Main test ──
def main():
    hp=subprocess.Popen([EXE,'--mode','hp'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    time.sleep(0.5)
    ok=True

    def session_done(c0,c1):
        send(c0,{'op':'done'}); send(c1,{'op':'done'})

    try:
        # Mul
        print('=== Pi_mul ===')
        c0=socket.socket(); c0.connect((HOST,PORT)); send(c0,{'role':'p0'})
        c1=socket.socket(); c1.connect((HOST,PORT)); send(c1,{'role':'p1'})
        r=mul_pair(c0,c1)
        exp=(12345*67890)%L_U64
        print(f'  {r} == {exp} [{"OK" if r==exp else "FAIL"}]'); ok&=r==exp
        session_done(c0,c1); c0.close(); c1.close()

        # Exp
        print('=== Pi_exp ===')
        c0=socket.socket(); c0.connect((HOST,PORT)); send(c0,{'role':'p0'})
        c1=socket.socket(); c1.connect((HOST,PORT)); send(c1,{'role':'p1'})
        r=exp_pair(c0,c1,1.5)
        ex=math.exp(1.5); err=abs(r-ex)
        print(f'  e^1.5={r:.8f} exp={ex:.8f} err={err:.1e} [{"OK" if err<1e-10 else "FAIL"}]')
        ok&=err<1e-10
        session_done(c0,c1); c0.close(); c1.close()

        # Softmax
        print('=== Pi_softmax ===')
        xs=[1.0,-1.5,0.3]; mx=max(xs); exps=[math.exp(v-mx) for v in xs]
        exp_sm=[e/sum(exps) for e in exps]
        for m in range(3):
            c0=socket.socket(); c0.connect((HOST,PORT)); send(c0,{'role':'p0'})
            c1=socket.socket(); c1.connect((HOST,PORT)); send(c1,{'role':'p1'})
            r=softmax_pair(c0,c1,xs,m)
            err=abs(r-exp_sm[m])
            print(f'  sm[{m}]={r:.6f} exp={exp_sm[m]:.6f} err={err:.1e} [{"OK" if err<1e-4 else "FAIL"}]')
            ok&=err<1e-4
            session_done(c0,c1); c0.close(); c1.close()

        # GeLU
        print('=== Pi_gelu ===')
        for xv in [0.5,-1.0,2.0]:
            ex_g=xv/(1.0+math.exp(-1.702*xv))
            c0=socket.socket(); c0.connect((HOST,PORT)); send(c0,{'role':'p0'})
            c1=socket.socket(); c1.connect((HOST,PORT)); send(c1,{'role':'p1'})
            r=gelu_pair(c0,c1,xv)
            err=abs(r-ex_g)
            print(f'  gelu({xv})={r:.6f} exp={ex_g:.6f} err={err:.1e} [{"OK" if err<1e-4 else "FAIL"}]')
            ok&=err<1e-4
            session_done(c0,c1); c0.close(); c1.close()

    finally:
        hp.terminate()

    sep = "=" * 50
    status = "ALL TCP PROTOCOLS OK" if ok else "SOME FAILED"
    print(f"\n{sep}\n  {status}\n{sep}")
    return 0 if ok else 1

if __name__=='__main__': exit(main())
