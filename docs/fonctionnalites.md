# Fonctionnalités de Purr-tage

**Français** · [English](fonctionnalites.en.md)

## Jeu

- Stratégie en temps réel entre deux clans de chats : le Clan Moustache contre la Horde Chartreux
- Victoire quand l'adversaire n'a plus de bâtiment de recrutement ni de Chaton pour en reconstruire un
- Écran de fin de partie

## Économie

- 4 ressources : croquettes, laine, herbe à chat, pierre
- Récolte par les Chatons, qui portent 12 unités et les déposent au Panier Royal le plus proche
- Les gisements s'épuisent et rapetissent
- Population limitée par les Paniers et les Cabanes

## Unités

- Chaton : récolte, construit, répare
- Griffeur : combat au corps à corps
- Cracheur : attaque à distance avec des boules de poils
- Matou : unité lourde, bonus de dégâts contre les bâtiments

## Bâtiments

- Panier Royal, Cabane, Griffoir, Dojo
- Tour à Griffes : défense automatique, avec 2 niveaux d'amélioration
- Remparts posés en ligne en glissant la souris
- Construction et réparation par les Chatons, file de production, annulation avec remboursement

## Améliorations au Dojo

- Griffes aiguisées (attaque), Fourrure épaisse (armure et points de vie), Pattes rapides (vitesse)

## Combat

- Attaque, attaque-déplacement, stop
- Un chat enchaîne sur l'ennemi suivant une fois sa cible abattue
- Riposte limitée pour qu'une garnison ne se laisse pas attirer au loin
- Projectiles et effets visuels

## Adversaire IA

- Mêmes règles que le joueur, sans tricher
- Gère son économie, suit un ordre de construction, améliore ses troupes
- Attaque par vagues de plus en plus grosses
- 3 niveaux de difficulté : kitten, tomcat, tiger

## Carte et monde

- Génération procédurale : terrain, lacs, gisements
- 4 tailles : 64, 96, 128 et 160 cases de côté
- Graine reproductible (`--seed`)
- Brouillard de guerre (zones explorées et zones visibles), désactivable
- Recherche de chemin A* sur 8 directions, avec trajectoires lissées

## Contrôles et interface

- Sélection simple, rectangulaire, avec Maj, et par double-clic sur un type d'unité
- Ordre contextuel au clic droit, ordres en file d'attente avec Maj
- Groupes de contrôle (Ctrl + 1 à 9), sélection d'un Chaton inoccupé
- Caméra : flèches, bord de l'écran, molette enfoncée, ZQSD ; 4 niveaux de zoom
- Minimap, barre de ressources, panneau d'actions
- Survol d'un gisement : il est mis en évidence et affiche ce qu'il contient
- Alertes, avec Espace pour centrer dessus
- Pause et vitesse de jeu réglable
- Touches entièrement reconfigurables, bascule AZERTY / QWERTY

## Écrans

- Menu principal, Options, Aide des commandes (F1), page « Comment jouer » (F2), pause

## Multijoueur

- Deux joueurs en réseau local
- Découverte automatique des parties (annonce UDP), ou saisie manuelle de l'adresse
- Simulation en pas verrouillé (lockstep) avec détection des désynchronisations
- Les cartes faites dans l'éditeur sont transmises à l'autre joueur

## Éditeur de cartes

- Peinture du terrain (eau, sable, herbe, prairie, fleurs) avec un pinceau de taille réglable
- Pose des ressources et de leur quantité, placement des deux bases, gomme
- Carte vierge ou aléatoire, ouverture, annulation, enregistrement
- Vérification avant enregistrement : la carte doit être jouable
- Format binaire `.pmap`

## Affichage et son

- Aucun fichier d'image ni de son : sprites dessinés par le code, bruitages synthétisés
- Deux styles de chats : le nouveau, tout en rondeurs, et l'ancien, vu de profil
- S'adapte à toutes les résolutions de 1280×760 à 2880×1800, fenêtre redimensionnable, plein écran
- Sprites redessinés à l'échelle choisie plutôt qu'agrandis

## Langues

- Français et anglais, changement possible en pleine partie, choix retenu
- Ajouter une langue se résume à déposer un fichier JSON

## Outils

- Signalement de bogue avec F8 : description, contexte détaillé et capture d'écran
- Options en ligne de commande (difficulté, graine, résolution, langue, son, etc.)
- Auto-vérification des paquets (`--verification`)
- Export des sprites en SVG
- Installeur Windows et AppImage Linux construits par l'intégration continue
