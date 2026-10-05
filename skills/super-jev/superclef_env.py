"""SUPERCLEF_X is the public name for SUPERJEV_X. Importing this copies each set SUPERCLEF_X into SUPERJEV_X (new name wins).
Internals keep reading SUPERJEV_*. Import it before any module that reads the environment."""
import os

NAMES = ("STATE_DIR", "PRINCIPAL", "CLEF_HOST", "CLEF_DIR", "JUDGE", "BIN_DIR", "INSTALL_DIR", "REPO_URL", "SAVE_AFTER", "AUTO_CACHE", "PRIVATE_DIRS", "GATE_CMD", "NEW_FILE_SCAN", "CLEF_IDLE", "CLEF_WARM")


def alias(env=None):
    env = os.environ if env is None else env
    for n in NAMES:
        v = env.get("SUPERCLEF_" + n)
        if v is not None and v != "":
            env["SUPERJEV_" + n] = v
    return env


alias()
