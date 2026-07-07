#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ORGA Pilotage - MVP réel
Application web interne de suivi d'avancement des projets.

Stack volontairement légère : Python standard library + SQLite.
Aucune dépendance externe n'est nécessaire pour lancer le MVP.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import html
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

APP_NAME = "ORGA Pilotage"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "orga_pilotage.sqlite3"
STATIC_DIR = BASE_DIR / "static"
SESSION_COOKIE = "orga_session"
PBKDF2_ITERATIONS = 180_000

PROJECT_STATUSES = [
    ("non_commence", "Non commencé"),
    ("en_cours", "En cours"),
    ("bloque", "Bloqué"),
    ("termine", "Terminé"),
    ("livre", "Livré"),
    ("valide", "Validé"),
]
TASK_STATUSES = [
    ("non_commence", "Non commencé"),
    ("en_cours", "En cours"),
    ("bloque", "Bloqué"),
    ("termine", "Terminé"),
    ("en_attente_validation", "En attente de validation"),
    ("valide", "Validé"),
]
PRIORITIES = [("basse", "Basse"), ("normale", "Normale"), ("urgente", "Urgente")]
ROLES = [("manager", "Manager"), ("collaborateur", "Collaborateur")]


@dataclass
class CurrentUser:
    id: int
    first_name: str
    last_name: str
    poste: str
    email: str
    role: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def today_iso() -> str:
    return dt.date.today().isoformat()


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def status_label(value: str, options: Iterable[Tuple[str, str]]) -> str:
    return dict(options).get(value, value or "—")


def status_class(value: str) -> str:
    mapping = {
        "non_commence": "muted",
        "en_cours": "info",
        "bloque": "danger",
        "termine": "success",
        "livre": "success",
        "valide": "success",
        "en_attente_validation": "warning",
        "basse": "muted",
        "normale": "info",
        "urgente": "danger",
    }
    return mapping.get(value, "muted")


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        method, iterations, salt, digest = stored.split("$", 3)
        if method != "pbkdf2_sha256":
            return False
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(calculated.hex(), digest)
    except Exception:
        return False


def init_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                poste TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('manager','collaborateur')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                objective TEXT,
                client TEXT,
                start_date TEXT,
                due_date TEXT,
                priority TEXT NOT NULL DEFAULT 'normale',
                responsible_user_id INTEGER,
                status TEXT NOT NULL DEFAULT 'non_commence',
                observations TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, user_id),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS work_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_in_project TEXT,
                work_description TEXT NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'non_commence',
                progress INTEGER NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
                blockage TEXT,
                next_action TEXT,
                comment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                project_id INTEGER,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        count = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count == 0:
            seed_users = [
                ("Abdoul", "Manager", "Gérant / Manager", "manager@orga.local", "manager", "admin123"),
                ("Aya", "Commerciale", "Commercial", "commercial@orga.local", "collaborateur", "test123"),
                ("Kouadio", "Projet", "Chef de projet", "chef.projet@orga.local", "collaborateur", "test123"),
                ("Mariam", "Technique", "Responsable technique et logistique", "technique@orga.local", "collaborateur", "test123"),
                ("Serge", "Finance", "RAF", "raf@orga.local", "collaborateur", "test123"),
                ("Aminata", "Assistante", "Assistante de direction", "assistante@orga.local", "collaborateur", "test123"),
            ]
            for first, last, poste, email, role, password in seed_users:
                db.execute(
                    """
                    INSERT INTO users(first_name,last_name,poste,email,password_hash,role,is_active)
                    VALUES(?,?,?,?,?,?,1)
                    """,
                    (first, last, poste, email, hash_password(password), role),
                )
            db.commit()


def query_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    with get_db() as db:
        return db.execute(sql, params).fetchone()


def query_all(sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    with get_db() as db:
        return db.execute(sql, params).fetchall()


def options_html(options: Iterable[Tuple[str, str]], selected: str = "") -> str:
    return "".join(
        f'<option value="{esc(value)}" {"selected" if value == selected else ""}>{esc(label)}</option>'
        for value, label in options
    )


def csrf_note() -> str:
    return ""  # MVP interne : la protection CSRF stricte peut être ajoutée en V1.1.


def send_assignment_email(to_email: str, to_name: str, project_name: str, project_id: int) -> bool:
    """Send a simple assignment email. If SMTP is not configured, write to outbox log."""
    subject = f"Nouveau projet assigné : {project_name}"
    app_url = os.environ.get("APP_URL", "http://localhost:8000")
    body = (
        f"Bonjour {to_name},\n\n"
        f"Vous avez été ajouté au projet : {project_name}.\n"
        f"Merci de vous connecter à ORGA Pilotage pour renseigner votre apport.\n\n"
        f"Accès projet : {app_url}/projects/{project_id}\n\n"
        "Ceci est un message automatique."
    )

    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "orga-pilotage@localhost"))
    if not smtp_host:
        outbox = DATA_DIR / "email_outbox.log"
        with outbox.open("a", encoding="utf-8") as f:
            f.write("\n--- EMAIL NON ENVOYÉ : SMTP NON CONFIGURÉ ---\n")
            f.write(f"Date: {now_iso()}\nTo: {to_email}\nSubject: {subject}\n{body}\n")
        return False

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    use_tls = os.environ.get("SMTP_TLS", "true").lower() in {"true", "1", "yes", "on"}

    try:
        with smtplib.SMTP(smtp_host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        outbox = DATA_DIR / "email_outbox.log"
        with outbox.open("a", encoding="utf-8") as f:
            f.write("\n--- ÉCHEC ENVOI EMAIL ---\n")
            f.write(f"Date: {now_iso()}\nErreur: {exc}\nTo: {to_email}\nSubject: {subject}\n{body}\n")
        return False


def create_notification(db: sqlite3.Connection, user_id: int, title: str, message: str, project_id: Optional[int], ntype: str = "assignation") -> None:
    db.execute(
        """
        INSERT INTO notifications(user_id,type,title,message,project_id,is_read,created_at)
        VALUES(?,?,?,?,?,0,?)
        """,
        (user_id, ntype, title, message, project_id, now_iso()),
    )


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with get_db() as db:
        db.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, user_id, now_iso()))
        db.commit()
    return token


def destroy_session(token: str) -> None:
    if not token:
        return
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        db.commit()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ORGAPilotage/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep console output readable.
        print(f"[{now_iso()}] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        try:
            self.route_get()
        except Exception as exc:
            self.render_error(500, f"Erreur interne : {esc(exc)}")

    def do_POST(self) -> None:
        try:
            self.route_post()
        except Exception as exc:
            self.render_error(500, f"Erreur interne : {esc(exc)}")

    @property
    def parsed_path(self):
        return urlparse(self.path)

    def get_cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie(raw)
        morsel = jar.get(name)
        return morsel.value if morsel else ""

    def current_user(self) -> Optional[CurrentUser]:
        token = self.get_cookie(SESSION_COOKIE)
        if not token:
            return None
        row = query_one(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.token=? AND u.is_active=1
            """,
            (token,),
        )
        if not row:
            return None
        return CurrentUser(row["id"], row["first_name"], row["last_name"], row["poste"], row["email"], row["role"])

    def require_user(self) -> CurrentUser:
        user = self.current_user()
        if not user:
            self.redirect("/login")
            raise RuntimeError("AUTH_REDIRECT")
        return user

    def read_form(self) -> Dict[str, List[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(raw, keep_blank_values=True)

    def form_value(self, form: Dict[str, List[str]], key: str, default: str = "") -> str:
        return form.get(key, [default])[0].strip()

    def form_values(self, form: Dict[str, List[str]], key: str) -> List[str]:
        return [v.strip() for v in form.get(key, []) if v.strip()]

    def send_html(self, content: str, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def render(self, title: str, content: str, user: Optional[CurrentUser] = None, notice: str = "") -> None:
        unread = 0
        if user:
            row = query_one("SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (user.id,))
            unread = row["c"] if row else 0
        nav = ""
        if user:
            nav = f"""
            <nav class="topbar">
              <a class="brand" href="/dashboard"><span class="brand-mark">O</span><span>{APP_NAME}</span></a>
              <div class="nav-links">
                <a href="/dashboard">Tableau de bord</a>
                <a href="/projects">Projets</a>
                <a href="/notifications">Notifications {f'<span class="pill danger">{unread}</span>' if unread else ''}</a>
                { '<a href="/users">Utilisateurs</a>' if user.is_manager else '' }
                <form method="post" action="/logout" class="inline-form"><button class="link-button" type="submit">Déconnexion</button></form>
              </div>
            </nav>
            """
        html_doc = f"""
        <!doctype html>
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{esc(title)} · {APP_NAME}</title>
          <link rel="stylesheet" href="/static/style.css">
        </head>
        <body>
          {nav}
          <main class="page">
            {f'<div class="notice">{esc(notice)}</div>' if notice else ''}
            {content}
          </main>
        </body>
        </html>
        """
        self.send_html(html_doc)

    def render_error(self, status: int, message: str) -> None:
        if "AUTH_REDIRECT" in message:
            return
        self.send_html(
            f"""
            <!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Erreur</title>
            <link rel="stylesheet" href="/static/style.css"></head><body><main class="page narrow">
            <div class="card"><h1>Erreur {status}</h1><p>{message}</p><a class="btn" href="/dashboard">Retour</a></div>
            </main></body></html>
            """,
            status=status,
        )

    def route_get(self) -> None:
        path = self.parsed_path.path
        if path.startswith("/static/"):
            return self.serve_static(path)
        if path == "/":
            return self.redirect("/dashboard")
        if path == "/login":
            return self.page_login()
        if path == "/dashboard":
            return self.page_dashboard()
        if path == "/projects":
            return self.page_projects()
        if path == "/projects/new":
            return self.page_project_new()
        if path == "/notifications":
            return self.page_notifications()
        if path == "/users":
            return self.page_users()
        match = re.fullmatch(r"/projects/(\d+)", path)
        if match:
            return self.page_project_detail(int(match.group(1)))
        match = re.fullmatch(r"/projects/(\d+)/work-items/new", path)
        if match:
            return self.page_work_item_form(int(match.group(1)), None)
        match = re.fullmatch(r"/work-items/(\d+)/edit", path)
        if match:
            return self.page_work_item_edit(int(match.group(1)))
        self.render_error(404, "Page introuvable.")

    def route_post(self) -> None:
        path = self.parsed_path.path
        if path == "/login":
            return self.action_login()
        if path == "/logout":
            return self.action_logout()
        if path == "/projects/new":
            return self.action_project_new()
        if path == "/users":
            return self.action_user_new()
        match = re.fullmatch(r"/projects/(\d+)/status", path)
        if match:
            return self.action_project_status(int(match.group(1)))
        match = re.fullmatch(r"/projects/(\d+)/work-items/new", path)
        if match:
            return self.action_work_item_save(project_id=int(match.group(1)), item_id=None)
        match = re.fullmatch(r"/work-items/(\d+)/edit", path)
        if match:
            return self.action_work_item_save(project_id=None, item_id=int(match.group(1)))
        match = re.fullmatch(r"/notifications/(\d+)/read", path)
        if match:
            return self.action_notification_read(int(match.group(1)))
        self.render_error(404, "Action introuvable.")

    def serve_static(self, path: str) -> None:
        relative = unquote(path.replace("/static/", "", 1))
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists() or target.is_dir():
            self.render_error(404, "Fichier introuvable.")
            return
        content_type = "text/plain; charset=utf-8"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def page_login(self, error: str = "") -> None:
        content = f"""
        <section class="login-shell">
          <div class="login-card">
            <div class="brand-large"><span class="brand-mark">O</span><div><h1>{APP_NAME}</h1><p>Suivi interne des projets et apports d'équipe</p></div></div>
            {f'<div class="alert danger">{esc(error)}</div>' if error else ''}
            <form method="post" action="/login" class="form">
              <label>Email</label>
              <input type="email" name="email" required placeholder="manager@orga.local">
              <label>Mot de passe</label>
              <input type="password" name="password" required placeholder="••••••••">
              <button class="btn primary full" type="submit">Se connecter</button>
            </form>
            <div class="demo-box">
              <strong>Comptes de test</strong><br>
              Manager : manager@orga.local / admin123<br>
              Collaborateurs : commercial@orga.local, chef.projet@orga.local, technique@orga.local, raf@orga.local, assistante@orga.local / test123
            </div>
          </div>
        </section>
        """
        self.render("Connexion", content, None)

    def action_login(self) -> None:
        form = self.read_form()
        email = self.form_value(form, "email").lower()
        password = self.form_value(form, "password")
        row = query_one("SELECT * FROM users WHERE email=? AND is_active=1", (email,))
        if not row or not verify_password(password, row["password_hash"]):
            return self.page_login("Email ou mot de passe incorrect.")
        token = create_session(row["id"])
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = token
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        self.send_response(303)
        self.send_header("Location", "/dashboard")
        self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.end_headers()

    def action_logout(self) -> None:
        token = self.get_cookie(SESSION_COOKIE)
        destroy_session(token)
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = ""
        cookie[SESSION_COOKIE]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        cookie[SESSION_COOKIE]["path"] = "/"
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.end_headers()

    def page_dashboard(self) -> None:
        user = self.require_user()
        if user.is_manager:
            return self.page_dashboard_manager(user)
        return self.page_dashboard_collaborator(user)

    def page_dashboard_manager(self, user: CurrentUser) -> None:
        totals = query_one(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status='en_cours' THEN 1 ELSE 0 END) AS en_cours,
              SUM(CASE WHEN status='bloque' THEN 1 ELSE 0 END) AS bloques,
              SUM(CASE WHEN status IN ('livre','valide','termine') THEN 1 ELSE 0 END) AS termines
            FROM projects
            """
        )
        work = query_one(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN status='bloque' THEN 1 ELSE 0 END) AS bloques,
              SUM(CASE WHEN due_date IS NOT NULL AND due_date < ? AND status NOT IN ('termine','valide') THEN 1 ELSE 0 END) AS retards,
              COALESCE(AVG(progress),0) AS avg_progress
            FROM work_items
            """,
            (today_iso(),),
        )
        projects = query_all(
            """
            SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name,
              COALESCE(AVG(w.progress),0) AS avg_progress,
              SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
              COUNT(w.id) AS item_count
            FROM projects p
            LEFT JOIN users u ON u.id=p.responsible_user_id
            LEFT JOIN work_items w ON w.project_id=p.id
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            LIMIT 8
            """
        )
        recent_notifications = query_all(
            """
            SELECT n.*, u.first_name || ' ' || u.last_name AS user_name, p.name AS project_name
            FROM notifications n
            JOIN users u ON u.id=n.user_id
            LEFT JOIN projects p ON p.id=n.project_id
            ORDER BY n.created_at DESC LIMIT 6
            """
        )
        cards = f"""
        <div class="grid metrics">
          {self.metric_card('Projets', totals['total'] or 0, 'Total créé')}
          {self.metric_card('En cours', totals['en_cours'] or 0, 'Projets actifs')}
          {self.metric_card('Bloqués', totals['bloques'] or 0, 'À arbitrer')}
          {self.metric_card('Avancement moyen', f"{round(work['avg_progress'] or 0)}%", 'Tous apports/tâches')}
        </div>
        """
        project_rows = "".join(self.project_row(p) for p in projects) or "<tr><td colspan='6'>Aucun projet pour le moment.</td></tr>"
        notif_rows = "".join(
            f"<li><span class='dot'></span><strong>{esc(n['title'])}</strong><br><small>{esc(n['user_name'])} · {esc(n['created_at'])}</small></li>"
            for n in recent_notifications
        ) or "<li>Aucune notification.</li>"
        content = f"""
        <header class="hero">
          <div>
            <p class="eyebrow">Vue manager</p>
            <h1>Tableau de bord général</h1>
            <p>Suivez l'état global des projets, les apports renseignés et les blocages.</p>
          </div>
          <a class="btn primary" href="/projects/new">Créer un projet</a>
        </header>
        {cards}
        <div class="grid two">
          <section class="card wide">
            <div class="section-head"><h2>Derniers projets</h2><a href="/projects">Voir tout</a></div>
            <div class="table-wrap"><table><thead><tr><th>Projet</th><th>Responsable</th><th>Statut</th><th>Priorité</th><th>Avancement</th><th>Blocages</th></tr></thead><tbody>{project_rows}</tbody></table></div>
          </section>
          <section class="card">
            <h2>Activité récente</h2>
            <ul class="timeline">{notif_rows}</ul>
          </section>
        </div>
        """
        self.render("Tableau de bord", content, user)

    def page_dashboard_collaborator(self, user: CurrentUser) -> None:
        projects = query_all(
            """
            SELECT p.*, COALESCE(AVG(w.progress),0) AS avg_progress,
                   COUNT(w.id) AS item_count
            FROM projects p
            JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=?
            LEFT JOIN work_items w ON w.project_id=p.id AND w.user_id=?
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            """,
            (user.id, user.id),
        )
        items = query_all(
            """
            SELECT w.*, p.name AS project_name FROM work_items w
            JOIN projects p ON p.id=w.project_id
            WHERE w.user_id=?
            ORDER BY w.updated_at DESC LIMIT 8
            """,
            (user.id,),
        )
        unread = query_all(
            """
            SELECT n.*, p.name AS project_name FROM notifications n
            LEFT JOIN projects p ON p.id=n.project_id
            WHERE n.user_id=? AND n.is_read=0
            ORDER BY n.created_at DESC LIMIT 5
            """,
            (user.id,),
        )
        project_cards = "".join(self.project_card(p, collaborator=True) for p in projects) or "<div class='empty'>Aucun projet assigné pour le moment.</div>"
        item_rows = "".join(self.work_item_row(i, show_project=True) for i in items) or "<tr><td colspan='5'>Aucun apport/tâche renseigné.</td></tr>"
        unread_html = "".join(
            f"<li><strong>{esc(n['title'])}</strong><br><span>{esc(n['message'])}</span><br><a href='/projects/{n['project_id']}'>Ouvrir le projet</a></li>"
            for n in unread
        ) or "<li>Aucune notification non lue.</li>"
        content = f"""
        <header class="hero">
          <div>
            <p class="eyebrow">Espace collaborateur</p>
            <h1>Bonjour {esc(user.first_name)}</h1>
            <p>Renseignez vos apports et mettez à jour votre avancement sur les projets assignés.</p>
          </div>
        </header>
        <section class="card">
          <h2>Notifications à traiter</h2>
          <ul class="notice-list">{unread_html}</ul>
        </section>
        <section>
          <div class="section-head"><h2>Mes projets</h2></div>
          <div class="grid cards">{project_cards}</div>
        </section>
        <section class="card">
          <h2>Mes derniers apports/tâches</h2>
          <div class="table-wrap"><table><thead><tr><th>Projet</th><th>Travail</th><th>Statut</th><th>Avancement</th><th>Action</th></tr></thead><tbody>{item_rows}</tbody></table></div>
        </section>
        """
        self.render("Tableau de bord", content, user)

    def metric_card(self, label: str, value: Any, hint: str) -> str:
        return f"<div class='metric'><span>{esc(label)}</span><strong>{esc(value)}</strong><small>{esc(hint)}</small></div>"

    def project_row(self, p: sqlite3.Row) -> str:
        return f"""
        <tr>
          <td><a class="strong" href="/projects/{p['id']}">{esc(p['name'])}</a><br><small>{esc(p['client'])}</small></td>
          <td>{esc(p['responsible_name'] or '—')}</td>
          <td><span class="pill {status_class(p['status'])}">{esc(status_label(p['status'], PROJECT_STATUSES))}</span></td>
          <td><span class="pill {status_class(p['priority'])}">{esc(status_label(p['priority'], PRIORITIES))}</span></td>
          <td><div class="progress"><span style="width:{int(p['avg_progress'] or 0)}%"></span></div><small>{round(p['avg_progress'] or 0)}%</small></td>
          <td>{p['blockers'] or 0}</td>
        </tr>
        """

    def project_card(self, p: sqlite3.Row, collaborator: bool = False) -> str:
        return f"""
        <article class="card project-card">
          <div class="section-head compact">
            <h3>{esc(p['name'])}</h3>
            <span class="pill {status_class(p['status'])}">{esc(status_label(p['status'], PROJECT_STATUSES))}</span>
          </div>
          <p>{esc(p['description'] or 'Aucune description.')}</p>
          <div class="progress large"><span style="width:{int(p['avg_progress'] or 0)}%"></span></div>
          <small>{round(p['avg_progress'] or 0)}% d'avancement · Échéance : {esc(p['due_date'] or '—')}</small>
          <div class="card-actions"><a class="btn" href="/projects/{p['id']}">Ouvrir</a>{f'<a class="btn ghost" href="/projects/{p["id"]}/work-items/new">Renseigner mon apport</a>' if collaborator else ''}</div>
        </article>
        """

    def work_item_row(self, item: sqlite3.Row, show_project: bool = False) -> str:
        first = f"<td>{esc(item['project_name'])}</td>" if show_project else f"<td>{esc(item['user_name'])}</td>"
        return f"""
        <tr>
          {first}
          <td>{esc(item['work_description'])}<br><small>{esc(item['next_action'] or '')}</small></td>
          <td><span class="pill {status_class(item['status'])}">{esc(status_label(item['status'], TASK_STATUSES))}</span></td>
          <td><div class="progress"><span style="width:{int(item['progress'] or 0)}%"></span></div><small>{int(item['progress'] or 0)}%</small></td>
          <td><a href="/work-items/{item['id']}/edit">Modifier</a></td>
        </tr>
        """

    def page_projects(self) -> None:
        user = self.require_user()
        if user.is_manager:
            projects = query_all(
                """
                SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name,
                  COALESCE(AVG(w.progress),0) AS avg_progress,
                  SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
                  COUNT(w.id) AS item_count
                FROM projects p
                LEFT JOIN users u ON u.id=p.responsible_user_id
                LEFT JOIN work_items w ON w.project_id=p.id
                GROUP BY p.id
                ORDER BY p.updated_at DESC
                """
            )
        else:
            projects = query_all(
                """
                SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name,
                  COALESCE(AVG(w.progress),0) AS avg_progress,
                  SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
                  COUNT(w.id) AS item_count
                FROM projects p
                JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=?
                LEFT JOIN users u ON u.id=p.responsible_user_id
                LEFT JOIN work_items w ON w.project_id=p.id
                GROUP BY p.id
                ORDER BY p.updated_at DESC
                """,
                (user.id,),
            )
        rows = "".join(self.project_row(p) for p in projects) or "<tr><td colspan='6'>Aucun projet.</td></tr>"
        content = f"""
        <header class="hero small">
          <div><p class="eyebrow">Projets</p><h1>Liste des projets</h1></div>
          { '<a class="btn primary" href="/projects/new">Créer un projet</a>' if user.is_manager else '' }
        </header>
        <section class="card">
          <div class="table-wrap"><table><thead><tr><th>Projet</th><th>Responsable</th><th>Statut</th><th>Priorité</th><th>Avancement</th><th>Blocages</th></tr></thead><tbody>{rows}</tbody></table></div>
        </section>
        """
        self.render("Projets", content, user)

    def page_project_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Accès réservé au manager.")
        collaborators = query_all("SELECT * FROM users WHERE is_active=1 ORDER BY role DESC, poste")
        member_checks = "".join(
            f"<label class='check'><input type='checkbox' name='member_ids' value='{u['id']}' {'checked' if u['role']=='collaborateur' else ''}> {esc(u['first_name'])} {esc(u['last_name'])} — <small>{esc(u['poste'])}</small></label>"
            for u in collaborators if u["id"] != user.id
        )
        responsible_options = "".join(
            f"<option value='{u['id']}'>{esc(u['first_name'])} {esc(u['last_name'])} — {esc(u['poste'])}</option>"
            for u in collaborators
        )
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Nouveau projet</p><h1>Créer un projet</h1><p>À la validation, les membres sélectionnés recevront une notification interne et un email d'assignation.</p></div></header>
        <section class="card form-card">
          <form method="post" action="/projects/new" class="form grid-form">
            <label>Nom du projet<input name="name" required placeholder="Ex : Organisation séminaire client"></label>
            <label>Client / bénéficiaire<input name="client" placeholder="Ex : EDISSOU Groupe"></label>
            <label>Date de début<input type="date" name="start_date"></label>
            <label>Date limite<input type="date" name="due_date"></label>
            <label>Priorité<select name="priority">{options_html(PRIORITIES, 'normale')}</select></label>
            <label>Statut<select name="status">{options_html(PROJECT_STATUSES, 'non_commence')}</select></label>
            <label>Responsable principal<select name="responsible_user_id">{responsible_options}</select></label>
            <label class="full">Objectif<textarea name="objective" rows="3" placeholder="Résultat attendu du projet"></textarea></label>
            <label class="full">Description courte<textarea name="description" rows="3"></textarea></label>
            <label class="full">Observations<textarea name="observations" rows="3"></textarea></label>
            <fieldset class="full check-panel"><legend>Membres impliqués</legend>{member_checks}</fieldset>
            <div class="full actions"><a class="btn ghost" href="/projects">Annuler</a><button class="btn primary" type="submit">Créer et notifier</button></div>
          </form>
        </section>
        """
        self.render("Créer un projet", content, user)

    def action_project_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Accès réservé au manager.")
        form = self.read_form()
        name = self.form_value(form, "name")
        if not name:
            return self.render_error(400, "Le nom du projet est obligatoire.")
        member_ids = [int(v) for v in self.form_values(form, "member_ids") if v.isdigit()]
        responsible_id = int(self.form_value(form, "responsible_user_id", str(user.id)) or user.id)
        if responsible_id not in member_ids and responsible_id != user.id:
            member_ids.append(responsible_id)
        with get_db() as db:
            cur = db.execute(
                """
                INSERT INTO projects(name,description,objective,client,start_date,due_date,priority,responsible_user_id,status,observations,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    self.form_value(form, "description"),
                    self.form_value(form, "objective"),
                    self.form_value(form, "client"),
                    self.form_value(form, "start_date"),
                    self.form_value(form, "due_date"),
                    self.form_value(form, "priority", "normale"),
                    responsible_id,
                    self.form_value(form, "status", "non_commence"),
                    self.form_value(form, "observations"),
                    user.id,
                    now_iso(),
                    now_iso(),
                ),
            )
            project_id = cur.lastrowid
            members = db.execute(
                f"SELECT * FROM users WHERE id IN ({','.join('?' for _ in member_ids)}) AND is_active=1",
                tuple(member_ids),
            ).fetchall() if member_ids else []
            for m in members:
                db.execute(
                    "INSERT OR IGNORE INTO project_members(project_id,user_id,created_at) VALUES(?,?,?)",
                    (project_id, m["id"], now_iso()),
                )
                create_notification(
                    db,
                    m["id"],
                    "Nouveau projet assigné",
                    f"Vous avez été ajouté au projet : {name}. Merci de renseigner votre apport.",
                    project_id,
                )
            db.commit()
        # Emails after DB commit: if SMTP fails, the application still works and logs the message.
        for m in members:
            send_assignment_email(m["email"], f"{m['first_name']} {m['last_name']}", name, project_id)
        self.redirect(f"/projects/{project_id}")

    def user_can_access_project(self, user: CurrentUser, project_id: int) -> bool:
        if user.is_manager:
            return True
        row = query_one("SELECT 1 FROM project_members WHERE project_id=? AND user_id=?", (project_id, user.id))
        return bool(row)

    def page_project_detail(self, project_id: int) -> None:
        user = self.require_user()
        if not self.user_can_access_project(user, project_id):
            return self.render_error(403, "Vous n'êtes pas associé à ce projet.")
        project = query_one(
            """
            SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name
            FROM projects p LEFT JOIN users u ON u.id=p.responsible_user_id
            WHERE p.id=?
            """,
            (project_id,),
        )
        if not project:
            return self.render_error(404, "Projet introuvable.")
        members = query_all(
            """
            SELECT u.* FROM project_members pm JOIN users u ON u.id=pm.user_id
            WHERE pm.project_id=? ORDER BY u.poste
            """,
            (project_id,),
        )
        items = query_all(
            """
            SELECT w.*, u.first_name || ' ' || u.last_name AS user_name
            FROM work_items w JOIN users u ON u.id=w.user_id
            WHERE w.project_id=? ORDER BY w.updated_at DESC
            """,
            (project_id,),
        )
        stats = query_one(
            """
            SELECT COALESCE(AVG(progress),0) AS avg_progress,
              COUNT(*) AS total,
              SUM(CASE WHEN status='bloque' THEN 1 ELSE 0 END) AS blockers,
              SUM(CASE WHEN status IN ('termine','valide') THEN 1 ELSE 0 END) AS done
            FROM work_items WHERE project_id=?
            """,
            (project_id,),
        )
        member_ids_with_items = {i["user_id"] for i in items}
        missing_members = [m for m in members if m["id"] not in member_ids_with_items]
        member_chips = "".join(f"<span class='chip'>{esc(m['first_name'])} {esc(m['last_name'])}<small>{esc(m['poste'])}</small></span>" for m in members) or "<span>Aucun membre.</span>"
        missing_html = "".join(f"<li>{esc(m['first_name'])} {esc(m['last_name'])} — {esc(m['poste'])}</li>" for m in missing_members) or "<li>Tous les membres ont au moins un apport/tâche.</li>"
        item_rows = "".join(self.work_item_row(i, show_project=False) for i in items) or "<tr><td colspan='5'>Aucun apport/tâche renseigné pour ce projet.</td></tr>"
        status_form = ""
        if user.is_manager:
            status_form = f"""
            <form method="post" action="/projects/{project_id}/status" class="inline-status">
              <select name="status">{options_html(PROJECT_STATUSES, project['status'])}</select>
              <button class="btn" type="submit">Mettre à jour</button>
            </form>
            """
        content = f"""
        <header class="hero small">
          <div>
            <p class="eyebrow">Détail projet</p>
            <h1>{esc(project['name'])}</h1>
            <p>{esc(project['description'] or '')}</p>
          </div>
          <a class="btn primary" href="/projects/{project_id}/work-items/new">Renseigner un apport</a>
        </header>
        <div class="grid metrics">
          {self.metric_card('Avancement', f"{round(stats['avg_progress'] or 0)}%", 'Moyenne des apports')}
          {self.metric_card('Apports/Tâches', stats['total'] or 0, 'Total renseigné')}
          {self.metric_card('Terminés', stats['done'] or 0, 'Terminés ou validés')}
          {self.metric_card('Blocages', stats['blockers'] or 0, 'Signalés')}
        </div>
        <div class="grid two">
          <section class="card">
            <h2>Informations</h2>
            <dl class="details">
              <dt>Objectif</dt><dd>{esc(project['objective'] or '—')}</dd>
              <dt>Client / bénéficiaire</dt><dd>{esc(project['client'] or '—')}</dd>
              <dt>Responsable principal</dt><dd>{esc(project['responsible_name'] or '—')}</dd>
              <dt>Échéance</dt><dd>{esc(project['due_date'] or '—')}</dd>
              <dt>Priorité</dt><dd><span class="pill {status_class(project['priority'])}">{esc(status_label(project['priority'], PRIORITIES))}</span></dd>
              <dt>Statut</dt><dd><span class="pill {status_class(project['status'])}">{esc(status_label(project['status'], PROJECT_STATUSES))}</span>{status_form}</dd>
              <dt>Observations</dt><dd>{esc(project['observations'] or '—')}</dd>
            </dl>
          </section>
          <section class="card">
            <h2>Membres impliqués</h2>
            <div class="chips">{member_chips}</div>
            <h3>Apport non renseigné</h3>
            <ul class="notice-list compact">{missing_html}</ul>
          </section>
        </div>
        <section class="card">
          <div class="section-head"><h2>Apports / Tâches du projet</h2><a href="/projects/{project_id}/work-items/new">Ajouter mon apport</a></div>
          <div class="table-wrap"><table><thead><tr><th>Membre</th><th>Travail</th><th>Statut</th><th>Avancement</th><th>Action</th></tr></thead><tbody>{item_rows}</tbody></table></div>
        </section>
        """
        self.render(project["name"], content, user)

    def action_project_status(self, project_id: int) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Accès réservé au manager.")
        form = self.read_form()
        status = self.form_value(form, "status")
        if status not in dict(PROJECT_STATUSES):
            return self.render_error(400, "Statut invalide.")
        with get_db() as db:
            db.execute("UPDATE projects SET status=?, updated_at=? WHERE id=?", (status, now_iso(), project_id))
            db.commit()
        self.redirect(f"/projects/{project_id}")

    def page_work_item_form(self, project_id: int, item: Optional[sqlite3.Row]) -> None:
        user = self.require_user()
        if not self.user_can_access_project(user, project_id):
            return self.render_error(403, "Vous n'êtes pas associé à ce projet.")
        project = query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not project:
            return self.render_error(404, "Projet introuvable.")
        title = "Modifier mon apport" if item else "Renseigner mon apport"
        action = f"/work-items/{item['id']}/edit" if item else f"/projects/{project_id}/work-items/new"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">{esc(project['name'])}</p><h1>{title}</h1><p>Décrivez clairement votre rôle, votre travail, vos blocages et votre prochaine action.</p></div></header>
        <section class="card form-card">
          <form method="post" action="{action}" class="form grid-form">
            <label>Mon rôle dans le projet<input name="role_in_project" value="{esc(item['role_in_project'] if item else '')}" placeholder="Ex : Suivi client / Logistique / Budget"></label>
            <label>Délai prévu<input type="date" name="due_date" value="{esc(item['due_date'] if item else '')}"></label>
            <label>Statut<select name="status">{options_html(TASK_STATUSES, item['status'] if item else 'non_commence')}</select></label>
            <label>Avancement (%)<input type="number" min="0" max="100" name="progress" value="{esc(item['progress'] if item else 0)}"></label>
            <label class="full">Description du travail / tâches prévues<textarea name="work_description" rows="4" required>{esc(item['work_description'] if item else '')}</textarea></label>
            <label class="full">Blocage éventuel<textarea name="blockage" rows="3" placeholder="Indiquer le blocage, sinon laisser vide">{esc(item['blockage'] if item else '')}</textarea></label>
            <label class="full">Prochaine action<textarea name="next_action" rows="3">{esc(item['next_action'] if item else '')}</textarea></label>
            <label class="full">Commentaire complémentaire<textarea name="comment" rows="3">{esc(item['comment'] if item else '')}</textarea></label>
            <div class="full actions"><a class="btn ghost" href="/projects/{project_id}">Annuler</a><button class="btn primary" type="submit">Enregistrer</button></div>
          </form>
        </section>
        """
        self.render(title, content, user)

    def page_work_item_edit(self, item_id: int) -> None:
        user = self.require_user()
        item = query_one("SELECT * FROM work_items WHERE id=?", (item_id,))
        if not item:
            return self.render_error(404, "Apport/tâche introuvable.")
        if not user.is_manager and item["user_id"] != user.id:
            return self.render_error(403, "Vous ne pouvez modifier que vos propres apports.")
        return self.page_work_item_form(item["project_id"], item)

    def action_work_item_save(self, project_id: Optional[int], item_id: Optional[int]) -> None:
        user = self.require_user()
        form = self.read_form()
        progress_raw = self.form_value(form, "progress", "0")
        try:
            progress = max(0, min(100, int(progress_raw)))
        except ValueError:
            progress = 0
        status = self.form_value(form, "status", "non_commence")
        if status not in dict(TASK_STATUSES):
            return self.render_error(400, "Statut invalide.")
        if item_id:
            item = query_one("SELECT * FROM work_items WHERE id=?", (item_id,))
            if not item:
                return self.render_error(404, "Apport/tâche introuvable.")
            if not user.is_manager and item["user_id"] != user.id:
                return self.render_error(403, "Vous ne pouvez modifier que vos propres apports.")
            project_id = item["project_id"]
            with get_db() as db:
                db.execute(
                    """
                    UPDATE work_items SET role_in_project=?, work_description=?, due_date=?, status=?, progress=?, blockage=?, next_action=?, comment=?, updated_at=? WHERE id=?
                    """,
                    (
                        self.form_value(form, "role_in_project"),
                        self.form_value(form, "work_description"),
                        self.form_value(form, "due_date"),
                        status,
                        progress,
                        self.form_value(form, "blockage"),
                        self.form_value(form, "next_action"),
                        self.form_value(form, "comment"),
                        now_iso(),
                        item_id,
                    ),
                )
                db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now_iso(), project_id))
                db.commit()
        else:
            if project_id is None or not self.user_can_access_project(user, project_id):
                return self.render_error(403, "Vous n'êtes pas associé à ce projet.")
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO work_items(project_id,user_id,role_in_project,work_description,due_date,status,progress,blockage,next_action,comment,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        project_id,
                        user.id,
                        self.form_value(form, "role_in_project"),
                        self.form_value(form, "work_description"),
                        self.form_value(form, "due_date"),
                        status,
                        progress,
                        self.form_value(form, "blockage"),
                        self.form_value(form, "next_action"),
                        self.form_value(form, "comment"),
                        now_iso(),
                        now_iso(),
                    ),
                )
                db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now_iso(), project_id))
                db.commit()
        self.redirect(f"/projects/{project_id}")

    def page_notifications(self) -> None:
        user = self.require_user()
        notifications = query_all(
            """
            SELECT n.*, p.name AS project_name FROM notifications n
            LEFT JOIN projects p ON p.id=n.project_id
            WHERE n.user_id=?
            ORDER BY n.created_at DESC
            """,
            (user.id,),
        )
        items = "".join(
            f"""
            <article class="notification {'unread' if not n['is_read'] else ''}">
              <div><h3>{esc(n['title'])}</h3><p>{esc(n['message'])}</p><small>{esc(n['created_at'])} · {esc(n['project_name'] or '')}</small></div>
              <div class="notification-actions">
                {f'<a class="btn" href="/projects/{n["project_id"]}">Ouvrir</a>' if n['project_id'] else ''}
                {f'<form method="post" action="/notifications/{n["id"]}/read"><button class="btn ghost" type="submit">Marquer lu</button></form>' if not n['is_read'] else '<span class="pill success">Lu</span>'}
              </div>
            </article>
            """ for n in notifications
        ) or "<div class='empty'>Aucune notification.</div>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Centre de notifications</p><h1>Notifications</h1></div></header>
        <section class="stack">{items}</section>
        """
        self.render("Notifications", content, user)

    def action_notification_read(self, notification_id: int) -> None:
        user = self.require_user()
        with get_db() as db:
            db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id, user.id))
            db.commit()
        self.redirect("/notifications")

    def page_users(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Accès réservé au manager.")
        users = query_all("SELECT * FROM users ORDER BY role DESC, poste")
        rows = "".join(
            f"<tr><td>{esc(u['first_name'])} {esc(u['last_name'])}</td><td>{esc(u['poste'])}</td><td>{esc(u['email'])}</td><td><span class='pill {status_class(u['role'])}'>{esc(dict(ROLES).get(u['role'], u['role']))}</span></td><td>{'Actif' if u['is_active'] else 'Inactif'}</td></tr>"
            for u in users
        )
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Administration</p><h1>Utilisateurs</h1><p>Gestion simple retenue pour le MVP.</p></div></header>
        <div class="grid two">
          <section class="card">
            <h2>Ajouter un utilisateur</h2>
            <form method="post" action="/users" class="form">
              <label>Prénom<input name="first_name" required></label>
              <label>Nom<input name="last_name" required></label>
              <label>Poste<input name="poste" required></label>
              <label>Email<input type="email" name="email" required></label>
              <label>Mot de passe temporaire<input name="password" required value="test123"></label>
              <label>Rôle<select name="role">{options_html(ROLES, 'collaborateur')}</select></label>
              <button class="btn primary" type="submit">Créer l'utilisateur</button>
            </form>
          </section>
          <section class="card wide">
            <h2>Équipe</h2>
            <div class="table-wrap"><table><thead><tr><th>Nom</th><th>Poste</th><th>Email</th><th>Rôle</th><th>Statut</th></tr></thead><tbody>{rows}</tbody></table></div>
          </section>
        </div>
        """
        self.render("Utilisateurs", content, user)

    def action_user_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Accès réservé au manager.")
        form = self.read_form()
        role = self.form_value(form, "role", "collaborateur")
        if role not in dict(ROLES):
            return self.render_error(400, "Rôle invalide.")
        try:
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO users(first_name,last_name,poste,email,password_hash,role,is_active)
                    VALUES(?,?,?,?,?,?,1)
                    """,
                    (
                        self.form_value(form, "first_name"),
                        self.form_value(form, "last_name"),
                        self.form_value(form, "poste"),
                        self.form_value(form, "email").lower(),
                        hash_password(self.form_value(form, "password")),
                        role,
                    ),
                )
                db.commit()
        except sqlite3.IntegrityError:
            return self.render_error(400, "Cet email existe déjà.")
        self.redirect("/users")


def run() -> None:
    init_db()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), AppHandler)
    print(f"{APP_NAME} lancé sur http://{host}:{port}")
    print("Connexion manager : manager@orga.local / admin123")
    httpd.serve_forever()


if __name__ == "__main__":
    run()
