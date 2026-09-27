<script lang="ts">
	import { getLocale, locales, setLocale, type Locale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import FormGroup from '$lib/ui/FormGroup.svelte';
	import OptionRow from '$lib/ui/OptionRow.svelte';

	const LOCALE_LABEL: Record<Locale, typeof m.localeSwitcher_en> = {
		en: m.localeSwitcher_en,
		'zh-Hant': m.localeSwitcher_zhHant
	};
</script>

<FormGroup legend={m.localeSwitcher_label()}>
	{#each locales as locale (locale)}
		<OptionRow
			type="radio"
			name="locale"
			value={locale}
			label={LOCALE_LABEL[locale]({}, { locale })}
			checked={getLocale() === locale}
			onChange={() => setLocale(locale)}
		/>
	{/each}
</FormGroup>
