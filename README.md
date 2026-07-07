# ORGA Pilotage — MVP réel

Application web interne de suivi d'avancement des projets pour une petite équipe.

## Fonctions incluses

- Connexion utilisateur avec 2 rôles : Manager / Collaborateur
- Comptes préchargés pour 6 personnes
- Création de projet par le manager
- Sélection des membres impliqués
- Notification interne à la création du projet
- Email d'assignation à la création du projet
- Fiche unique **Apport / Tâche** par membre et par projet
- Tableau de bord manager global
- Tableau de bord collaborateur
- Liste et détail des projets
- Centre de notifications
- Gestion simple des utilisateurs
- Base de données SQLite locale

## Fonctions volontairement hors MVP

- Rappels automatiques par email
- Emails de retard, blocage, livraison
- Export PDF / Excel
- Application mobile native
- IA, paie, RH complète, messagerie interne

## Lancer l'application en local

Prérequis : Python 3.10 ou plus récent.

```bash
cd orga-pilotage-mvp
python server.py
```

Puis ouvrir :

```text
http://localhost:8000
```

## Comptes de test

| Rôle | Email | Mot de passe |
|---|---|---|
| Manager | manager@orga.local | admin123 |
| Commercial | commercial@orga.local | test123 |
| Chef de projet | chef.projet@orga.local | test123 |
| Responsable technique/logistique | technique@orga.local | test123 |
| RAF | raf@orga.local | test123 |
| Assistante de direction | assistante@orga.local | test123 |

## Email d'assignation

Le système sait envoyer un email lorsqu'un membre est ajouté à un projet.

Par défaut, si aucun SMTP n'est configuré, les emails sont enregistrés dans :

```text
data/email_outbox.log
```

Pour activer l'envoi réel, définir ces variables d'environnement avant de lancer l'application :

```bash
export APP_URL="https://votre-domaine.com"
export SMTP_HOST="smtp.votre-fournisseur.com"
export SMTP_PORT="587"
export SMTP_USER="votre-compte-smtp"
export SMTP_PASS="votre-mot-de-passe-smtp"
export SMTP_FROM="ORGA Pilotage <no-reply@votre-domaine.com>"
export SMTP_TLS="true"
python server.py
```

Sous Windows PowerShell :

```powershell
$env:APP_URL="https://votre-domaine.com"
$env:SMTP_HOST="smtp.votre-fournisseur.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="votre-compte-smtp"
$env:SMTP_PASS="votre-mot-de-passe-smtp"
$env:SMTP_FROM="ORGA Pilotage <no-reply@votre-domaine.com>"
$env:SMTP_TLS="true"
python server.py
```

## Déploiement simple sur VPS / cloud interne

1. Copier le dossier `orga-pilotage-mvp` sur le serveur.
2. Lancer avec Python : `python server.py`.
3. Définir `HOST=0.0.0.0` et `PORT=8000` pour accès réseau.
4. Placer un reverse proxy Nginx/Apache devant l'application.
5. Activer HTTPS.
6. Configurer SMTP pour l'envoi réel des emails.
7. Sauvegarder régulièrement le dossier `data/`.

Exemple :

```bash
HOST=0.0.0.0 PORT=8000 python server.py
```

## Notes de sécurité pour une mise en production

Cette version est un MVP fonctionnel. Avant usage réel sensible :

- remplacer les mots de passe de test ;
- activer HTTPS ;
- limiter l'accès réseau ;
- ajouter une politique de sauvegarde ;
- ajouter la protection CSRF ;
- prévoir un service systemd ou équivalent ;
- placer l'application derrière un reverse proxy.

## Structure

```text
orga-pilotage-mvp/
├── server.py
├── static/
│   └── style.css
├── data/
│   └── orga_pilotage.sqlite3  # créé automatiquement au lancement
├── docs/
│   └── brief-mvp-reel.txt
└── README.md
```
