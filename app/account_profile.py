"""Versioned, optional account administration fields. Never stores passwords."""

import datetime

FIELDS = {
    "display_name": 100,
    "student_id": 40,
    "email": 160,
    "joined_on": 10,
    "expires_on": 10,
    "notes": 600,
}
SCHEMA_VERSION = 1


def clean(req):
    result = {"schema_version": SCHEMA_VERSION}
    for key, limit in FIELDS.items():
        value = str(req.get(key) or "").strip()
        if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("계정 정보의 길이와 입력값을 확인하세요.")
        if key in ("joined_on", "expires_on") and value:
            try:
                datetime.date.fromisoformat(value)
            except ValueError:
                raise ValueError("날짜는 YYYY-MM-DD 형식으로 입력하세요.") from None
        result[key] = value or None
    if (
        result["joined_on"]
        and result["expires_on"]
        and result["expires_on"] < result["joined_on"]
    ):
        raise ValueError("이용 종료일은 추가일자보다 빠를 수 없습니다.")
    return result


def public(user):
    return {k: user.get("profile", {}).get(k) for k in FIELDS}
