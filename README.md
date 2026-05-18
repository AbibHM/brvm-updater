# BRVM Daily Updater

Mise à jour automatique des cours BRVM dans Supabase, sans aucune dépendance externe tierce.

**Source des données :** brvm.org (scraping direct)  
**Stockage :** Supabase (table `brvm_prices`)  
**Déclenchement :** GitHub Actions (gratuit, cloud, indépendant)

---

## 🚀 Installation (une seule fois)

### 1. Créer un repository GitHub privé

1. Aller sur [github.com/new](https://github.com/new)
2. Nommer le repo `brvm-updater` (privé)
3. Ne pas initialiser avec README

### 2. Pousser ces fichiers

```bash
git init
git add .
git commit -m "Initial commit — BRVM updater"
git branch -M main
git remote add origin https://github.com/VOTRE_USERNAME/brvm-updater.git
git push -u origin main
```

### 3. Configurer les secrets GitHub

Dans votre repo : **Settings → Secrets and variables → Actions → New repository secret**

| Nom | Valeur |
|-----|--------|
| `SUPABASE_URL` | `https://jblrvlmxrjkwcpadcmny.supabase.co` |
| `SUPABASE_KEY` | `sb_publishable_kv6SyXEAcc4vi3wgKjofmQ_kaZ-pb0f` |

---

## ▶️ Utilisation

### Automatique
Le script tourne tous les jours de la semaine à **19h30 (heure Abidjan)** — aucune action requise.

### Manuel (déclencher à la demande)
1. Aller dans votre repo GitHub → onglet **Actions**
2. Cliquer sur **BRVM Daily Update**
3. Cliquer **Run workflow** → **Run workflow**

C'est tout. Le script s'exécute en ~30 secondes.

---

## 🧠 Comportement intelligent

- ✅ Vérifie d'abord si les données du jour sont déjà dans Supabase → évite les doublons
- ✅ Si brvm.org n'a pas encore publié les cours → exit propre (code 1) sans erreur fatale
- ✅ Upsert par batch de 50 lignes (robuste)
- ✅ Met à jour `brvm_meta` après chaque run

---

## 🔧 Lancer en local

```bash
pip install -r requirements.txt

# Avec les variables d'environnement
SUPABASE_URL="https://..." SUPABASE_KEY="sb_..." python brvm_update.py

# Ou directement (clés incluses dans le script par défaut)
python brvm_update.py
```
