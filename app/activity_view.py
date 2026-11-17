"""Presentation metadata only; unknown actions retain their original identifier."""

ACTIONS = {
    "linux_login": ("person", "Linux 로그인"),
    "linux_logout": ("person", "로그아웃"),
    "identity_check": ("person", "실행 권한 확인"),
    "container_rename": ("box", "컨테이너 이름 변경"),
    "files": ("disk", "파일 조회"),
    "provision_plans": ("lab", "생성 계획 조회"),
    "create": ("lab", "환경 생성"),
    "recreate": ("restart", "환경 재생성"),
    "start": ("restart", "환경 시작"),
    "stop": ("restart", "환경 정지"),
    "password": ("person", "비밀번호 변경"),
    "gpu_test": ("chip", "GPU 점검"),
    "grow": ("disk", "저장공간 확장"),
    "account_create": ("person", "계정 추가"),
    "account_backup": ("archive", "계정 백업"),
    "account_delete": ("person", "계정 삭제"),
    "lab_restart": ("power", "연구실 재시작"),
    "account_password": ("key", "비밀번호 변경"),
    "lab_share": ("settings", "공용 컨테이너 전환"),
    "adduser": ("person", "계정 추가"),
    "account_metadata": ("person", "계정 정보 변경"),
    "metadata": ("lab", "연구실 정보 변경"),
    "gpu_reconfigure": ("chip", "GPU 배정 변경"),
    "resources": ("chip", "CPU·메모리 변경"),
    "environment_apply": ("box", "개발환경 교체"),
    "maintenance_restart": ("restart", "환경 재시작"),
    "maintenance_recreate": ("restart", "환경 재생성"),
    "backup": ("disk", "백업 생성"),
    "profile_save": ("box", "프리셋 저장"),
    "register": ("lab", "연구실 등록"),
    "provision_prepare": ("lab", "연구실 생성 준비"),
    "provision_submit": ("lab", "연구실 생성 요청"),
    "telemetry_retention": ("clock", "기록 보관 변경"),
    "storage_grow": ("disk", "저장공간 확장"),
}
ICONS = {
    "key": "🔑",
    "power": "↻",
    "archive": "▤",
    "settings": "⚙",
    "person": "♙",
    "lab": "▦",
    "chip": "▥",
    "box": "▣",
    "restart": "↻",
    "disk": "▤",
    "clock": "◷",
    "other": "◇",
}
ASYNC = {
    "account_create",
    "environment_apply",
    "backup",
    "provision_prepare",
    "provision_submit",
}


def events(data):
    names = {l["id"]: l["title"] for l in data.get("labs", [])}
    result = []
    for e in data.get("events", []):
        kind, label = ACTIONS.get(e.get("action"), ("other", "관리 작업"))
        status = e.get("result", "unknown")
        result.append(
            dict(
                time=e.get("time", "N/A"),
                lab=names.get(e.get("lab"), e.get("lab") or "서버"),
                user=e.get("user") or "전체",
                actor=e.get("actor") or "N/A",
                code=e.get("action", "N/A"),
                label=label,
                icon=ICONS.get(kind, ICONS["other"]),
                state=status,
                read=e.get("action") in {"files", "provision_plans"},
                label_result=("요청 접수" if e.get("action") in ASYNC else "처리 완료")
                if status == "ok"
                else "권한 거부"
                if status == "denied"
                else "실패"
                if status == "failed"
                else "확인 필요",
            )
        )
    return result
