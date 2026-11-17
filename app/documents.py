"""Version 1 access-sheet data contract. No credentials or request-supplied specs."""

import re
import permissions

SCHEMA_VERSION = 1
NA = "N/A"


def value(v):
    return NA if v is None or v == "" else str(v)


def compose(settings, data, lab, accounts, lang="ko", note=""):
    if lang not in ("ko", "en") or len(note) > 600:
        raise ValueError("문서 언어와 추가 안내를 확인하세요.")
    defaults = settings.get("document_defaults", {})
    profile = dict(defaults)
    profile.update(settings.get("document_labs", {}).get(lab["id"], {}))
    if profile.get("schema_version", 1) != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 안내서 설정 버전입니다.")
    tr = lambda ko, en: ko if lang == "ko" else en
    host = profile.get("access_host") or settings.get("access_host")
    if host and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise ValueError("서버 주소 설정을 확인하세요.")
    selected = lab.get("gpu_indices", [lab.get("gpu")])
    gpus = [g for g in data.get("gpus", []) if g["index"] in selected]
    gpu_specs = [
        "{} / {} GiB".format(g.get("name", NA), round(g["total"] / 1024, 1))
        for g in gpus
    ]
    gpu_text = " + ".join(gpu_specs) if gpu_specs else NA
    cpu_model = data.get("cpu_model") or NA
    cpu_values, ram_values = [], []
    for u in accounts:
        cpu_values.append(str(u["cpu"]) + " cores" if u.get("cpu") else cpu_model)
        ram_values.append(
            str(u["ram"]) + " GiB"
            if u.get("ram")
            else value(data.get("memory_total_gib")) + " GiB"
        )

    def account_values(values):
        if not values:
            return NA
        if len(set(values)) == 1:
            return values[0]
        return "\n".join(u["name"] + ": " + v for u, v in zip(accounts, values))

    resources = [
        dict(id="gpu", label="GPU", value=gpu_text),
        dict(id="cpu", label="CPU", value=account_values(cpu_values)),
        dict(
            id="memory",
            label=tr("시스템 메모리", "System memory"),
            value=account_values(ram_values),
        ),
        dict(
            id="storage",
            label=tr("공유 저장공간", "Shared storage"),
            value=(
                str(lab["storage_gb"]) + " GB"
                if lab.get("storage_gb") is not None
                else NA
            ),
        ),
        dict(
            id="environment",
            label=tr("기본 개발 환경", "Development environment"),
            value=value(profile.get("environment_" + lang)),
        ),
        dict(
            id="permissions",
            label=tr("권한 범위", "Permissions"),
            value=account_values([permissions.text(u.get("permissions"), lang) for u in accounts]),
        ),
    ]
    if lab.get('home_only'):
        storage = next(r for r in resources if r['id']=='storage')
        storage['label'] = tr('연구실 저장공간','Laboratory storage')
        amount = lab.get('allocated_gb')
        capacity = (f'{amount / 1000:g} TB' if amount is not None else storage['value'])
        storage['value'] = capacity + tr(' 전체 계정 공동 사용 · 개인별 용량 제한 없음',' total across accounts; no individual quota')
        resources.insert(0,dict(id='layout',label=tr('사용 환경','Workspace'),value=tr('공용 컨테이너 1개 · 개인 계정으로 접속','One laboratory container; individual user accounts')))
        resources.insert(5,dict(id='home',label=tr('개인 작업공간','Personal workspace'),value=tr('/home/본인ID · 일반 계정은 본인 폴더만 접근','/home/your-ID; standard users can access only their own home')))
        admins = [u['name'] for u in accounts if u.get('permissions',{}).get('container_sudo')]
        roles = tr('일반 계정: 개인 Python·Conda 환경에 패키지 설치','Standard accounts: install packages in personal Python/Conda environments')
        if admins:
            roles += '\n' + tr('관리자','Administrators') + ' (' + ', '.join(admins) + '): ' + tr('컨테이너 내부 sudo','sudo inside the container')
        next(r for r in resources if r['id']=='permissions')['value'] = roles
        if lab.get('account_backend') == 'native_etc':
            resources.append(dict(id='password_change',label=tr('비밀번호 변경','Password change'),value=tr('passwd · 본인 비밀번호 변경','passwd - change your own password')))
    extras = profile.get("extra_fields", [])
    if not isinstance(extras, list) or len(extras) > 12:
        raise ValueError("안내서 추가 항목 설정을 확인하세요.")
    for field in extras:
        label = value(field.get("label_" + lang) or field.get("label"))
        content = value(field.get("value_" + lang) or field.get("value"))
        if len(label) > 80 or len(content) > 1200:
            raise ValueError("안내서 추가 항목 길이를 확인하세요.")
        resources.append(dict(id=value(field.get("id")), label=label, value=content))
    users = []
    for u in lab.get("users", []):
        port = u.get("port")
        name = u.get("name")
        command = f"ssh -p {port} {name}@{host}" if host and port and name else NA
        users.append(
            dict(
                id=value(name),
                display_name=value(u.get("profile", {}).get("display_name")),
                port=value(port),
                command=command,
            )
        )
    return dict(
        schema_version=SCHEMA_VERSION,
        lab_id=lab["id"],
        title=value(lab.get("title")),
        language=lang,
        host=value(host),
        accounts=users,
        resources=resources,
        note=note,
        shared_memory=bool(accounts) and any(not u.get("ram") for u in accounts),
    )
