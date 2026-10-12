# Settings dialog enhancement (2026-10-12)

Commits: 0554ece (tabs/segmented/switches/descriptions/reset), d889c28 (tileSize), fea2128 (handOrder), 43f652a (screenshot). Not pushed at session end.

- Settings.svelte: tabs Calls/Gameplay/Display; inactive panels `hidden` (not unmounted) -> hidden controls drop out of a11y tree, so e2e must click `getByRole('tab', {name:'Display', exact:true})` (or `settings-tab-<id>` testid) first. Switches are checkbox role="switch" -> `getByRole('switch')`.
- New shared components: lib/ui/SegmentedControl.svelte (radio group, generic T), SwitchRow.svelte. LocaleSwitcher now uses SegmentedControl.
- Locale switch reloads -> lands on first tab; e2e uses `.click()` not `.check()` on the locale radio (check() waits forever for checked state on a now-hidden radio).
- DEFAULT_CLIENT_PREFS / DEFAULT_AUTO_ARM exported from settings-storage.ts; every new pref is migrated in loadClientPrefs (validator still only checks soundEnabled+motion).
- tileSize -> html[data-tile-size] -> --tile-scale in app.scss. Rotated left/right opponent strips deliberately NOT scaled (height-bound; melds wrap into backs column at large).
- handOrder manual: live-only; page `manualOrder` + reconcileHandOrder/moveTile (lib/table/hand-order.ts). Live hand tiles now keyed `t-<tile_id>` (drawn too). Drag uses offsetLeft/Top (not getBoundingClientRect) to avoid flip oscillation; release click swallowed in capture phase.
- Running playwright natively: webServer runs bare `vite dev` -> needs `PATH=$PWD/node_modules/.bin:$PATH`. context-mode ctx_execute can't start it (exit 127); use Bash.
- Follow-ups: no "Sort now" button in manual mode; keyboard reorder only works on your turn (tiles focusable only when discardable).
