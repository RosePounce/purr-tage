# Purr-tage — development notes 🐾

[Français](README-dev.md) · **English**

Everything needed to work on the code: installing from source, command-line
options, adding a language, the network protocol, the architecture, the tests
and building the packages. The player's manual — installing the packages, the
rules and the controls — is in [README.en.md](README.en.md), and an inventory
of what already exists in
[docs/fonctionnalites.en.md](docs/fonctionnalites.en.md).

---

## Installing from source

```bash
pip install -r requirements.txt
python main.py
```

Python 3.8 or newer. No dependency other than pygame.

> **Python 3.14** — "mainline" pygame does not publish a prebuilt wheel for
> this version yet: pip then compiles it from source and the font module
> (SDL_ttf) often ends up broken, with a `font module not available` error.
> `requirements.txt` therefore installs **pygame-ce** from 3.14 onwards — same
> API, up-to-date wheels:
>
> ```
> pygame==2.6.1   ; python_version <  "3.14"
> pygame-ce>=2.5.8 ; python_version >= "3.14"
> ```
>
> If you had already installed pygame by hand, clean up first:
> `pip uninstall -y pygame pygame-ce && pip install -r requirements.txt`.
>
> The game also switches to `pygame.ftfont` (the bundled FreeType font engine)
> all by itself when `pygame.font` is unavailable, and prints what to do when
> neither of the two responds.

---

## Command-line options

```bash
python main.py --direct                 # start without going through the menu
python main.py --difficulty tiger       # kitten | tomcat | tiger
python main.py --seed 1234              # replay exactly the same map
python main.py --no-fog                 # turn the fog of war off
python main.py --no-sound               # mute the sound
python main.py --fullscreen             # fullscreen
python main.py --resolution 2880x1800   # native rendering at that resolution
python main.py --language en            # force the language (fr | en | …)
```

---

## Adding a language

A language is one file. Copy `purrtage/locales/fr.json` — the reference
language — under the ISO 639-1 code you want, then translate the texts without
touching the keys:

```bash
cp purrtage/locales/fr.json purrtage/locales/es.json
python main.py --language es
```

The file is read again at start-up and the language shows up by itself in the
**Language** button: there is no list to keep up to date in the code.

A few rules:

* `language.code` and `language.name` are mandatory; the name is written in
  the language itself ("Español"), and that is what the button displays.
* The fields in braces — `{name}`, `{count}` — must be kept as they are;
  their order within the sentence, however, is free.
* `app.title` and `menu.title` carry the game name: keep "Purr-tage", that is
  the brand; the second half does get translated ("The Cat War",
  "La Guerre des Chats").
* The `one` / `other` keys carry the singular and the plural.
* `units.*.gender` and `buildings.*.gender` are `"m"` or `"f"`: French uses
  them to agree "terminé" / "terminée". A language without agreement puts
  `"m"` everywhere and gives the same sentence twice.
* Texts split into lists (`guide.goal_lines`, `help.sections`) are displayed
  line by line: the translator decides where the breaks go.
* A forgotten key is taken from French rather than leaving a hole;
  `python -m unittest tests.test_i18n` reports the ones that are missing.

To translate without rebuilding the game, the same file can be dropped into
`locales/` inside the data folder (the one `python main.py --verification`
prints): it takes priority over the one that ships with the game.

---

## How the game stays in sync

The game runs in **lockstep**: nothing of the game state travels, only the
orders. Each machine simulates the same game from the same map — the same
seed, or the same bytes for a map from the editor — and replays both players'
orders.

Time is cut into turns of a tenth of a second. An order given during turn T
runs on turn T+2, at the same instant on both sides: that small deferral is
what gives the packets time to arrive, and it is why a click takes a tenth of
a second to take effect. A machine never advances a turn without the other
side's orders; when the network hiccups, both wait together rather than
diverging, and a "Waiting for the opponent" banner appears.

Each turn additionally carries a fingerprint of the simulation. Were the two
machines computing different games, the discrepancy would be reported instead
of going unnoticed.

None of this means anything unless the simulation is strictly reproducible. It
advances in fixed steps of 1/30 s, uses no global random draw, employs only
`math.sqrt` (the one function whose rounding the IEEE 754 standard mandates,
unlike `math.hypot` or the trigonometric functions), and renumbers its
entities on every game. Two games launched with the same orders produce the
same fingerprint, bit for bit.

---

## Sending bug reports

The game only talks to a relay, a Cloudflare Worker described in
[`relay/`](relay/README.en.md), which then forwards to GitHub, Discord or by
e-mail. Its address is `BUG_REPORT_URL`, in `purrtage/settings.py`.

Run from the sources, the game sends nothing: trials and the test suite must
not fill the reports channel. To try the sending out, point the game at the
relay by hand:

```bash
PURRTAGE_REPORT_URL=https://purr-tage.rose-pounce.workers.dev/report python main.py
```

Every attempt is written to `saves/bug/send.log` — sent, kept for lack of a
network, refused — with the relay's answer.

The [`relay/`](relay/README.en.md) folder is **reserved**: the game's relay
runs on RosePounce's Cloudflare account, its secrets are not in there, the
*Relay guard* check refuses any pull request touching it and
`.github/CODEOWNERS` reserves its review. Contributing to the game never
requires touching it; to try the sending out, deploy your own relay from your
fork and point the game at it with `PURRTAGE_REPORT_URL`, as above.

---

## Under the hood

```
main.py                entry point (command-line arguments)
purrtage/
  settings.py          every constant and the balancing, in one place
  i18n.py              languages: loading, fallback, remembered choice
  locales/*.json       one file per language (fr, en, …)
  world.py             the map: procedural generation (value noise, lakes,
                       nodes) at every size, blank map
  mapfile.py           binary map format, files, checks
  editor.py            map editor: terrain, resources, bases
  pathfinding.py       8-direction A* + "taut string" path smoothing
  entities.py          units (state machine), buildings, projectiles, effects
  player.py            treasury, population, upgrades
  ai.py                the opponent: economy, build order, assaults
  game.py              simulation, orders, selection, victory conditions
  render.py            world rendering, fog, interpolations
  sprites.py           all the art, drawn in code and cached
  ui.py                resource bar, minimap, action panel
  screens.py           menu, pause, help, end screen
  camera.py            scrolling, zoom, screen <-> world conversions
  commands.py          serialisable orders: what travels over the network
  net.py               TCP transport + UDP advertisement on the local network
  lockstep.py          turns, order deferral, divergence detection
  layout.py            interface scaling according to the resolution
  fog.py               fog of war (explored / visible)
  audio.py             synthesised sounds (meows, impacts, fanfares)
  bugreport.py         bug reports: context, screenshot, writing
  bugsend.py           sending reports to the relay, outbox, send.log
  fonts.py             font loading with a FreeType fallback
tests/test_core.py     pathfinding, economy, combat, bug reports…
tests/test_i18n.py     translations: missing keys, {…} fields, layout
tests/test_net.py      lockstep: orders, turns, divergence
relay/                 the bug report relay (Cloudflare Worker, reserved
                       folder: see relay/README.en.md)
```

A few technical choices:

* **Zero assets.** The cats are drawn supersampled x3 then scaled down with
  `smoothscale`, which smooths the outlines without an image library.
* **No text in the code.** `settings.py` only keeps the identifiers; the
  labels live in `purrtage/locales/` and are read again on every draw, which
  makes it possible to switch language without restarting the game.
* **Interface in units**, converted to pixels by `Layout`: a single constant
  describes a spacing, whatever the resolution.
* **Fog applied after the scaling**, on a grid of one pixel per tile
  refreshed five times a second. The enlarged image depends only on the
  visible tile block, so it is cached: it used to be the most expensive item
  in the rendering (9.6 ms per frame at 2880x1800).
* **Zoom steps filtered** according to the resolution: a zoom-out that would
  show more than the whole map, or whose intermediate surface would exceed
  the pixel budget, is simply dropped.
* **Budgeted path computations** (16 per frame) to avoid the stutters when
  giving an order to 40 cats at once.
* **Rectangle distances** for the buildings: a cat "arrives" at the edge of
  the footprint, not at the center.

Measured in purely software rendering (no GPU), 168 units in a full battle,
camera scrolling:

| Resolution | Sprites | Normal zoom | Max zoom-out |
|---|---|---|---|
| 1280 x 760 | x1 | 138 fps | 102 fps |
| 1920 x 1080 | x1.5 | 81 fps | 50 fps |
| 2880 x 1800 | x2 | 47 fps | 37 fps |

On a real machine the result is better: here the GPU is not called upon at
all.

### Running the tests

```bash
python -m unittest discover -s tests -v
```

### Building the packages

```bash
pip install pyinstaller pillow
python packaging/make_icon.py                      # icon, drawn by the game
pyinstaller --noconfirm --clean --distpath dist \
            --workpath build/pyi packaging/purrtage.spec
./dist/Purrtage/Purrtage --verification                # package self-test
bash packaging/linux/make_appimage.sh 1.0.0        # Linux
```

On Windows, the `.exe` is turned into an installer with Inno Setup:
`iscc /DVersion=1.0.0 packaging\windows\installer.iss`.

`--verification` runs a real game, draws for a few seconds, saves a
screenshot then quits. A package that can neither generate its map, nor load
its fonts, nor draw fails there rather than at the player's place — that is
what the integration pipeline runs after every build.

PyInstaller does not cross-compile: the `.exe` can only be made on Windows.
Hence two integration pipelines:

| Pipeline | Trigger | What it does |
|---|---|---|
| `tests.yml` | every push and pull request | the test suite, in some fifteen seconds |
| `packages.yml` | **a `v*` tag** | both installers, then the final release |
| `packages.yml` | **Run workflow** on `main` | the same, the release being tagged from `__version__` |
| `packages.yml` | **Run workflow** on `develop` | the same, but as a test **pre-release** |

For a final version, the tag stays the simplest way:

```bash
git tag v1.0.0 && git push --tags
```

The packages are then built on Windows and on Linux, each one run and
self-checked, then attached to the release.

Nothing triggers on a plain push: building two installers on every commit
would serve no purpose. For a **test release**, go through **Run workflow** in
the Actions tab and pick the `develop` branch: the number becomes
`<version>-dev.<run number>`, hence one tag per run, and the release is marked
*pre-release* — GitHub keeps showing the last final version as *latest*. The
form's **version** field lets you force a number should you need to
(`1.1.0-rc1`).

A guard rail refuses a number that is already released: run on `main` without
`__version__` having been bumped since the last release, the workflow stops
with a message saying so, rather than overwriting an existing tag.

### Exporting the sprites as SVG

```bash
python packaging/export_svg.py                     # into build/svg/
python packaging/export_svg.py press/ --team 1
```

The cats, the buildings, the resource nodes and the decor come out as SVG —
handy for a press shot, a web page or a sticker, without ever depending on a
resolution.

This is possible because the art is already vector based: `sprites.py` only
paints ellipses, circles, rounded rectangles, polygons and lines, through a
small internal painter. The export therefore redraws nothing, it replaces
that painter with a recorder that writes SVG and lets the drawing code run as
it is — a single place where the art is described, and a test that fails if
the game painter gains a primitive the export does not know about.

The terrain tiles are the exception: they are painted pixel by pixel, and an
SVG with one element per pixel would be of no use at all.

---

## Where this could go

* walls and gates, formations, mounted units (cats on Roombas)
* several opponents and team games
* saving / loading a game
* more than two bases per map, once games with more players exist
