// .svelte.spec.ts for the client project's real DOM (label -> control click re-dispatch).
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { applySoundPrefs, installClickSound, isClickTarget, previewClick } from './sfx';

let starts = 0;
let lastGain: number | null = null;

class FakeAudioContext {
	state = 'running';
	destination = {};
	resume = async () => {};
	decodeAudioData = async () => ({});
	createBufferSource() {
		return { buffer: null, connect: (node: unknown) => node, start: () => void starts++ };
	}
	createGain() {
		const node = {
			gain: { value: 1 },
			connect: () => {
				lastGain = node.gain.value;
			}
		};
		return node;
	}
}

function setSoundEnabled(on: boolean, volume = 100): void {
	applySoundPrefs({ soundEnabled: on, sfxVolume: volume });
}

function el(html: string): HTMLElement {
	const host = document.createElement('div');
	host.innerHTML = html;
	document.body.append(host);
	return host;
}

describe('sfx', () => {
	let dispose: () => void;

	beforeAll(async () => {
		vi.stubGlobal('AudioContext', FakeAudioContext);
		vi.stubGlobal('fetch', async () => new Response(new ArrayBuffer(8)));
		dispose = installClickSound();
		// warm the decode so later plays are synchronous
		setSoundEnabled(true);
		el('<button id="warm">x</button>').querySelector('button')!.click();
		await vi.waitFor(() => expect(starts).toBe(1));
	});

	afterAll(() => {
		dispose();
		vi.unstubAllGlobals();
		document.body.replaceChildren();
	});

	beforeEach(() => {
		starts = 0;
		setSoundEnabled(true);
	});

	it('plays on a button click', () => {
		el('<button><span>label</span></button>').querySelector('span')!.click();
		expect(starts).toBe(1);
	});

	it('is silent while sound is disabled', () => {
		setSoundEnabled(false);
		el('<button>x</button>').querySelector('button')!.click();
		expect(starts).toBe(0);
	});

	it('plays once for a switch clicked through its label', () => {
		el('<label><input type="checkbox" role="switch" /> Sound</label>')
			.querySelector('label')!
			.click();
		expect(starts).toBe(1);
	});

	it('is silent for a non-control click and a disabled button', () => {
		el('<div>text</div>').querySelector('div')!.click();
		el('<button disabled>x</button>').querySelector('button')!.click();
		expect(starts).toBe(0);
	});

	it('stops after the disposer runs', () => {
		dispose();
		el('<button>x</button>').querySelector('button')!.click();
		expect(starts).toBe(0);
		dispose = installClickSound();
	});

	it('scales the gain by the square of the volume', () => {
		setSoundEnabled(true, 50);
		el('<button>x</button>').querySelector('button')!.click();
		expect(lastGain).toBe(0.25);
	});

	it('previewClick plays without a target, but not while disabled', () => {
		previewClick();
		expect(starts).toBe(1);
		setSoundEnabled(false);
		previewClick();
		expect(starts).toBe(1);
	});

	it('isClickTarget honours data-sfx="off" and aria-disabled', () => {
		const host = el(
			'<div data-sfx="off"><button id="a">a</button></div>' +
				'<div role="button" aria-disabled="true" id="b">b</div>' +
				'<div role="tab" id="c">c</div>'
		);
		expect(isClickTarget(host.querySelector('#a'))).toBe(false);
		expect(isClickTarget(host.querySelector('#b'))).toBe(false);
		expect(isClickTarget(host.querySelector('#c'))).toBe(true);
		expect(isClickTarget(null)).toBe(false);
	});

	it('isClickTarget skips plain links but takes opted-in links and <summary>', () => {
		const host = el(
			'<a href="#x" id="plain">x</a>' +
				'<a href="#y" data-sfx="on" id="opted"><span id="inner">y</span></a>' +
				'<details><summary id="sum">more</summary></details>'
		);
		expect(isClickTarget(host.querySelector('#plain'))).toBe(false);
		expect(isClickTarget(host.querySelector('#inner'))).toBe(true);
		expect(isClickTarget(host.querySelector('#sum'))).toBe(true);
	});
});
