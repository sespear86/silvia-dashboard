# Silvia Dashboard rebuild plan

Path: `C:\Users\Irika\.grok\silvia-dashboard\REBUILD-PLAN.md`

This document is the Silvia Dashboard rebuild plan to execute on a later prompt. The session that writes this file does not rebuild the app. The next prompt executes the steps below, in order, on the existing tree.

Entry today and after the rebuild: `python "$HOME/.grok/silvia-dashboard/__main__.py"`

Catalog id stays `cli.silvia-dashboard`. This plan does not choose a second dashboard app, a new TCP listener on this PC, or hosting this UI on the Pi.

## Current app

The shipped app is one local Windows program. `redirect` is false on `dump`, `pages`, `switch`, `inspect`, and `launch`. Those commands do not open a listen port. `dump`, `pages`, `switch`, and `inspect` are one-shot processes and exit. `launch` opens a Tk window and returns when that window closes. It is not a socket.

Commands the later session must keep working:

| Command | Role now |
| --- | --- |
| `dump` | One-shot JSON snapshot. No `--page` uses layout `live-diagrams-giant-tree`, so the page is Live diagrams. `redirect` is false. `systems` is still attached. |
| `pages` | One-shot JSON. Seven page ids, plus a navigation target per system. `redirect` is false. |
| `switch` | `--page` of a page id switches page. `--page` of a system id returns that system's detail without a live snapshot. |
| `inspect` | `--id` of a system id returns that system's detail. Any other id uses `select_entity`. |
| `launch` | Tk window. No `--page` follows the same default layout, so the window opens on Live diagrams. The Desktop shortcut calls this with no extra arguments. |

Other parsers stay as they are: `evolve`, `screenshot`, `layout`, `overflow`, `diagrams`, `imagine-inventory`, `imagine-open`, `giant-update`. Do not remove them.

`theme.DEFAULT_LAYOUT_ID` is `live-diagrams-giant-tree`. `theme.DEFAULT_SCHEME` is `oled-cyan`. `test_theme.py` asserts the default layout id string. Keep that constant. Change the bare command's page in `__main__.py`, not by renaming the constant.

Pages, verbatim, from `world.PAGES`:

| id | title |
| --- | --- |
| overview | Overview |
| butler-host | Butler & Hosting |
| memory | Memory |
| catalog | Catalog |
| orchestrator | Orchestrator |
| usage | SuperGrok Heavy |
| live-diagrams | Live diagrams |
| task-view | Task view |
| sessions | Sessions |
| commands | Commands |

`page_view` shows every entity on Overview. Butler & Hosting keeps hostlands, silvia-precinct, capabilities, and probes. Memory keeps region `memory-archipelago` and category `Memory`. Catalog keeps `kind == resource`. Orchestrator keeps region `watch-range` and ids `orchestrator` and `cli.orchestrator`. SuperGrok Heavy keeps usage rows and the billing fields. Live diagrams keeps sections `running`, `available`, and `giant`.

### Inventory

Presence is true only when that system's path exists. A missing path is absent. `systems.probe_presence` returns `present` or `absent` from `Path.exists` only. `systems.presence_value` returns True or the string `absent`. Hub, Pi, and Grok Bot health are not path presence. Do not start or mutate the other systems while probing.

| id | display name | path | purpose token |
| --- | --- | --- | --- |
| silvia | Silvia | `C:\Users\Irika\.grok\silvia` | butler |
| si-butler | SI Butler voice | `C:\Users\Irika\si-butler` | voice |
| silvia-android | Silvia Android | `C:\Users\Irika\.grok\silvia-android` | Android |
| mempalace | MemPalace | `C:\Users\Irika\.grok\mempalace-stack` | memory |
| resource-list | Resource catalog | `C:\Users\Irika\.grok\resource-list` | catalog |
| workflow-memory | Workflow memory | `C:\Users\Irika\.grok\workflow-memory` | playbook |
| orchestrator | Orchestrator | `C:\Users\Irika\.grok\orchestrator` | orchestrator |
| pi-device | Pi device | `C:\Users\Irika\.grok\pi-device` | Pi |
| money-loop | Source Supply money-loop | `C:\Users\Irika\.grok\money-loop` | money-loop |
| source-supply-site | Source Supply site | `C:\Users\Irika\.grok\source-supply-site` | site |
| grok-bots | Grok bots | `C:\Users\Irika\.grok\grok-bot-roster` | bots |
| goal-split | Goal split | `C:\Users\Irika\.grok\goal-split` | goal-split |
| portion-plan | Portion plan | `C:\Users\Irika\.grok\portion-plan` | portion |
| family-stack | Family Grok stack | `C:\Users\Irika\.grok\family-stack` | family |
| dualboot-memory | Dual-boot memory share | `C:\Users\Irika\.grok\dualboot-memory` | dual-boot |
| steam-lan | Steam LAN host check | `C:\Users\Irika\.grok\steam-lan-host-check` | Steam |
| source-bus | Source bus | `C:\Users\Irika\.grok\source-bus` | bus |
| desk | Desk | `C:\Users\Irika\.grok\desk` | bench |
| edge-check | Edge check | `C:\Users\Irika\.grok\edge-check` | edge-check |
| review-board | Review board | `C:\Users\Irika\.grok\review-board-phase0` | review |
| specialist-models | Specialist models | `C:\Users\Irika\.grok\specialist-models` | specialist |
| afterfive | AfterFive | `C:\Users\Irika\afterfive` | AfterFive |
| sable | Sable | `C:\Users\Irika\sable` | Sable |
| ridgeready | RidgeReady | `C:\Users\Irika\RidgeReady` | RidgeReady |

Do not add or rename these ids. Each purpose line must still contain its token with that exact case. `tests/test_systems.py` is the lock.

### Desktop shortcut

`C:\Users\Irika\OneDrive\Desktop\Silvia Dashboard.lnk` is `pythonw` launching that entry with `launch`.

Measured target: `C:\Python314\pythonw.exe`. Arguments: `"C:\Users\Irika\.grok\silvia-dashboard\__main__.py" launch`. Working directory: `C:\Users\Irika\.grok\silvia-dashboard`. Do not rewrite the shortcut. Bare `launch` is what the icon runs, so the window change belongs in `launch`, not in the `.lnk`.

### Limits in the current source

1. Overview mixes the system list with the catalog game pieces on one scroll. `app._draw_named_game` paints system rows and then every `view_entities` row into the same canvas and one scrollbar.
2. A plain `dump` and a window open run live HTTP probes before path presence is needed. `live.load_probes` calls `_http` (timeout 4) for MemPalace hub `http://127.0.0.1:8765/healthz` and Pi `http://192.168.1.235:8870/`. Grok Bot is not that `_http` call. `load_probes` calls `_grok_bot_probe()`, which calls `hosting.probe_grok_bot`. That calls `probe_url` / `http_get` with timeout 5, then `grok_bot_process_running` (`tasklist`, timeout 8). `_grok_bot_probe` then calls `_bot_running` (`tasklist`, timeout 8). `load_probes` also calls `load_source_bus`. `dump` and `launch` call `live_snapshot()` before `overview_systems()` is required. `pages` and system `inspect` / `switch` already skip that snapshot.
3. `screenshot` draws the giant-tree graphic rather than the systems overview. `capture.capture_world` always calls `layout_tree` on the giant tree.
4. The system id `orchestrator` is the same string as the stack probe id `orchestrator`. The local `probe_meta` tuple inside `build_world` uses that id, `live.load_probes` uses that key, and `select_entity` returns the system detail first, so a click on the probe row opens the system.
5. The default layout is the live-diagrams giant tree, so a plain `dump` is not the systems overview. The same default makes bare `launch` open Live diagrams. The system rows exist on the payload, and they are on screen only after the user switches to Overview.

## Constraints for every step

- Edit the existing modules under `C:\Users\Irika\.grok\silvia-dashboard`. Do not create a second dashboard app.
- Do not open a new listen port on this PC. Keep `redirect` false.
- Do not host this UI on the Pi. The Pi device row stays a path-presence system. Pi LAN health stays a probe field.
- Do not copy hub, Pi, or Grok Bot `ok` into `systems[].presence`.
- Do not start or mutate Silvia, the money-loop, source-bus, dual-boot, Steam, or any other system while probing. Reads are `Path.exists`, catalog JSON, and the existing HTTP health helpers.
- Keep the seven page titles and the 24 inventory ids and display names.
- Keep `DEFAULT_LAYOUT_ID` equal to `live-diagrams-giant-tree`.

## Changes

Each surface is an improvement or an explicit keep. Deferred items are labeled deferred.

### Overview — improvement

Two panes. Top pane: the 24 systems (display name, id, path, presence). Bottom pane: the catalog game pieces that Overview already lists. Each pane has its own canvas and scrollbar. The search box filters both. Clicking a system still calls `select_entity`, which calls `open_system`.

Bare `dump` and bare `launch` select page `overview` when `--page` is empty. `--page live-diagrams` and `--layout-id` behavior for an explicit page stay. Do not change the default layout id constant.

### 24-system overview and per-system detail — improvement on the list, keep on the record

Keep `open_system` fields: `title` is the display name, `path` is the inventory path, `presence` is True or `absent`, `purpose` contains the token, `body` contains the path, the presence line, and the purpose line. Keep `overview_systems` as the only presence source.

The user-visible improvement is the split pane plus the bare command landing on that list. A missing path still returns a detail view that says absent.

### Butler & Hosting — improvement

Keep the current entity filter. Add a `health` list on this page only, built from the probe dict keys `mempalace.hub`, `grok.bot`, and `pi.lan`, plus the file probes already on the page. Each health row has its own `ok` and url or path. Do not write that `ok` into any system `presence`. The mempalace system can be present while hub health is down.

### Memory — improvement

Keep the memory-archipelago and category `Memory` entities. Put the `mempalace` system row (id, display name, path, presence, purpose) in a `system` field on this page. Presence comes from `presence_value` of the inventory path, not from hub health.

### Catalog — improvement

Keep `kind == resource` as `view_entities`. Put the `resource-list` system in a `system` field on this page so the catalog tool's own tree is visible once, and is not inserted as a fake resource row.

### Orchestrator — improvement

Keep the page. Show two different records. `inspect --id orchestrator` stays the system: title `Orchestrator`, path `C:\Users\Irika\.grok\orchestrator`, presence from that folder, purpose containing `orchestrator`. The stack probe entity id becomes `probe.orchestrator`. It still reads the live probe dict key `orchestrator` so existing snapshot fixtures keep that key. `inspect --id probe.orchestrator` returns the probe, and its `ok` is not system presence. Update the Orchestrator page filter and the status-line keys in `app.py` that currently look up the entity id `orchestrator`.

### SuperGrok Heavy — keep, plus one label

Keep the usage tier, percents, products, and breakdown. Do not treat those figures as path presence. Add one header string on the page and in the usage detail text: `SuperGrok Heavy weekly usage, not disk presence`. Existing usage assertions must still pass.

### Live diagrams — keep, and stop being the bare landing page

Keep sections `running`, `available`, and `giant`, including expand, search, and collapse. Bare `dump` no longer selects this page. `dump --page live-diagrams` and layout id `live-diagrams-giant-tree` still do. `screenshot --page live-diagrams` still draws the giant tree.

### CLI `dump` — improvement

When `--page` is empty, the JSON `page` is `overview`. `redirect` stays false. The process still exits. `system_ids` is the 24 inventory ids in inventory order. Presence still comes from `presence_value`. For this overview path, call `load_probes(http=False)` so `_http` is not called, `_grok_bot_probe` is not called, and `load_source_bus` is not called. File-existence probe keys may still be filled locally. `dump --page butler-host` and `dump --page orchestrator` still load HTTP health. `dump --snapshot` stays file-only, as it is now.

### CLI `pages` — keep

Keep `pages_payload`: seven pages, `redirect` false, and one navigation target per system id (`inspect`, target equals the id). No new page ids.

### CLI `switch` — keep

Keep the system-id short-circuit and `switch_page` for the seven page ids. An unknown page id still raises. System switch still returns title, path, presence, and purpose, and still does not call `live_snapshot`.

### CLI `inspect` — improvement

Keep the system-id short-circuit, including silvia: title `Silvia`, inventory path, presence true when that folder exists, purpose containing `butler`. Add the `probe.orchestrator` id so the probe is reachable. Do not change the silvia payload shape.

### Tk `launch` — improvement

When `--page` is empty, open Overview and draw the two panes. Refresh rebuilds the world. Overview refresh uses `load_probes(http=False)`. Butler & Hosting and Orchestrator refresh may call `_http`. The window is still Tk. Do not open a listen port. `launch --dump` stays the JSON path and follows the same page rule.

### `screenshot` — improvement

`screenshot` with no `--page` writes the systems overview: one row per inventory id with display name and presence word (`present` or `absent`). Return the list of labels drawn so a test can see them without OCR. `screenshot --page live-diagrams` keeps `capture_world` on the giant tree.

### Desktop shortcut — keep the file, improvement is the window it already opens

Do not edit `C:\Users\Irika\OneDrive\Desktop\Silvia Dashboard.lnk`. After bare `launch` opens Overview, the same icon shows the systems panes. Check by reading the shortcut with `WScript.Shell`: target ends with `pythonw.exe`, arguments contain `__main__.py` and `launch`.

## Ordered steps

1. In `live.load_probes`, add `http: bool = True`. When `http` is false, do not call `_http`, do not call `_grok_bot_probe`, and do not call `load_source_bus`. `_grok_bot_probe` is the Grok Bot path (`hosting.probe_grok_bot` → `probe_url` / `http_get` timeout 5, and `tasklist` timeout 8). Skipping only `_http` still runs that probe. Return the file-existence probe keys only, and set `mempalace.hub`, `grok.bot`, and `pi.lan` to `{"ok": None, "skipped": True}` so a missing health check is not painted as present. Check: a test monkeypatches `live._http` and `live._grok_bot_probe` to raise `AssertionError`. `load_probes(http=False)` must return and must not call either one. If `_grok_bot_probe` runs, the test fails. `load_probes()` still calls both.

2. In `__main__.py` `dump_payload` and `launch`, when `args.page` is empty, set the page to `overview` after `apply_selection`. Do not change `DEFAULT_LAYOUT_ID`. Pass `http=False` through `live_snapshot` into `load_probes` when the page is `overview`, unless `--snapshot` was passed. Check: `dump` with no `--page` and no `--snapshot` exits 0, `page` is `overview`, `redirect` is false, and the monkeypatched `_http` and `_grok_bot_probe` were not called. If `_grok_bot_probe` runs, the test fails. `dump --page live-diagrams` still has diagram sections `running`, `available`, and `giant`.

3. In `app.py`, replace the single overview canvas scroll with a vertical `PanedWindow`. Top canvas: `view["systems"]` only. Bottom canvas: `view_entities` only. Give each canvas its own scrollbar. Search filters each list. System hits call `select_entity`. Check: a headless test is not required for Tk; assert the source of `_draw_named_game` constructs two canvases, and `page_view(..., "overview")` still returns both `system_ids` and `view_entities` as separate lists.

4. In `world.py`, change the probe entity id from `orchestrator` to `probe.orchestrator`. Read probe body from `probes["orchestrator"]`. Add `probe.orchestrator` to the Orchestrator page filter. In `app.py` status keys, use `probe.orchestrator`. Check: `inspect --id orchestrator` title is `Orchestrator`, path is `C:\Users\Irika\.grok\orchestrator`, presence is True when that folder exists, and purpose contains `orchestrator`. `inspect --id probe.orchestrator` returns a probe whose id is `probe.orchestrator` and whose `ok` is not copied onto the system row.

5. In `page_view` for Butler & Hosting, set `health` from the probe dict without writing `presence`. For Memory, set `system` from `open_system("mempalace")`. For Catalog, set `system` from `open_system("resource-list")`. For Orchestrator, set `system` from `open_system("orchestrator")` and include the probe entity. Check: a snapshot with `mempalace.hub.ok` false still yields mempalace system presence from `Path.exists`. Catalog `view_ids` stay resource ids and also expose `system.id == resource-list`.

6. On the usage page, set `usage_note` to `SuperGrok Heavy weekly usage, not disk presence` and show that string in `_draw_usage` and the detail pane. Check: `dump --page usage` still has `usage_tier` and `usage_percent` from the snapshot, and the note string is present.

7. In `capture.py`, add `render_systems_png(systems, path)` that draws each display name and presence word and returns `labels`. `screenshot` with no `--page`, or with overview, calls it. `screenshot --page live-diagrams` still calls `capture_world`. Check: the returned labels include every inventory display name; the PNG file size is greater than 0; a live-diagrams screenshot result still has `graphic` true.

8. Run the existing pytest suite twice. Update a test only when it required bare `dump` to select Live diagrams or the probe entity id to be the string `orchestrator`. Do not weaken `tests/test_systems.py`. Check: both suite runs exit 0. Then run `pages`, `inspect --id silvia`, `inspect --id orchestrator`, and `inspect --id probe.orchestrator` from fresh processes. Read the Desktop shortcut with `WScript.Shell` and confirm the target and arguments are unchanged.

## Deferred

- A new game metaphor is deferred. The named regions and game pieces stay. Reason: Overview's improvement is the split from that list, and the evolve, name, and layout tests already lock the pieces.
- Regenerating Imagine drafts is deferred. Reason: the schemes already paint the window, and new images are not required to fix the five limits above.
- Adding systems past the 24 rows is deferred. Reason: the inventory table in this file is the closed list.
- Rewriting the Desktop shortcut is deferred. Reason: the icon already runs bare `launch`, and step 2 changes what that command shows.
- Requiring MemPalace hub, Pi LAN, or Grok Bot to be up is deferred. Reason: those values are health, and the overview must open when they are down.
