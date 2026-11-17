"""Ephemeral sudo-backed Linux sessions. No password or user database."""
import json,os,pathlib,pwd,secrets,select,subprocess,threading,time
import pam_auth
import spwd
WORKER=str(pathlib.Path(__file__).with_name('session_worker.py'))
PYTHON='/usr/bin/python3'
SESSIONS={}
LOCK=threading.Lock()
FAILURES={}

def allowed(user):
    try:
        p=pwd.getpwnam(user)
        if p.pw_uid==0 or p.pw_shell.endswith(('nologin','false')): return False
        if spwd.getspnam(user).sp_pwdp.startswith(("!", "*")): return False
        if not pam_auth.authenticate(user): return False
        r=subprocess.run(['sudo','-n','-l','-U',user,'--',PYTHON,'-I',WORKER],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        return r.returncode==0
    except (KeyError,subprocess.SubprocessError): return False

def read_line(process, timeout):
    if not select.select([process.stdout],[],[],timeout)[0]: raise ValueError('Linux 인증 응답 시간이 초과되었습니다.')
    line=process.stdout.readline(1048576)
    if not line: raise ValueError('로그인 세션이 종료되었습니다. 다시 로그인하세요.')
    return json.loads(line)

def login(req):
    user=str(req.get('username') or '')
    password=req.pop('password','')
    if not user or len(user)>64 or not password or len(password)>512 or '\n' in password: raise ValueError('계정 또는 비밀번호를 확인하세요.')
    now=time.monotonic()
    with LOCK:
        expired=[token for token,item in SESSIONS.items() if now>item['expires'] or item['process'].poll() is not None]
    for token in expired: close(token)
    with LOCK:
        recent=[t for t in FAILURES.get(user,[]) if now-t<900]
        if len(recent)>=8: raise ValueError('로그인 시도 횟수를 초과했습니다.')
        FAILURES[user]=recent+[now]
        if len(SESSIONS)>=8: raise ValueError('활성 로그인 세션이 너무 많습니다.')
    if not pam_auth.authenticate(user,password) or not allowed(user): raise ValueError('계정 또는 sudo 권한을 확인하세요.')
    p=pwd.getpwnam(user)
    process=subprocess.Popen(['sudo','-k','-S','-p','','--',PYTHON,'-I',WORKER],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,user=p.pw_uid,group=p.pw_gid,extra_groups=os.getgrouplist(user,p.pw_gid),cwd='/',env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','HOME':p.pw_dir,'USER':user,'LOGNAME':user},bufsize=0)
    try:
        process.stdin.write((password+'\n').encode());password=None
        ready=read_line(process,15)
        process.stdin.write(b'{"action":"_ready"}\n')
        if ready.get('actor')!=user or ready.get('uid')!=p.pw_uid or ready.get('euid')!=0: raise ValueError('Linux 실행 권한을 확인하세요.')
    except Exception:
        process.stdin.close();process.terminate();raise
    token=secrets.token_urlsafe(32)
    with LOCK:
        SESSIONS[token]={'process':process,'user':user,'expires':now+1800,'lock':threading.Lock()}
        FAILURES.pop(user,None)
    return {'token':token,'username':user}

def close(token):
    with LOCK: item=SESSIONS.pop(token,None)
    if item:
        with item['lock']:
            item['process'].stdin.close()
            threading.Thread(target=item['process'].wait,daemon=True).start()

def handle(req):
    try:
        action=req.get('action')
        if action=='linux_login': return {'ok':True,'data':login(req)}
        token=req.pop('_session',None)
        with LOCK: item=SESSIONS.get(token)
        if not item or time.monotonic()>item['expires'] or not allowed(item['user']):
            close(token);raise ValueError('Linux 로그인 세션이 만료되었습니다. 다시 로그인하세요.')
        if action=='linux_logout': close(token);return {'ok':True,'data':{}}
        if action=='linux_session': return {'ok':True,'data':{'username':item['user']}}
        req.pop('actor',None);req.pop('actor_uid',None)
        with item['lock']:
            item['process'].stdin.write((json.dumps(req)+'\n').encode())
            return read_line(item['process'],145)
    except Exception as e:
        return {'ok':False,'error':str(e) if isinstance(e,ValueError) else 'Linux 인증 또는 실행에 실패했습니다.'}
