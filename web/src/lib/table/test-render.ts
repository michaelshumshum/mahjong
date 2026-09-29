import { mount, unmount } from 'svelte';
import type { Component } from 'svelte';

export interface RenderResult {
	target: HTMLDivElement;
	instance: Record<string, unknown>;
}

const rendered: RenderResult[] = [];

export function render<Props extends Record<string, unknown>>(
	Component: Component<Props, Record<string, unknown>, string>,
	props: Props
): RenderResult {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const instance = mount(Component, { target, props });
	const result = { target, instance };
	rendered.push(result);
	return result;
}

export function cleanup(result: RenderResult): void {
	unmount(result.instance);
	result.target.remove();
	const index = rendered.indexOf(result);
	if (index !== -1) rendered.splice(index, 1);
}

// bulk counterpart to cleanup() -- specs that don't hold on to each render() result
// call this once from afterEach instead of tracking/cleaning up individually.
export function cleanupAll(): void {
	while (rendered.length > 0) {
		const result = rendered.pop()!;
		unmount(result.instance);
		result.target.remove();
	}
}
