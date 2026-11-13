import json, pathlib
from html import escape
from html.parser import HTMLParser
from flask import request, session

ROOT = pathlib.Path(__file__).parent / "locales"
TRANSLATIONS = {
    p.stem: json.loads(p.read_text(encoding="utf-8-sig")) for p in ROOT.glob("*.json")
}


def language():
    return (
        session.get("language")
        if session.get("language") in TRANSLATIONS
        else request.accept_languages.best_match(list(TRANSLATIONS), default="ko")
    )


def translate(text, lang):
    if lang == "ko" or "교수님" in text:
        return text
    d = TRANSLATIONS.get(lang, {})
    if text.strip() in d:
        return text.replace(text.strip(), d[text.strip()])
    normalized = " ".join(text.split())
    if normalized in d:
        return text.replace(text.strip(), d[normalized])
    # Longest-first matching avoids translating text produced by a previous match twice.
    import re

    pattern = "|".join(re.escape(k) for k in sorted(d, key=len, reverse=True))
    return re.sub(pattern, lambda m: d[m.group()], text) if pattern else text


class LocalizedHTML(HTMLParser):
    def __init__(self, lang):
        super().__init__(convert_charrefs=False)
        self.lang = lang
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        import re

        if tag in ("script", "style"):
            self.skip += 1
        raw = self.get_starttag_text()
        if tag == "html":
            raw = re.sub(r'lang="[^"]*"', 'lang="' + self.lang + '"', raw)
        for k, v in attrs:
            if k in ("placeholder", "aria-label", "title") and v:
                raw = raw.replace(
                    k + '="' + v + '"',
                    k + '="' + escape(translate(v, self.lang), quote=True) + '"',
                )
        self.parts.append(raw)

    def handle_endtag(self, tag):
        self.parts.append("</" + tag + ">")
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_data(self, data):
        self.parts.append(data if self.skip else translate(data, self.lang))

    def handle_entityref(self, name):
        self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        self.parts.append("&#" + name + ";")

    def handle_decl(self, decl):
        self.parts.append("<!" + decl + ">")

    def handle_comment(self, data):
        self.parts.append("<!--" + data + "-->")


def return_path(value, host):
    from urllib.parse import urlsplit, unquote

    if any(ord(c) < 32 for c in value):
        return "/"
    target = urlsplit(value)
    decoded = unquote(target.path)
    if (
        target.netloc not in ("", host)
        or target.scheme not in ("", "http", "https")
        or not decoded.startswith("/")
        or decoded.startswith("//")
        or chr(92) in decoded
    ):
        return "/"
    return target.path + ("?" + target.query if target.query else "")
