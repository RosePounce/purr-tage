# Les rulesets du dépôt

Deux rulesets, en JSON, prêts à importer. Ce dossier n'est que le dépôt de
leur texte : GitHub ne les lit pas depuis le code, il faut les importer une
fois dans **Settings** > **Rules** > **Rulesets** > **New ruleset** >
**Import a ruleset**, puis les relire à l'écran avant d'enregistrer.

## `main-protection.json` — ce qui protège vraiment `relay/`

Cible `main` et `develop`. Il exige une pull request avec **une revue du
propriétaire du code** (`.github/CODEOWNERS`, qui couvre `/relay/` et
`/.github/`), interdit la suppression de la branche et le `force push`, et
réclame les trois vérifications de l'intégration continue :

| Vérification | Workflow |
|---|---|
| **Relay guard** | `relay-guard.yml` — refuse un changement sous `relay/` |
| **Test suite** | `tests.yml` — la suite de tests Python |
| **Bug report relay** | `tests.yml` — les tests du relais |

C'est ce ruleset qui empêche un autre développeur de faire entrer un
changement dans `relay/` : une pull request qui en touche un fichier échoue à
la vérification *Relay guard* **et** attend une revue que seul le propriétaire
peut donner.

Le `bypass_actors` laisse passer le rôle **Repository admin** — toi — pour que
le dépôt reste utilisable en direct. L'écran d'import affiche le rôle en
clair : vérifie qu'il dit bien « Repository admin » (`actor_id: 5`), et retire
la ligne si tu veux t'imposer la même discipline.

## `relay-off-limits.json` — le verrou dur, sous condition

Un ruleset de type **push** avec la règle *Restrict file paths* sur
`relay/**` : tout push dont le diff touche le dossier est refusé par le
serveur, sur le dépôt **et sur tout son réseau de forks**.

**Il ne fonctionne que sur un dépôt privé ou interne.** La documentation
GitHub est explicite : les push rulesets bloquent les pushes « vers un dépôt
privé ou interne et tout son réseau de forks ». `purr-tage` étant public, cet
import sera refusé ou restera sans effet. Il est gardé ici pour le jour où le
dépôt passerait en privé, ou serait recopié dans une organisation sur l'offre
Team. En attendant, c'est `main-protection.json` + `relay-guard.yml` qui font
le travail.

## Une limite à connaître

Pour un événement `pull_request`, GitHub exécute le workflow tel qu'il est
dans la branche proposée : une pull request qui modifie `relay-guard.yml`
peut donc neutraliser sa propre vérification. C'est pourquoi
`.github/CODEOWNERS` couvre `/.github/` autant que `/relay/` — la revue, elle,
est appliquée par le serveur et ne se contourne pas depuis le contenu d'une
pull request.

## Au lieu de l'écran d'import

Avec `gh` installé et authentifié :

```bash
gh api -X POST repos/RosePounce/purr-tage/rulesets \
       --input .github/rulesets/main-protection.json
gh ruleset list --repo RosePounce/purr-tage
```
