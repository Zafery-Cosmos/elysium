"""Curated marketplace catalog of well-known MCP servers.

Static data only: installing an entry persists a row in ``mcp_servers``
(``url_or_command`` = the install hint command).  The runtime MCP client —
actually spawning/connecting to these servers — is a later phase; until then
every privileged action still goes through the Rust permission broker
(ADR-003).  Descriptions, categories and permission notes are in French,
matching the product UI language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

McpTransport = Literal["stdio", "http"]

# Ordered list of catalog categories (French). ``categories()`` returns this;
# the marketplace UI renders sections in this order.
CATEGORIES: Final[tuple[str, ...]] = (
    "Système de fichiers",
    "Développement",
    "Bases de données",
    "Web & recherche",
    "Cloud",
    "Productivité",
    "Mémoire & connaissance",
    "Outils",
)


@dataclass(frozen=True, slots=True)
class McpCatalogEntry:
    catalog_id: str
    name: str
    description: str
    category: str
    transport: McpTransport
    install_hint: str  # command used as url_or_command when installed
    permissions_note: str
    official: bool


CATALOG: Final[tuple[McpCatalogEntry, ...]] = (
    # ------------------------------------------------ Système de fichiers
    McpCatalogEntry(
        catalog_id="filesystem",
        name="Filesystem",
        description="Lecture et écriture de fichiers dans les dossiers que vous autorisez.",
        category="Système de fichiers",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-filesystem <dossier>",
        permissions_note="Accède aux fichiers des dossiers autorisés uniquement.",
        official=True,
    ),
    # ------------------------------------------------------ Développement
    McpCatalogEntry(
        catalog_id="github",
        name="GitHub",
        description="Gestion des dépôts GitHub : issues, pull requests, fichiers et recherche.",
        category="Développement",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-github",
        permissions_note="Nécessite un jeton GitHub ; peut lire et modifier vos dépôts.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="gitlab",
        name="GitLab",
        description="Gestion des projets GitLab : issues, merge requests et fichiers.",
        category="Développement",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-gitlab",
        permissions_note="Nécessite un jeton GitLab ; peut lire et modifier vos projets.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="git",
        name="Git",
        description="Opérations Git locales : historique, diff, commits et branches.",
        category="Développement",
        transport="stdio",
        install_hint="uvx mcp-server-git",
        permissions_note="Lit et modifie les dépôts Git locaux autorisés.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="docker",
        name="Docker",
        description="Gestion des conteneurs, images et volumes Docker locaux.",
        category="Développement",
        transport="stdio",
        install_hint="uvx mcp-server-docker",
        permissions_note="Contrôle le démon Docker local : création et arrêt de conteneurs.",
        official=False,
    ),
    McpCatalogEntry(
        catalog_id="kubernetes",
        name="Kubernetes",
        description="Pilotage d'un cluster Kubernetes : pods, déploiements et logs.",
        category="Développement",
        transport="stdio",
        install_hint="npx -y mcp-server-kubernetes",
        permissions_note="Utilise votre kubeconfig ; peut modifier les ressources du cluster.",
        official=False,
    ),
    # -------------------------------------------------- Bases de données
    McpCatalogEntry(
        catalog_id="postgres",
        name="PostgreSQL",
        description="Interrogation de bases PostgreSQL : schéma et requêtes SQL en lecture.",
        category="Bases de données",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-postgres <url-connexion>",
        permissions_note="Accès en lecture à la base indiquée par l'URL de connexion.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="mysql",
        name="MySQL",
        description="Interrogation de bases MySQL et MariaDB : schéma et requêtes SQL.",
        category="Bases de données",
        transport="stdio",
        install_hint="npx -y @benborla29/mcp-server-mysql",
        permissions_note="Accès à la base indiquée par les identifiants de connexion.",
        official=False,
    ),
    McpCatalogEntry(
        catalog_id="sqlite",
        name="SQLite",
        description="Interrogation et analyse de fichiers de base SQLite.",
        category="Bases de données",
        transport="stdio",
        install_hint="uvx mcp-server-sqlite --db-path <fichier.db>",
        permissions_note="Lit et écrit dans le fichier de base indiqué.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="mongodb",
        name="MongoDB",
        description="Interrogation de bases MongoDB : collections, documents et agrégations.",
        category="Bases de données",
        transport="stdio",
        install_hint="npx -y mongodb-mcp-server",
        permissions_note="Accès à la base indiquée par la chaîne de connexion.",
        official=False,
    ),
    McpCatalogEntry(
        catalog_id="redis",
        name="Redis",
        description="Lecture et écriture de clés dans une base Redis.",
        category="Bases de données",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-redis <url-connexion>",
        permissions_note="Accès en lecture/écriture à l'instance Redis indiquée.",
        official=True,
    ),
    # ---------------------------------------------------- Web & recherche
    McpCatalogEntry(
        catalog_id="brave-search",
        name="Brave Search",
        description="Recherche web via l'API Brave Search.",
        category="Web & recherche",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-brave-search",
        permissions_note="Nécessite une clé API Brave ; envoie les requêtes au service Brave.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="fetch",
        name="Fetch",
        description="Récupération de pages web et conversion en texte exploitable.",
        category="Web & recherche",
        transport="stdio",
        install_hint="uvx mcp-server-fetch",
        permissions_note="Effectue des requêtes HTTP sortantes vers les URL demandées.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="puppeteer",
        name="Puppeteer",
        description="Automatisation d'un navigateur Chrome : navigation et captures d'écran.",
        category="Web & recherche",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-puppeteer",
        permissions_note="Contrôle un navigateur et peut visiter n'importe quel site.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="playwright",
        name="Playwright",
        description="Pilotage d'un navigateur : navigation, clics, captures d'écran.",
        category="Web & recherche",
        transport="stdio",
        install_hint="npx -y @playwright/mcp@latest",
        permissions_note="Contrôle un navigateur et peut visiter n'importe quel site.",
        official=True,
    ),
    # ---------------------------------------------------------------- Cloud
    McpCatalogEntry(
        catalog_id="aws",
        name="AWS",
        description="Accès aux services AWS : documentation, coûts et ressources.",
        category="Cloud",
        transport="stdio",
        install_hint="uvx awslabs.core-mcp-server",
        permissions_note="Utilise vos identifiants AWS ; peut lire et modifier vos ressources.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="cloudflare",
        name="Cloudflare",
        description="Gestion des ressources Cloudflare : Workers, DNS et analytics.",
        category="Cloud",
        transport="stdio",
        install_hint="npx -y @cloudflare/mcp-server-cloudflare",
        permissions_note="Nécessite un jeton Cloudflare ; peut modifier votre compte.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="sentry",
        name="Sentry",
        description="Consultation des erreurs et problèmes remontés dans Sentry.",
        category="Cloud",
        transport="stdio",
        install_hint="uvx mcp-server-sentry",
        permissions_note="Nécessite un jeton Sentry ; accès en lecture à vos projets.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="grafana",
        name="Grafana",
        description="Consultation des tableaux de bord, alertes et sources de données Grafana.",
        category="Cloud",
        transport="stdio",
        install_hint="docker run -i --rm mcp/grafana",
        permissions_note="Nécessite un jeton Grafana ; accès à vos tableaux de bord.",
        official=False,
    ),
    # --------------------------------------------------------- Productivité
    McpCatalogEntry(
        catalog_id="slack",
        name="Slack",
        description="Lecture des canaux Slack et envoi de messages.",
        category="Productivité",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-slack",
        permissions_note="Nécessite un jeton Slack ; peut lire et publier dans vos canaux.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="notion",
        name="Notion",
        description="Lecture et édition de pages et bases de données Notion.",
        category="Productivité",
        transport="stdio",
        install_hint="npx -y @notionhq/notion-mcp-server",
        permissions_note="Nécessite un jeton Notion ; peut lire et modifier votre espace.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="linear",
        name="Linear",
        description="Gestion des tickets et projets Linear.",
        category="Productivité",
        transport="http",
        install_hint="npx -y mcp-remote https://mcp.linear.app/sse",
        permissions_note="Authentification Linear ; peut lire et modifier vos tickets.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="google-drive",
        name="Google Drive",
        description="Recherche et lecture de fichiers stockés sur Google Drive.",
        category="Productivité",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-gdrive",
        permissions_note="Authentification Google ; accès en lecture à vos fichiers Drive.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="gmail",
        name="Gmail",
        description="Lecture, recherche et envoi d'e-mails via Gmail.",
        category="Productivité",
        transport="stdio",
        install_hint="npx -y @gongrzhe/server-gmail-autoauth-mcp",
        permissions_note="Authentification Google ; peut lire et envoyer des e-mails.",
        official=False,
    ),
    McpCatalogEntry(
        catalog_id="google-calendar",
        name="Google Calendar",
        description="Consultation et création d'événements dans Google Agenda.",
        category="Productivité",
        transport="stdio",
        install_hint="npx -y @cocal/google-calendar-mcp",
        permissions_note="Authentification Google ; peut lire et modifier votre agenda.",
        official=False,
    ),
    # ------------------------------------------------ Mémoire & connaissance
    McpCatalogEntry(
        catalog_id="memory",
        name="Memory",
        description="Mémoire persistante sous forme de graphe de connaissances.",
        category="Mémoire & connaissance",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-memory",
        permissions_note="Stocke des informations localement entre les sessions.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="knowledge-graph",
        name="Knowledge Graph",
        description="Graphe de connaissances persistant avec mémoire par projet.",
        category="Mémoire & connaissance",
        transport="stdio",
        install_hint="npx -y mcp-knowledge-graph",
        permissions_note="Stocke le graphe localement sur le disque.",
        official=False,
    ),
    # -------------------------------------------------------------- Outils
    McpCatalogEntry(
        catalog_id="time",
        name="Time",
        description="Heure courante et conversions de fuseaux horaires.",
        category="Outils",
        transport="stdio",
        install_hint="uvx mcp-server-time",
        permissions_note="Aucun accès sensible : lecture de l'horloge système uniquement.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="everything",
        name="Everything",
        description="Serveur de démonstration exposant tous les types de primitives MCP.",
        category="Outils",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-everything",
        permissions_note="Serveur de test sans accès à des données sensibles.",
        official=True,
    ),
    McpCatalogEntry(
        catalog_id="sequential-thinking",
        name="Sequential Thinking",
        description="Aide au raisonnement structuré étape par étape.",
        category="Outils",
        transport="stdio",
        install_hint="npx -y @modelcontextprotocol/server-sequential-thinking",
        permissions_note="Aucun accès sensible : raisonnement en mémoire uniquement.",
        official=True,
    ),
)

CATALOG_BY_ID: Final[dict[str, McpCatalogEntry]] = {
    entry.catalog_id: entry for entry in CATALOG
}


def categories() -> list[str]:
    """Ordered list of catalog categories for the marketplace UI."""
    return list(CATEGORIES)
