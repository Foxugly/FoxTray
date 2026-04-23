# FoxTray — Brief technique

## Contexte et objectif

Je développe plusieurs applications web, chacune composée d'un **backend Django** et d'un **frontend Angular**. Les projets utilisent souvent les mêmes ports (8000 / 4200), donc je ne peux en lancer qu'un à la fois.

Actuellement, switcher de projet = retrouver les bons terminaux, killer les process, naviguer dans les dossiers, relancer `runserver` et `ng serve`. Trop de friction.

**L'objectif** : un petit outil de productivité qui vit dans le tray icon Windows et permet de démarrer/arrêter n'importe quel projet (backend + frontend simultanément) en deux clics.

---

## Plateforme

- **Windows uniquement** (pour l'instant)
- **Python 3.14**
- Un seul projet actif à la fois (contrainte de ports)

---

## Stack technique validée

| Usage | Lib |
|---|---|
| Tray icon | `pystray` |
| Gestion process (kill d'arbre) | `psutil` |
| Lancement process | `subprocess` avec `CREATE_NEW_PROCESS_GROUP` |
| Config | `PyYAML` |
| Health check HTTP | `requests` |
| Packaging (plus tard) | `pyinstaller` |

---

## Points techniques critiques

### 1. Kill propre des arbres de process

Le piège classique : `ng serve` spawn des process enfants Node. Un simple `process.terminate()` laisse Node tourner en fond et le port 4200 reste occupé.

**Solution** : lancer les process avec `subprocess.Popen(..., creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)`, puis au kill, utiliser `psutil.Process(pid).children(recursive=True)` pour tuer tout l'arbre.

### 2. Venv Django : pas d'activation

Plutôt que d'activer le venv avec un script, appeler directement le python du venv :
```
D:\PycharmProjects\MonProjet\.venv\Scripts\python.exe manage.py runserver 8000
```
Plus fiable, pas de problème de shell.

### 3. Détection d'état réelle

Ne pas se fier uniquement au PID stocké : un process peut crasher sans qu'on le sache. Faire un health check HTTP sur le port avant d'afficher "running". Un projet est vraiment UP quand backend ET frontend répondent sur leurs ports.

### 4. Switch atomique

Quand on passe du projet A au B : attendre que le port de A soit libéré avant de lancer B, sinon `EADDRINUSE`.

### 5. Auto-stop sur switch

Si un projet tourne et l'utilisateur en démarre un autre, on stop automatiquement l'ancien avant de lancer le nouveau. Pas de confirmation à demander (comportement choisi).

---

## Configuration

Format : **YAML**, fichier `config.yaml` à la racine.

**Exemple à reproduire** (mes vrais projets) :

```yaml
projects:
  - name: FoxRunner
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\FoxRunner_server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: C:\Users\Renaud\WebstormProjects\FoxRunner_frontend
      command: ng serve --port 4200
      port: 4200

  - name: QuizOnline
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\QuizOnline\quizonline-server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: D:\PycharmProjects\QuizOnline\quizonline-frontend
      command: ng serve --port 4200
      port: 4200

  - name: PushIT
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\PushIT_server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: C:\Users\Renaud\WebstormProjects\PushIT_frontend
      command: ng serve --port 4200
      port: 4200
```

**Note** : le champ `venv` indique le nom du dossier venv dans `backend.path`. Le code doit construire `{backend.path}\{venv}\Scripts\python.exe` et l'utiliser à la place du `python` dans `command`.

---

## Logs

- Emplacement : `%APPDATA%\project-switcher\logs\`
- Un fichier par projet et par composant : `{projet}_backend.log`, `{projet}_frontend.log`
- Rotation simple : on garde la session courante + la précédente (`.log` + `.log.1`)
- stdout et stderr des process y sont redirigés
- Accès via l'UI (menu tray → View logs) : fenêtre tkinter avec tail en temps réel et bouton "Open in Explorer"

---

## État persistant

Stocker dans `%APPDATA%\project-switcher\state.json` :
- Le projet actuellement actif (pour l'afficher au redémarrage de l'app)
- Optionnel : proposer de relancer au démarrage

---

## Architecture cible

```
project-switcher/
├── config.yaml
├── main.py                 # Entry point (CLI + tray selon flag)
├── requirements.txt
├── README.md
└── switcher/
    ├── __init__.py
    ├── config.py           # Chargement + validation YAML (dataclasses)
    ├── paths.py            # Helpers APPDATA, logs dir, state file
    ├── process.py          # ProcessManager: start/stop/kill tree
    ├── project.py          # Project: orchestration backend + frontend
    ├── health.py           # Health check HTTP + attente port libéré
    ├── state.py            # Persistance (projet actif)
    ├── logs.py             # Écriture + rotation + lecture tail
    └── ui/
        ├── __init__.py
        ├── tray.py         # pystray menu dynamique
        └── log_viewer.py   # Fenêtre tkinter pour les logs
```

---

## Plan d'itérations

### Iter 1 — CLI pure (PRIORITAIRE)
Aucune UI. On valide la logique de gestion des process avant tout le reste.

Commandes :
- `python main.py list` — liste les projets avec leur état (running/stopped)
- `python main.py start <nom>` — auto-stop l'actif + start le nouveau
- `python main.py stop <nom>` — arrêt propre avec kill de l'arbre
- `python main.py stop-all` — arrête tout
- `python main.py status <nom>` — health check détaillé (backend, frontend, ports)

**Critère de succès** : `stop` tue bien Node (vérifier avec le Task Manager, aucun `node.exe` résiduel, port 4200 libre).

### Iter 2 — Tray icon
- `pystray` avec menu dynamique qui reflète l'état
- Icône colorée (vert = running, gris = stopped)
- Items : Start/Stop, Open in browser, Open backend/frontend folder
- `python main.py tray` pour lancer en mode tray

### Iter 3 — Logs UI + robustesse
- Viewer tkinter avec tail des logs backend/frontend
- Health check intégré (un projet est "running" seulement si les ports répondent)
- Persistance du projet actif

### Iter 4 — Update + packaging
- Action "Update" : `git pull`, `pip install -r requirements.txt`, `python manage.py migrate`, `npm install` — avec feedback visuel
- Raccourci clavier global (ex: `Ctrl+Alt+P`) pour ouvrir le menu
- Packaging `.exe` avec pyinstaller
- Lancement au démarrage Windows (optionnel)

---

## Règles de dev

- **Type hints partout**, dataclasses pour les structures de config
- **Pas de globals**, injection de dépendances propre
- **Logging** interne de l'app via `logging` (distinct des logs des projets gérés)
- **Tests** : au minimum un test manuel documenté par itération. Unit tests bienvenus sur `process.py` et `config.py`
- **Commits** petits et fréquents, un commit par fonctionnalité
- **README** mis à jour au fur et à mesure (installation, usage, config)

---

## Première tâche

Commence par **l'Iter 1 uniquement**. Ne touche pas au tray pour l'instant.

Ordre suggéré :
1. `requirements.txt` + `README.md` initial
2. `config.yaml` avec les 3 projets ci-dessus
3. `switcher/config.py` (chargement + validation)
4. `switcher/paths.py` (helpers APPDATA)
5. `switcher/process.py` (start/stop/kill tree) — **le morceau critique**
6. `switcher/project.py` (orchestration backend + frontend)
7. `main.py` avec les commandes CLI via `argparse`
8. Test manuel : `list`, `start FoxRunner`, vérifier les deux process, `stop FoxRunner`, vérifier qu'il ne reste aucun `node.exe`.

Une fois l'Iter 1 fonctionnelle et testée, on passe à l'Iter 2.