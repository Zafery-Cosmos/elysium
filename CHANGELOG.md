# Journal des modifications d'Elysium

Toutes les évolutions notables d'Elysium sont consignées ici.

## Non publié

### Licence

Elysium passe sous **licence MIT** : le code peut être utilisé, modifié et redistribué, y compris à des fins commerciales, à condition de conserver la notice de licence. Le changement s'applique à partir de ce commit, les versions déjà publiées restent sous la licence qu'elles contenaient. La licence ne donne aucun droit sur le nom « Elysium » ni sur son logo.

## Version 1.5.1

Publiée le 8 novembre 2026, juste après la 1.5.0. Cette version ajoute le tutoriel interactif et range les modèles par mode de connexion ; elle ne change ni le moteur ni les contrôles de sécurité.

### Tutoriel interactif après la connexion

Une fois connecté (ou après avoir passé la connexion), Elysium ouvre une visite guidée en sept étapes. Elle manipule de **faux éléments** : rien n'est envoyé à une IA, rien n'est écrit sur le disque.

1. **L'équipe** : les huit agents et les trois principes (vous décrivez, vous décidez, tout est annulable).
2. **Une fausse conversation** : la phrase se tape toute seule, vous cliquez sur Envoyer, la réponse du chef de projet arrive mot à mot et l'indicateur de compréhension monte.
3. **Les modes** : Discuter, Plan, Éditer, puis Simple, Expert Analyse et Expert Complet, avec ce que chacun fait.
4. **Un faux plan** : Valider fait avancer les tâches une à une, Refuser les retire.
5. **Un faux diff** : Appliquer, puis Annuler, avec les contrôles que fait le cœur Rust avant d'écrire.
6. **Le choix du modèle**, rangé par mode de connexion.
7. **Le reste de l'application** : aperçu, mémoire, administration, outils MCP, bouton Arrêter.

Le tutoriel se ferme avec Échap ou « Passer le tutoriel », les flèches changent d'étape, et il respecte le réglage des animations (en mouvement réduit, chaque scène saute à son état final). Il est traduit en français, anglais et espagnol et se rejoue depuis Réglages › Général.

### Modèles rangés par mode de connexion

Le sélecteur de modèle du chat range maintenant les fournisseurs en trois groupes, dans cet ordre : **Abonnement (OAuth)** (Claude Code, Codex), **API (clé)** et **Local** (Ollama, LM Studio). Dans un groupe, les fournisseurs configurés passent en premier. Les listes de modèles de Réglages › IA et de la page Agents utilisent le même rangement.

### Corrigé

- **Aperçu : un serveur qui ne répond pas laissait voir un PID périmé.** Quand le serveur de développement d'un projet ne répondait pas dans le délai, Elysium le tuait bien, mais annonçait l'échec avant d'effacer son identifiant de processus. Pendant ce court intervalle, l'aperçu apparaissait en échec tout en pointant vers un processus qui n'existait plus. L'identifiant est maintenant libéré avant l'annonce de l'échec. Ce défaut faisait échouer par intermittence un test sur la machine de CI Linux.

## Version 1.5.0

Préparée le 8 novembre 2026, à partir de la version 1.1.2.

Cette version est la plus importante publiée à ce jour. Elle a deux volets. Le premier est un audit complet du logiciel : sécurité, stabilité, interface, chat, orchestrateur, mémoire, aperçu, base de données et dépendances. Tous les défauts confirmés ont été corrigés à la racine, et chaque correction importante est couverte par un test. Le second volet termine les fonctions qui manquaient ou qui n'avaient aucun effet réel : le mode Expert Complet, les outils MCP utilisés par les agents, le bouton d'arrêt, le tableau des tâches, PostgreSQL depuis l'interface, et une longue liste de réglages et de contrôles qui ne faisaient rien.

En résumé :

- Les agents peuvent désormais modifier vos projets, sous votre contrôle, fichier par fichier.
- Les agents peuvent utiliser les outils de vos serveurs MCP, avec votre accord à chaque appel.
- Un travail en cours peut être arrêté à tout moment.
- Elysium peut enregistrer ses données sur un serveur PostgreSQL, en reprenant vos données locales.
- De nombreuses failles et pannes ont été corrigées, dont plusieurs qui rendaient des fonctions centrales inutilisables.

## Nouveautés

### Mode Expert Complet

Le mode Expert Complet n'est plus grisé. L'équipe d'agents réalise maintenant les tâches du plan et propose de vrais fichiers, que vous relisez avant toute écriture.

Le principe de sécurité est simple : **un modèle ne peut jamais écrire sur votre disque**. Un agent décrit dans sa réponse les fichiers qu'il veut créer, remplacer ou supprimer. Ces descriptions deviennent des propositions enregistrées, sans aucune écriture. C'est vous qui décidez ensuite, fichier par fichier.

Déroulement d'un run Complet :

1. Vous reliez le projet à un dossier. Si ce n'est pas encore fait, Elysium vous le demande directement dans la conversation, sans changer de page, et votre message n'est pas perdu.
2. Elysium met à jour sa carte des fichiers du projet. Les fichiers inchangés ne sont pas relus.
3. Chaque agent reçoit la liste des fichiers et le contenu des plus pertinents pour sa tâche, marqués comme de simples données à analyser.
4. Les agents autorisés à écrire proposent leurs fichiers. Les autres donnent un résultat écrit qui sert à leurs collègues.
5. Un bandeau indique le nombre de fichiers à relire. La revue affiche les différences ligne par ligne, avec les lignes ajoutées et retirées.
6. Vous acceptez ou refusez chaque fichier, ou vous acceptez tout d'un coup.
7. Un changement appliqué reste annulable, et l'annulation restaure le fichier d'origine à l'octet près, fins de ligne comprises.

Plusieurs détails rendent ce fonctionnement fiable :

- Si un agent propose le même fichier deux fois dans un run, vous n'avez qu'une seule revue, avec la dernière version.
- Une tâche suivante voit ce que les tâches précédentes ont proposé, même si ce n'est pas encore écrit sur le disque.
- Une proposition identique au fichier existant est ignorée.
- Si le fichier a changé sur le disque depuis la proposition, l'écriture est refusée au lieu d'écraser votre travail, et un message l'explique.
- Si un fichier est proposé en dehors du projet, ou s'il est protégé, la proposition est refusée et le motif est affiché dans la conversation.

Les chemins sont vérifiés deux fois, par le moteur puis par le broker Rust. Sont refusés : les chemins absolus ou qui remontent hors du projet, les dossiers `.git`, `.ssh`, `.aws`, `.gnupg`, `.venv` et `node_modules`, les fichiers `.env` (sauf `.env.example` et équivalents), les clés privées, les noms réservés de Windows, les flux de données alternatifs, et les variantes comme `.git.` que Windows traite comme `.git`.

### Le broker Rust écrit enfin les fichiers

Le broker de permissions Rust existait, mais aucune partie de l'application ne l'utilisait. Il est désormais le seul chemin d'écriture du mode Complet, grâce à une nouvelle commande `fs_apply_change`.

Pour chaque fichier accepté, le broker :

- vérifie que le dossier a bien été autorisé par vous dans le sélecteur natif de la session ;
- refuse les fichiers protégés, y compris lorsqu'un lien tente d'y mener ;
- compare l'empreinte SHA-256 du fichier sur le disque avec celle de la version relue ;
- écrit à travers un fichier ouvert et vérifié, ce qui ferme la fenêtre entre contrôle et écriture ;
- consigne chaque décision, autorisation comme refus, dans le journal d'audit.

Le moteur Python ne possède aucune route capable d'écrire dans un projet. Après un redémarrage de l'application, le dossier vous est redemandé une seule fois avant la première écriture.

### Outils MCP utilisés par les agents

Les serveurs MCP installés ne servaient qu'à être testés. Les agents peuvent maintenant s'en servir pendant un run Expert, avec tous les fournisseurs, y compris les abonnements Claude Code et Codex.

Quand un agent a besoin d'un outil, le travail se met en pause et une carte apparaît dans la conversation. Elle indique l'agent, le serveur, l'outil et les arguments exacts. Rien ne s'exécute avant votre décision.

Garanties mises en place :

- Chaque appel demande votre accord individuel. Il n'existe pas d'autorisation globale.
- Sans réponse sous dix minutes, l'appel est refusé.
- Le bouton mis en avant n'est jamais le seul choix proposé : Refuser vient en premier.
- Seuls les agents dont la permission Réseau est active se voient proposer des outils.
- Seuls les serveurs activés sont proposés, et uniquement les outils trouvés lors de leur dernier test réussi.
- Un agent ne peut pas demander un outil qui ne figure pas dans cette liste.
- Les arguments affichés sont masqués s'ils contiennent des secrets.
- Le résultat d'un outil est transmis à l'agent comme une donnée à analyser, jamais comme une instruction, et sa taille est limitée.
- Un agent peut enchaîner au maximum cinq appels par tâche.
- Les serveurs lancés pour un run sont arrêtés à sa fin, avec leurs processus enfants.

Un interrupteur « Disponible pour les agents » a été ajouté sur chaque carte de serveur MCP. La fonction existait dans le moteur, mais aucun contrôle ne permettait de l'utiliser.

### Bouton Arrêter

Pendant qu'un agent travaille, le bouton d'envoi devient un bouton d'arrêt. Il fonctionne en mode Simple comme en mode Expert.

- Le texte déjà écrit par l'agent reste dans la conversation.
- Les résultats des tâches terminées sont conservés.
- Les tâches inachevées retournent dans la colonne À faire.
- Les processus lancés pour la réponse sont arrêtés.
- La saisie se débloque immédiatement.

### Tableau des tâches

Le moteur savait créer, modifier et supprimer des tâches, mais l'interface n'offrait aucun tableau, alors qu'un message d'erreur invitait à « corriger sur le tableau ». Un bouton Tâches ouvre maintenant un tableau à quatre colonnes : À faire, En cours, Terminées et Bloquées.

Vous pouvez y ajouter une tâche, choisir l'agent responsable, changer un état, supprimer une tâche, et voir pourquoi une tâche est bloquée. Remettre une tâche à faire permet aussi de la relancer.

### PostgreSQL depuis les Réglages

Une section Base de données a été ajoutée aux Réglages. Elle montre la base utilisée et permet de :

- tester une connexion avant de l'enregistrer ;
- utiliser un serveur PostgreSQL à la place de la base locale ;
- copier automatiquement vos données actuelles vers ce serveur ;
- revenir à la base locale à tout moment.

L'adresse complète, qui contient le mot de passe, est conservée dans le trousseau du système. Elle n'est jamais renvoyée à l'interface, qui affiche seulement l'utilisateur, le serveur et le nom de la base.

La copie ne s'effectue que vers une base vide, car fusionner deux historiques risquerait d'en abîmer un. Elle se fait dans une seule transaction, et les compteurs automatiques sont remis au bon niveau.

Si le serveur enregistré est injoignable au démarrage, Elysium ouvre la base locale et affiche la raison, au lieu de vous empêcher d'entrer dans l'application. Le pilote PostgreSQL est désormais inclus dans les versions distribuées.

Cette fonction a été vérifiée sur un vrai serveur PostgreSQL 17 : création du schéma, copie, refus d'une seconde copie, reprise des données, et fonctionnement de l'API sur ce serveur.

### Autres ajouts

- **Renommer un projet** depuis le menu de la barre latérale.
- **Rétablir les réglages par défaut**, sans toucher aux projets, aux clés ni aux données.
- **Coût des 30 derniers jours** sur le tableau de bord, à la place d'une tuile vide marquée « Bientôt ».
- **Progression réelle des projets** sur le tableau de bord, calculée à partir de leurs tâches terminées.
- **Tâche en cours** affichée sur chaque carte d'agent, à la place d'un texte figé qui disait toujours qu'il n'y en avait aucune.
- **Plan : deux choix de validation.** Vous pouvez faire analyser le plan, sans rien modifier, ou le faire exécuter, avec les fichiers relus un à un.
- **Liens externes** ouverts dans le navigateur du système. Les liens http et https sont les seuls acceptés.

## Sécurité

Aucune faille critique exploitable à distance n'a été trouvée. Les correctifs suivants portent sur des problèmes réels, reproduits lorsque c'était possible.

### Exécution et commandes

- **Aperçu : accord lié au contenu.** Un `package.json` réécrit après votre accord, par un `git pull` par exemple, s'exécutait sans rien redemander. L'accord porte maintenant sur l'empreinte exacte du fichier. S'il change, l'accord est redemandé.
- **Injection de commande sous Windows.** Le caractère `&` dans un nom de modèle ou une valeur de configuration MCP permettait d'exécuter une commande à travers les lanceurs `.cmd`. Les caractères interprétés par l'interpréteur Windows sont maintenant refusés à cet endroit, avec un message clair.
- **Accès au disque.** Une page compromise pouvait s'accorder l'accès à tout le disque. Seuls les dossiers choisis dans le sélecteur natif sont désormais acceptés.
- **Liens symboliques.** Un lien dont la cible n'existe pas permettait d'écrire hors du dossier autorisé. Il est maintenant détecté et refusé.
- **Autorisations imbriquées.** Un sous-dossier en lecture seule devenait inscriptible s'il se trouvait dans un dossier inscriptible. C'est désormais l'autorisation la plus précise qui décide.
- **Fichiers remplacés au dernier moment.** Le broker prouve maintenant que le fichier ouvert est bien celui qui a été autorisé.

### Secrets et confidentialité

- **Masquage des secrets réécrit.** Il laissait passer dix formes courantes sur onze, dont `DB_PASSWORD=`, `AWS_SECRET_ACCESS_KEY=`, les adresses contenant un mot de passe, les authentifications Basic, les JWT, les clés Stripe et les clés PEM tronquées. Le JSON reste valide après masquage, et le temps de traitement est borné.
- **Mode 100 % local.** Il reposait sur une simple case. Une adresse publique déclarée comme locale passait, et un proxy pouvait capter les requêtes. L'adresse est maintenant vérifiée, et les proxys sont ignorés pour les fournisseurs locaux.
- **Sélecteur de modèle.** En mode 100 % local, les modèles distants ne peuvent plus être choisis.
- **Serveurs MCP.** Les secrets restaient dans le trousseau après la désinstallation, et le champ manuel « Secret » était stocké en clair. Les deux problèmes sont corrigés.
- **Noms de fournisseurs.** Un nom bien choisi pouvait écraser un secret MCP dans le trousseau. Les noms sont validés, et l'adresse doit être http ou https.

### Accès au moteur

- **Jeton vide.** Un jeton de session vide était accepté et ouvrait toutes les routes. Il est refusé au démarrage et à la comparaison.
- **DNS rebinding.** L'en-tête `Host` est maintenant contrôlé.
- **Schéma de l'API.** Il n'est plus accessible publiquement.
- **Couverture de l'authentification.** Un test parcourt désormais toute la table des routes.

### Aperçu et contenu

- Un fichier `index.html` en lien symbolique permettait de lire un fichier hors du projet.
- La liste des fichiers d'un dossier exposait `.env` et `.git`. Elle est désactivée.
- Les noms de fichiers, les titres et les résultats d'agents étaient insérés sans délimitation dans les instructions envoyées aux modèles. Ils sont maintenant marqués comme des données, ce qui réduit les risques d'injection de consignes.

### Dépendances

`react-router` passe à la version 7.18.5 pour corriger un avis de sécurité. Les dépendances embarquées dans l'application ne présentent aucun avis connu.

## Corrections de bugs

### Agents

- **Activer un agent ou changer ses permissions échouait toujours.** Toutes les requêtes étaient rejetées, alors que les Réglages affichaient le changement comme réussi. C'était le défaut le plus grave de l'application.
- **Les permissions des agents ont maintenant un effet réel.** La permission Fichiers décide de ce qu'un agent peut lire et proposer, et la permission Réseau décide de l'accès aux outils MCP.
- **Le chef de projet ne peut plus être désactivé par erreur.** L'interrupteur laissait croire qu'il pouvait être coupé, alors qu'il répond à chaque message.

### Chat

- Rouvrir une conversation rejouait le passé : ancien plan reproposé, anciennes erreurs, réponse en cours effacée.
- Un flux coupé restait mort et bloquait la saisie indéfiniment. Il se reconnecte maintenant et reprend au bon endroit.
- Un message pouvait partir dans le mauvais projet, et les messages d'un projet pouvaient apparaître dans un autre.
- Un double envoi lançait deux réponses en parallèle.
- Un message qui n'a pas pu partir était perdu. Il revient maintenant dans la zone de saisie.
- La touche Entrée pendant la saisie d'un accent envoyait le message.
- Le défilement était forcé pendant une réponse.
- Les blocs techniques destinés au moteur ne s'affichent plus pendant la réponse d'un agent.
- La jauge de compréhension ne monte plus artificiellement à chaque événement. Elle reflète seulement la couverture réellement mesurée.

### Orchestrateur et mode Expert

- Supprimer une tâche pendant un run faisait planter tout le run, sans événement de fin.
- Une même tâche pouvait être exécutée deux fois depuis deux conversations. Un seul run par projet est maintenant possible.
- Une réponse tronquée était considérée comme une réussite et servait de base aux tâches suivantes. Elle bloque maintenant la tâche.
- Après un arrêt brutal, un agent restait affiché « en réflexion » pour toujours, et ses tâches restaient en cours.
- Les résultats du mode Expert disparaissaient du fil à la fin du run. Ils sont enregistrés.
- Une tâche dont la dépendance a échoué est signalée comme bloquée, avec la raison.
- Les dépendances circulaires sont refusées.
- Le mode Plan fonctionne maintenant en Expert. Auparavant, l'équipe tentait d'exécuter un graphe de tâches inexistant.
- Lancer l'équipe alors que tout est terminé affiche maintenant une explication au lieu de ne rien faire.
- Un plan inutilisable n'efface plus le plan précédent, et la taille des plans est limitée.

### Réglages sans effet en mode Expert

Une grande partie des réglages n'était appliquée qu'en mode Simple. Le mode Expert respecte désormais :

- la mise en cache des prompts ;
- le niveau d'effort, par défaut ou choisi dans le sélecteur ;
- la langue de réponse des agents, qui ne s'appliquait qu'au chef de projet ;
- le modèle choisi pour le message ;
- le modèle par défaut lorsque le routage automatique est désactivé.

Un agent auquel vous avez attribué un modèle précis garde toujours ce modèle.

### Mémoire

- Un import inhabituel comme `import x from "."` faisait échouer toute l'analyse d'un projet.
- Un fichier piégé de 200 Ko gelait l'analyse pendant 75 secondes. Les expressions utilisées sont maintenant bornées.
- Changer de dossier mélangeait deux cartes de fichiers.
- Les jonctions Windows étaient suivies.
- Le graphe de fichiers restait flou après un changement d'écran.

### Aperçu en direct

- Un manifeste invalide provoquait une erreur interne à chaque interrogation. Il est maintenant signalé proprement.
- Le framework restait figé : un site statique devenu projet Vite restait considéré comme statique, et sans demande d'accord.
- La case de confiance restait cochée d'un projet à l'autre.
- Le serveur d'aperçu est maintenant arrêté lorsqu'un projet est supprimé.

### MCP

- Ajouter un serveur personnalisé était toujours refusé à cause de champs incorrects.
- Arrêter un serveur laissait ses processus enfants en vie.

### Fournisseurs d'IA

- Un JSON invalide ou une connexion refusée apparaissait comme une erreur interne.
- Un flux coupé en plein milieu était pris pour une réponse complète.

### Base de données et démarrage

- Les clés étrangères étaient ignorées par SQLite. Elles sont maintenant appliquées.
- Une clé de réglage obsolète provoquait une erreur sur la page Réglages et sur chaque message.
- Les valeurs numériques invalides sont refusées.
- Une tâche interrompue par un arrêt du moteur restait en cours pour toujours. Elle est remise en file au démarrage.

### Modales et formulaires

- Chaque frappe dans une modale renvoyait le focus au premier champ, ce qui rendait la saisie très pénible.
- Le focus reste maintenant dans la modale et revient à l'élément d'origine à la fermeture.
- Annuler affichait « enregistré ».
- Un échec de suppression restait silencieux.
- Un menu ne pouvait pas être refermé avec le bouton qui l'avait ouvert.

### Contrôles et liens

- Les liens Documentation et Code source pointaient vers la page d'accueil de GitHub. Ils mènent maintenant au projet.
- Les liens externes ne s'ouvraient pas de manière fiable dans la fenêtre de l'application.
- Une commande refusée par le système pouvait être envoyée une seconde fois. Elle ne l'est plus, ce qui est indispensable pour les écritures.
- Une méthode qui appelait une route inexistante a été retirée.

## Interface

L'interface a été mesurée sur 10 pages, 7 tailles d'écran et 2 thèmes, soit 140 écrans, avant et après les corrections.

- **Contraste :** 70 écrans présentaient des textes secondaires trop peu lisibles. Après correction, il n'y en a plus aucun.
- **Débordements :** aucun débordement horizontal, aucun élément coupé, aucune erreur dans la console sur les 140 écrans.
- **Jauge de compréhension :** elle apparaissait pleine à 0 % dans le thème sombre.
- **En-tête de l'aperçu :** avec les panneaux ouverts, le titre s'empilait lettre par lettre et les boutons étaient coupés.
- **Titres :** ils étaient tronqués sur les fenêtres de 960 pixels.

### Traductions

Le changement de langue ne s'appliquait pas partout. Les pages Projets et MCP, l'accueil, la fenêtre de mise à jour et le diagnostic du moteur sont maintenant traduits en français, en anglais et en espagnol. Toutes les nouveautés de cette version le sont aussi.

## Métadonnées et distribution

- Les fichiers de configuration indiquaient les licences MIT et Apache, en contradiction avec la licence propriétaire du projet. Ils ont été alignés.
- La mention « open source » a été retirée de l'interface.
- Le pilote PostgreSQL est ajouté à la compilation de la version distribuée.
- L'installeur Windows revient au modèle standard, avec seulement le logo d'Elysium.
- La documentation technique et le README décrivent maintenant les nouvelles routes, le mode Complet et le fonctionnement des outils MCP.

## Changements de comportement à connaître

Après la mise à jour :

- **Aperçu :** chaque dossier redemandera votre accord une fois, car l'accord est maintenant lié au contenu du manifeste.
- **Réponses tronquées :** une tâche dont la réponse est coupée passe en « bloquée » au lieu d'être marquée terminée.
- **Lanceurs `.cmd` sous Windows :** un argument contenant `&` ou un caractère équivalent est refusé avec un message clair.
- **Mode Plan en Expert :** ce choix produit un plan, il ne lance plus l'équipe.
- **Mode Complet :** il exige un dossier relié au projet.
- **Écriture de fichiers :** elle n'est possible que dans l'application de bureau, car elle passe par le broker.
- **PostgreSQL :** un changement de base prend effet au prochain démarrage.

## Base de données

Une migration ajoute la table `file_changes`, qui contient les fichiers proposés et leur version d'origine. Une autre ajoute le suivi de l'accord d'aperçu. Ces migrations sont uniquement additives : aucune donnée existante n'est modifiée ni supprimée. Elles s'appliquent automatiquement au démarrage.

## Qualité et vérifications

| Vérification | Avant cette version | Après |
|---|---|---|
| Tests du moteur Python | 348 | **543 réussis** |
| Tests de l'interface | 30 | **56 réussis** |
| Tests du broker Rust | non exécutables | **24 réussis** |
| Types TypeScript, ESLint, compilation | OK | OK |
| `cargo fmt` et Clippy sans avertissement | OK | OK |
| Avis de sécurité sur les dépendances embarquées | 1 | **0** |

Vérifications réelles menées en plus des tests :

- le mode Complet, la revue des fichiers, l'annulation, un outil MCP réel, le bouton Arrêter, le tableau des tâches et les nouveaux réglages, dans un vrai navigateur avec le moteur réel et un fournisseur simulé ;
- le flux du chat, la réouverture d'une conversation, le double envoi et l'aperçu statique, dans les mêmes conditions ;
- PostgreSQL 17 sur un serveur temporaire isolé ;
- les règles de chemin du broker sur de vraies jonctions Windows ;
- les 140 écrans de l'interface.

Tests existants modifiés, et pourquoi :

- Les tests qui exigeaient le refus du mode Complet vérifient maintenant son vrai comportement, puisqu'il existe.
- Le test de migration attend la nouvelle version du schéma.
- Le test du flux tient compte du marqueur de fin d'historique.
- Le client de test utilise un hôte autorisé, car l'en-tête `Host` est maintenant contrôlé.

## Limites connues

Ces points n'ont pas pu être vérifiés ou restent à faire :

- L'application empaquetée n'a pas été lancée dans sa vraie fenêtre. Dans le navigateur, les appels au broker étaient simulés, et le code du broker a été testé séparément.
- `cargo test` complet et les tests propres à Linux et macOS doivent passer en intégration continue.
- Les vrais fournisseurs d'IA et les vrais CLI n'ont pas été appelés pendant ces tests.
- Les agents ne peuvent pas exécuter de commandes. La permission Terminal reste sans effet tant que le terminal supervisé n'existe pas.
- Les serveurs MCP distants en HTTP ne sont pas pris en charge. Une passerelle locale reste possible.
- Un projet ne donne accès qu'à une seule conversation dans l'interface.
- Le plafond de budget du mode Expert s'applique à chaque run, et non de manière cumulée.
- Les outils de développement (Vitest, Vite, ESLint) font l'objet d'avis de sécurité. Ils ne sont pas inclus dans l'application distribuée, et leur mise à niveau fera l'objet d'un travail séparé.
