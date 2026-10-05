/** SUPERCLEF_X is the public name for SUPERJEV_X: copy each set one over (new name wins).
 * Same name list as skills/super-jev/superclef_env.py. Internals keep reading SUPERJEV_*. */
export const ALIAS_NAMES = ['STATE_DIR', 'PRINCIPAL', 'CLEF_HOST', 'CLEF_DIR', 'JUDGE', 'BIN_DIR', 'INSTALL_DIR', 'REPO_URL', 'SAVE_AFTER', 'AUTO_CACHE', 'PRIVATE_DIRS', 'GATE_CMD', 'NEW_FILE_SCAN'];

export function aliasEnv(env: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  for (const n of ALIAS_NAMES) if (env['SUPERCLEF_' + n]) env['SUPERJEV_' + n] = env['SUPERCLEF_' + n];
  return env;
}
