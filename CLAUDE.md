# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Primary Directive

**THE BOT MUST BEHAVE LIKE A HUMAN PLAYER AT ALL TIMES.**

This is a multiplayer online game where other players can observe and report suspicious behavior. The absolute priority is making all bot actions indistinguishable from human gameplay:
- Use randomized delays with natural variance (Gaussian distribution)
- Avoid mechanical patterns (perfect timing, instant reactions, repetitive movements)
- React to game events with human-like response times
- Never perform actions faster than a human could

Players who suspect botting will report to Game Masters, resulting in account bans.

## About Tibia 7.72

Tibia is a **massively multiplayer online RPG** (MMORPG) with heavy player interaction:
- Hundreds of players share the same game world simultaneously
- Players can observe each other's behavior, chat, trade, and cooperate
- Player-killing (PvP) and competition for hunting spots are common
- The community actively reports suspected bots to Game Masters

## Game Mechanics

### Grid-Based World
- The world is a 2D grid of tiles (SQM - square meters)
- **Players and creatures are solid obstacles** - they block movement like walls
- You cannot walk through or overlap with any player/creature
- Pathfinding must dynamically recalculate when blocked by entities
- The visible viewport is 15x11 tiles centered on the player

### Turn-Based Movement
- Movement happens in **discrete tile-to-tile steps**, not continuous
- Each step has a duration based on: player speed + ground type
- The next movement can only begin after the current step completes
- `movement_status`: 0 = stopped, 1 = moving (must wait for 0 before actions)

### Action Timing
- All actions (attack, use item, cast spell) have cooldowns
- Sending packets during cooldown = ignored or flagged as suspicious
- Must respect the natural rhythm: move → stop → act → move

### Collision & Blocking
- Tiles can be: walkable, blocked (walls), or temporarily blocked (creatures/players)
- Creatures in combat block their tile until killed
- Other players block tiles and may intentionally block your path
- Corpses with loot appear on tiles and must be opened to collect items

### Coordinate System
- Global: Absolute world position (X, Y, Z)
- Relative: Position from player's perspective (-7 to +7 tiles)
- Z levels: 7 = ground, <7 = above ground, >7 = underground

## Bot Modules

| Module | Purpose |
|--------|---------|
| trainer.py | Combat - target selection, attack timing, kill-steal avoidance |
| cavebot.py | Navigation - waypoint following, pathfinding around obstacles |
| auto_loot.py | Looting - open corpses, collect items with human-like delays |
| alarm.py | Safety - detect Game Masters and other players, pause bot |
| fisher.py | Fishing automation |
| runemaker.py | Spell casting |
| eater.py | Food consumption |
| stacker.py | Inventory organization |

## Commands

```bash
python main.py                    # Run bot
pyinstaller MolodoyBot.spec       # Build executable
publicar.bat                      # Build + publish to GitHub
```

## Key Technical Notes

- Memory reading via Pymem (process: Tibia.exe)
- Packet injection via x86 assembly (core/packet.py)
- Thread-safe state management (core/bot_state.py)
- A* pathfinding for navigation (core/astar_walker.py)
- All memory offsets in config.py are specific to Tibia 7.72 client
