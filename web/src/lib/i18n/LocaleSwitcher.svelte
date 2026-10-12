<script lang="ts">
	import { getLocale, locales, setLocale, type Locale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import SegmentedControl from '$lib/ui/SegmentedControl.svelte';

	const LOCALE_LABEL: Record<Locale, typeof m.localeSwitcher_en> = {
		en: m.localeSwitcher_en,
		'zh-Hant': m.localeSwitcher_zhHant
	};
</script>

<SegmentedControl
	legend={m.localeSwitcher_label()}
	name="locale"
	options={locales.map((locale) => ({
		value: locale,
		label: LOCALE_LABEL[locale]({}, { locale })
	}))}
	value={getLocale()}
	onChange={(locale) => setLocale(locale)}
/>
