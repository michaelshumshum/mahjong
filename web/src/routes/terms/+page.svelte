<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import LegalPage from '$lib/ui/LegalPage.svelte';
</script>

<LegalPage
	pageTitle={m.termsPage_pageTitle()}
	title={m.termsPage_title()}
	summary={m.termsPage_summary()}
	testId="terms-page"
>
	<section>
		<h2>{m.termsPage_serviceHeading()}</h2>
		<p>{m.termsPage_serviceBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_accountsHeading()}</h2>
		<p>{m.termsPage_accountsBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_conductHeading()}</h2>
		<p>{m.termsPage_conductIntro()}</p>
		<ul>
			<li>{m.termsPage_conductName()}</li>
			<li>{m.termsPage_conductCheat()}</li>
			<li>{m.termsPage_conductHarass()}</li>
			<li>{m.termsPage_conductService()}</li>
		</ul>
		<p>{m.termsPage_conductAction()}</p>
	</section>

	<section>
		<h2>{m.termsPage_gamblingHeading()}</h2>
		<p>{m.termsPage_gamblingBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_namesHeading()}</h2>
		<p>{m.termsPage_namesBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_sourceHeading()}</h2>
		<p>{m.termsPage_sourceBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_warrantyHeading()}</h2>
		<p>{m.termsPage_warrantyBody()}</p>
	</section>

	<section>
		<h2>{m.termsPage_changesHeading()}</h2>
		<p>{m.termsPage_changesBody()}</p>
	</section>
</LegalPage>
