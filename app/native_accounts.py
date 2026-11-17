"""Use native shadow tools for persistent /etc accounts and password locking."""
import crypt
import os
import pathlib
import re
import shutil
import time
import account_profile
import hotops


def set_password(container, name, value=None, hashed=None):
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{1,30}', name):
        raise ValueError('Invalid account name')
    hashed = hashed or crypt.crypt(value, crypt.mksalt(crypt.METHOD_SHA512))
    # Never put passwords or hashes in process arguments. Native tools coordinate
    # with passwd/useradd/userdel rather than overwriting stale account snapshots.
    hotops.run('docker','exec','-i',container,'chpasswd','-e',input=name+':'+hashed+'\n')


def create(req, cfg, spec, source_user, obj):
    name, password = req.get('new_user',''), req.get('password','')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{1,30}',name) or not 8 <= len(password) <= 128 or any(ord(x)<32 for x in password):
        raise ValueError('계정 ID와 8자 이상의 비밀번호를 확인하세요.')
    if any(u['name']==name for s in cfg['labs'].values() for u in s['users']):
        raise ValueError('이미 등록된 계정입니다.')
    root = pathlib.Path(spec['storage'])
    etc = root/'.admin/shared/etc'
    passwd = (etc/'passwd').read_text()
    group = (etc/'group').read_text()
    if any(r.split(':')[0]==name for r in passwd.splitlines()):
        raise ValueError('컨테이너에 이미 존재하는 계정입니다.')
    used = {int(r.split(':')[2]) for r in (passwd+group).splitlines() if r}
    used |= {u['uid'] for s in cfg['labs'].values() for u in s['users']}
    uid = next(i for i in range(12000,60001) if i not in used)
    home = root/name
    if home.exists() or home.is_symlink():
        raise ValueError('사용자 저장 경로가 이미 존재합니다.')
    home.mkdir(mode=0o700)
    added = registered = False
    try:
        for child in ('.tmp','.cache','.conda'):
            (home/child).mkdir(mode=0o700)
        (home/'.bashrc').write_text('[ ! -f /etc/profile.d/research.sh ] || . /etc/profile.d/research.sh\n')
        (home/'.bash_profile').write_text('. ~/.bashrc\n')
        for p in [home,*home.iterdir()]: os.chown(p,uid,uid)
        hotops.run('docker','exec',obj['Id'],'useradd','-M','-U','-u',str(uid),'-G','orvia-research','-s','/bin/bash',name)
        added = True
        set_password(obj['Id'],name,password)
        if hotops.run('docker','exec',obj['Id'],'id','-u',name) != str(uid):
            raise ValueError('계정 UID 검증 실패')
        profile = account_profile.clean(req)
        profile['joined_on'] = profile.get('joined_on') or time.strftime('%Y-%m-%d')
        spec['users'].append(dict(name=name,uid=uid,container=hotops.name(spec,source_user),port=source_user['port'],profile=profile,root_access=False,credential_dir='.admin/shared/etc'))
        hotops.save(hotops.ETC/'policy.json',cfg)
        registered = True
        return {'message':'공용 컨테이너에 계정을 추가했습니다. 재시작 없이 접속할 수 있습니다.'}
    finally:
        if not registered:
            if added: hotops.run('docker','exec',obj['Id'],'userdel',name)
            shutil.rmtree(home)


def restore(container, name, originals):
    """Restore only the deleted user, never overwrite other users' new passwords."""
    db = {p.name:text for p,text in originals.items()}
    row = next(r.split(':') for r in db['passwd'].splitlines() if r.split(':')[0]==name)
    gid = row[3]
    groups = [r.split(':')[0] for r in db['group'].splitlines() if name in r.split(':')[3].split(',')]
    existing = hotops.run('docker','exec',container,'cat','/etc/group')
    if not any(r.split(':')[2]==gid for r in existing.splitlines()):
        hotops.run('docker','exec',container,'groupadd','-g',gid,name)
    hotops.run('docker','exec',container,'useradd','-M','-u',row[2],'-g',gid,'-d',row[5],'-s',row[6],name)
    if groups: hotops.run('docker','exec',container,'usermod','-aG',','.join(groups),name)
    secret = next(r.split(':')[1] for r in db['shadow'].splitlines() if r.split(':')[0]==name)
    set_password(container,name,hashed=secret)
