"""Guarded consolidation of compatible personal containers into one laboratory."""
import copy
import os
import pathlib
import threading
import time
import uuid

import hotops
import maintenance
import reconfigure
import recovery
from shared_accounts import DATABASES, validate_shared
from shared_migration import require_idle


def merge_databases(sources, users, gid):
    names = {u['name'] for u in users}
    merged = {}
    for key in DATABASES:
        records = {}
        for user in users:
            rows = [r.split(':') for r in sources[user['name']][key].splitlines()]
            for row in rows:
                name = row[0]
                if name in names and name != user['name']:
                    continue
                if key in ('group', 'gshadow'):
                    row[3] = ','.join(x for x in row[3].split(',') if x not in names or x == user['name'])
                if key == 'shadow' and name not in names:
                    row[1] = '!'
                old = records.get(name)
                if old and old != row:
                    if key in ('group', 'gshadow') and old[:3] == row[:3]:
                        row[3] = ','.join(sorted(set(filter(None, (old[3]+','+row[3]).split(',')))))
                    else:
                        raise ValueError('계정 또는 시스템 그룹 정보가 충돌하여 전환할 수 없습니다.')
                records[name] = row
        if key == 'passwd':
            for u in users:
                row = records.get(u['name'], [])
                if len(row) != 7 or row[2] != str(u['uid']) or row[5] != '/home/'+u['name']:
                    raise ValueError('계정 UID와 개인 폴더를 확인하세요.')
            if len({r[2] for r in records.values()}) != len(records):
                raise ValueError('중복 UID가 있어 병합할 수 없습니다.')
        if key == 'group':
            records['orvia-research'] = ['orvia-research','x',str(gid),','.join(sorted(names))]
            if len({r[2] for r in records.values()}) != len(records):
                raise ValueError('중복 그룹 ID가 있어 병합할 수 없습니다.')
        if key == 'gshadow':
            records['orvia-research'] = ['orvia-research','!','',','.join(sorted(names))]
        if key == 'shadow' and not names.issubset(records):
            raise ValueError('계정 비밀번호 정보를 확인할 수 없습니다.')
        merged[key] = '\n'.join(':'.join(r) for r in records.values())+'\n'
    return merged


def validate(req):
    c, spec, selected, source = hotops.authorize(req)
    if spec.get('account_layout') == 'shared':
        raise ValueError('이미 연구실 공용 컨테이너입니다.')
    if req.get('ack_downtime') != 'yes' or req.get('ack_recreate') != 'yes':
        raise ValueError('연구실 접속 종료와 공용 환경 전환을 확인하세요.')
    objects = {}
    for user in spec['users']:
        _, _, _, obj = hotops.authorize(dict(req,user=user['name']))
        maintenance.validate(spec,user,obj)
        objects[user['name']] = obj
    if reconfigure.fingerprint(list(objects.values())) != req.get('expected_fingerprint'):
        raise ValueError('환경 상태가 변경되었습니다. 화면을 다시 열어 확인하세요.')
    fields = ('Memory','MemorySwap','NanoCpus','CpuQuota','CpuPeriod','CpusetCpus','DeviceRequests','Devices','CapAdd','CapDrop','SecurityOpt','Privileged','Tmpfs','ShmSize')
    for obj in objects.values():
        if obj['Image'] != source['Image'] or not obj['HostConfig'].get('ReadonlyRootfs'):
            raise ValueError('동일한 읽기 전용 개발환경만 자동 병합합니다. 다른 이미지는 환경 통일이 필요합니다.')
        if any(obj['HostConfig'].get(k) != source['HostConfig'].get(k) for k in fields):
            raise ValueError('자원 한도 또는 권한 설정이 다릅니다. 환경 통일 후 전환하세요.')
        env = lambda o: sorted(e for e in o['Config'].get('Env',[]) if e.split('=',1)[0] not in ('RESEARCH_USER','HOME','USER','LOGNAME'))
        if env(obj) != env(source):
            raise ValueError('개발환경 변수가 서로 달라 자동으로 병합할 수 없습니다.')
    root = pathlib.Path(spec['storage'])
    for user in spec['users']:
        home = root/user['name']
        if home.is_symlink() or home.stat().st_uid != user['uid'] or home.stat().st_mode & 0o077:
            raise ValueError('개인 폴더 소유자 또는 비공개 권한을 확인하세요.')
        mounts = {m['Destination']:m for m in objects[user['name']]['Mounts']}
        allowed = {'/home/'+user['name'],'/shared','/etc/research-ssh','/usr/local/sbin/research-entrypoint'} | {'/etc/'+k for k in DATABASES}
        if set(mounts)-allowed or mounts.get('/home/'+user['name'],{}).get('Source') != str(home):
            raise ValueError('사용자 지정 저장 연결이 있어 별도 이전 검토가 필요합니다.')
        if spec.get('shared_folder') and mounts.get('/shared',{}).get('Source') != spec['shared_folder']:
            raise ValueError('공동 자료 폴더 연결이 일치하지 않습니다.')
    require_idle(spec)
    for obj in objects.values():
        rows = hotops.run('docker','top',obj['Id'],'-eo','uid,pid,comm').splitlines()[1:]
        if any(r.split() and (r.split()[0] != '0' or r.split()[-1] not in ('sshd','tini')) for r in rows):
            raise ValueError('접속 또는 실행 작업이 있습니다. 작업 종료 후 전환하세요.')
    return c,spec,selected,source,objects


def submit(req):
    validate(req)
    if not hotops.JOB_LOCK.acquire(blocking=False):
        raise ValueError('다른 관리 작업이 진행 중입니다.')
    job = dict(id=uuid.uuid4().hex[:12],lab=req['lab'],kind='layout',state='queued',time=time.strftime('%Y-%m-%d %H:%M:%S'),message='공용 환경 준비 중')
    try:
        (hotops.STATE/'jobs').mkdir(exist_ok=True)
        hotops.save(hotops.STATE/'jobs'/(job['id']+'.json'),job)
        threading.Thread(target=worker,args=(dict(req),job),daemon=True).start()
    except Exception:
        hotops.JOB_LOCK.release()
        raise
    return {'message':'연구실 공용 컨테이너 전환을 시작했습니다.'}


def worker(req, job):
    stopped,renamed,files = [],[],{}
    created = None
    paused = policy_saved = admin_created = False
    prior_admin = None
    try:
        c,spec,user,source,objects = validate(req)
        previous = copy.deepcopy(spec)
        root = pathlib.Path(spec['storage'])
        token = job['id']
        archive = root/'.admin'/('merge-'+token)
        archive.mkdir(mode=0o700)
        hotops.save(archive/'policy-before.json',spec)
        hotops.save(archive/'containers-before.json',objects)
        sources = {name:{k:hotops.run('docker','exec',o['Id'],'cat','/etc/'+k)+'\n' for k in DATABASES} for name,o in objects.items()}
        gids = {int(r.split(':')[2]) for db in sources.values() for r in db['group'].splitlines()}
        existing = {int(r.split(':')[2]) for db in sources.values() for r in db['group'].splitlines() if r.startswith('orvia-research:')}
        gid = spec.get('shared_gid') or (next(iter(existing)) if len(existing)==1 else next(i for i in range(60001,65000) if i not in gids))
        databases = merge_databases(sources,spec['users'],gid)
        admin = root/'.admin/shared'
        if any(pathlib.Path(m['Source']).is_relative_to(admin) for o in objects.values() for m in o['Mounts']):
            raise ValueError('기존 환경이 공용 계정 파일을 사용 중입니다.')
        if admin.exists():
            prior_admin = archive/'previous-shared'
            admin.rename(prior_admin)
        admin.mkdir(mode=0o700)
        admin_created = True
        for key,value in databases.items():
            p = admin/key
            p.write_text(value)
            p.chmod(0o600 if key in ('shadow','gshadow') else 0o644)
        entry = pathlib.Path(__file__).with_name('research-entrypoint.sh').read_text().replace('AllowUsers $RESEARCH_USER','AllowGroups orvia-research')
        (admin/'entrypoint.sh').write_text(entry)
        (admin/'entrypoint.sh').chmod(0o755)
        desired = maintenance.create_payload(source)
        h = desired['HostConfig']
        h['Binds'] = None
        h['Mounts'] = [dict(Type='bind',Source=str(root),Target='/home',ReadOnly=False)]
        h['Mounts'] += [dict(Type='bind',Source=str(admin/k),Target='/etc/'+k,ReadOnly=True) for k in DATABASES]
        h['Mounts'] += [dict(Type='bind',Source=str(admin/'entrypoint.sh'),Target='/usr/local/sbin/research-entrypoint',ReadOnly=True)]
        h['Mounts'] += [dict(Type='bind',Source=m['Source'],Target=m['Destination'],ReadOnly=not m['RW']) for m in source['Mounts'] if m['Destination'] in ('/shared','/etc/research-ssh')]
        validate(req)
        active = recovery.pause(spec)
        paused = True
        api = '/v'+maintenance.engine('GET','/version')['ApiVersion']
        for obj in objects.values():
            maintenance.engine('POST',api+'/containers/'+obj['Id']+'/stop?t=15')
            stopped.append(obj)
            name = obj['Name'].lstrip('/')
            maintenance.engine('POST',api+'/containers/'+obj['Id']+'/rename?name='+name+'-merge-'+token)
            renamed.append(obj)
        name = source['Name'].lstrip('/')
        created = maintenance.engine('POST',api+'/containers/create?name='+name,desired)['Id']
        maintenance.engine('POST',api+'/containers/'+created+'/start')
        for attempt in range(20):
            try:
                hotops.run('docker','exec',created,'/usr/sbin/sshd','-t','-f','/run/sshd_config')
                break
            except Exception:
                if attempt == 19: raise
                time.sleep(.5)
        for member in spec['users']:
            if hotops.run('docker','exec',created,'id','-u',member['name']) != str(member['uid']):
                raise ValueError('공용 계정 검증 실패')
            member.update(container=name,port=user['port'],credential_dir='.admin/shared')
        spec.update(account_layout='shared',shared_container=name)
        current = hotops.obj(created)
        validate_shared(spec,current)
        visible = hotops.run('docker','exec','--user',str(user['uid']),created,'nvidia-smi','--query-gpu=uuid','--format=csv,noheader')
        if set(visible.splitlines()) != set(spec.get('gpus',[spec['gpu']])):
            raise ValueError('GPU 연결 검증 실패')
        files = recovery.install(req['lab'],spec,[current])
        latest = hotops.cfg()
        if latest['labs'][req['lab']] != previous:
            raise ValueError('연구실 설정이 변경되어 이전 환경으로 복구합니다.')
        latest['labs'][req['lab']] = spec
        hotops.save(hotops.ETC/'policy.json',latest)
        policy_saved = True
        job.update(state='complete',message='공용 컨테이너 전환 완료',port=user['port'],retained=[o['Name'].lstrip('/')+'-merge-'+token for o in renamed])
    except Exception as error:
        try:
            if files: recovery.restore(files)
            if policy_saved:
                latest = hotops.cfg();latest['labs'][req['lab']] = previous
                hotops.save(hotops.ETC/'policy.json',latest)
            if created: maintenance.engine('DELETE',api+'/containers/'+created+'?force=true&v=false')
            for obj in reversed(renamed):
                maintenance.engine('POST',api+'/containers/'+obj['Id']+'/rename?name='+obj['Name'].lstrip('/'))
            for obj in stopped: maintenance.engine('POST',api+'/containers/'+obj['Id']+'/start')
            if admin_created: admin.rename(archive/'failed-shared')
            if prior_admin: prior_admin.rename(admin)
            job.update(state='failed',message=str(error) if isinstance(error,ValueError) else '전환 실패 · 이전 환경 복구 완료')
        except Exception:
            job.update(state='failed',message='자동 복구 확인 필요 · 관리 기록을 확인하세요.')
    finally:
        try:
            if paused: recovery.resume(spec,active)
            hotops.save(hotops.STATE/'jobs'/(job['id']+'.json'),job)
        finally: hotops.JOB_LOCK.release()
