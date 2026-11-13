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
    return jsonify(status="ok", version="0.6.4")


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


def access_document(lab_id, lang, note=""):
    from documents import compose

    data = call({"action": "status"})
    lab = next(
        (l for l in data["labs"] if l["id"] == lab_id),
        data["labs"][0] if not lab_id and data["labs"] else None,
    )
    if lab is None:
        abort(404)
    catalog = call({"action": "catalog"})
    accounts = next((l["users"] for l in catalog["labs"] if l["id"] == lab["id"]), [])
    document_settings = json.loads(
        pathlib.Path(
            os.environ.get("H200_WEB_CONFIG", "/etc/h200-console/web.json")
        ).read_text()
    )
    return data, lab, compose(document_settings, data, lab, accounts, lang, note)


@app.get("/manual")
def manual():
    from i18n import language

    data, lab, document = access_document(request.args.get("lab"), language())
    return render_template(
        "manual.html", data=data, lab=lab, document=document, locale=language()
    )


@app.post("/manual/pdf")
def manual_pdf():
    from manual_pdf import make_pdf

    try:
        data, lab, document = access_document(
            request.form.get("lab"),
            request.form.get("document_language", "ko"),
            request.form.get("note", ""),
        )
        pdf = make_pdf(document)
    except ValueError as e:
        return str(e), 400
    return send_file(
        pdf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="Orvia_" + lab["id"] + "_" + document["language"] + ".pdf",
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
        resources="자원 배정",
        limits="CPU·메모리 할당",
        gpu="GPU",
        storage="공유 저장공간",
        images="환경 템플릿",
        backups="백업",
        maintenance="환경 관리",
        files="저장공간 분석",
    )
    if section not in titles:
        abort(404)
    data = call({"action": "status"})
    lab = next((l for l in data["labs"] if l["id"] == lab_id), None)
    if not lab:
        abort(404)
    catalog = call({"action": "catalog"})
    current = next(l for l in catalog["labs"] if l["id"] == lab_id)
    files, file_error = None, None
    if section == "files":
        try:
            files = call(
                dict(action="files", lab=lab_id, path=request.args.get("path", ""))
            )
        except (OSError, ValueError) as e:
            file_error = str(e)
    return render_template(
        "lab.html",
        files=files,
        file_error=file_error,
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
    data = call({"action": "status"})
    catalog = call({"action": "catalog"})
    return render_template(
        "activity.html",
        data=data,
        records=__import__("activity_view").events(data),
        jobs=catalog.get("jobs", [])[:10],
    )


@app.route("/provision", methods=["GET", "POST"])
def provision_page():
    if request.method == "POST":
        try:
            result = call(
                dict(
                    action="provision_submit",
                    plan=request.form.get("plan"),
                    storage_name=request.form.get("storage_name"),
                    confirm=request.form.get("confirm"),
                )
            )
            flash(result["message"], "success")
        except (ValueError, OSError) as exc:
            flash(str(exc), "error")
        return redirect("/provision")
    data = call({"action": "status"})
    used = {i for l in data["labs"] for i in l.get("gpu_indices", [l["gpu"]])}
    default_gpu = next(
        (
            g["index"]
            for g in sorted(data["gpus"], key=lambda g: -g["index"])
            if g["index"] not in used and not g["util"] and g["used"] <= 32
        ),
        None,
    )
    return render_template(
        "provision.html",
        changes=call({"action": "provision_plans"}),
        data=data,
        default_gpu=default_gpu,
    )


@app.post("/provision/prepare")
def provision_prepare():
    fields = [
        "id",
        "title",
        "new_user",
        "password",
        "source_container",
        "gpu_index",
        "storage_gb",
        "storage_name",
        "ack_shared",
        "display_name",
        "student_id",
        "email",
        "notes",
    ]
    req = {k: request.form.get(k, "") for k in fields}
    req["action"] = "provision_prepare"
    try:
        flash(call(req)["message"], "success")
    except (ValueError, OSError) as e:
        flash(str(e), "error")
    return redirect("/provision")


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
        "ack_downtime",
        "ack_recreate",
        "ack_environment",
        "ack_shared",
        "expected_fingerprint",
        "display_name",
        "student_id",
        "email",
        "joined_on",
        "expires_on",
        "notes",
        "expected_id",
        "expected_started",
        "title",
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
        "permission_profile",
        "storage",
        "gpu_selection",
    ]
    req = {k: request.form.get(k) for k in fields}
    if req.get("action") == "gpu_reconfigure":
        req["gpu_selection"] = ",".join(request.form.getlist("gpu_selection"))
    try:
        flash(call(req)["message"], "success")
    except (ValueError, OSError) as e:
        flash(str(e), "error")
    target = {
        "account_metadata": "accounts",
        "account_create": "accounts",
        "gpu_reconfigure": "gpu",
        "maintenance_restart": "maintenance",
        "maintenance_recreate": "maintenance",
        "resources": "limits",
        "backup": "backups",
        "adduser": "accounts",
        "profile_save": "images",
        "environment_apply": "images",
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
    from i18n import return_path

    return redirect(
        return_path(request.args.get("next") or request.referrer or "/", request.host)
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
        "permission_profiles": __import__("permissions").CATALOG["profiles"],
        "languages": {
            code: phrases.get("_language_name", code)
            for code, phrases in TRANSLATIONS.items()
        },
    }


@app.get("/api/storage-usage/<lab_id>")
def storage_usage_api(lab_id):
    try:
        return jsonify(
            call(
                dict(
                    action="storage_usage",
                    lab=lab_id,
                    path=request.args.get("path", ""),
                )
            )
        )
    except (ValueError, OSError) as e:
        return jsonify(error=str(e)), 400


@app.get("/monitor")
def monitor_page():
    return render_template("monitor.html")


@app.get("/api/telemetry")
def telemetry_api():
    try:
        return jsonify(
            call(
                {
                    "action": "telemetry",
                    "hours": request.args.get("hours", "2"),
                    "start": request.args.get("start"),
                    "end": request.args.get("end"),
                }
            )
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.post("/api/telemetry/retention")
def telemetry_retention():
    try:
        return jsonify(
            call({"action": "telemetry_retention", "values": request.get_json()})
        )
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
