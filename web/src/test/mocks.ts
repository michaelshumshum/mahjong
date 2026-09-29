// stand-in for paraglide's generated `m` object: any `m.someKey(...)` call resolves to the
// key name itself, so specs can assert on message keys without real translated strings.
export function createMessagesProxy(): Record<string, (...args: unknown[]) => string> {
	return new Proxy(
		{},
		{
			get(_target, prop: string) {
				return () => prop;
			}
		}
	) as Record<string, (...args: unknown[]) => string>;
}
