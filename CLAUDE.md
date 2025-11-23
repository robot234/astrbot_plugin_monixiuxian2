# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AstrBot Plugin: Text-Based Cultivation Game (模拟修仙)** - A feature-rich, idle-style cultivation/xianxia RPG game plugin for AstrBot (QQ chatbot framework). Players experience a complete cultivation journey from mortal to immortal through chat commands.

**Current Version:** v2.4.0
**License:** AGPL-3.0

## Core Architecture

### Layered Design Pattern

The codebase follows a clean 4-layer architecture:

1. **Entry Layer** ([main.py](main.py)) - Plugin registration, command routing, access control
2. **Handler Layer** ([handlers/](handlers/)) - Command processors with async generators (`async for yield`)
3. **Business Logic Layer** ([core/](core/)) - Game mechanics (combat, cultivation, realms, sects)
4. **Data Layer** ([data/](data/)) - Database abstraction and migration system

### Critical Architectural Concepts

**Command Flow:**
```
User Message → AstrBot → @filter.command decorator → Handler method →
Business Logic (core/) → DataBase operations → Response generator (yield)
```

**Async Generator Pattern:**
All handlers use `async for yield` to stream responses back to users. This is the required pattern for AstrBot plugins.

Example:
```python
@filter.command(CMD_PLAYER_INFO)
async def handle_player_info(self, event: AstrMessageEvent):
    async for msg in self.player_handler.handle_player_info(event):
        yield msg
```

**Player Required Decorator:**
Most game commands require an existing player. Use `@player_required` decorator from [handlers/utils.py](handlers/utils.py) which automatically handles player validation and passes the Player object.

**Database Transaction Pattern:**
Use transactional operations for gold/item exchanges to ensure data integrity:
```python
# In data_manager.py
await self.deduct_gold(user_id, cost)  # Atomic operation
await self.add_item_to_inventory(user_id, item_id, quantity)
```

## Database Architecture

**Database:** SQLite with aiosqlite (async)
**Current Schema Version:** v15 (managed by [data/migration.py](data/migration.py))

**Migration System:**
- Decorator-based: `@migration(version_number)`
- Automatically runs on plugin initialization
- Supports both full schema creation and incremental upgrades
- Version tracked in `db_info` table

**Key Tables:**
- `players` - Core player data (25+ columns including HP, attack, defense, spiritual_power, mental_power, equipped items, breakthrough_bonus)
- `inventory` - Player items with unique constraint on (user_id, item_id)
- `sects` - Guild system
- `active_world_bosses` - Currently spawned bosses
- `world_boss_participants` - Boss damage tracking for reward distribution
- `shop_inventory` - Daily shop stock (date-seeded random generation)
- `boss_cooldowns` - Boss respawn timers
- `fixed_deposits` & `current_deposits` - Banking system with compound interest

**When Adding Database Columns:**
1. Create a new migration function decorated with `@migration(next_version_number)`
2. Update `LATEST_DB_VERSION` constant in [data/migration.py](data/migration.py:8)
3. Add ALTER TABLE statements for existing tables
4. Update the `_create_all_tables_v{version}()` function for fresh installs
5. Update the Player dataclass in [models.py](models.py) if adding player fields
6. Test both migration path and fresh install path

## Configuration System

**Config Files (JSON):**
- [_conf_schema.json](_conf_schema.json) - Plugin settings (access control, game values, file paths)
- [config/level_config.json](config/level_config.json) - 30 cultivation realms with progression data
- [config/items.json](config/items.json) - 30+ items/pills (1-9 grades)
- [config/monsters.json](config/monsters.json) - Monster templates
- [config/bosses.json](config/bosses.json) - 40+ world bosses
- [config/tags.json](config/tags.json) - 17 monster tags for procedural generation

**ConfigManager Pattern:**
Loaded once on initialization, cached in memory. Access via `self.config_manager`:
```python
item = self.config_manager.get_item_by_name("引气丹")
level_data = self.config_manager.level_data[player.level_index]
```

**Plugin Configuration:**
AstrBot provides runtime config via `self.config` (loaded from _conf_schema.json). Access nested values:
```python
values = self.config.get("VALUES", {})
initial_gold = values.get("INITIAL_GOLD", 100)
```

## Game Systems Architecture

### Tag-Based Generation System

**Monster/Boss Creation:**
The game uses a powerful tag composition system ([config/tags.json](config/tags.json)) to dynamically generate content:

1. **Tag Definition**: Each tag (野兽, 精英, 剧毒, 雷霆, etc.) defines attribute multipliers, loot modifiers, name affixes
2. **Composition**: Monsters/bosses are defined as `base_template + tags[]`
3. **Dynamic Scaling**: Final stats scale to player level automatically

This allows 17 tags to generate thousands of unique enemy combinations.

### Combat System

**Turn-Based Battle Engine** ([core/combat_manager.py](core/combat_manager.py)):
- Level advantage system: ±20% damage modifier based on level difference
- Damage formula: `(attacker.attack - defender.defense) * random(0.9, 1.1) * level_advantage`
- PvP battles are simulated (no HP loss)
- World boss battles apply real damage and track contributions

### Cultivation & Breakthrough System

**Cultivation Flow** ([core/cultivation_manager.py](core/cultivation_manager.py)):
1. "闭关" - Enter meditation state, record timestamp
2. Offline time accumulates
3. "出关" - Calculate exp: `base_exp * minutes * spiritual_root_multiplier`
4. Restore HP proportionally to gained exp

**Breakthrough Mechanics:**
- Success rate defined per level in [config/level_config.json](config/level_config.json)
- Breakthrough pills add temporary bonus (10%-50%) stored in `player.breakthrough_bonus`
- Failure penalty: lose 10% of required exp
- Success: advance realm, recalculate all attributes from level config
- Pill buff consumed on attempt (success or failure)

**17 Spiritual Root Types:**
From worst to best: 废灵根 (0.5x) → 先天道体 (2.5x) cultivation speed.
Weights configured in _conf_schema.json for rarity control.

### Attribute System (v2.4.0)

**Five Core Attributes:**
- 气血 (HP) - Health points
- 攻击 (Attack) - Physical damage
- 防御 (Defense) - Damage reduction
- 灵力 (Spiritual Power) - Magical ability
- 精神力 (Mental Power) - Mental strength

**Attribute Sources:**
1. Base values from level_config.json (per realm)
2. Equipment bonuses via `item.equip_effects`
3. Permanent boosts from high-grade pills

**Calculation:**
Call `player.get_combat_stats(config_manager)` to get final stats including equipment.

### Shop & Economy System

**Daily Shop Refresh** ([handlers/shop_handler.py](handlers/shop_handler.py)):
- Seed from current date ensures consistency
- Randomly selects N items (default 8) from items.json
- Stock inversely proportional to price (expensive = scarce)
- Stored in `shop_inventory` table

**Banking System** ([handlers/bank_handler.py](handlers/bank_handler.py)):
- **Fixed Deposits**: Min 24h, 0.3%/hour compound interest
- **Current Deposits**: Min 1h, 0.1%/hour compound interest
- Interest formula: `principal * (rate_multiplier ^ hours)`
- Supports player-to-player transfers

### Secret Realm System

**Procedural Dungeon Generation** ([core/realm_manager.py](core/realm_manager.py)):
- Floors = `base_floors + (player.level_index / 2)`
- 70% monster encounters, 30% treasure rooms (configurable)
- Final floor always contains boss
- Boss scaled to player level (default 70% strength)

## Development Workflow

### Running the Plugin

This plugin runs within AstrBot framework. There is no standalone run command. Testing requires:
1. AstrBot instance properly configured
2. Plugin loaded in AstrBot's plugin directory
3. QQ bot connected to test group/account

### Testing Changes

**Manual Testing Flow:**
1. Modify code
2. Restart AstrBot instance
3. Send commands in QQ chat to test
4. Check AstrBot logs for errors

**Database Testing:**
- Database file: `xiuxian_data.db` (configurable in _conf_schema.json)
- Use SQLite browser to inspect data during development
- Test both migration and fresh install paths when changing schema

### Adding New Commands

**Complete Flow:**
1. Define command string constant in [main.py](main.py) (e.g., `CMD_NEW_FEATURE = "新功能"`)
2. Create handler method in appropriate handler class
3. Add `@player_required` decorator if command needs player data
4. Implement async generator with `async for yield` pattern
5. Wire command in main.py:
   ```python
   @filter.command(CMD_NEW_FEATURE)
   async def handle_new_feature(self, event: AstrMessageEvent):
       async for msg in self.handler.handle_new_feature(event):
           yield msg
   ```
6. Update help text in [handlers/misc_handler.py](handlers/misc_handler.py)

### Adding New Items

1. Add item definition to [config/items.json](config/items.json):
   ```json
   {
     "id": "unique_id",
     "name": "物品名称",
     "type": "pill|equipment",
     "rank": "品级",
     "description": "描述",
     "price": 1000,
     "effect": { "hp": 100 },  // For consumables
     "subtype": "武器",  // For equipment
     "equip_effects": { "attack": 50 }  // For equipment
   }
   ```
2. Reload plugin (items loaded from JSON at startup)
3. No code changes needed unless adding new effect types

### Adding New Realms

1. Add realm entry to [config/level_config.json](config/level_config.json):
   ```json
   {
     "level_index": 30,
     "level_name": "新境界",
     "required_exp": 1000000,
     "base_gold": 5000,
     "success_rate": 0.15,
     "base_hp": 10000,
     "base_attack": 800,
     "base_defense": 400,
     "base_spiritual_power": 600,
     "base_mental_power": 600
   }
   ```
2. Maintain sequential level_index values
3. Update breakthrough system limits if needed

### Common Pitfalls

**1. Forgetting Async Context:**
All database operations are async. Always `await` calls to `self.db.*` methods.

**2. Not Using Transactions:**
When modifying multiple related records (e.g., gold + inventory), use the transactional methods in DataBase class.

**3. Spiritual Root Speed Not Applied:**
Remember cultivation exp calculation: `base_exp * time * root_speed_multiplier`

**4. Equipment Not Loaded:**
Always use `player.get_combat_stats(config_manager)` for combat calculations, not raw player attributes.

**5. Migration Version Skew:**
When adding migrations, ensure `LATEST_DB_VERSION` matches highest `@migration(n)` decorator.

**6. Shop Stock Depletion:**
Shop stock must be checked and decremented atomically. Use existing `shop_inventory` table methods.

## Code Style & Patterns

**String Formatting:**
Use f-strings for clarity: `f"{player.gold}灵石"`

**Error Handling:**
Validate inputs early, return user-friendly error messages via `yield`

**Type Hints:**
Models use dataclasses with type hints. Maintain this pattern for new models.

**Chinese Comments/Strings:**
This is a Chinese game. Comments can be in Chinese, all user-facing strings MUST be Chinese.

**Logging:**
Use `logger.info()`, `logger.error()` from `astrbot.api` for debugging.

## Key Files Reference

- [main.py](main.py) - Plugin entry, command routing (349 lines)
- [models.py](models.py) - Data models (Player, Item, Boss, etc.)
- [data/data_manager.py](data/data_manager.py) - Database operations (615 lines)
- [data/migration.py](data/migration.py) - Schema migrations (1,018 lines)
- [core/combat_manager.py](core/combat_manager.py) - Battle system (544 lines)
- [core/cultivation_manager.py](core/cultivation_manager.py) - Cultivation mechanics (562 lines)
- [handlers/shop_handler.py](handlers/shop_handler.py) - Shop/inventory/equipment (367 lines)
- [handlers/bank_handler.py](handlers/bank_handler.py) - Banking system (548 lines)
- [config_manager.py](config_manager.py) - Config file loader (86 lines)

## Important Implementation Notes

**Breakthrough Pill System (v2.4.0):**
- Breakthrough pills set `player.breakthrough_bonus` when used
- Bonus is a float (0.1 = 10% increase to success rate)
- Consumed on next breakthrough attempt regardless of outcome
- Check for active bonus in player info display

**World Boss System:**
- Boss levels scale to average of top N players (default 5)
- Participants tracked with damage contribution
- Rewards distributed proportionally to damage dealt
- 24-hour cooldown per boss ID

**Dao Name (道号) System:**
- Server-wide unique constraint
- 2-20 characters allowed
- Nullable field, optional feature

**Access Control:**
- Whitelist configured in _conf_schema.json
- Empty whitelist = allow all groups
- Private messages always allowed
- Check performed in `_check_access()` method

## Repository Information

**Original Author:** oldPeter616
**Current Maintainer:** linjianyan0229
**GitHub:** https://github.com/linjianyan0229/astrbot_plugin_monixiuxian
**Based On:** [@Zhalslar's](https://github.com/Zhalslar) modular architecture design
