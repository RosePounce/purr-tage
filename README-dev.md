# Purr-tage — notes de développement 🐾

**Français** · [English](README-dev.en.md)

Tout ce qu'il faut pour travailler sur le code : installation depuis les
sources, options de la ligne de commande, ajout d'une langue, protocole
réseau, architecture, tests et construction des paquets. Le manuel du joueur —
installation des paquets, règles du jeu et commandes — est dans
[README.md](README.md), et l'inventaire de ce qui existe déjà dans
[docs/fonctionnalites.md](docs/fonctionnalites.md).

---

## Installation depuis les sources

```bash
pip install -r requirements.txt
python main.py
```

Python 3.8 ou plus récent. Aucune autre dépendance que pygame.

> **Python 3.14** — pygame « mainline » ne publie pas encore de paquet
> pré-compilé pour cette version : pip le compile alors depuis les sources et
> le module de polices (SDL_ttf) finit souvent cassé, avec une erreur
> `font module not available`. `requirements.txt` installe donc **pygame-ce**
> à partir de 3.14 — même API, paquets pré-compilés à jour :
>
> ```
> pygame==2.6.1   ; python_version <  "3.14"
> pygame-ce>=2.5.8 ; python_version >= "3.14"
> ```
>
> Si vous aviez déjà installé pygame à la main, nettoyez d'abord :
> `pip uninstall -y pygame pygame-ce && pip install -r requirements.txt`.
>
> Le jeu bascule par ailleurs tout seul sur `pygame.ftfont` (le moteur de
> polices FreeType embarqué) si `pygame.font` est indisponible, et affiche la
> marche à suivre si aucun des deux ne répond.

---

## Options de la ligne de commande

```bash
python main.py --direct                 # démarrer sans passer par le menu
python main.py --difficulty tiger       # kitten | tomcat | tiger
python main.py --seed 1234              # rejouer exactement la même carte
python main.py --no-fog                 # désactiver le brouillard de guerre
python main.py --no-sound               # couper le son
python main.py --fullscreen             # plein écran
python main.py --resolution 2880x1800   # rendu natif à cette résolution
python main.py --language en            # forcer la langue (fr | en | …)
```

---

## Ajouter une langue

Une langue, c'est un fichier. Copiez `purrtage/locales/fr.json` — la langue de
référence — sous le code ISO 639-1 voulu, puis traduisez les textes sans
toucher aux clés :

```bash
cp purrtage/locales/fr.json purrtage/locales/es.json
python main.py --language es
```

Le fichier est relu au démarrage et la langue apparaît d'elle-même dans le
bouton **Langue** : il n'y a aucune liste à tenir à jour dans le code.

Quelques règles :

* `language.code` et `language.name` sont obligatoires ; le nom s'écrit dans
  la langue elle-même (« Español »), c'est lui qu'affiche le bouton.
* Les champs entre accolades — `{name}`, `{count}` — doivent être conservés
  tels quels ; leur ordre dans la phrase, lui, est libre.
* `app.title` et `menu.title` portent le nom du jeu : gardez « Purr-tage »,
  c'est la marque ; la seconde moitié, elle, se traduit (« The Cat War »,
  « La Guerre des Chats »).
* Les clés `one` / `other` portent le singulier et le pluriel.
* `units.*.gender` et `buildings.*.gender` valent `"m"` ou `"f"` : le français
  s'en sert pour accorder « terminé » / « terminée ». Une langue sans accord
  met `"m"` partout et donne deux fois la même phrase.
* Les textes découpés en listes (`guide.goal_lines`, `help.sections`) sont
  affichés ligne par ligne : c'est le traducteur qui décide des retours.
* Une clé oubliée est reprise du français plutôt que de laisser un trou ;
  `python -m unittest tests.test_i18n` signale celles qui manquent.

Pour traduire sans reconstruire le jeu, le même fichier peut être déposé dans
`locales/` à l'intérieur du dossier de données (celui qu'affiche
`python main.py --verification`) : il a priorité sur celui qui est livré.

---

## Comment la partie reste synchrone

Le jeu fonctionne en **pas verrouillé** : rien de l'état de la partie ne
circule, seulement les ordres. Chaque machine simule la même partie à partir
de la même carte — la même graine, ou les mêmes octets pour une carte de
l'éditeur — et rejoue les ordres des deux joueurs.

Le temps est découpé en tours d'un dixième de seconde. Un ordre donné pendant
le tour T s'exécute au tour T+2, au même instant des deux côtés : ce léger
report est ce qui laisse aux paquets le temps d'arriver, et c'est pourquoi un
clic met un dixième de seconde à prendre effet. Une machine n'avance jamais un
tour sans les ordres de l'autre ; si le réseau hoquette, les deux attendent
ensemble plutôt que de diverger, et un bandeau « En attente de l'adversaire »
s'affiche.

Chaque tour transporte en plus une empreinte de la simulation. Si les deux
machines calculaient des parties différentes, l'écart serait signalé au lieu
de passer inaperçu.

Cela n'a de sens que si la simulation est strictement reproductible. Elle
avance par pas fixes de 1/30 s, n'utilise aucun tirage aléatoire global,
n'emploie que `math.sqrt` (seule fonction dont la norme IEEE 754 impose
l'arrondi, contrairement à `math.hypot` ou aux fonctions trigonométriques), et
renumérote ses entités à chaque partie. Deux parties lancées avec les mêmes
ordres donnent la même empreinte, bit pour bit.

---

## L'envoi des rapports de bogue

Le jeu ne parle qu'à un relais, un Cloudflare Worker décrit dans
[`relay/`](relay/README.md), qui transmet ensuite à GitHub, Discord ou par
e-mail. Son adresse est `BUG_REPORT_URL`, dans `purrtage/settings.py`.

Lancé depuis les sources, le jeu n'envoie rien : les essais et la suite de
tests ne doivent pas remplir le salon des rapports. Pour essayer l'envoi,
on désigne le relais à la main :

```bash
PURRTAGE_REPORT_URL=https://purr-tage.rose-pounce.workers.dev/report python main.py
```

Chaque tentative est notée dans `saves/bug/send.log` — envoyé, gardé faute de
réseau, refusé — avec la réponse du relais.

Le dossier [`relay/`](relay/README.md) est **réservé** : le relais du jeu
tourne sur le compte Cloudflare de RosePounce, ses secrets n'y sont pas, la
vérification *Relay guard* refuse toute pull request qui y touche et
`.github/CODEOWNERS` en réserve la revue. Contribuer au jeu ne demande jamais
d'y toucher ; pour essayer l'envoi, on déploie son propre relais depuis son
fork et on le désigne par `PURRTAGE_REPORT_URL`, comme ci-dessus.

---

## Sous le capot

```
main.py                point d'entrée (arguments de ligne de commande)
purrtage/
  settings.py          toutes les constantes et l'équilibrage, au même endroit
  i18n.py              langues : chargement, repli, choix retenu
  locales/*.json       un fichier par langue (fr, en, …)
  world.py             la carte : génération procédurale (bruit de valeur,
                       lacs, gisements) à chaque taille, carte vierge
  mapfile.py           format binaire des cartes, fichiers, contrôles
  editor.py            éditeur de cartes : terrain, ressources, bases
  pathfinding.py       A* 8 directions + lissage de trajectoire « corde tendue »
  entities.py          unités (machine à états), bâtiments, projectiles, effets
  player.py            trésorerie, population, améliorations
  ai.py                adversaire : économie, ordre de construction, assauts
  game.py              simulation, ordres, sélection, conditions de victoire
  render.py            rendu du monde, brouillard, interpolations
  sprites.py           tout l'art, dessiné en code et mis en cache
  ui.py                barre de ressources, minimap, panneau d'actions
  screens.py           menu, pause, aide, écran de fin
  camera.py            défilement, zoom, conversions écran ↔ monde
  commands.py          ordres sérialisables : ce qui circule sur le réseau
  net.py               transport TCP + annonce UDP sur le réseau local
  lockstep.py          tours, report des ordres, détection de divergence
  layout.py            mise à l'échelle de l'interface selon la résolution
  fog.py               brouillard de guerre (exploré / visible)
  audio.py             sons synthétisés (miaulements, impacts, fanfares)
  bugreport.py         rapports de bogue : contexte, capture, écriture
  bugsend.py           envoi des rapports au relais, boîte d'envoi, send.log
  fonts.py             chargement des polices avec repli sur FreeType
tests/test_core.py     pathfinding, économie, combat, rapports de bogue…
tests/test_i18n.py     traductions : clés manquantes, champs {…}, mise en page
tests/test_net.py      pas verrouillé : ordres, tours, divergence
relay/                 le relais des rapports de bogue (Cloudflare Worker,
                       dossier réservé : voir relay/README.md)
```

Quelques choix techniques :

* **Zéro asset.** Les chats sont dessinés en suréchantillonnage ×3 puis réduits
  avec `smoothscale`, ce qui lisse les contours sans bibliothèque d'images.
* **Aucun texte dans le code.** `settings.py` ne garde que les identifiants ;
  les étiquettes vivent dans `purrtage/locales/` et sont relues à chaque
  affichage, ce qui permet de changer de langue sans relancer la partie.
* **Interface en unités**, converties en pixels par `Layout` : une seule
  constante décrit un espacement, quelle que soit la résolution.
* **Brouillard appliqué après la mise à l'échelle**, sur une grille d'un pixel
  par tuile rafraîchie 5 fois par seconde. L'image agrandie ne dépend que du
  bloc de tuiles visible, donc elle est mise en cache : c'était le poste le
  plus coûteux du rendu (9,6 ms par image en 2880×1800).
* **Paliers de zoom filtrés** selon la résolution : un dézoom qui afficherait
  plus que la carte entière, ou dont la surface intermédiaire dépasserait le
  budget de pixels, est simplement retiré.
* **Calculs de chemin budgétés** (16 par image) pour éviter les à-coups quand
  on donne un ordre à 40 chats d'un coup.
* **Distances au rectangle** pour les bâtiments : un chat « arrive » au bord de
  l'empreinte, pas au centre.

Mesuré en rendu purement logiciel (sans GPU), 168 unités en pleine bataille,
caméra en défilement :

| Résolution | Sprites | Zoom normal | Zoom arrière max |
|---|---|---|---|
| 1280 × 760 | ×1 | 138 fps | 102 fps |
| 1920 × 1080 | ×1,5 | 81 fps | 50 fps |
| 2880 × 1800 | ×2 | 47 fps | 37 fps |

Sur une machine réelle le résultat est meilleur : ici le GPU n'est pas
sollicité du tout.

### Lancer les tests

```bash
python -m unittest discover -s tests -v
```

### Construire les paquets

```bash
pip install pyinstaller pillow
python packaging/make_icon.py                      # icône, dessinée par le jeu
pyinstaller --noconfirm --clean --distpath dist \
            --workpath build/pyi packaging/purrtage.spec
./dist/Purrtage/Purrtage --verification                # auto-test du paquet
bash packaging/linux/make_appimage.sh 1.0.0        # Linux
```

Sous Windows, le `.exe` se transforme en installeur avec Inno Setup :
`iscc /DVersion=1.0.0 packaging\windows\installer.iss`.

`--verification` lance une vraie partie, dessine quelques secondes, enregistre
une capture puis quitte. Un paquet qui ne sait ni générer sa carte, ni charger
ses polices, ni dessiner échoue là plutôt que chez le joueur — c'est ce que la
chaîne d'intégration exécute après chaque construction.

PyInstaller ne compile pas en croisé : le `.exe` ne peut être fabriqué que sur
Windows. D'où deux chaînes d'intégration :

| Chaîne | Déclenchement | Ce qu'elle fait |
|---|---|---|
| `tests.yml` | chaque poussée et pull request | la suite de tests, en une quinzaine de secondes |
| `packages.yml` | **tag `v*`** | les deux installeurs, puis la release définitive |
| `packages.yml` | **Run workflow** sur `main` | idem, la release étant tagguée depuis `__version__` |
| `packages.yml` | **Run workflow** sur `develop` | idem, mais en **pré-release** de test |

Pour une version définitive, le tag reste la façon la plus simple :

```bash
git tag v1.0.0 && git push --tags
```

Les paquets sont alors construits sur Windows et sur Linux, chacun lancé et
auto-vérifié, puis attachés à la release.

Rien ne se déclenche sur une simple poussée : construire deux installeurs à
chaque commit ne servirait à rien. Pour une **release de test**, passez par
**Run workflow** dans l'onglet Actions en choisissant la branche `develop` :
le numéro devient `<version>-dev.<n° d'exécution>`, donc un tag par
exécution, et la release est marquée *pre-release* — GitHub continue d'afficher
la dernière version définitive comme *latest*. Le champ **version** du
formulaire permet au besoin de forcer un numéro (`1.1.0-rc1`).

Un garde-fou refuse un numéro déjà publié : lancé sur `main` sans que
`__version__` ait été incrémenté depuis la dernière release, le workflow
s'arrête avec le message qui le dit, plutôt que d'écraser un tag existant.

### Exporter les sprites en SVG

```bash
python packaging/export_svg.py                     # dans build/svg/
python packaging/export_svg.py presse/ --team 1
```

Les chats, les bâtiments, les gisements et le décor sortent en SVG — pratique
pour une capture de presse, une page web ou un autocollant, sans jamais
dépendre d'une résolution.

C'est possible parce que l'art est déjà vectoriel : `sprites.py` ne peint que
des ellipses, des cercles, des rectangles arrondis, des polygones et des
lignes, à travers un petit peintre interne. L'export ne redessine donc rien,
il remplace ce peintre par un enregistreur qui écrit du SVG et laisse le code
de dessin tourner tel quel — un seul endroit où l'art est décrit, et un test
qui échoue si le peintre du jeu gagne une primitive que l'export ne connaît
pas.

Les tuiles de terrain font exception : elles sont peintes pixel par pixel, et
un SVG d'un élément par pixel n'aurait aucun intérêt.

---

## Pistes d'évolution

* murs et portes, formations, unités montées (chats sur Roomba)
* plusieurs adversaires et parties en équipe
* sauvegarde / chargement de partie
* plus de deux bases par carte, une fois les parties à plusieurs en place
