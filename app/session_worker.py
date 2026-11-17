"""Root worker entered through the authenticating Linux user's sudo command."""
import sys,pathlib,os,json,fcntl,select,time,threading,subprocess
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import broker,hotops
READS={'status','catalog','provision_sources','provision_plans','telemetry','storage_usage','files'}

def main():
    if os.geteuid()!=0 or not os.environ.get('SUDO_USER') or not os.environ.get('SUDO_UID'): raise SystemExit(1)
    actor=os.environ['SUDO_USER'];uid=int(os.environ['SUDO_UID'])
    print(json.dumps({'actor':actor,'uid':uid,'euid':os.geteuid()}),flush=True)
    broker.audit('linux_login',None,None,'ok')
    # sudo may not consume stdin on NOPASSWD hosts; discard the password line.
    stream=os.fdopen(sys.stdin.fileno(),'rb',buffering=0,closefd=False)
    while True:
        if not select.select([stream],[],[],15)[0]: return
        raw=stream.readline(8193)
        if not raw: return
        if raw.strip()==b'{"action":"_ready"}': break
    deadline=time.monotonic()+1800
    gate=open('/run/h200-console/management.lock','a+')
    held=False
    try:
        while time.monotonic()<deadline:
            if held and not hotops.JOB_LOCK.locked(): fcntl.flock(gate,fcntl.LOCK_UN);held=False
            if not select.select([stream],[],[],1)[0]: continue
            line=stream.readline(8193)
            if not line: break
            req=json.loads(line)
            mutation=req.get('action') not in READS
            if mutation and held:
                response={'ok':False,'error':'다른 관리 작업이 진행 중입니다.'}
            else:
                try:
                    if mutation: fcntl.flock(gate,fcntl.LOCK_EX|fcntl.LOCK_NB);held=True
                    if req.get('action')=='identity_check':
                        broker.audit('identity_check',None,None,'ok')
                        response={'ok':True,'data':{'actor':actor,'uid':uid,'effective_uid':os.geteuid()}}
                    else: response=broker.process_request(req)
                except BlockingIOError: response={'ok':False,'error':'다른 관리 작업이 진행 중입니다.'}
            print(json.dumps(response,ensure_ascii=False),flush=True)
    finally:
        while hotops.JOB_LOCK.locked(): time.sleep(1)
        gate.close();broker.audit('linux_logout',None,None,'ok')

if __name__=='__main__': main()
