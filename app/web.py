import datetime, json, os, pathlib, secrets, socket, threading, time
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    send_file,
)
from werkzeug.security import check_password_hash

settings = json.loads(
    pathlib.Path(
        os.environ.get("H200_WEB_CONFIG", "/etc/h200-console/web.json")
    ).read_text()
)
app = Flask(__name__)
app.config.update(
    SECRET_KEY=settings["secret"],
    MAX_CONTENT_LENGTH=8192,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(minutes=30),
    TRUSTED_HOSTS=os.environ.get("H200_TRUSTED_HOSTS", "127.0.0.1,localhost").split(
        ","
    ),
)
attempts = {}
lock = threading.Lock()


def call(data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(150)
        s.connect(
            os.environ.get("H200_BROKER_SOCKET", "/run/h200-console/control.sock")
        )
        s.sendall((json.dumps(data) + "\n").encode())
        res = json.loads(s.makefile("rb").readline(1024 * 1024))
    if not res["ok"]:
        raise ValueError(res["error"])
    return res["data"]


@app.before_request
def guard():
    if request.path == "/healthz":
        return
    session.setdefault("csrf", secrets.token_urlsafe(32))
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(403)
    if (
        request.path not in ["/login", "/language"]
        and not request.path.startswith("/static/")
        and not session.get("admin")
    ):
        if request.path.startswith("/api/"):
            abort(401)
        return redirect(url_for("login"))


@app.after_request
def headers(res):
    res.headers["Cache-Control"] = "no-store"
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    return res


@app.route("/healthz")
def health():
    return jsonify(status="ok", version="0.5.2")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key = request.remote_addr
        now = time.monotonic()
        with lock:
            failures = [t for t in attempts.get(key, []) if now - t < 900]
            if len(failures) >= 8:
                abort(429)
            if request.form.get("username") == settings.get(
                "username", "admin"
            ) and check_password_hash(
                settings["password_hash"], request.form.get("password", "")
            ):
                attempts.pop(key, None)
                lang = session.get("language")
                session.clear()
                session["language"] = lang
                session["admin"] = True
                session["csrf"] = secrets.token_urlsafe(32)
                session.permanent = True
                return redirect("/")
            attempts[key] = failures + [now]
        flash("계정 또는 비밀번호를 확인하세요.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.get("/")
def home():
    try:
        data = call({"action": "status"})
    except (OSError, ValueError):
        return render_template("unavailable.html"), 503
    return render_template("home.html", data=data)


@app.get("/api/status")
def status():
    return jsonify(call({"action": "status"}))


@app.post("/action")
def action():
    data = {
        k: request.form.get(k)
        for k in ["action", "lab", "user", "confirm", "password", "size_gb"]
    }
    try:
        flash(call(data)["message"], "success")
    except (OSError, ValueError) as e:
        flash(str(e), "error")
    return redirect(url_for("lab_page", lab_id=data["lab"], section="storage"))


@app.post("/api/action")
def api_action():
    try:
        return jsonify(call(request.get_json()))
    except ValueError as e:
        return jsonify(error=str(e)), 403


@app.get("/manual")
def manual():
    data = call({"action": "status"})
    lab = next(
        (l for l in data["labs"] if l["id"] == request.args.get("lab")),
        data["labs"][0] if data["labs"] else None,
    )
    if lab is None:
        abort(404)
    from i18n import language

    cpu = next(
        (
            l.split(":", 1)[1].strip()
            for l in pathlib.Path("/proc/cpuinfo").read_text().splitlines()
            if l.startswith("model name")
        ),
        "CPU",
    )
    blocks = [
        dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        for block in pathlib.Path("/proc/cpuinfo").read_text().split("\n\n")
        if block.strip()
    ]
    sockets = {b.get("physical id\t", "0").strip() for b in blocks}
    cpu = cpu + " × " + str(len(sockets)) + " / " + str(os.cpu_count()) + " threads"
    defaults = settings.get("document_defaults", {})
    lang = language()
    return render_template(
        "manual.html",
        data=data,
        lab=lab,
        locale=lang,
        default_host="127.0.0.1" if lab["sandbox"] else request.host.split(":")[0],
        cpu_model=cpu,
        environment=defaults.get("environment_" + lang, ""),
        permissions=defaults.get("permissions_" + lang, ""),
    )


@app.post("/manual/pdf")
def manual_pdf():
    from manual_pdf import make_pdf

    data = call({"action": "status"})
    labs = [l for l in data["labs"] if l["id"] == request.form.get("lab")]
    if not labs:
        abort(400)
    catalog = call({"action": "catalog"})
    data["account_resources"] = next(
        l["users"] for l in catalog["labs"] if l["id"] == labs[0]["id"]
    )
    try:
        pdf = make_pdf(data, labs, request.form)
    except ValueError as e:
        return str(e), 400
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="LabHarbor_"
        + labs[0]["id"]
        + "_"
        + request.form.get("document_language", "ko")
        + ".pdf",
        max_age=0,
    )


@app.get("/labs")
def labs_page():
    return render_template("labs.html", data=call({"action": "status"}))


@app.get("/labs/<lab_id>")
@app.get("/labs/<lab_id>/<section>")
def lab_page(lab_id, section="overview"):
    titles = dict(
        overview="연구실 설정",
        accounts="계정",
        resources="자원 설정",
        limits="CPU·메모리 조정",
        gpu="GPU",
        storage="공유 저장공간",
        images="이미지 프리셋",
        backups="백업",
    )
    if section not in titles:
        abort(404)
    data = call({"action": "status"})
    lab = next((l for l in data["labs"] if l["id"] == lab_id), None)
    if not lab:
        abort(404)
    catalog = call({"action": "catalog"})
    current = next(l for l in catalog["labs"] if l["id"] == lab_id)
    return render_template(
        "lab.html",
        data=data,
        lab=lab,
        current=current,
        catalog=catalog,
        section=section,
        titles=titles,
        storage_limit=catalog["storage_limit"],
    )


@app.get("/activity")
def activity_page():
    return render_template("activity.html", data=call({"action": "status"}))


@app.route("/provision", methods=["GET", "POST"])
def provision_page():
    if request.method == "POST":
        try:
            result = call(
                dict(
                    action="provision_submit",
                    plan=request.form.get("plan"),
                    confirm=request.form.get("confirm"),
                )
            )
            flash(result["message"], "success")
        except (ValueError, OSError) as exc:
            flash(str(exc), "error")
        return redirect("/provision")
    return render_template(
        "provision.html", changes=call({"action": "provision_plans"})
    )


@app.get("/api/provision")
def provision_status():
    return jsonify(call({"action": "provision_plans"}))


@app.get("/api/catalog")
def catalog_api():
    return jsonify(call({"action": "catalog"}))


@app.get("/api/images/<provider>")
def images_api(provider):
    import image_catalog

    try:
        return jsonify(image_catalog.catalog(provider))
    except ValueError:
        abort(400)


@app.post("/hot-action")
def hot_action():
    fields = [
        "action",
        "lab",
        "user",
        "confirm",
        "cpu",
        "ram",
        "consistency",
        "new_user",
        "password",
        "image_provider",
        "image_tag",
        "root_access",
        "storage",
        "gpu_selection",
    ]
    req = {k: request.form.get(k) for k in fields}
    try:
        flash(call(req)["message"], "success")
    except (ValueError, OSError) as e:
        flash(str(e), "error")
    target = {
        "resources": "limits",
        "backup": "backups",
        "adduser": "accounts",
        "profile_save": "images",
    }.get(req["action"], "overview")
    return redirect(url_for("lab_page", lab_id=req.get("lab", ""), section=target))


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "POST":
        req = {
            k: request.form.get(k)
            for k in ["id", "title", "container", "storage", "username", "port"]
        }
        req["action"] = "register"
        try:
            flash(call(req)["message"], "success")
            return redirect("/labs")
        except (OSError, ValueError) as e:
            flash(str(e), "error")
    return render_template("register.html", catalog=call({"action": "catalog"}))


@app.get("/language")
def set_language():
    from i18n import TRANSLATIONS

    lang = request.args.get("lang")
    if lang in TRANSLATIONS:
        session["language"] = lang
    from urllib.parse import urlsplit

    previous = urlsplit(request.referrer or "/")
    return redirect(
        previous.path
        if previous.netloc == request.host
        and previous.path.startswith("/")
        and not previous.path.startswith("//")
        else "/"
    )


@app.get("/api/translations")
def translations():
    from i18n import language, TRANSLATIONS

    return jsonify(TRANSLATIONS.get(language(), {}))


@app.after_request
def localize_response(response):
    if response.mimetype == "text/html":
        from i18n import language, LocalizedHTML

        parser = LocalizedHTML(language())
        parser.feed(response.get_data(as_text=True))
        response.set_data("".join(parser.parts))
        response.headers["Content-Language"] = language()
    return response


@app.get("/api/document-defaults")
def document_defaults():
    return jsonify(settings.get("document_defaults", {}))


@app.context_processor
def language_options():
    from i18n import TRANSLATIONS

    return {
        "languages": {
            code: phrases.get("_language_name", code)
            for code, phrases in TRANSLATIONS.items()
        }
    }
