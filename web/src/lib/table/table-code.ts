// invite codes are entirely client-generated (docs/03-frontend.md's "/table/[id] wiring": `[id]`
// is a real table id, auto-created against the backend on first WS connect), so there is nothing
// to validate client-side before navigating.
const TABLE_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I — avoids look-alikes
export const TABLE_CODE_LENGTH = 6;

export function generateTableCode(): string {
	let code = '';
	for (let i = 0; i < TABLE_CODE_LENGTH; i++) {
		code += TABLE_CODE_ALPHABET[Math.floor(Math.random() * TABLE_CODE_ALPHABET.length)];
	}
	return code;
}
