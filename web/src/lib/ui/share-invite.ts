export type ShareOutcome = 'shared' | 'copied' | 'cancelled' | 'failed';

type ShareNavigator = Pick<Navigator, 'clipboard'> & {
	share?: Navigator['share'];
	canShare?: Navigator['canShare'];
};

/** The OS share sheet where the browser has one (phones), else the clipboard. */
export async function shareOrCopy(
	data: { url: string; title: string; text: string },
	nav: ShareNavigator = navigator
): Promise<ShareOutcome> {
	if (nav.share && (!nav.canShare || nav.canShare(data))) {
		try {
			await nav.share(data);
			return 'shared';
		} catch (err) {
			// dismissing the sheet rejects with AbortError -- a choice, not a failure.
			if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled';
		}
	}
	try {
		await nav.clipboard.writeText(data.url);
		return 'copied';
	} catch {
		return 'failed';
	}
}
