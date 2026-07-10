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
import json
import mimetypes
import os
import re
import secrets
import shutil
import smtplib
import sqlite3
import ssl
import uuid
import zipfile
from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_policy
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
UPLOAD_DIR = DATA_DIR / "uploads"
BACKUP_DIR = DATA_DIR / "backups"
SESSION_COOKIE = "orga_session"
PBKDF2_ITERATIONS = 180_000
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "12"))
MAX_UPLOAD_SIZE = 5 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_UPLOAD_MIME_PREFIXES = ("application/pdf", "image/jpeg", "image/png")

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
DOCUMENT_STATUSES = [
    ("en_attente", "En attente"),
    ("valide", "Valide"),
    ("archive", "Archive"),
    ("remplace", "Remplace"),
]
DOCUMENT_TYPES = [
    ("justificatif", "Justificatif"),
    ("devis", "Devis"),
    ("facture", "Facture"),
    ("contrat", "Contrat"),
    ("rapport", "Rapport"),
    ("photo", "Photo"),
    ("preuve", "Preuve"),
    ("autre", "Autre"),
]
FIELD_REPORT_STATUSES = [("brouillon", "Brouillon"), ("envoye", "Envoye"), ("lu", "Lu")]

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
    profile_photo: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def session_expiry_iso() -> str:
    return (dt.datetime.now() + dt.timedelta(hours=SESSION_HOURS)).replace(microsecond=0).isoformat(sep=" ")


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
        "en_attente": "warning",
        "archive": "muted",
        "remplace": "muted",
        "brouillon": "muted",
        "envoye": "info",
        "lu": "success",
        "a_completer": "warning",
    }
    return mapping.get(value, "muted")


def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)
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


def seed_finished_demo_projects(db: sqlite3.Connection) -> None:
    existing = db.execute("SELECT COUNT(*) AS c FROM projects WHERE name LIKE 'Demo termine - %'").fetchone()["c"]
    if existing:
        return
    manager = db.execute("SELECT * FROM users WHERE role='manager' ORDER BY id LIMIT 1").fetchone()
    if not manager:
        return
    collaborators = db.execute("SELECT * FROM users WHERE role='collaborateur' AND is_active=1 ORDER BY id").fetchall()
    domains = db.execute("SELECT * FROM domains ORDER BY id").fetchall()
    if not collaborators or not domains:
        return
    samples = [
        ("Demo termine - Seminaire client Abidjan", "Organisation d'un seminaire client finalise avec installation et rapport de cloture.", "EDISSOU Groupe", "evenementiel", 42),
        ("Demo termine - Kits cadeaux partenaires", "Production et livraison de gadgets personnalises pour partenaires strategiques.", "Partenaires ORGA", "cadeaux_gadgets", 30),
        ("Demo termine - Mission conseil PME", "Diagnostic operationnel et restitution des recommandations au client.", "PME Horizon", "conseil", 18),
    ]
    domain_by_code = {d["code"]: d for d in domains}
    today = dt.date.today()
    for idx, (name, description, client, domain_code, days_ago) in enumerate(samples):
        domain = domain_by_code.get(domain_code) or domains[0]
        start = today - dt.timedelta(days=days_ago + 12)
        due = today - dt.timedelta(days=days_ago)
        responsible = collaborators[idx % len(collaborators)]
        cur = db.execute(
            """
            INSERT INTO projects(name,domain_id,description,objective,client,start_date,due_date,priority,responsible_user_id,status,observations,created_by,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                name,
                domain["id"],
                description,
                "Projet fictif termine pour alimenter le tableau de bord.",
                client,
                start.isoformat(),
                due.isoformat(),
                "normale",
                responsible["id"],
                "termine",
                "Donnees de demonstration.",
                manager["id"],
                f"{start.isoformat()} 09:00:00",
                f"{due.isoformat()} 17:30:00",
            ),
        )
        project_id = cur.lastrowid
        members = collaborators[: min(4, len(collaborators))]
        for member in members:
            db.execute("INSERT OR IGNORE INTO project_members(project_id,user_id,created_at) VALUES(?,?,?)", (project_id, member["id"], now_iso()))
        generated = generate_project_tasks(db, project_id, domain["id"], members, manager["id"], due.isoformat())
        for task in generated:
            db.execute(
                "UPDATE project_tasks SET status='valide', progress_percent=100, is_completed=1, updated_at=? WHERE id=?",
                (f"{due.isoformat()} 17:30:00", task["id"]),
            )
            db.execute(
                "INSERT INTO task_comments(task_id,user_id,comment,blocker,next_action,created_at) VALUES(?,?,?,?,?,?)",
                (task["id"], task["assigned_user_id"], "Tache terminee et validee dans les donnees de demonstration.", "", "Aucune action restante.", f"{due.isoformat()} 16:30:00"),
            )
    db.commit()


def add_days(date_value: str, days: int) -> str:
    try:
        base = dt.date.fromisoformat(date_value) if date_value else dt.date.today()
    except ValueError:
        base = dt.date.today()
    return (base + dt.timedelta(days=days)).isoformat()


def initials(first_name: str, last_name: str) -> str:
    value = f"{(first_name or 'U')[:1]}{(last_name or '')[:1]}".upper()
    return value or "U"


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

            CREATE TABLE IF NOT EXISTS field_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'brouillon',
                submitted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'justificatif',
                status TEXT NOT NULL DEFAULT 'en_attente',
                project_id INTEGER,
                task_id INTEGER,
                weekly_report_id INTEGER,
                report_id INTEGER,
                uploaded_by INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL,
                FOREIGN KEY(task_id) REFERENCES project_tasks(id) ON DELETE SET NULL,
                FOREIGN KEY(weekly_report_id) REFERENCES weekly_reports(id) ON DELETE SET NULL,
                FOREIGN KEY(report_id) REFERENCES field_reports(id) ON DELETE SET NULL,
                FOREIGN KEY(uploaded_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_name TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                backup_type TEXT NOT NULL DEFAULT 'manuelle',
                file_size INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_by INTEGER,
                deleted_at TEXT,
                FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(deleted_by) REFERENCES users(id) ON DELETE SET NULL
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
        ensure_column(db, "users", "profile_photo", "TEXT")
        ensure_column(db, "sessions", "csrf_token", "TEXT")
        ensure_column(db, "sessions", "expires_at", "TEXT")
        for session in db.execute("SELECT token FROM sessions WHERE csrf_token IS NULL OR csrf_token=''").fetchall():
            db.execute("UPDATE sessions SET csrf_token=? WHERE token=?", (secrets.token_urlsafe(32), session["token"]))
        db.execute("UPDATE sessions SET expires_at=? WHERE expires_at IS NULL OR expires_at=''", (session_expiry_iso(),))
        db.commit()
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
        if os.environ.get("ENABLE_DEMO_DATA", "").lower() in {"true", "1", "yes", "on"}:
            seed_finished_demo_projects(db)


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


def safe_filename(name: str) -> str:
    stem = Path(name or "document").stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-") or "document"
    return stem[:80]


def validate_upload(filename: str, content_type: str, data: bytes) -> Tuple[bool, str]:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, "Format refuse. Formats autorises : PDF, JPG, JPEG, PNG."
    if len(data) > MAX_UPLOAD_SIZE:
        return False, "Fichier trop volumineux. Taille maximale : 5 Mo."
    detected = (content_type or mimetypes.guess_type(filename or "")[0] or "").lower()
    if detected and not any(detected.startswith(prefix) for prefix in ALLOWED_UPLOAD_MIME_PREFIXES):
        return False, "Type de fichier refuse."
    signatures = {
        ".pdf": data.startswith(b"%PDF"),
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
    }
    if data and not signatures.get(suffix, False):
        return False, "Le contenu du fichier ne correspond pas a son extension."
    return True, ""


def store_document_file(
    db: sqlite3.Connection,
    *,
    file_info: Dict[str, Any],
    user_id: int,
    title: str,
    document_type: str = "justificatif",
    project_id: Optional[int] = None,
    task_id: Optional[int] = None,
    weekly_report_id: Optional[int] = None,
    report_id: Optional[int] = None,
    comment: str = "",
) -> Optional[int]:
    original_name = file_info.get("filename") or ""
    data = file_info.get("data") or b""
    if not original_name or not data:
        return None
    ok, error = validate_upload(original_name, file_info.get("content_type", ""), data)
    if not ok:
        raise ValueError(error)
    suffix = Path(original_name).suffix.lower()
    stored_name = f"{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex}{suffix}"
    target_dir = UPLOAD_DIR / dt.datetime.now().strftime("%Y/%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / stored_name
    target.write_bytes(data)
    rel_path = str(target.relative_to(DATA_DIR)).replace("\\", "/")
    file_type = suffix.lstrip(".").upper()
    cur = db.execute(
        """
        INSERT INTO documents(title,original_name,stored_name,file_path,file_type,file_size,document_type,status,project_id,task_id,weekly_report_id,report_id,uploaded_by,comment,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            title or safe_filename(original_name),
            original_name,
            stored_name,
            rel_path,
            file_type,
            len(data),
            document_type if document_type in dict(DOCUMENT_TYPES) else "autre",
            "en_attente",
            project_id,
            task_id,
            weekly_report_id,
            report_id,
            user_id,
            comment,
            now_iso(),
        ),
    )
    return cur.lastrowid


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE expires_at IS NOT NULL AND expires_at < ?", (now_iso(),))
        db.execute(
            "INSERT INTO sessions(token,user_id,created_at,csrf_token,expires_at) VALUES(?,?,?,?,?)",
            (token, user_id, now_iso(), csrf_token, session_expiry_iso()),
        )
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
            print(f"[{now_iso()}] ERREUR GET {self.path}: {exc}")
            self.render_error(500, "Erreur interne. Merci de reessayer ou de contacter l'administrateur.")

    def do_POST(self) -> None:
        try:
            self.route_post()
        except Exception as exc:
            print(f"[{now_iso()}] ERREUR POST {self.path}: {exc}")
            self.render_error(500, "Erreur interne. Merci de reessayer ou de contacter l'administrateur.")

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
        session = query_one("SELECT * FROM sessions WHERE token=?", (token,))
        if session and session["expires_at"] and session["expires_at"] < now_iso():
            destroy_session(token)
            return None
        if not row:
            return None
        return CurrentUser(row["id"], row["first_name"], row["last_name"], row["poste"], row["email"], row["role"], row["profile_photo"] if "profile_photo" in row.keys() else "")

    def require_user(self) -> CurrentUser:
        user = self.current_user()
        if not user:
            self.redirect("/login")
            raise RuntimeError("AUTH_REDIRECT")
        return user

    def read_body(self) -> bytes:
        if hasattr(self, "_cached_body"):
            return self._cached_body
        length = int(self.headers.get("Content-Length", "0"))
        self._cached_body = self.rfile.read(length) if length else b""
        return self._cached_body

    def read_form(self) -> Dict[str, List[str]]:
        raw = self.read_body().decode("utf-8") if self.read_body() else ""
        return parse_qs(raw, keep_blank_values=True)

    def read_multipart_form(self) -> Tuple[Dict[str, List[str]], List[Dict[str, Any]]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > (MAX_UPLOAD_SIZE * 8):
            raise ValueError("Envoi trop volumineux.")
        body = self.read_body()
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return parse_qs(body.decode("utf-8"), keep_blank_values=True), []
        raw = b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        message = BytesParser(policy=email_policy).parsebytes(raw)
        fields: Dict[str, List[str]] = {}
        files: List[Dict[str, Any]] = []
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                if payload:
                    files.append(
                        {
                            "field": name or "files",
                            "filename": filename,
                            "content_type": part.get_content_type(),
                            "data": payload,
                        }
                    )
            elif name:
                fields.setdefault(name, []).append(payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip())
        return fields, files

    def session_csrf_token(self) -> str:
        token = self.get_cookie(SESSION_COOKIE)
        if not token:
            return ""
        row = query_one("SELECT csrf_token FROM sessions WHERE token=?", (token,))
        return row["csrf_token"] if row and row["csrf_token"] else ""

    def verify_csrf(self) -> bool:
        expected = self.session_csrf_token()
        if not expected:
            return False
        content_type = self.headers.get("Content-Type", "")
        try:
            form, _files = self.read_multipart_form() if "multipart/form-data" in content_type else (self.read_form(), [])
        except Exception:
            return False
        submitted = self.form_value(form, "_csrf")
        return bool(submitted) and hmac.compare_digest(submitted, expected)

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

    def should_use_secure_cookie(self) -> bool:
        if os.environ.get("COOKIE_SECURE", "").lower() in {"true", "1", "yes", "on"}:
            return True
        if os.environ.get("APP_URL", "").lower().startswith("https://"):
            return True
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

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
            ("/documents", "Gestion documentaire", "Retrouvez les justificatifs, contrats, factures et preuves classes par projet."),
            ("/field-reports", "Rapports", "Redigez un compte rendu simple avec pieces justificatives rattachees au projet."),
            ("/reports/new", "Bilan hebdomadaire", "Resumez la semaine : realisations, blocages et priorites suivantes."),
            ("/reports", "Bilans", "Consultez ou envoyez les bilans hebdomadaires selon votre role."),
            ("/chat", "Chat equipe", "Echangez rapidement dans le groupe general ; classez les documents importants dans les projets."),
            ("/backups", "Sauvegarde", "Telechargez une archive complete de la base et des fichiers televerses."),
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
            avatar = f"<img src='{esc(user.profile_photo)}' alt='Photo profil'>" if user.profile_photo else esc(initials(user.first_name, user.last_name))
            nav = f"""
            <nav class="topbar">
              <a class="brand" href="/dashboard"><span class="brand-mark">O</span><span>{APP_NAME}</span></a>
              <a class="sidebar-profile" href="/profile">
                <span class="profile-avatar">{avatar}</span>
                <span><strong>{esc(user.full_name)}</strong><small>{esc(user.poste)}</small></span>
              </a>
              <div class="nav-links">
                <a href="/dashboard">Tableau de bord</a>
                <a href="/projects">Projets</a>
                <a href="/tasks">Mes taches</a>
                { '<a href="/tasks/new">Nouvelle tache</a>' if user.is_manager else '' }
                <a href="/documents">Documents</a>
                <a href="/field-reports">Rapports</a>
                <a href="/reports">Bilans</a>
                <a href="/chat">Chat</a>
                { '<a href="/backups">Sauvegarde</a>' if user.is_manager else '' }
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
        if user:
            csrf = esc(self.session_csrf_token())
            html_doc = re.sub(
                r'(<form\b(?=[^>]*method="post")[^>]*>)',
                rf'\1<input type="hidden" name="_csrf" value="{csrf}">',
                html_doc,
                flags=re.IGNORECASE,
            )
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
        if path == "/profile":
            return self.page_profile()
        if path == "/projects":
            return self.page_projects()
        if path == "/projects/new":
            return self.page_project_new()
        if path == "/tasks":
            return self.page_tasks()
        if path == "/tasks/new":
            return self.page_task_new()
        if path == "/documents":
            return self.page_documents()
        if path == "/documents/new":
            return self.page_document_new()
        if path == "/field-reports":
            return self.page_field_reports()
        if path == "/field-reports/new":
            return self.page_field_report_form()
        if path == "/reports":
            return self.page_reports()
        if path == "/reports/new":
            return self.page_report_form(None)
        if path == "/chat":
            return self.page_chat()
        if path == "/backups":
            return self.page_backups()
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
        match = re.fullmatch(r"/documents/(\d+)/(download|view)", path)
        if match:
            return self.serve_document(int(match.group(1)), inline=match.group(2) == "view")
        match = re.fullmatch(r"/field-reports/(\d+)", path)
        if match:
            return self.page_field_report_detail(int(match.group(1)))
        match = re.fullmatch(r"/backups/(\d+)/download", path)
        if match:
            return self.serve_backup(int(match.group(1)))
        match = re.fullmatch(r"/reports/(\d+)", path)
        if match:
            return self.page_report_detail(int(match.group(1)))
        self.render_error(404, "Page introuvable.")

    def route_post(self) -> None:
        path = self.parsed_path.path
        if path == "/login":
            return self.action_login()
        if not self.verify_csrf():
            return self.render_error(403, "Session expiree ou formulaire invalide. Merci de recharger la page.")
        if path == "/logout":
            return self.action_logout()
        if path == "/profile/password":
            return self.action_profile_password()
        if path == "/projects/new":
            return self.action_project_new()
        if path == "/users":
            return self.action_user_new()
        if path == "/tasks/new":
            return self.action_task_new()
        if path == "/documents/new":
            return self.action_document_new()
        if path == "/field-reports/new":
            return self.action_field_report_new()
        if path == "/reports/new":
            return self.action_report_save(None)
        if path == "/chat":
            return self.action_chat_send()
        if path == "/backups/new":
            return self.action_backup_new()
        match = re.fullmatch(r"/projects/(\d+)/status", path)
        if match:
            return self.action_project_status(int(match.group(1)))
        match = re.fullmatch(r"/tasks/(\d+)/update", path)
        if match:
            return self.action_task_update(int(match.group(1)))
        match = re.fullmatch(r"/tasks/(\d+)/comment", path)
        if match:
            return self.action_task_comment(int(match.group(1)))
        match = re.fullmatch(r"/documents/(\d+)/status", path)
        if match:
            return self.action_document_status(int(match.group(1)))
        match = re.fullmatch(r"/chat/(\d+)/delete", path)
        if match:
            return self.action_chat_delete(int(match.group(1)))
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
        demo_box = ""
        if os.environ.get("SHOW_DEMO_CREDENTIALS", "").lower() in {"true", "1", "yes", "on"}:
            demo_box = """
            <div class="demo-box">
              <strong>Comptes de test</strong><br>
              Manager : manager@orga.local / admin123<br>
              Collaborateurs : commercial@orga.local, chef.projet@orga.local, technique@orga.local, raf@orga.local, assistante@orga.local / test123
            </div>
            """
        content = f"""
        <section class="login-shell">
          <div class="login-card">
            <div class="brand-large"><span class="brand-mark">O</span><div><h1>{APP_NAME}</h1><p>Suivi interne des projets et apports d'equipe</p></div></div>
            {f'<div class="alert danger">{esc(error)}</div>' if error else ''}
            <form method="post" action="/login" class="form">
              <label>Email</label>
              <input type="email" name="email" required placeholder="votre.email@entreprise.com">
              <label>Mot de passe</label>
              <input type="password" name="password" required placeholder="Mot de passe">
              <button class="btn primary full" type="submit">Se connecter</button>
            </form>
            {demo_box}
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
        if self.should_use_secure_cookie():
            cookie[SESSION_COOKIE]["secure"] = True
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
        if self.should_use_secure_cookie():
            cookie[SESSION_COOKIE]["secure"] = True
        self.send_response(303)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", cookie.output(header="").strip())
        self.end_headers()

    def page_profile(self, message: str = "") -> None:
        user = self.require_user()
        avatar = f"<img src='{esc(user.profile_photo)}' alt='Photo profil'>" if user.profile_photo else esc(initials(user.first_name, user.last_name))
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Espace profil</p><h1>{esc(user.full_name)}</h1><p>Consultez vos informations et modifiez votre mot de passe.</p></div></header>
        {f'<div class="notice">{esc(message)}</div>' if message else ''}
        <div class="grid two">
          <section class="card profile-card">
            <span class="profile-avatar large">{avatar}</span>
            <h2>{esc(user.full_name)}</h2>
            <dl class="details">
              <dt>Poste</dt><dd>{esc(user.poste)}</dd>
              <dt>Email</dt><dd>{esc(user.email)}</dd>
              <dt>Role</dt><dd><span class="pill {status_class(user.role)}">{esc(dict(ROLES).get(user.role, user.role))}</span></dd>
            </dl>
          </section>
          <section class="card">
            <h2>Modifier le mot de passe</h2>
            <form method="post" action="/profile/password" class="form">
              <label>Mot de passe actuel<input type="password" name="current_password" required></label>
              <label>Nouveau mot de passe<input type="password" name="new_password" required minlength="6"></label>
              <label>Confirmer le nouveau mot de passe<input type="password" name="confirm_password" required minlength="6"></label>
              <button class="btn primary" type="submit">Mettre a jour</button>
            </form>
          </section>
        </div>
        """
        self.render("Profil", content, user)

    def action_profile_password(self) -> None:
        user = self.require_user()
        form = self.read_form()
        current = self.form_value(form, "current_password")
        new_password = self.form_value(form, "new_password")
        confirm = self.form_value(form, "confirm_password")
        row = query_one("SELECT * FROM users WHERE id=?", (user.id,))
        if not row or not verify_password(current, row["password_hash"]):
            return self.page_profile("Mot de passe actuel incorrect.")
        if len(new_password) < 6:
            return self.page_profile("Le nouveau mot de passe doit contenir au moins 6 caracteres.")
        if new_password != confirm:
            return self.page_profile("La confirmation ne correspond pas au nouveau mot de passe.")
        with get_db() as db:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user.id))
            db.commit()
        self.page_profile("Mot de passe mis a jour.")

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
            <p class="eyebrow">Vue manager - {esc(user.full_name)}</p>
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
            <p class="eyebrow">Espace collaborateur - {esc(user.full_name)}</p>
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
        project_docs = [d for d in self.visible_documents(user) if d["project_id"] == project_id]
        doc_rows = self.documents_table(project_docs, user)
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
          <div class="section-head"><h2>Documents du projet</h2><a href="/documents/new">Ajouter un document</a></div>
          <div class="table-wrap"><table><thead><tr><th>Document</th><th>Type</th><th>Projet</th><th>Ajoute par</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{doc_rows}</tbody></table></div>
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
          <form method="post" action="/tasks/{task_id}/comment" enctype="multipart/form-data" class="form grid-form">
            <label class="full">Ce qui a ete fait / information a remonter<textarea name="comment" rows="3" required></textarea></label>
            <label>Blocage eventuel<textarea name="blocker" rows="3"></textarea></label>
            <label>Prochaine action<textarea name="next_action" rows="3"></textarea></label>
            <label class="full">Piece justificative<input type="file" name="files" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" multiple></label>
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
        try:
            form, files = self.read_multipart_form()
            with get_db() as db:
                cur = db.execute(
                    "INSERT INTO task_comments(task_id,user_id,comment,blocker,next_action,created_at) VALUES(?,?,?,?,?,?)",
                    (task_id, user.id, self.form_value(form, "comment"), self.form_value(form, "blocker"), self.form_value(form, "next_action"), now_iso()),
                )
                for f in files:
                    store_document_file(
                        db,
                        file_info=f,
                        user_id=user.id,
                        title=f"Justificatif - {task['title']}",
                        document_type="justificatif",
                        project_id=task["project_id"],
                        task_id=task_id,
                        comment=f"Piece jointe au commentaire #{cur.lastrowid}",
                    )
                if self.form_value(form, "blocker"):
                    db.execute("UPDATE project_tasks SET status='bloque', updated_at=? WHERE id=?", (now_iso(), task_id))
                db.commit()
        except ValueError as exc:
            return self.render_error(400, esc(exc))
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

    def document_query(self) -> List[sqlite3.Row]:
        return query_all(
            """
            SELECT d.*, p.name AS project_name, p.client AS project_client,
                   u.first_name || ' ' || u.last_name AS uploader_name,
                   t.title AS task_title, wr.week_label AS weekly_label, fr.title AS report_title
            FROM documents d
            LEFT JOIN projects p ON p.id=d.project_id
            LEFT JOIN users u ON u.id=d.uploaded_by
            LEFT JOIN project_tasks t ON t.id=d.task_id
            LEFT JOIN weekly_reports wr ON wr.id=d.weekly_report_id
            LEFT JOIN field_reports fr ON fr.id=d.report_id
            ORDER BY d.created_at DESC
            """
        )

    def user_can_access_document(self, user: CurrentUser, doc: sqlite3.Row) -> bool:
        if user.is_manager or doc["uploaded_by"] == user.id:
            return True
        if doc["project_id"] and self.user_can_access_project(user, doc["project_id"]):
            return True
        if doc["task_id"]:
            row = query_one("SELECT 1 FROM project_tasks WHERE id=? AND assigned_user_id=?", (doc["task_id"], user.id))
            if row:
                return True
        if doc["weekly_report_id"]:
            row = query_one("SELECT 1 FROM weekly_reports WHERE id=? AND user_id=?", (doc["weekly_report_id"], user.id))
            if row:
                return True
        if doc["report_id"]:
            row = query_one("SELECT 1 FROM field_reports WHERE id=? AND user_id=?", (doc["report_id"], user.id))
            if row:
                return True
        return False

    def visible_documents(self, user: CurrentUser) -> List[sqlite3.Row]:
        docs = self.document_query()
        return [d for d in docs if self.user_can_access_document(user, d)]

    def documents_table(self, docs: List[sqlite3.Row], user: CurrentUser) -> str:
        rows = []
        for d in docs:
            manager_actions = ""
            if user.is_manager:
                manager_actions = f"""
                <form method="post" action="/documents/{d['id']}/status" class="inline-form">
                  <input type="hidden" name="status" value="valide"><button class="link-button" type="submit">Valider</button>
                </form>
                <form method="post" action="/documents/{d['id']}/status" class="inline-form">
                  <input type="hidden" name="status" value="archive"><button class="link-button" type="submit">Archiver</button>
                </form>
                """
            rows.append(
                f"""
                <tr>
                  <td><a class="strong" href="/documents/{d['id']}/view">{esc(d['title'])}</a><br><small>{esc(d['original_name'])}</small></td>
                  <td>{esc(dict(DOCUMENT_TYPES).get(d['document_type'], d['document_type']))}<br><small>{esc(d['file_type'])} - {round((d['file_size'] or 0)/1024, 1)} Ko</small></td>
                  <td>{esc(d['project_name'] or 'Entreprise')}</td>
                  <td>{esc(d['uploader_name'] or '')}</td>
                  <td>{esc(d['created_at'])}</td>
                  <td><span class="pill {status_class(d['status'])}">{esc(status_label(d['status'], DOCUMENT_STATUSES))}</span></td>
                  <td><a href="/documents/{d['id']}/view">Ouvrir</a> | <a href="/documents/{d['id']}/download">Telecharger</a>{manager_actions}</td>
                </tr>
                """
            )
        return "".join(rows) or "<tr><td colspan='7'>Aucun document.</td></tr>"

    def page_documents(self) -> None:
        user = self.require_user()
        docs = self.visible_documents(user)
        query = parse_qs(self.parsed_path.query)
        q = (query.get("q", [""])[0] or "").lower()
        project_filter = query.get("project_id", [""])[0]
        type_filter = query.get("document_type", [""])[0]
        if q:
            docs = [d for d in docs if q in (d["title"] or "").lower() or q in (d["original_name"] or "").lower() or q in (d["project_name"] or "").lower()]
        if project_filter.isdigit():
            docs = [d for d in docs if str(d["project_id"] or "") == project_filter]
        if type_filter:
            docs = [d for d in docs if d["document_type"] == type_filter]
        projects = query_all("SELECT id,name FROM projects ORDER BY updated_at DESC") if user.is_manager else query_all(
            "SELECT p.id,p.name FROM projects p JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=? ORDER BY p.updated_at DESC",
            (user.id,),
        )
        project_options = "<option value=''>Tous les projets</option>" + "".join(f"<option value='{p['id']}' {'selected' if str(p['id']) == project_filter else ''}>{esc(p['name'])}</option>" for p in projects)
        type_options = "<option value=''>Tous les types</option>" + options_html(DOCUMENT_TYPES, type_filter)
        rows = self.documents_table(docs, user)
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Preuves et fichiers</p><h1>Gestion documentaire</h1><p>Centralisez les justificatifs, contrats, factures, photos et rapports lies aux projets.</p></div><a class="btn primary" href="/documents/new">Ajouter un document</a></header>
        <section class="card">
          <form method="get" action="/documents" class="form grid-form">
            <label>Recherche<input name="q" value="{esc(q)}" placeholder="Nom, fichier ou projet"></label>
            <label>Projet<select name="project_id">{project_options}</select></label>
            <label>Type<select name="document_type">{type_options}</select></label>
            <div class="actions"><button class="btn primary" type="submit">Filtrer</button><a class="btn ghost" href="/documents">Reinitialiser</a></div>
          </form>
        </section>
        <section class="card">
          <div class="table-wrap"><table><thead><tr><th>Document</th><th>Type</th><th>Projet</th><th>Ajoute par</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div>
        </section>
        """
        self.render("Gestion documentaire", content, user)

    def page_document_new(self) -> None:
        user = self.require_user()
        projects = query_all("SELECT id,name FROM projects ORDER BY updated_at DESC") if user.is_manager else query_all(
            "SELECT p.id,p.name FROM projects p JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=? ORDER BY p.updated_at DESC",
            (user.id,),
        )
        project_options = "<option value=''>Entreprise / non lie</option>" + "".join(f"<option value='{p['id']}'>{esc(p['name'])}</option>" for p in projects)
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Document</p><h1>Ajouter un document</h1><p>Formats autorises : PDF, JPG, JPEG, PNG. Taille maximale : 5 Mo par fichier.</p></div></header>
        <section class="card form-card">
          <form method="post" action="/documents/new" enctype="multipart/form-data" class="form grid-form">
            <label>Titre du document<input name="title" required></label>
            <label>Type<select name="document_type">{options_html(DOCUMENT_TYPES, 'justificatif')}</select></label>
            <label class="full">Projet associe<select name="project_id">{project_options}</select></label>
            <label class="full">Commentaire<textarea name="comment" rows="3"></textarea></label>
            <label class="full">Fichier<input type="file" name="files" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" required></label>
            <div class="full actions"><a class="btn ghost" href="/documents">Annuler</a><button class="btn primary" type="submit">Enregistrer</button></div>
          </form>
        </section>
        """
        self.render("Ajouter un document", content, user)

    def action_document_new(self) -> None:
        user = self.require_user()
        try:
            form, files = self.read_multipart_form()
            project_id_raw = self.form_value(form, "project_id")
            project_id = int(project_id_raw) if project_id_raw.isdigit() else None
            if project_id and not self.user_can_access_project(user, project_id):
                return self.render_error(403, "Vous ne pouvez pas ajouter de document sur ce projet.")
            with get_db() as db:
                for f in files:
                    store_document_file(
                        db,
                        file_info=f,
                        user_id=user.id,
                        title=self.form_value(form, "title") or safe_filename(f["filename"]),
                        document_type=self.form_value(form, "document_type", "justificatif"),
                        project_id=project_id,
                        comment=self.form_value(form, "comment"),
                    )
                if user.is_manager is False:
                    managers = db.execute("SELECT id FROM users WHERE role='manager' AND is_active=1").fetchall()
                    for manager in managers:
                        create_notification(db, manager["id"], "Nouveau document ajoute", f"{user.full_name} a ajoute un document.", project_id, "document")
                db.commit()
        except ValueError as exc:
            return self.render_error(400, esc(exc))
        self.redirect("/documents")

    def action_document_status(self, document_id: int) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        form = self.read_form()
        status = self.form_value(form, "status")
        if status not in dict(DOCUMENT_STATUSES):
            return self.render_error(400, "Statut documentaire invalide.")
        with get_db() as db:
            db.execute("UPDATE documents SET status=? WHERE id=?", (status, document_id))
            db.commit()
        self.redirect("/documents")

    def serve_document(self, document_id: int, inline: bool = False) -> None:
        user = self.require_user()
        doc = query_one("SELECT * FROM documents WHERE id=?", (document_id,))
        if not doc:
            return self.render_error(404, "Document introuvable.")
        if not self.user_can_access_document(user, doc):
            return self.render_error(403, "Acces refuse a ce document.")
        target = (DATA_DIR / doc["file_path"]).resolve()
        if not str(target).startswith(str(DATA_DIR.resolve())) or not target.exists():
            return self.render_error(404, "Fichier introuvable.")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(doc["original_name"])[0] or "application/octet-stream"
        disposition = "inline" if inline else "attachment"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'{disposition}; filename="{safe_filename(doc["original_name"])}{Path(doc["original_name"]).suffix}"')
        self.end_headers()
        self.wfile.write(data)

    def page_field_reports(self) -> None:
        user = self.require_user()
        if user.is_manager:
            reports = query_all(
                """
                SELECT r.*, p.name AS project_name, u.first_name || ' ' || u.last_name AS user_name
                FROM field_reports r
                LEFT JOIN projects p ON p.id=r.project_id
                JOIN users u ON u.id=r.user_id
                ORDER BY COALESCE(r.submitted_at, r.updated_at) DESC
                """
            )
        else:
            reports = query_all(
                """
                SELECT r.*, p.name AS project_name, u.first_name || ' ' || u.last_name AS user_name
                FROM field_reports r
                LEFT JOIN projects p ON p.id=r.project_id
                JOIN users u ON u.id=r.user_id
                WHERE r.user_id=? OR r.project_id IN (SELECT project_id FROM project_members WHERE user_id=?)
                ORDER BY COALESCE(r.submitted_at, r.updated_at) DESC
                """,
                (user.id, user.id),
            )
        rows = "".join(
            f"<tr><td><a class='strong' href='/field-reports/{r['id']}'>{esc(r['title'])}</a></td><td>{esc(r['project_name'] or 'Non lie')}</td><td>{esc(r['user_name'])}</td><td><span class='pill {status_class(r['status'])}'>{esc(status_label(r['status'], FIELD_REPORT_STATUSES))}</span></td><td>{esc(r['submitted_at'] or r['created_at'])}</td></tr>"
            for r in reports
        ) or "<tr><td colspan='5'>Aucun rapport.</td></tr>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Comptes rendus</p><h1>Rapports</h1><p>Visites terrain, livraisons, reunions, controles et retours clients avec justificatifs.</p></div><a class="btn primary" href="/field-reports/new">Nouveau rapport</a></header>
        <section class="card"><div class="table-wrap"><table><thead><tr><th>Titre</th><th>Projet</th><th>Auteur</th><th>Statut</th><th>Date</th></tr></thead><tbody>{rows}</tbody></table></div></section>
        """
        self.render("Rapports", content, user)

    def page_field_report_form(self) -> None:
        user = self.require_user()
        projects = query_all("SELECT id,name FROM projects ORDER BY updated_at DESC") if user.is_manager else query_all(
            "SELECT p.id,p.name FROM projects p JOIN project_members pm ON pm.project_id=p.id AND pm.user_id=? ORDER BY p.updated_at DESC",
            (user.id,),
        )
        project_options = "<option value=''>Non lie</option>" + "".join(f"<option value='{p['id']}'>{esc(p['name'])}</option>" for p in projects)
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Rapport</p><h1>Nouveau rapport</h1><p>Gardez le compte rendu court et rattachez les preuves utiles.</p></div></header>
        <section class="card form-card">
          <form method="post" action="/field-reports/new" enctype="multipart/form-data" class="form grid-form">
            <label>Titre<input name="title" required></label>
            <label>Projet<select name="project_id">{project_options}</select></label>
            <label>Statut<select name="status">{options_html(FIELD_REPORT_STATUSES, 'envoye')}</select></label>
            <label class="full">Compte rendu<textarea name="content" rows="6" required></textarea></label>
            <label class="full">Pieces jointes<input type="file" name="files" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" multiple></label>
            <div class="full actions"><a class="btn ghost" href="/field-reports">Annuler</a><button class="btn primary" type="submit">Enregistrer</button></div>
          </form>
        </section>
        """
        self.render("Nouveau rapport", content, user)

    def action_field_report_new(self) -> None:
        user = self.require_user()
        try:
            form, files = self.read_multipart_form()
            project_raw = self.form_value(form, "project_id")
            project_id = int(project_raw) if project_raw.isdigit() else None
            if project_id and not self.user_can_access_project(user, project_id):
                return self.render_error(403, "Vous ne pouvez pas creer de rapport sur ce projet.")
            status = self.form_value(form, "status", "envoye")
            if status not in dict(FIELD_REPORT_STATUSES):
                return self.render_error(400, "Statut de rapport invalide.")
            submitted_at = now_iso() if status == "envoye" else None
            with get_db() as db:
                cur = db.execute(
                    """
                    INSERT INTO field_reports(project_id,user_id,title,content,status,submitted_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (project_id, user.id, self.form_value(form, "title"), self.form_value(form, "content"), status, submitted_at, now_iso(), now_iso()),
                )
                report_id = cur.lastrowid
                for f in files:
                    store_document_file(
                        db,
                        file_info=f,
                        user_id=user.id,
                        title=f"Piece rapport - {self.form_value(form, 'title')}",
                        document_type="rapport",
                        project_id=project_id,
                        report_id=report_id,
                        comment="Piece jointe au rapport",
                    )
                if status == "envoye":
                    managers = db.execute("SELECT id FROM users WHERE role='manager' AND is_active=1").fetchall()
                    for manager in managers:
                        create_notification(db, manager["id"], "Rapport envoye", f"{user.full_name} a envoye le rapport : {self.form_value(form, 'title')}.", project_id, "rapport")
                db.commit()
        except ValueError as exc:
            return self.render_error(400, esc(exc))
        self.redirect(f"/field-reports/{report_id}")

    def page_field_report_detail(self, report_id: int) -> None:
        user = self.require_user()
        report = query_one(
            """
            SELECT r.*, p.name AS project_name, u.first_name || ' ' || u.last_name AS user_name
            FROM field_reports r
            LEFT JOIN projects p ON p.id=r.project_id
            JOIN users u ON u.id=r.user_id
            WHERE r.id=?
            """,
            (report_id,),
        )
        if not report:
            return self.render_error(404, "Rapport introuvable.")
        if not user.is_manager and report["user_id"] != user.id and not (report["project_id"] and self.user_can_access_project(user, report["project_id"])):
            return self.render_error(403, "Acces refuse a ce rapport.")
        docs = [d for d in self.visible_documents(user) if d["report_id"] == report_id]
        doc_rows = self.documents_table(docs, user)
        content = f"""
        <header class="hero small"><div><p class="eyebrow">{esc(report['project_name'] or 'Rapport')}</p><h1>{esc(report['title'])}</h1><p>{esc(report['user_name'])} - {esc(report['submitted_at'] or report['created_at'])}</p></div></header>
        <section class="card"><h2>Compte rendu</h2><p>{esc(report['content'])}</p><p><span class="pill {status_class(report['status'])}">{esc(status_label(report['status'], FIELD_REPORT_STATUSES))}</span></p></section>
        <section class="card"><h2>Pieces jointes</h2><div class="table-wrap"><table><thead><tr><th>Document</th><th>Type</th><th>Projet</th><th>Ajoute par</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{doc_rows}</tbody></table></div></section>
        """
        self.render(report["title"], content, user)

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
          <form method="post" action="/reports/new" enctype="multipart/form-data" class="form grid-form">
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
            <label class="full">Pieces justificatives<input type="file" name="files" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" multiple></label>
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
        try:
            form, files = self.read_multipart_form()
        except ValueError as exc:
            return self.render_error(400, esc(exc))
        status = self.form_value(form, "status", "envoye")
        if status not in dict(REPORT_STATUSES):
            return self.render_error(400, "Statut de bilan invalide.")
        submitted_at = now_iso() if status == "envoye" else None
        try:
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
                for f in files:
                    store_document_file(
                        db,
                        file_info=f,
                        user_id=user.id,
                        title=f"Justificatif bilan - {self.form_value(form, 'week_label')}",
                        document_type="justificatif",
                        weekly_report_id=report_id,
                        comment="Piece jointe au bilan hebdomadaire",
                    )
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
        except ValueError as exc:
            return self.render_error(400, esc(exc))
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
        report_docs = [d for d in self.visible_documents(user) if d["weekly_report_id"] == report_id]
        doc_rows = self.documents_table(report_docs, user)
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
        <section class="card">
          <h2>Pieces justificatives</h2>
          <div class="table-wrap"><table><thead><tr><th>Document</th><th>Type</th><th>Projet</th><th>Ajoute par</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{doc_rows}</tbody></table></div>
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

    def page_chat(self) -> None:
        user = self.require_user()
        messages = query_all(
            """
            SELECT m.*, u.first_name || ' ' || u.last_name AS sender_name
            FROM chat_messages m JOIN users u ON u.id=m.sender_id
            ORDER BY m.created_at ASC
            LIMIT 200
            """
        )
        items = "".join(
            f"""
            <article class="notification {'muted' if m['is_deleted'] else ''}">
              <div><h3>{esc(m['sender_name'])}</h3><p>{esc('Message masque par le manager.' if m['is_deleted'] else m['message'])}</p><small>{esc(m['created_at'])}</small></div>
              {f'<form method="post" action="/chat/{m["id"]}/delete"><button class="btn ghost" type="submit">Masquer</button></form>' if user.is_manager and not m['is_deleted'] else ''}
            </article>
            """
            for m in messages
        ) or "<div class='empty'>Aucun message pour le moment.</div>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Groupe general</p><h1>Chat equipe</h1><p>Messages courts pour coordonner l'equipe. Les documents importants restent classes dans les projets.</p></div></header>
        <section class="stack">{items}</section>
        <section class="card">
          <form method="post" action="/chat" class="form">
            <label>Message<textarea name="message" rows="3" required maxlength="1000"></textarea></label>
            <div class="actions"><button class="btn primary" type="submit">Envoyer</button></div>
          </form>
        </section>
        """
        self.render("Chat equipe", content, user)

    def action_chat_send(self) -> None:
        user = self.require_user()
        form = self.read_form()
        message = self.form_value(form, "message")
        if not message:
            return self.render_error(400, "Le message est obligatoire.")
        with get_db() as db:
            db.execute("INSERT INTO chat_messages(sender_id,message,created_at) VALUES(?,?,?)", (user.id, message[:1000], now_iso()))
            recipients = db.execute("SELECT id FROM users WHERE is_active=1 AND id<>?", (user.id,)).fetchall()
            for recipient in recipients:
                create_notification(db, recipient["id"], "Nouveau message chat", f"{user.full_name} a ecrit dans le chat equipe.", None, "chat")
            db.commit()
        self.redirect("/chat")

    def action_chat_delete(self, message_id: int) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        with get_db() as db:
            db.execute("UPDATE chat_messages SET is_deleted=1, deleted_by=?, deleted_at=? WHERE id=?", (user.id, now_iso(), message_id))
            db.commit()
        self.redirect("/chat")

    def page_backups(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        backups = query_all(
            """
            SELECT b.*, u.first_name || ' ' || u.last_name AS user_name
            FROM backups b JOIN users u ON u.id=b.created_by
            ORDER BY b.created_at DESC
            """
        )
        rows = "".join(
            f"<tr><td>{esc(b['backup_name'])}</td><td>{esc(b['created_at'])}</td><td>{esc(b['user_name'])}</td><td>{round((b['file_size'] or 0)/1024, 1)} Ko</td><td><a href='/backups/{b['id']}/download'>Telecharger</a></td></tr>"
            for b in backups
        ) or "<tr><td colspan='5'>Aucune sauvegarde.</td></tr>"
        content = f"""
        <header class="hero small"><div><p class="eyebrow">Manager</p><h1>Sauvegardes</h1><p>Archive ZIP contenant la base SQLite, les documents televerses et un manifeste.</p></div>
          <form method="post" action="/backups/new"><button class="btn primary" type="submit">Telecharger une sauvegarde complete</button></form>
        </header>
        <section class="card"><div class="table-wrap"><table><thead><tr><th>Nom</th><th>Date</th><th>Lance par</th><th>Taille</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div></section>
        """
        self.render("Sauvegardes", content, user)

    def action_backup_new(self) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"orga-pilotage-sauvegarde-{stamp}.zip"
        target = BACKUP_DIR / backup_name
        db_snapshot = BACKUP_DIR / f"snapshot-{stamp}.sqlite3"
        manifest = {
            "created_at": now_iso(),
            "created_by": user.full_name,
            "database": DB_PATH.name,
            "uploads_dir": "uploads",
        }
        if DB_PATH.exists():
            source = sqlite3.connect(DB_PATH)
            dest = sqlite3.connect(db_snapshot)
            try:
                source.backup(dest)
            finally:
                dest.close()
                source.close()
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                if db_snapshot.exists():
                    z.write(db_snapshot, f"database/{DB_PATH.name}")
                if UPLOAD_DIR.exists():
                    for f in UPLOAD_DIR.rglob("*"):
                        if f.is_file():
                            z.write(f, f"uploads/{f.relative_to(UPLOAD_DIR)}")
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        finally:
            if db_snapshot.exists():
                db_snapshot.unlink()
        size = target.stat().st_size
        rel = str(target.relative_to(DATA_DIR)).replace("\\", "/")
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO backups(backup_name,backup_path,backup_type,file_size,created_by,created_at) VALUES(?,?,?,?,?,?)",
                (backup_name, rel, "manuelle", size, user.id, now_iso()),
            )
            create_notification(db, user.id, "Sauvegarde generee", f"Sauvegarde prete : {backup_name}.", None, "sauvegarde")
            db.commit()
            backup_id = cur.lastrowid
        self.redirect(f"/backups/{backup_id}/download")

    def serve_backup(self, backup_id: int) -> None:
        user = self.require_user()
        if not user.is_manager:
            return self.render_error(403, "Acces reserve au manager.")
        backup = query_one("SELECT * FROM backups WHERE id=?", (backup_id,))
        if not backup:
            return self.render_error(404, "Sauvegarde introuvable.")
        target = (DATA_DIR / backup["backup_path"]).resolve()
        if not str(target).startswith(str(DATA_DIR.resolve())) or not target.exists():
            return self.render_error(404, "Fichier de sauvegarde introuvable.")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{backup["backup_name"]}"')
        self.end_headers()
        self.wfile.write(data)

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
