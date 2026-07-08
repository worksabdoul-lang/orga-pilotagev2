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
REPORT_STATUSES = [
    ("brouillon", "Brouillon"),
    ("envoye", "Envoye"),
    ("lu", "Lu par le gerant"),
    ("a_completer", "A completer"),
]

DOMAIN_TASK_SEEDS = {
    "evenementiel": {
        "name": "Evenementiel",
        "description": "Organisation et pilotage d'evenements.",
        "tasks": {
            "Commercial": [
                ("Recueillir le besoin du client", "Qualifier les attentes, contraintes, budget et objectifs du client."),
                ("Faire valider le devis", "Preparer, transmettre et suivre la validation du devis."),
                ("Suivre les echanges client", "Centraliser les retours client et remonter les points sensibles."),
            ],
            "Chef de projet": [
                ("Construire le planning general", "Definir les jalons, responsabilites et dates cles."),
                ("Coordonner les intervenants", "S'assurer que chaque acteur dispose des informations utiles."),
                ("Suivre l'avancement global", "Mettre a jour l'etat d'avancement et les alertes projet."),
            ],
            "Responsable technique et logistique": [
                ("Verifier les besoins materiels", "Lister le materiel et anticiper les contraintes techniques."),
                ("Coordonner la logistique terrain", "Organiser transport, installation et acces au site."),
                ("Superviser l'installation", "Controler la mise en place avant livraison au client."),
            ],
            "RAF": [
                ("Preparer le budget", "Structurer le budget previsionnel et les lignes de couts."),
                ("Suivre les depenses", "Controler les engagements et ecarts budgetaires."),
                ("Valider les paiements", "Verifier les justificatifs et lancer les validations."),
            ],
            "Assistante de direction": [
                ("Preparer les documents administratifs", "Rassembler les documents utiles au projet."),
                ("Centraliser les informations", "Tenir a jour les informations partagees."),
                ("Suivre les confirmations", "Relancer et confirmer les participations ou validations."),
            ],
        },
    },
    "cadeaux_gadgets": {
        "name": "Cadeaux et gadgets personnalises",
        "description": "Production et livraison d'objets personnalises.",
        "tasks": {
            "Commercial": [("Valider le besoin client", "Confirmer quantites, personnalisation et budget."), ("Faire valider le BAT", "Obtenir la validation client avant production.")],
            "Chef de projet": [("Planifier la production", "Organiser les etapes de conception, validation et livraison."), ("Suivre les validations", "Controler les points de decision client.")],
            "Responsable technique et logistique": [("Controler les specifications", "Verifier formats, supports et contraintes fournisseur."), ("Organiser la livraison", "Planifier l'expedition et confirmer la reception.")],
            "RAF": [("Suivre les couts fournisseurs", "Controler les devis, marges et paiements."), ("Valider les factures", "Controler les pieces avant paiement.")],
            "Assistante de direction": [("Archiver les validations", "Classer devis, BAT et bons de livraison."), ("Suivre les documents", "Centraliser les pieces administratives.")],
        },
    },
    "voyages": {
        "name": "Organisation de voyages",
        "description": "Coordination de voyages, missions et deplacements.",
        "tasks": {
            "Commercial": [("Confirmer le besoin de voyage", "Valider destination, nombre de personnes et contraintes."), ("Suivre la relation client", "Informer le client des options et arbitrages.")],
            "Chef de projet": [("Construire l'itineraire", "Planifier les etapes et responsabilites."), ("Coordonner les prestataires", "Suivre agences, hebergements et transports.")],
            "Responsable technique et logistique": [("Verifier la logistique", "Controler transport, hebergement et transferts."), ("Suivre les confirmations", "Centraliser les reservations confirmees.")],
            "RAF": [("Preparer le budget voyage", "Calculer les couts et marges."), ("Suivre les paiements", "Controler avances, factures et soldes.")],
            "Assistante de direction": [("Rassembler les documents voyageurs", "Collecter informations et documents necessaires."), ("Tenir le dossier administratif", "Classer confirmations, contacts et documents utiles.")],
        },
    },
    "conseil": {
        "name": "Conseil d'entreprise",
        "description": "Missions de conseil, diagnostic et accompagnement.",
        "tasks": {
            "Commercial": [("Cadrer le besoin client", "Clarifier le probleme, les attentes et le perimetre."), ("Suivre la proposition", "Faire valider l'offre et les conditions.")],
            "Chef de projet": [("Construire le plan de mission", "Definir jalons, livrables et responsabilites."), ("Suivre les livrables", "Controler la production et les validations.")],
            "Responsable technique et logistique": [("Preparer les supports techniques", "Rassembler outils, donnees et materiels utiles."), ("Appuyer la mise en oeuvre", "Soutenir les actions terrain si necessaire.")],
            "RAF": [("Suivre la rentabilite", "Controler temps, couts et facturation."), ("Preparer la facturation", "Emettre ou valider les elements de facturation.")],
            "Assistante de direction": [("Organiser les rendez-vous", "Planifier ateliers, comites et points de suivi."), ("Centraliser les comptes rendus", "Classer et partager les documents de mission.")],
        },
    },
}


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


def ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_domains_and_templates(db: sqlite3.Connection) -> None:
    for code, domain in DOMAIN_TASK_SEEDS.items():
        db.execute(
            """
            INSERT OR IGNORE INTO domains(code,name,description,status,created_at)
            VALUES(?,?,?,?,?)
            """,
            (code, domain["name"], domain["description"], "actif", now_iso()),
        )
        domain_id = db.execute("SELECT id FROM domains WHERE code=?", (code,)).fetchone()["id"]
        existing = db.execute("SELECT COUNT(*) AS c FROM task_templates WHERE domain_id=?", (domain_id,)).fetchone()["c"]
        if existing:
            continue
        for profile, tasks in domain["tasks"].items():
            for title, description in tasks:
                db.execute(
                    """
                    INSERT INTO task_templates(domain_id,profile,title,description,default_priority,default_delay_days,status,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (domain_id, profile, title, description, "normale", 7, "actif", now_iso()),
                )
    db.commit()


def add_days(date_value: str, days: int) -> str:
    try:
        base = dt.date.fromisoformat(date_value) if date_value else dt.date.today()
    except ValueError:
        base = dt.date.today()
    return (base + dt.timedelta(days=days)).isoformat()


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

            CREATE TABLE IF NOT EXISTS domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'actif',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_id INTEGER NOT NULL,
                profile TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                default_priority TEXT NOT NULL DEFAULT 'normale',
                default_delay_days INTEGER NOT NULL DEFAULT 7,
                status TEXT NOT NULL DEFAULT 'actif',
                created_at TEXT NOT NULL,
                FOREIGN KEY(domain_id) REFERENCES domains(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                assigned_user_id INTEGER NOT NULL,
                template_id INTEGER,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'normale',
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'non_commence',
                progress_percent INTEGER NOT NULL DEFAULT 0 CHECK(progress_percent >= 0 AND progress_percent <= 100),
                is_completed INTEGER NOT NULL DEFAULT 0,
                is_manual INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(assigned_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(template_id) REFERENCES task_templates(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                comment TEXT,
                blocker TEXT,
                next_action TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES project_tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS weekly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                week_label TEXT NOT NULL,
                week_start TEXT,
                week_end TEXT,
                projects_followed TEXT,
                tasks_done TEXT,
                tasks_pending TEXT,
                blockers TEXT,
                support_needed TEXT,
                next_week_priorities TEXT,
                general_comment TEXT,
                status TEXT NOT NULL DEFAULT 'brouillon',
                submitted_at TEXT,
                read_at TEXT,
                manager_comment TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        ensure_column(db, "projects", "domain_id", "INTEGER")
        ensure_column(db, "notifications", "task_id", "INTEGER")
        ensure_column(db, "notifications", "report_id", "INTEGER")
        seed_domains_and_templates(db)
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


def send_task_email(to_email: str, to_name: str, project_name: str, project_id: int, task_title: str, deadline: str) -> bool:
    subject = f"Nouvelle tache : {task_title}"
    app_url = os.environ.get("APP_URL", "http://localhost:8000")
    body = (
        f"Bonjour {to_name},\n\n"
        f"Une nouvelle tache vous a ete attribuee sur le projet : {project_name}.\n"
        f"Tache : {task_title}\n"
        f"Date limite : {deadline or 'Non definie'}\n\n"
        f"Acces projet : {app_url}/projects/{project_id}\n"
        f"Mes taches : {app_url}/tasks\n\n"
        "Ceci est un message automatique."
    )
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "orga-pilotage@localhost"))
    if not smtp_host:
        outbox = DATA_DIR / "email_outbox.log"
        with outbox.open("a", encoding="utf-8") as f:
            f.write("\n--- EMAIL TACHE NON ENVOYE : SMTP NON CONFIGURE ---\n")
            f.write(f"Date: {now_iso()}\nTo: {to_email}\nSubject: {subject}\n{body}\n")
        return False
    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_tls = os.environ.get("SMTP_TLS", "true").lower() in {"true", "1", "yes", "on"}
    try:
        with smtplib.SMTP(smtp_host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if os.environ.get("SMTP_USER", ""):
                smtp.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""))
            smtp.send_message(msg)
        return True
    except Exception as exc:
        outbox = DATA_DIR / "email_outbox.log"
        with outbox.open("a", encoding="utf-8") as f:
            f.write("\n--- ECHEC ENVOI EMAIL TACHE ---\n")
            f.write(f"Date: {now_iso()}\nErreur: {exc}\nTo: {to_email}\nSubject: {subject}\n{body}\n")
        return False


def create_notification(
    db: sqlite3.Connection,
    user_id: int,
    title: str,
    message: str,
    project_id: Optional[int],
    ntype: str = "assignation",
    task_id: Optional[int] = None,
    report_id: Optional[int] = None,
) -> None:
    db.execute(
        """
        INSERT INTO notifications(user_id,type,title,message,project_id,task_id,report_id,is_read,created_at)
        VALUES(?,?,?,?,?,?,?,0,?)
        """,
        (user_id, ntype, title, message, project_id, task_id, report_id, now_iso()),
    )


def normalize_profile(poste: str, role: str = "") -> str:
    text = (poste or "").lower()
    if role == "manager" or "gerant" in text or "manager" in text:
        return "Manager / Gerant"
    if "commercial" in text:
        return "Commercial"
    if "chef" in text and "projet" in text:
        return "Chef de projet"
    if "technique" in text or "logistique" in text:
        return "Responsable technique et logistique"
    if "raf" in text or "finance" in text:
        return "RAF"
    if "assistante" in text or "direction" in text:
        return "Assistante de direction"
    return poste or "Collaborateur"


def generate_project_tasks(db: sqlite3.Connection, project_id: int, domain_id: int, members: List[sqlite3.Row], created_by: int, project_due_date: str = "") -> List[sqlite3.Row]:
    generated: List[sqlite3.Row] = []
    for member in members:
        profile = normalize_profile(member["poste"], member["role"])
        templates = db.execute(
            """
            SELECT * FROM task_templates
            WHERE domain_id=? AND profile=? AND status='actif'
            ORDER BY id
            """,
            (domain_id, profile),
        ).fetchall()
        for template in templates:
            deadline = project_due_date or add_days(today_iso(), template["default_delay_days"])
            cur = db.execute(
                """
                INSERT INTO project_tasks(project_id,assigned_user_id,template_id,title,description,priority,deadline,status,progress_percent,is_completed,is_manual,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    member["id"],
                    template["id"],
                    template["title"],
                    template["description"],
                    template["default_priority"],
                    deadline,
                    "non_commence",
                    0,
                    0,
                    0,
                    created_by,
                    now_iso(),
                    now_iso(),
                ),
            )
            generated.append(db.execute("SELECT * FROM project_tasks WHERE id=?", (cur.lastrowid,)).fetchone())
    return generated


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

    def orientation_hint(self, user: Optional[CurrentUser]) -> str:
        if not user:
            return ""
        path = self.parsed_path.path
        label = "Guide rapide"
        message = "Suivez les actions principales de la page, puis revenez au tableau de bord pour controler l'avancement."
        hints = [
            ("/dashboard", "Vue d'ensemble", "Commencez ici pour lire les priorites, les blocages et les elements recents."),
            ("/projects/new", "Creation de projet", "Choisissez un domaine : les taches utiles seront generees automatiquement."),
            ("/projects", "Portefeuille projets", "Ouvrez un projet pour voir son domaine, son equipe et ses taches."),
            ("/tasks/new", "Tache manuelle", "Ajoutez ici une tache ponctuelle qui n'existe pas dans les modeles."),
            ("/tasks", "To-do list", "Mettez vos taches a jour et ajoutez un suivi si besoin."),
            ("/reports/new", "Bilan hebdomadaire", "Resumez la semaine : realisations, blocages et priorites suivantes."),
            ("/reports", "Bilans", "Consultez ou envoyez les bilans hebdomadaires selon votre role."),
            ("/notifications", "Notifications", "Retrouvez les assignations, demandes de suivi et bilans envoyes."),
            ("/users", "Equipe", "Ajoutez ou verifiez les comptes actifs de l'application."),
        ]
        for prefix, candidate_label, candidate_message in hints:
            if path == prefix or path.startswith(prefix + "/"):
                label = candidate_label
                message = candidate_message
                break
        return f"""
        <aside class="orientation-bubble" aria-label="Aide contextuelle">
          <span class="orientation-dot">?</span>
          <div><strong>{esc(label)}</strong><span>{esc(message)}</span></div>
        </aside>
        """

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
                <a href="/tasks">Mes tÃ¢ches</a>
                { '<a href="/tasks/new">Nouvelle tÃ¢che</a>' if user.is_manager else '' }
                <a href="/reports">Bilans</a>
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
            {self.orientation_hint(user)}
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
        if path == "/tasks":
            return self.page_tasks()
        if path == "/tasks/new":
            return self.page_task_new()
        if path == "/reports":
            return self.page_reports()
        if path == "/reports/new":
            return self.page_report_form(None)
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
        match = re.fullmatch(r"/tasks/(\d+)", path)
        if match:
            return self.page_task_detail(int(match.group(1)))
        match = re.fullmatch(r"/reports/(\d+)", path)
        if match:
            return self.page_report_detail(int(match.group(1)))
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
        if path == "/tasks/new":
            return self.action_task_new()
        if path == "/reports/new":
            return self.action_report_save(None)
        match = re.fullmatch(r"/projects/(\d+)/status", path)
        if match:
            return self.action_project_status(int(match.group(1)))
        match = re.fullmatch(r"/tasks/(\d+)/update", path)
        if match:
            return self.action_task_update(int(match.group(1)))
        match = re.fullmatch(r"/tasks/(\d+)/comment", path)
        if match:
            return self.action_task_comment(int(match.group(1)))
        match = re.fullmatch(r"/reports/(\d+)/manager", path)
        if match:
            return self.action_report_manager(int(match.group(1)))
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
              SUM(CASE WHEN deadline IS NOT NULL AND deadline < ? AND status NOT IN ('termine','valide') THEN 1 ELSE 0 END) AS retards,
              COALESCE(AVG(progress_percent),0) AS avg_progress
            FROM project_tasks
            """,
            (today_iso(),),
        )
        projects = query_all(
            """
            SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name,
              COALESCE(AVG(w.progress_percent),0) AS avg_progress,
              SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
              COUNT(w.id) AS item_count
            FROM projects p
            LEFT JOIN users u ON u.id=p.responsible_user_id
            LEFT JOIN project_tasks w ON w.project_id=p.id
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
            SELECT p.*, COALESCE(AVG(w.progress_percent),0) AS avg_progress,
                   COUNT(w.id) AS item_count
            FROM projects p
            JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=?
            LEFT JOIN project_tasks w ON w.project_id=p.id AND w.assigned_user_id=?
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            """,
            (user.id, user.id),
        )
        items = query_all(
            """
            SELECT t.*, p.name AS project_name, d.name AS domain_name,
                   u.first_name || ' ' || u.last_name AS assignee_name
            FROM project_tasks t
            JOIN projects p ON p.id=t.project_id
            LEFT JOIN domains d ON d.id=p.domain_id
            JOIN users u ON u.id=t.assigned_user_id
            WHERE t.assigned_user_id=?
            ORDER BY t.updated_at DESC LIMIT 8
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
        item_rows = "".join(self.task_row(i, show_project=True) for i in items) or "<tr><td colspan='7'>Aucune tache attribuee.</td></tr>"
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
          <div class="table-wrap"><table><thead><tr><th>Projet</th><th>Tache</th><th>Assigne</th><th>Priorite</th><th>Date limite</th><th>Statut</th><th>Avancement</th></tr></thead><tbody>{item_rows}</tbody></table></div>
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
          <div class="card-actions"><a class="btn" href="/projects/{p['id']}">Ouvrir</a>{f'<a class="btn ghost" href="/tasks">Voir mes taches</a>' if collaborator else ''}</div>
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
                  COALESCE(AVG(w.progress_percent),0) AS avg_progress,
                  SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
                  COUNT(w.id) AS item_count
                FROM projects p
                LEFT JOIN users u ON u.id=p.responsible_user_id
                LEFT JOIN project_tasks w ON w.project_id=p.id
                GROUP BY p.id
                ORDER BY p.updated_at DESC
                """
            )
        else:
            projects = query_all(
                """
                SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name,
                  COALESCE(AVG(w.progress_percent),0) AS avg_progress,
                  SUM(CASE WHEN w.status='bloque' THEN 1 ELSE 0 END) AS blockers,
                  COUNT(w.id) AS item_count
                FROM projects p
                JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=?
                LEFT JOIN users u ON u.id=p.responsible_user_id
                LEFT JOIN project_tasks w ON w.project_id=p.id
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
        domains = query_all("SELECT * FROM domains WHERE status='actif' ORDER BY name")
        domain_options = "".join(f"<option value='{d['id']}'>{esc(d['name'])}</option>" for d in domains)
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
            <label>Domaine d'activité<select name="domain_id" required>{domain_options}</select></label>
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
        domain_raw = self.form_value(form, "domain_id")
        if not domain_raw.isdigit():
            return self.render_error(400, "Le domaine d'activite est obligatoire.")
        domain_id = int(domain_raw)
        domain = query_one("SELECT * FROM domains WHERE id=? AND status='actif'", (domain_id,))
        if not domain:
            return self.render_error(400, "Domaine d'activite invalide.")
        member_ids = [int(v) for v in self.form_values(form, "member_ids") if v.isdigit()]
        responsible_id = int(self.form_value(form, "responsible_user_id", str(user.id)) or user.id)
        if responsible_id not in member_ids and responsible_id != user.id:
            member_ids.append(responsible_id)
        with get_db() as db:
            cur = db.execute(
                """
                INSERT INTO projects(name,domain_id,description,objective,client,start_date,due_date,priority,responsible_user_id,status,observations,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    domain_id,
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
            generated_tasks = generate_project_tasks(db, project_id, domain_id, members, user.id, self.form_value(form, "due_date"))
            tasks_by_user: Dict[int, List[str]] = {}
            for task in generated_tasks:
                tasks_by_user.setdefault(task["assigned_user_id"], []).append(task["title"])
            for m in members:
                task_list = ", ".join(tasks_by_user.get(m["id"], [])) or "Aucune tache automatique pour ce profil"
                create_notification(
                    db,
                    m["id"],
                    "Nouveau projet assigne",
                    f"Projet : {name}. Domaine : {domain['name']}. Taches attribuees : {task_list}.",
                    project_id,
                    "projet",
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
            return self.render_error(403, "Vous n'etes pas associe a ce projet.")
        project = query_one(
            """
            SELECT p.*, u.first_name || ' ' || u.last_name AS responsible_name, d.name AS domain_name
            FROM projects p
            LEFT JOIN users u ON u.id=p.responsible_user_id
            LEFT JOIN domains d ON d.id=p.domain_id
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
        tasks = self.task_query("WHERE t.project_id=?", (project_id,))
        stats = query_one(
            """
            SELECT COALESCE(AVG(progress_percent),0) AS avg_progress,
              COUNT(*) AS total,
              SUM(CASE WHEN status='bloque' THEN 1 ELSE 0 END) AS blockers,
              SUM(CASE WHEN status IN ('termine','valide') THEN 1 ELSE 0 END) AS done
            FROM project_tasks WHERE project_id=?
            """,
            (project_id,),
        )
        member_ids_with_tasks = {t["assigned_user_id"] for t in tasks}
        missing_members = [m for m in members if m["id"] not in member_ids_with_tasks]
        member_chips = "".join(f"<span class='chip'>{esc(m['first_name'])} {esc(m['last_name'])}<small>{esc(m['poste'])}</small></span>" for m in members) or "<span>Aucun membre.</span>"
        missing_html = "".join(f"<li>{esc(m['first_name'])} {esc(m['last_name'])} - {esc(m['poste'])}</li>" for m in missing_members) or "<li>Tous les membres ont au moins une tache.</li>"
        task_rows = "".join(self.task_row(t, show_project=False) for t in tasks) or "<tr><td colspan='6'>Aucune tache generee pour ce projet.</td></tr>"
        item_rows = "".join(self.work_item_row(i, show_project=False) for i in items) or "<tr><td colspan='5'>Aucun ancien apport libre.</td></tr>"
        status_form = ""
        if user.is_manager:
            status_form = f"""
            <form method="post" action="/projects/{project_id}/status" class="inline-status">
              <select name="status">{options_html(PROJECT_STATUSES, project['status'])}</select>
              <button class="btn" type="submit">Mettre a jour</button>
            </form>
            """
        hero_action = '<a class="btn primary" href="/tasks/new">Ajouter une tache</a>' if user.is_manager else '<a class="btn primary" href="/tasks">Mes taches</a>'
        task_action = '<a href="/tasks/new">Ajouter une tache manuelle</a>' if user.is_manager else '<a href="/tasks">Voir mes taches</a>'
        content = f"""
        <header class="hero small">
          <div>
            <p class="eyebrow">Detail projet</p>
            <h1>{esc(project['name'])}</h1>
            <p>{esc(project['description'] or '')}</p>
          </div>
          {hero_action}
        </header>
        <div class="grid metrics">
          {self.metric_card('Avancement', f"{round(stats['avg_progress'] or 0)}%", 'Moyenne des taches')}
          {self.metric_card('Taches', stats['total'] or 0, 'Total genere')}
          {self.metric_card('Terminees', stats['done'] or 0, 'Terminees ou validees')}
          {self.metric_card('Blocages', stats['blockers'] or 0, 'Signales')}
        </div>
        <div class="grid two">
          <section class="card">
            <h2>Informations</h2>
            <dl class="details">
              <dt>Objectif</dt><dd>{esc(project['objective'] or '-')}</dd>
              <dt>Domaine</dt><dd>{esc(project['domain_name'] or 'Non renseigne')}</dd>
              <dt>Client / beneficiaire</dt><dd>{esc(project['client'] or '-')}</dd>
              <dt>Responsable principal</dt><dd>{esc(project['responsible_name'] or '-')}</dd>
              <dt>Echeance</dt><dd>{esc(project['due_date'] or '-')}</dd>
              <dt>Priorite</dt><dd><span class="pill {status_class(project['priority'])}">{esc(status_label(project['priority'], PRIORITIES))}</span></dd>
              <dt>Statut</dt><dd><span class="pill {status_class(project['status'])}">{esc(status_label(project['status'], PROJECT_STATUSES))}</span>{status_form}</dd>
              <dt>Observations</dt><dd>{esc(project['observations'] or '-')}</dd>
            </dl>
          </section>
          <section class="card">
            <h2>Membres impliques</h2>
            <div class="chips">{member_chips}</div>
            <h3>Sans tache generee</h3>
            <ul class="notice-list compact">{missing_html}</ul>
          </section>
        </div>
        <section class="card">
          <div class="section-head"><h2>Taches du projet</h2>{task_action}</div>
          <div class="table-wrap"><table><thead><tr><th>Tache</th><th>Assigne</th><th>Priorite</th><th>Date limite</th><th>Statut</th><th>Avancement</th></tr></thead><tbody>{task_rows}</tbody></table></div>
        </section>
        <section class="card">
          <div class="section-head"><h2>Anciens apports libres</h2><a href="/projects/{project_id}/work-items/new">Ajouter un apport libre</a></div>
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

    def task_row(self, task: sqlite3.Row, show_project: bool = True) -> str:
        project_cell = f"<td><a href='/projects/{task['project_id']}'>{esc(task['project_name'])}</a><br><small>{esc(task['domain_name'] or '')}</small></td>" if show_project else ""
        return f"""
        <tr>
          {project_cell}
          <td><a class="strong" href="/tasks/{task['id']}">{esc(task['title'])}</a><br><small>{esc(task['description'] or '')}</small></td>
          <td>{esc(task['assignee_name'])}</td>
          <td><span class="pill {status_class(task['priority'])}">{esc(status_label(task['priority'], PRIORITIES))}</span></td>
          <td>{esc(task['deadline'] or 'Aucune')}</td>
          <td><span class="pill {status_class(task['status'])}">{esc(status_label(task['status'], TASK_STATUSES))}</span></td>
          <td><div class="progress"><span style="width:{int(task['progress_percent'] or 0)}%"></span></div><small>{int(task['progress_percent'] or 0)}%</small></td>
        </tr>
        """

    def task_query(self, where: str = "", params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        return query_all(
            f"""
            SELECT t.*, p.name AS project_name, d.name AS domain_name,
                   u.first_name || ' ' || u.last_name AS assignee_name
            FROM project_tasks t
            JOIN projects p ON p.id=t.project_id
            LEFT JOIN domains d ON d.id=p.domain_id
            JOIN users u ON u.id=t.assigned_user_id
            {where}
            ORDER BY t.updated_at DESC
            """,
            params,
        )

    def user_can_access_task(self, user: CurrentUser, task: sqlite3.Row) -> bool:
        return user.is_manager or task["assigned_user_id"] == user.id

    def page_tasks(self) -> None:
        user = self.require_user()
        if user.is_manager:
            tasks = self.task_query()
            title = "Toutes les taches"
            action = '<a class="btn primary" href="/tasks/new">Ajouter une tache</a>'
        else:
            tasks = self.task_query("WHERE t.assigned_user_id=?", (user.id,))
            title = "Mes taches"
            action = '<a class="btn primary" href="/reports/new">Creer mon bilan hebdomadaire</a>'
        rows = "".join(self.task_row(t) for t in tasks) or "<tr><td colspan='7'>Aucune tache.</td></tr>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">To-do list</p><h1>{title}</h1><p>Suivez les taches generees automatiquement et les taches ajoutees manuellement.</p></div>{action}</header>
        <section class="card">
          <div class="table-wrap"><table><thead><tr><th>Projet</th><th>Tache</th><th>Assigne</th><th>Priorite</th><th>Date limite</th><th>Statut</th><th>Avancement</th></tr></thead><tbody>{rows}</tbody></table></div>
        </section>
        """
        self.render(title, content, user)

    def page_task_detail(self, task_id: int) -> None:
        user = self.require_user()
        tasks = self.task_query("WHERE t.id=?", (task_id,))
        if not tasks:
            return self.render_error(404, "Tache introuvable.")
        task = tasks[0]
        if not self.user_can_access_task(user, task):
            return self.render_error(403, "Vous ne pouvez pas consulter cette tache.")
        comments = query_all(
            """
            SELECT c.*, u.first_name || ' ' || u.last_name AS user_name
            FROM task_comments c JOIN users u ON u.id=c.user_id
            WHERE c.task_id=? ORDER BY c.created_at DESC
            """,
            (task_id,),
        )
        comment_items = "".join(
            f"<li><strong>{esc(c['user_name'])}</strong> <small>{esc(c['created_at'])}</small><br>{esc(c['comment'] or '')}<br><small>Blocage : {esc(c['blocker'] or 'Aucun')} | Prochaine action : {esc(c['next_action'] or 'Non renseignee')}</small></li>"
            for c in comments
        ) or "<li>Aucun commentaire de suivi.</li>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">{esc(task['project_name'])} - {esc(task['domain_name'] or '')}</p><h1>{esc(task['title'])}</h1><p>{esc(task['description'] or '')}</p></div></header>
        <div class="grid two">
          <section class="card">
            <h2>Mettre a jour</h2>
            <form method="post" action="/tasks/{task_id}/update" class="form">
              <label>Statut<select name="status">{options_html(TASK_STATUSES, task['status'])}</select></label>
              <label>Avancement (%)<input type="number" min="0" max="100" name="progress_percent" value="{esc(task['progress_percent'])}"></label>
              <label class="check"><input type="checkbox" name="is_completed" value="1" {'checked' if task['is_completed'] else ''}> Tache terminee</label>
              <button class="btn primary" type="submit">Enregistrer</button>
            </form>
          </section>
          <section class="card">
            <h2>Informations</h2>
            <dl class="details">
              <dt>Assigne</dt><dd>{esc(task['assignee_name'])}</dd>
              <dt>Priorite</dt><dd><span class="pill {status_class(task['priority'])}">{esc(status_label(task['priority'], PRIORITIES))}</span></dd>
              <dt>Date limite</dt><dd>{esc(task['deadline'] or 'Aucune')}</dd>
              <dt>Type</dt><dd>{'Manuelle' if task['is_manual'] else 'Modele automatique'}</dd>
            </dl>
          </section>
        </div>
        <section class="card">
          <h2>Ajouter un commentaire de suivi</h2>
          <form method="post" action="/tasks/{task_id}/comment" class="form grid-form">
            <label class="full">Ce qui a ete fait / information a remonter<textarea name="comment" rows="3" required></textarea></label>
            <label>Blocage eventuel<textarea name="blocker" rows="3"></textarea></label>
            <label>Prochaine action<textarea name="next_action" rows="3"></textarea></label>
            <div class="full actions"><button class="btn primary" type="submit">Ajouter le suivi</button></div>
          </form>
        </section>
        <section class="card">
          <h2>Historique de suivi</h2>
          <ul class="notice-list">{comment_items}</ul>
        </section>
        """
        self.render(task["title"], content, user)

    def action_task_update(self, task_id: int) -> None:
        user = self.require_user()
        tasks = self.task_query("WHERE t.id=?", (task_id,))
        if not tasks:
            return self.render_error(404, "Tache introuvable.")
        task = tasks[0]
        if not self.user_can_access_task(user, task):
            return self.render_error(403, "Vous ne pouvez pas modifier cette tache.")
        form = self.read_form()
        status = self.form_value(form, "status", "non_commence")
        if status not in dict(TASK_STATUSES):
            return self.render_error(400, "Statut invalide.")
        try:
            progress = max(0, min(100, int(self.form_value(form, "progress_percent", "0"))))
        except ValueError:
            progress = 0
        completed = 1 if self.form_value(form, "is_completed") == "1" or status in {"termine", "valide"} else 0
        if completed and status == "non_commence":
            status = "termine"
            progress = 100
        with get_db() as db:
            db.execute(
                "UPDATE project_tasks SET status=?, progress_percent=?, is_completed=?, updated_at=? WHERE id=?",
                (status, progress, completed, now_iso(), task_id),
            )
            db.execute("UPDATE projects SET updated_at=? WHERE id=?", (now_iso(), task["project_id"]))
            db.commit()
        self.redirect(f"/tasks/{task_id}")

    def action_task_comment(self, task_id: int) -> None:
        user = self.require_user()
        tasks = self.task_query("WHERE t.id=?", (task_id,))
        if not tasks:
            return self.render_error(404, "Tache introuvable.")
        task = tasks[0]
        if not self.user_can_access_task(user, task):
            return self.render_error(403, "Vous ne pouvez pas commenter cette tache.")
        form = self.read_form()
        with get_db() as db:
            db.execute(
                "INSERT INTO task_comments(task_id,user_id,comment,blocker,next_action,created_at) VALUES(?,?,?,?,?,?)",
                (task_id, user.id, self.form_value(form, "comment"), self.form_value(form, "blocker"), self.form_value(form, "next_action"), now_iso()),
            )
            if self.form_value(form, "blocker"):
                db.execute("UPDATE project_tasks SET status='bloque', updated_at=? WHERE id=?", (now_iso(), task_id))
            db.commit()
        self.redirect(f"/tasks/{task_id}")

    def page_task_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        projects = query_all("SELECT * FROM projects ORDER BY updated_at DESC")
        users = query_all("SELECT * FROM users WHERE is_active=1 ORDER BY poste")
        project_options = "".join(f"<option value='{p['id']}'>{esc(p['name'])}</option>" for p in projects)
        user_options = "".join(f"<option value='{u['id']}'>{esc(u['first_name'])} {esc(u['last_name'])} - {esc(u['poste'])}</option>" for u in users)
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Manager</p><h1>Ajouter une tache manuelle</h1><p>Attribuez une tache hors modele a un collaborateur.</p></div></header>
        <section class="card form-card">
          <form method="post" action="/tasks/new" class="form grid-form">
            <label>Projet<select name="project_id" required>{project_options}</select></label>
            <label>Collaborateur assigne<select name="assigned_user_id" required>{user_options}</select></label>
            <label>Titre<input name="title" required></label>
            <label>Priorite<select name="priority">{options_html(PRIORITIES, 'normale')}</select></label>
            <label>Date limite<input type="date" name="deadline"></label>
            <label class="full">Description<textarea name="description" rows="4"></textarea></label>
            <label class="full">Observation<textarea name="observation" rows="3"></textarea></label>
            <div class="full actions"><a class="btn ghost" href="/tasks">Annuler</a><button class="btn primary" type="submit">Attribuer la tache</button></div>
          </form>
        </section>
        """
        self.render("Ajouter une tache", content, user)

    def action_task_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        form = self.read_form()
        project_id = int(self.form_value(form, "project_id", "0") or 0)
        assigned_user_id = int(self.form_value(form, "assigned_user_id", "0") or 0)
        title = self.form_value(form, "title")
        if not project_id or not assigned_user_id or not title:
            return self.render_error(400, "Projet, collaborateur et titre sont obligatoires.")
        project = query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        assigned = query_one("SELECT * FROM users WHERE id=? AND is_active=1", (assigned_user_id,))
        if not project or not assigned:
            return self.render_error(400, "Projet ou collaborateur invalide.")
        with get_db() as db:
            db.execute("INSERT OR IGNORE INTO project_members(project_id,user_id,created_at) VALUES(?,?,?)", (project_id, assigned_user_id, now_iso()))
            cur = db.execute(
                """
                INSERT INTO project_tasks(project_id,assigned_user_id,title,description,priority,deadline,status,progress_percent,is_completed,is_manual,created_by,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (project_id, assigned_user_id, title, self.form_value(form, "description"), self.form_value(form, "priority", "normale"), self.form_value(form, "deadline"), "non_commence", 0, 0, 1, user.id, now_iso(), now_iso()),
            )
            task_id = cur.lastrowid
            create_notification(
                db,
                assigned_user_id,
                "Nouvelle tache attribuee",
                f"Projet : {project['name']}. Tache : {title}. Date limite : {self.form_value(form, 'deadline') or 'Non definie'}.",
                project_id,
                "tache",
                task_id,
            )
            db.commit()
        send_task_email(assigned["email"], f"{assigned['first_name']} {assigned['last_name']}", project["name"], project_id, title, self.form_value(form, "deadline"))
        self.redirect(f"/tasks/{task_id}")

    def page_reports(self) -> None:
        user = self.require_user()
        if user.is_manager:
            reports = query_all(
                """
                SELECT r.*, u.first_name || ' ' || u.last_name AS user_name
                FROM weekly_reports r JOIN users u ON u.id=r.user_id
                ORDER BY COALESCE(r.submitted_at, r.updated_at) DESC
                """
            )
            rows = "".join(
                f"<tr><td>{esc(r['user_name'])}</td><td>{esc(r['week_label'])}</td><td>{esc(r['submitted_at'] or 'Non envoye')}</td><td><span class='pill {status_class(r['status'])}'>{esc(status_label(r['status'], REPORT_STATUSES))}</span></td><td><a href='/reports/{r['id']}'>Voir</a></td></tr>"
                for r in reports
            ) or "<tr><td colspan='5'>Aucun bilan hebdomadaire.</td></tr>"
            content = f"""
            <header class="hero small"><div><p class="eyebrow">Manager</p><h1>Bilans hebdomadaires</h1><p>Consultez les bilans par collaborateur, semaine et statut.</p></div></header>
            <section class="card"><div class="table-wrap"><table><thead><tr><th>Collaborateur</th><th>Semaine</th><th>Date d'envoi</th><th>Statut</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div></section>
            """
        else:
            reports = query_all("SELECT * FROM weekly_reports WHERE user_id=? ORDER BY updated_at DESC", (user.id,))
            rows = "".join(
                f"<tr><td>{esc(r['week_label'])}</td><td>{esc(r['submitted_at'] or 'Non envoye')}</td><td><span class='pill {status_class(r['status'])}'>{esc(status_label(r['status'], REPORT_STATUSES))}</span></td><td><a href='/reports/{r['id']}'>Voir</a></td></tr>"
                for r in reports
            ) or "<tr><td colspan='4'>Aucun bilan.</td></tr>"
            content = f"""
            <header class="hero small"><div><p class="eyebrow">Collaborateur</p><h1>Mes bilans hebdomadaires</h1><p>Renvoyez au gerant vos realisations, blocages et priorites.</p></div><a class="btn primary" href="/reports/new">Creer mon bilan hebdomadaire</a></header>
            <section class="card"><div class="table-wrap"><table><thead><tr><th>Semaine</th><th>Date d'envoi</th><th>Statut</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div></section>
            """
        self.render("Bilans hebdomadaires", content, user)

    def page_report_form(self, report: Optional[sqlite3.Row]) -> None:
        user = self.require_user()
        title = "Creer mon bilan hebdomadaire"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Bilan hebdomadaire</p><h1>{title}</h1><p>Resumez les projets suivis, les taches terminees, les blocages et les priorites de la semaine prochaine.</p></div></header>
        <section class="card form-card">
          <form method="post" action="/reports/new" class="form grid-form">
            <label>Semaine concernee<input name="week_label" required placeholder="Ex : 12-17 aout"></label>
            <label>Date debut<input type="date" name="week_start"></label>
            <label>Date fin<input type="date" name="week_end"></label>
            <label>Statut<select name="status">{options_html(REPORT_STATUSES, 'envoye')}</select></label>
            <label class="full">Projets suivis<textarea name="projects_followed" rows="3"></textarea></label>
            <label class="full">Taches realisees<textarea name="tasks_done" rows="3"></textarea></label>
            <label class="full">Taches non terminees<textarea name="tasks_pending" rows="3"></textarea></label>
            <label class="full">Difficultes ou blocages<textarea name="blockers" rows="3"></textarea></label>
            <label class="full">Besoins d'aide ou de validation<textarea name="support_needed" rows="3"></textarea></label>
            <label class="full">Priorites de la semaine prochaine<textarea name="next_week_priorities" rows="3"></textarea></label>
            <label class="full">Commentaire general<textarea name="general_comment" rows="3"></textarea></label>
            <div class="full actions"><a class="btn ghost" href="/reports">Annuler</a><button class="btn primary" type="submit">Enregistrer le bilan</button></div>
          </form>
        </section>
        """
        self.render(title, content, user)

    def action_report_save(self, report_id: Optional[int]) -> None:
        user = self.require_user()
        if user.is_manager:
            return self.render_error(403, "Le manager consulte les bilans mais ne les cree pas.")
        form = self.read_form()
        status = self.form_value(form, "status", "envoye")
        if status not in dict(REPORT_STATUSES):
            return self.render_error(400, "Statut de bilan invalide.")
        submitted_at = now_iso() if status == "envoye" else None
        with get_db() as db:
            cur = db.execute(
                """
                INSERT INTO weekly_reports(user_id,week_label,week_start,week_end,projects_followed,tasks_done,tasks_pending,blockers,support_needed,next_week_priorities,general_comment,status,submitted_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    user.id,
                    self.form_value(form, "week_label"),
                    self.form_value(form, "week_start"),
                    self.form_value(form, "week_end"),
                    self.form_value(form, "projects_followed"),
                    self.form_value(form, "tasks_done"),
                    self.form_value(form, "tasks_pending"),
                    self.form_value(form, "blockers"),
                    self.form_value(form, "support_needed"),
                    self.form_value(form, "next_week_priorities"),
                    self.form_value(form, "general_comment"),
                    status,
                    submitted_at,
                    now_iso(),
                    now_iso(),
                ),
            )
            report_id = cur.lastrowid
            managers = db.execute("SELECT * FROM users WHERE role='manager' AND is_active=1").fetchall()
            for manager in managers:
                create_notification(
                    db,
                    manager["id"],
                    "Bilan hebdomadaire envoye",
                    f"{user.full_name} a envoye le bilan : {self.form_value(form, 'week_label')}.",
                    None,
                    "bilan",
                    None,
                    report_id,
                )
            db.commit()
        self.redirect(f"/reports/{report_id}")

    def page_report_detail(self, report_id: int) -> None:
        user = self.require_user()
        report = query_one(
            """
            SELECT r.*, u.first_name || ' ' || u.last_name AS user_name
            FROM weekly_reports r JOIN users u ON u.id=r.user_id
            WHERE r.id=?
            """,
            (report_id,),
        )
        if not report:
            return self.render_error(404, "Bilan introuvable.")
        if not user.is_manager and report["user_id"] != user.id:
            return self.render_error(403, "Vous ne pouvez pas consulter ce bilan.")
        manager_form = ""
        if user.is_manager:
            manager_form = f"""
            <section class="card">
              <h2>Action manager</h2>
              <form method="post" action="/reports/{report_id}/manager" class="form">
                <label>Statut<select name="status">{options_html(REPORT_STATUSES, report['status'])}</select></label>
                <label>Commentaire manager<textarea name="manager_comment" rows="3">{esc(report['manager_comment'] or '')}</textarea></label>
                <button class="btn primary" type="submit">Mettre a jour</button>
              </form>
            </section>
            """
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Bilan hebdomadaire</p><h1>{esc(report['week_label'])}</h1><p>{esc(report['user_name'])} - {esc(report['submitted_at'] or 'Non envoye')}</p></div></header>
        <section class="card">
          <dl class="details">
            <dt>Statut</dt><dd><span class="pill {status_class(report['status'])}">{esc(status_label(report['status'], REPORT_STATUSES))}</span></dd>
            <dt>Projets suivis</dt><dd>{esc(report['projects_followed'] or '')}</dd>
            <dt>Taches realisees</dt><dd>{esc(report['tasks_done'] or '')}</dd>
            <dt>Taches non terminees</dt><dd>{esc(report['tasks_pending'] or '')}</dd>
            <dt>Blocages</dt><dd>{esc(report['blockers'] or '')}</dd>
            <dt>Besoins</dt><dd>{esc(report['support_needed'] or '')}</dd>
            <dt>Priorites suivantes</dt><dd>{esc(report['next_week_priorities'] or '')}</dd>
            <dt>Commentaire general</dt><dd>{esc(report['general_comment'] or '')}</dd>
            <dt>Commentaire manager</dt><dd>{esc(report['manager_comment'] or '')}</dd>
          </dl>
        </section>
        {manager_form}
        """
        self.render("Bilan hebdomadaire", content, user)

    def action_report_manager(self, report_id: int) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        form = self.read_form()
        status = self.form_value(form, "status", "lu")
        if status not in dict(REPORT_STATUSES):
            return self.render_error(400, "Statut de bilan invalide.")
        read_at = now_iso() if status == "lu" else None
        with get_db() as db:
            db.execute(
                "UPDATE weekly_reports SET status=?, read_at=COALESCE(read_at, ?), manager_comment=?, updated_at=? WHERE id=?",
                (status, read_at, self.form_value(form, "manager_comment"), now_iso(), report_id),
            )
            db.commit()
        self.redirect(f"/reports/{report_id}")

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
