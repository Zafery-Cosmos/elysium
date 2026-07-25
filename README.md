<div align="center">

<img src="frontend/public/logo.png" width="120" alt="Elysium" />

# Elysium

### Votre équipe de développement, propulsée par l'IA.

**Décrivez une idée. Regardez-la devenir un logiciel.**

Elysium n'est pas un chatbot. Ce n'est pas un simple générateur de code.
C'est un **environnement de développement intelligent** où une équipe d'agents IA
spécialisés — chef de projet, architecte, développeurs, ingénieur base de données,
DevOps, sécurité, QA — collabore pour transformer votre idée en application
fonctionnelle, pendant que **vous gardez le contrôle à chaque étape**.

> Un chatbot répond. Un assistant code. **Une équipe construit.**

*Application desktop · Windows · macOS · Linux*

</div>

---

## Pourquoi Elysium

Vous avez une idée. Vous n'avez pas forcément les compétences techniques, ou pas
le temps. Vous ouvrez Elysium, vous écrivez une phrase :

> « Je veux une application pour réserver des restaurants. »

Elysium comprend votre intention, vous pose les bonnes questions (et seulement
celles-là), rédige un cahier des charges, propose une architecture, puis passe à
la construction — en vous montrant chaque décision, chaque fichier, chaque
commande **avant** de l'exécuter.

## Ce qui rend Elysium différent

- 🧠 **Une vraie équipe d'agents** — des rôles explicites qui se répartissent le
  travail, débattent des choix techniques et gardent une mémoire du projet.
  Choisissez le mode **Simple** (un modèle en solo) ou **Expert** (toute l'équipe).
- 💬 **Du langage naturel au logiciel** — questions adaptatives, génération de
  plan, édition guidée. Trois modes de chat : Discuter · Plan · Éditer.
- 🔐 **Vous décidez, refus par défaut** — chaque action sensible passe par un
  gardien de permissions en Rust, avec accès fichiers limité, validation à
  l'action et journal d'audit. Une injection de prompt ne peut jamais dépasser
  ce que vous avez autorisé.
- 🌐 **Multi-modèles, sans dépendance** — Anthropic, OpenAI, Google, Mistral,
  DeepSeek, OpenRouter, et vos **modèles locaux** (Ollama, LM Studio). Sélecteur
  de modèle avec coût (`$`→`$$$$`), date de sortie et niveau d'effort.
- 🔌 **Marketplace MCP** — connectez GitHub, Docker, Postgres, Slack et des
  dizaines d'outils à vos agents.
- 🎛️ **Réglages poussés** — IA, cache de prompts, permissions par agent,
  confidentialité, mode développeur, et l'interface en **français, anglais,
  espagnol**.
- 🎨 **Une interface soignée** — thème clair épuré, animations fluides, pensée
  pour être aussi simple pour un débutant que complète pour un pro.

## Aperçu

> _(Captures d'écran à venir.)_

## Statut du projet

> ⚙️ **Développement actif — v0.5.** La fondation, l'interface, la configuration
> IA et la marketplace MCP sont en place. L'orchestration multi-agents complète
> (exécution réelle du code, terminal, Git, déploiement) arrive dans les
> prochaines versions. Voir [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Installation (développeurs)

**Prérequis :** Node.js 20+ et pnpm · Rust (via [rustup](https://rustup.rs)) +
les [dépendances système Tauri v2](https://v2.tauri.app/start/prerequisites/) ·
Python 3.11+.

```sh
git clone <votre-repo> elysium
cd elysium
scripts/setup.sh        # dépendances frontend + environnement Python du moteur
pnpm install && pnpm tauri dev   # lance l'application desktop (depuis la racine)
```

Sur Fedora, les dépendances système :

```sh
sudo dnf install webkit2gtk4.1-devel openssl-devel libappindicator-gtk3-devel librsvg2-devel
```

## Architecture

```
Frontend (React + TS + Tailwind)  ──IPC──▶  Cœur Rust (Tauri)
     interface uniquement                    permissions · secrets · sidecar
                                                        │
                                             HTTP + SSE (127.0.0.1, token)
                                                        ▼
                                             Moteur IA Python (FastAPI)
                                             agents · modèles · mémoire
                                                        │
                                             SQLite (défaut) / PostgreSQL + pgvector
```

Détails et décisions d'architecture (ADR) : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation

| Document | Contenu |
|---|---|
| [`docs/VISION.md`](docs/VISION.md) | Ce qu'est Elysium, principes, positionnement |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Couches, contrats API/IPC, ADR |
| [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) | Personas, modes UI, parcours, fonctionnalités |
| [`docs/AI_SYSTEM.md`](docs/AI_SYSTEM.md) | Agents, questionnement adaptatif, routage, mémoire |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Modèle de menace, permissions, human-in-the-loop |
| [`docs/UI_UX.md`](docs/UI_UX.md) | Design system, composants, accessibilité |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Modèle de données, migrations, mémoire vectorielle |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Feuille de route par phases |

## Licence

**Propriétaire — tous droits réservés © 2026 Nathan Ratté.** Le code est
_source-available_ (visible et exécutable pour évaluation personnelle non
commerciale) mais **pas open source** : sa réutilisation, redistribution ou
modification est interdite sans autorisation écrite. Voir [`LICENSE`](LICENSE).
