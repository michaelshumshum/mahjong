// client-only settings shapes (Settings.svelte edits them, settings-storage.ts persists them).

// pre-arm toggles sent via `auto`, enforced server-side. No `auto_win` on purpose -- declining
// a win is a real strategic choice under min_faan rulesets, so it always opens a real claim_offer.
export interface AutoArm {
	noCalls: boolean;
	autoPassChow: boolean;
}

export type MotionPref = 'system' | 'reduced' | 'full';

// two-step: tap/click lifts a tile, a second tap/Enter on it discards -- lets you see the
// full tile before committing. one-tap: today's original behaviour.
export type DiscardMode = 'two-step' | 'one-tap';

export type TileSize = 'small' | 'medium' | 'large';

// manual: tiles stay where the player drags them; new tiles join at the right.
export type HandOrder = 'auto' | 'manual';

// client-only prefs, no wire equivalent. `haptics` is separate from `motion`: vibration is
// always feature-detected to mobile, this setting only gates whether it fires at all.
export interface ClientPrefs {
	soundEnabled: boolean;
	// 0-100 in steps of 5, perceived loudness; sfx.ts squares it into a gain.
	sfxVolume: number;
	motion: MotionPref;
	discardMode: DiscardMode;
	haptics: boolean;
	// screen-reader verbosity: every discard, not just claim-relevant ones (frontend.md §9).
	announceAllDiscards: boolean;
	tileSize: TileSize;
	handOrder: HandOrder;
}
