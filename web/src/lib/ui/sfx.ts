import clickUrl from '$lib/assets/sfx/click.mp3';
import type { ClientPrefs } from './client-prefs';

// eight takes of one tile clack, cut from a single recording and level-matched to click.mp3.
const TILE_URLS = Object.values(
	import.meta.glob<string>('$lib/assets/sfx/tile-*.mp3', {
		eager: true,
		query: '?url',
		import: 'default'
	})
);

// native checkbox/radio included: a click on their <label> is re-dispatched on the control.
// links stay silent unless styled as a button and marked `data-sfx="on"`.
const CLICK_TARGET =
	'button, [role="button"], [role="tab"], input[type="checkbox"], input[type="radio"], summary, [data-sfx="on"]';

let enabled = false;
let gain = 1;
let ctx: AudioContext | null = null;
// resolved buffers kept apart from pending decodes so a warm play starts synchronously.
const buffers = new Map<string, AudioBuffer>();
const decoding = new Map<string, Promise<AudioBuffer>>();
let lastTile = -1;

export function applySoundPrefs(prefs: Pick<ClientPrefs, 'soundEnabled' | 'sfxVolume'>): void {
	enabled = prefs.soundEnabled;
	// squared: a linear gain slider crowds all the audible change into its bottom end.
	gain = (prefs.sfxVolume / 100) ** 2;
}

/** Whether a click on `target` is a button-like control that should click. `data-sfx="on"`
 * opts a button-styled link in; `data-sfx="off"` on the control or any ancestor opts it out. */
export function isClickTarget(target: EventTarget | null): boolean {
	if (!(target instanceof Element)) return false;
	const el = target.closest(CLICK_TARGET);
	if (!el || el.closest('[data-sfx="off"]')) return false;
	return el.getAttribute('aria-disabled') !== 'true';
}

// web audio, not <audio>: no ios start lag, and rapid clicks overlap instead of cutting off.
// the context is created inside the first click so autoplay policy lets it run.
async function playClip(url: string): Promise<void> {
	ctx ??= new AudioContext();
	if (ctx.state !== 'running') void ctx.resume();
	const audio = ctx;
	let buffer = buffers.get(url);
	if (!buffer) {
		let pending = decoding.get(url);
		if (!pending) {
			pending = fetch(url)
				.then((res) => res.arrayBuffer())
				.then((bytes) => audio.decodeAudioData(bytes));
			decoding.set(url, pending);
		}
		buffer = await pending;
		buffers.set(url, buffer);
	}
	const source = audio.createBufferSource();
	const level = audio.createGain();
	source.buffer = buffer;
	level.gain.value = gain;
	source.connect(level).connect(audio.destination);
	source.start();
}

function play(url: string): void {
	if (!enabled) return;
	playClip(url).catch(() => {
		decoding.delete(url);
	});
}

/** Plays the click once at the current volume, for the Settings volume slider. */
export function previewClick(): void {
	play(clickUrl);
}

/** Plays a random tile clack, never the same take twice in a row. */
export function playTile(): void {
	const first = lastTile < 0;
	let pick = Math.floor(Math.random() * (TILE_URLS.length - (first ? 0 : 1)));
	if (!first && pick >= lastTile) pick++;
	lastTile = pick;
	play(TILE_URLS[pick]);
}

/** One delegated listener for every button-like control; returns its disposer. `click`, not
 * `pointerdown`: covers keyboard activation and never fires on a disabled button. */
export function installClickSound(root: Document = document): () => void {
	const onClick = (event: Event) => {
		if (isClickTarget(event.target)) play(clickUrl);
	};
	root.addEventListener('click', onClick);
	return () => root.removeEventListener('click', onClick);
}
