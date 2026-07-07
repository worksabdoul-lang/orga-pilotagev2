# Déploiement sur Render — ORGA Pilotage MVP

## Pourquoi l'erreur est apparue

Render exécute la commande :

```bash
pip install -r requirements.txt
```

L'erreur `No such file or directory: requirements.txt` signifie que Render ne trouve pas ce fichier à la racine du projet déployé.

Cette version ajoute donc :

- `requirements.txt` ;
- `Procfile` ;
- `render.yaml` ;
- `.python-version` ;
- correction du serveur pour écouter sur `0.0.0.0`, obligatoire pour Render.

## Structure attendue à la racine du dépôt GitHub

Les fichiers suivants doivent être visibles directement à la racine du dépôt GitHub ou dans le dossier choisi comme Root Directory sur Render :

```text
server.py
requirements.txt
Procfile
render.yaml
.python-version
static/
data/
docs/
README.md
```

Si tu mets le dossier complet `orga-pilotage-mvp` dans GitHub, alors dans Render tu dois mettre :

```text
Root Directory: orga-pilotage-mvp
```

Si tu mets directement les fichiers du dossier dans GitHub, laisse le Root Directory vide.

## Réglages Render recommandés

Dans Render :

1. New +
2. Web Service
3. Connecter le dépôt GitHub
4. Runtime : Python
5. Build Command :

```bash
pip install -r requirements.txt
```

6. Start Command :

```bash
python server.py
```

7. Environment Variables :

```text
HOST=0.0.0.0
APP_URL=https://ton-nom-de-service.onrender.com
```

Render fournit automatiquement la variable `PORT`. Le fichier `server.py` la lit déjà.

## Configuration email optionnelle

Sans configuration SMTP, les emails ne sont pas réellement envoyés. Ils sont enregistrés dans :

```text
data/email_outbox.log
```

Pour activer les emails réels, ajoute dans Render les variables d'environnement suivantes :

```text
SMTP_HOST=smtp.tonservice.com
SMTP_PORT=587
SMTP_USER=ton_email
SMTP_PASSWORD=ton_mot_de_passe
SMTP_FROM=ton_email
APP_URL=https://ton-nom-de-service.onrender.com
```

## Comptes de test

Manager :

```text
manager@orga.local
admin123
```

Collaborateurs :

```text
commercial@orga.local
chef.projet@orga.local
technique@orga.local
raf@orga.local
assistante@orga.local

Mot de passe : test123
```
