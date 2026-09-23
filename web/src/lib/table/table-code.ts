// table ids are generated server-side (POST /tables, server/app/main.py's create_table) --
// this is just the shape a code has, for the join-by-code input's maxlength and any client-side
// display. Any code still works as a direct WS connect target regardless of whether it was ever
// minted via POST /tables (docs/03-frontend.md's "/table/[id] wiring": auto-created on first
// WS connect), so there is nothing to validate client-side before navigating.
export const TABLE_CODE_LENGTH = 6;
