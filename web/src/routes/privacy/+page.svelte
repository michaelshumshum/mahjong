<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import LegalPage from '$lib/ui/LegalPage.svelte';
</script>

<LegalPage
	pageTitle={m.privacyPage_pageTitle()}
	title={m.privacyPage_title()}
	summary={m.privacyPage_summary()}
	testId="privacy-page"
>
	<section>
		<h2>{m.privacyPage_guestHeading()}</h2>
		<ul>
			<li>{m.privacyPage_guestDevice()}</li>
			<li>{m.privacyPage_guestGames()}</li>
			<li>{m.privacyPage_guestNetwork()}</li>
		</ul>
	</section>

	<section>
		<h2>{m.privacyPage_accountHeading()}</h2>
		<p>{m.privacyPage_accountIntro()}</p>
		<ul>
			<li>{m.privacyPage_accountGoogle()}</li>
			<li>{m.privacyPage_accountName()}</li>
			<li>{m.privacyPage_accountSessions()}</li>
			<li>{m.privacyPage_accountGames()}</li>
			<li>{m.privacyPage_accountLearn()}</li>
			<li>{m.privacyPage_accountConsent()}</li>
		</ul>
		<p>{m.privacyPage_accountUse()}</p>
	</section>

	<section>
		<h2>{m.privacyPage_trainingHeading()}</h2>
		<p>{m.privacyPage_trainingOptIn()}</p>
		<p>{m.privacyPage_trainingWithdraw()}</p>
		<p>{m.privacyPage_trainingNow()}</p>
	</section>

	<section>
		<h2>{m.privacyPage_cookiesHeading()}</h2>
		<p>{m.privacyPage_cookiesIntro()}</p>
		<dl class="cookies">
			<dt><code>mj_session</code></dt>
			<dd>{m.privacyPage_cookieSession()}</dd>
			<dt><code>mj_oauth</code></dt>
			<dd>{m.privacyPage_cookieOauth()}</dd>
			<dt><code>PARAGLIDE_LOCALE</code></dt>
			<dd>{m.privacyPage_cookieLocale()}</dd>
		</dl>
		<p>{m.privacyPage_cookiesStorage()}</p>
	</section>

	<section>
		<h2>{m.privacyPage_providersHeading()}</h2>
		<ul>
			<li>{m.privacyPage_providerGoogle()}</li>
			<li>{m.privacyPage_providerAws()}</li>
			<li>{m.privacyPage_providerCloudflare()}</li>
		</ul>
		<p>{m.privacyPage_providersNote()}</p>
	</section>

	<section>
		<h2>{m.privacyPage_keepHeading()}</h2>
		<ul>
			<li>{m.privacyPage_keepAccount()}</li>
			<li>{m.privacyPage_keepDelete()}</li>
			<li>{m.privacyPage_keepGames()}</li>
		</ul>
	</section>

	<section>
		<h2>{m.privacyPage_choicesHeading()}</h2>
		<ul>
			<li>{m.privacyPage_choicesExport()}</li>
			<li>{m.privacyPage_choicesEdit()}</li>
			<li>{m.privacyPage_choicesOther()}</li>
		</ul>
	</section>

	<section>
		<h2>{m.privacyPage_childrenHeading()}</h2>
		<p>{m.privacyPage_childrenBody()}</p>
	</section>

	<section>
		<h2>{m.privacyPage_changesHeading()}</h2>
		<p>{m.privacyPage_changesBody()}</p>
	</section>
</LegalPage>

<style lang="scss">
	.cookies {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-4);

		dt {
			font-size: var(--font-size-sm);
		}

		dd {
			margin: 0;
		}

		@media (max-width: 30rem) {
			grid-template-columns: 1fr;
			gap: var(--space-1);

			dd {
				margin-bottom: var(--space-2);
			}
		}
	}
</style>
