# Purr-tage features

[Français](fonctionnalites.md) · **English**

## Game

- Real-time strategy between two cat clans: the Whisker Clan against the Chartreux Horde
- You win when the opponent has no recruiting building left and no Kitten to rebuild one
- End-of-game screen

## Economy

- 4 resources: kibble, wool, catnip, stone
- Gathered by Kittens, who carry 12 units and drop them at the nearest Royal Basket
- Deposits run out and shrink
- Population capped by Baskets and Sheds

## Units

- Kitten: gathers, builds, repairs
- Scratcher: melee fighter
- Spitter: ranged attack with hairballs
- Tomcat: heavy unit, bonus damage against buildings

## Buildings

- Royal Basket, Shed, Scratching Post, Dojo
- Claw Tower: automatic defence, with 2 upgrade levels
- Ramparts laid out in a line by dragging the mouse
- Built and repaired by Kittens, production queue, cancelling refunds the cost

## Dojo upgrades

- Sharpened Claws (attack), Thick Fur (armour and hit points), Quick Paws (speed)

## Combat

- Attack, attack-move, stop
- A cat moves on to the next enemy once its target is down
- Limited retaliation, so that a garrison is not lured far away
- Projectiles and visual effects

## AI opponent

- Same rules as the player, no cheating
- Runs its economy, follows a build order, upgrades its troops
- Attacks in ever larger waves
- 3 difficulty levels: kitten, tomcat, tiger

## Map and world

- Procedural generation: terrain, lakes, deposits
- 4 sizes: 64, 96, 128 and 160 tiles across
- Reproducible seed (`--seed`)
- Fog of war (explored and visible areas), can be turned off
- A* pathfinding in 8 directions, with smoothed paths

## Controls and interface

- Single, box, Shift and double-click (same unit type) selection
- Context order on right click, queued orders with Shift
- Control groups (Ctrl + 1 to 9), idle Kitten selection
- Camera: arrow keys, screen edge, middle mouse button, ZQSD; 4 zoom levels
- Minimap, resource bar, action panel
- Hovering a deposit highlights it and shows what it still holds
- Alerts, with Space to centre on them
- Pause and adjustable game speed
- Fully rebindable keys, one-click AZERTY / QWERTY switch

## Screens

- Main menu, Options, Controls help (F1), "How to play" page (F2), pause

## Multiplayer

- Two players over the local network
- Automatic game discovery (UDP beacon), or typing the address by hand
- Lockstep simulation with desync detection
- Maps made in the editor are sent to the other player

## Map editor

- Terrain painting (water, sand, grass, meadow, flowers) with an adjustable brush
- Placing resources and their amount, placing both bases, eraser
- Blank or random map, open, undo, save
- Checked before saving: the map must be playable
- Binary `.pmap` format

## Graphics and sound

- No image or sound file: sprites drawn by code, sound effects synthesised
- Two cat styles: the new, rounded look and the old one, seen in profile
- Adapts to any resolution from 1280×760 to 2880×1800, resizable window, fullscreen
- Sprites redrawn at the chosen scale rather than enlarged

## Languages

- French and English, can be switched mid-game, choice remembered
- Adding a language comes down to dropping in a JSON file

## Tools

- Bug report with F8: description, detailed context and screenshot
- Command-line options (difficulty, seed, resolution, language, sound, etc.)
- Package self-test (`--verification`)
- Sprite export to SVG
- Windows installer and Linux AppImage built by continuous integration
