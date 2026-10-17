# Le relais des rapports de bogue

**Français** · [English](README.en.md)

> **Dossier réservé** — ce relais est celui du jeu : il tourne sur le compte
> Cloudflare de RosePounce et reçoit les rapports des joueurs. Rien ne s'y
> fait pour contribuer au jeu, et une pull request qui touche à `relay/` n'est
> pas fusionnée : la vérification *Relay guard* la refuse et
> `.github/CODEOWNERS` en réserve la revue. Un contributeur n'a de toute façon
> pas à le déployer : lancé depuis les sources, le jeu n'envoie aucun rapport
> ([README-dev.md](../README-dev.md#lenvoi-des-rapports-de-bogue)).
>
> La suite de cette page sert à qui tient le relais du jeu, ou à qui héberge
> le sien sur son propre fork et son propre compte.

Le jeu ne connaît qu'une seule adresse : celle de ce relais. Quand un joueur
envoie un rapport (**F8**), le relais le vérifie, en garde une copie et le
transmet à tous les services branchés :

```
Jeu (F8)  ──HTTPS──>  Relais /report  ──>  GitHub Issues
                          │            ──>  Discord
                          │            ──>  e-mail (Resend)
                          └─ copie dans Workers KV (rapport, capture)
```

Brancher ou débrancher un service se fait sur le relais, sans nouvelle version
du jeu. Aucune clé ne se trouve dans le jeu, dont le code est public.

C'est un [Cloudflare Worker](https://developers.cloudflare.com/workers/),
écrit en JavaScript sans aucune dépendance. Le Worker comme son stockage,
Workers KV, restent dans l'offre gratuite de Cloudflare pour un jeu de cette
taille : 1 Go de stockage et 1 000 écritures par jour, soit plus de 300
rapports quotidiens.

## Mettre le relais en ligne

Il faut un compte Cloudflare, sur l'offre gratuite : aucun moyen de paiement
n'est demandé. Deux façons de faire, au choix.

### Depuis le tableau de bord, sans rien installer

Cloudflare suit le dépôt GitHub et redéploie le relais à chaque push : c'est
la méthode la plus simple quand on travaille sur plusieurs ordinateurs.

1. **Storage & Databases** > **Workers KV** > **Create** : nommer l'espace
   `purrtage-reports`, puis copier son **ID**.
2. Coller cet ID dans `wrangler.toml`, à la place de
   `REPLACE_WITH_THE_NAMESPACE_ID`, puis commiter et pousser. L'ID n'a rien
   de secret.
3. **Workers & Pages** > **Create** > **Import a repository** : choisir le
   dépôt, la branche qui contient `relay/`, et indiquer `relay` comme
   **Root directory**. La commande de déploiement par défaut,
   `npx wrangler deploy`, convient.

Les secrets des services s'ajoutent ensuite dans la page du Worker :
**Settings** > **Variables and Secrets** > **Add**, type **Secret**. Ils sont
conservés d'un déploiement à l'autre. Les réglages publics, eux —
`GITHUB_REPO`, `GITHUB_LABELS`, `REPORT_TTL_DAYS` — sont réécrits à chaque
déploiement depuis `wrangler.toml` : c'est là qu'on les change.

### En ligne de commande

Il faut Node.js 18 ou plus récent, avec npm.

```bash
cd relay
npm install                                    # installe wrangler, l'outil de Cloudflare
npx wrangler login                             # ouvre le navigateur
npx wrangler kv namespace create purrtage-reports   # affiche l'ID à coller dans wrangler.toml
npx wrangler deploy
```

Les secrets s'ajoutent alors avec `npx wrangler secret put`, comme indiqué
pour chaque service ci-dessous.

### Essayer

Le tableau de bord comme `deploy` donnent l'adresse du relais, de la forme
`https://purr-tage.<votre-compte>.workers.dev`.

Avant de toucher au jeu, on l'essaie avec la version de développement :

```bash
PURRTAGE_REPORT_URL=https://purr-tage.<votre-compte>.workers.dev/report python main.py
```

**F8**, un mot, **Entrée** : la fenêtre doit afficher « Envoyé à l'équipe du
jeu. Merci ! ». Une fois l'essai concluant, l'adresse va dans
`BUG_REPORT_URL`, dans `purrtage/settings.py`, et les paquets construits
ensuite enverront leurs rapports.

Sans aucun service branché, le relais garde quand même chaque rapport dans
KV : on peut le déployer d'abord et brancher les services ensuite.

## Brancher les services

Chaque service s'allume dès que ses secrets sont renseignés, et s'éteint quand
on les retire. `wrangler secret put` demande la valeur au clavier : elle ne
passe ni dans l'historique du terminal, ni dans le dépôt.

### GitHub Issues

Un rapport devient une issue du dépôt, avec la capture affichée dedans.

1. GitHub > **Settings** > **Developer settings** > **Fine-grained tokens** >
   **Generate new token**.
2. **Repository access** : uniquement `purr-tage`. **Permissions** :
   **Issues**, en lecture et écriture. Rien d'autre.
3. ```bash
   npx wrangler secret put GITHUB_TOKEN
   ```

Le dépôt et les étiquettes se règlent dans `wrangler.toml` (`GITHUB_REPO`,
`GITHUB_LABELS`). Un jeton a une date d'expiration : à son échéance, les
issues cessent d'arriver, et il faut en générer un nouveau.

### Discord

Un message dans un salon, avec le rapport et la capture en pièces jointes.

1. Paramètres du salon > **Intégrations** > **Webhooks** > **Nouveau
   webhook** > **Copier l'URL du webhook**.
2. ```bash
   npx wrangler secret put DISCORD_WEBHOOK_URL
   ```

Les mentions sont désactivées : un joueur qui écrit `@everyone` ne réveille
personne.

### E-mail

Un e-mail par rapport, avec le rapport et la capture en pièces jointes. Il
passe par [Resend](https://resend.com), dont l'offre gratuite suffit
largement.

1. Créer un compte Resend, y vérifier un nom de domaine, puis créer une clé
   d'API. Sans domaine vérifié, Resend n'accepte d'envoyer qu'à l'adresse du
   compte, depuis `onboarding@resend.dev`.
2. ```bash
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put EMAIL_FROM     # ex. bogues@votre-domaine.fr
   npx wrangler secret put EMAIL_TO       # une ou plusieurs adresses, séparées par des virgules
   ```

Les adresses sont des secrets plutôt que des réglages de `wrangler.toml` :
elles n'ont pas à figurer dans le dépôt public.

### Débrancher un service

```bash
npx wrangler secret delete DISCORD_WEBHOOK_URL
```

### Ajouter un service

Un service, c'est un fichier dans `src/connectors/`, sur le modèle de
`discord.js` : un `name`, une fonction `enabled(env)` qui regarde si ses
secrets sont là, et une fonction `send(report, env)` qui lève une erreur en
cas d'échec. On l'ajoute ensuite à la liste de `src/connectors/index.js`.
`src/connectors/format.js` fournit déjà le titre, le résumé et la mise en
forme communs.

## Ce que le relais accepte

| | |
|---|---|
| Adresse | `POST /report`, en `multipart/form-data` |
| `meta` | JSON : `version`, `language`, `system`, `install`, `description` |
| `report` | le fichier `.txt` du rapport, 64 Kio au plus |
| `screenshot` | facultatif, un PNG de 6 Mio au plus |
| En-tête | un `User-Agent` qui commence par `Purrtage/` |

Les réponses, et ce qu'en fait le jeu :

| Réponse | Sens | Le jeu |
|---|---|---|
| 202 | rapport conservé, ou transmis à au moins un service | l'oublie |
| 400, 413 | refusé : mal formé, trop gros | l'abandonne |
| 429 | plus de 5 rapports en une minute depuis la même adresse | le renvoie au lancement suivant |
| 503 | ni stockage, ni service joignable | le renvoie au lancement suivant |

`GET /shot/<id>.png` sert une capture conservée : c'est le lien que
contiennent les issues.

## Confidentialité

* Un rapport ne contient rien de personnel : la description du joueur, l'état
  de la partie, les versions du jeu et du système.
* L'adresse IP sert uniquement à limiter le nombre d'envois. Elle n'est ni
  enregistrée, ni transmise.
* Une capture est accessible à quiconque connaît son lien, qui contient
  96 bits aléatoires. Comme le dépôt est public, une capture liée depuis une
  issue est publique elle aussi. Le joueur peut décocher la capture avant
  d'envoyer.
* KV efface chaque rapport et sa capture au bout de 180 jours. La durée se
  règle par `REPORT_TTL_DAYS`, dans `wrangler.toml` ; elle vaut pour les
  rapports reçus ensuite. Passé ce délai, le lien de la capture dans une
  issue ne mène plus à rien.

## Diagnostiquer

Quand un rapport n'arrive pas, trois endroits disent où il s'est arrêté.

1. **Côté jeu** : `send.log`, dans le dossier des rapports (le bouton
   **Ouvrir le dossier** de la fenêtre F8 y mène). Une ligne par tentative :
   `not sent, no relay address` (le jeu ne connaît pas le relais),
   `unreachable` (réseau, DNS, certificat), `refused` ou `sent`, avec la
   réponse du relais.
2. **L'état du relais** : `https://purr-tage.<votre-compte>.workers.dev/health`
   indique si le stockage KV est branché et quels services ont trouvé leurs
   secrets — sans jamais les afficher.
   ```json
   {"storage":true,"limiter":true,"connectors":["discord"]}
   ```
   Un service absent de `connectors` n'a pas son secret, ou le secret porte
   un autre nom.
3. **Les journaux du relais** : page du Worker > **Logs**. Une ligne JSON par
   rapport (`"event":"report"`) avec `stored`, `delivered` et, pour chaque
   service en échec, l'erreur qu'il a renvoyée ; une ligne `"event":"refused"`
   pour chaque rapport refusé. Ni l'adresse IP, ni les mots du joueur.

## Développer

```bash
npm test               # les tests, avec Node 22 seul : aucune dépendance
npx wrangler dev       # le relais sur http://localhost:8787
npx wrangler tail      # les journaux du relais en ligne, en direct
```

Avec `wrangler dev`, les secrets se mettent dans un fichier `.dev.vars`, que
Git ignore :

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```
