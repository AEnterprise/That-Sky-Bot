import asyncio
from collections import deque
from dataclasses import dataclass
import json

from utils import Logging, Utils

MASTER_CONFIG = dict()
MASTER_LOADED = False
PERSISTENT = dict()
PERSISTENT_LOADED = False
PERSISTENT_DEQUE = deque()
PERSISTENT_LOCK = False
PERSISTENT_AIO_QUEUE: asyncio.Queue


@dataclass()
class PersistentAction:
    delete: bool = False
    key: str = None
    value: str = None
    tolerate_missing: bool = False


def save():
    global MASTER_CONFIG
    with open('config.json', 'w') as jsonfile:
        jsonfile.write((json.dumps(MASTER_CONFIG, indent=4, skipkeys=True, sort_keys=True)))
        jsonfile.close()


# Ugly but this prevents import loop errors
def load():
    global MASTER_CONFIG, MASTER_LOADED
    try:
        with open('config.json', 'r') as jsonfile:
            MASTER_CONFIG = json.load(jsonfile)
            MASTER_LOADED = True
    except FileNotFoundError:
        Logging.error("Unable to load config, running with defaults.")
    except Exception as e:
        Logging.error("Failed to parse configuration.")
        print(e)
        raise e


def get_var(key, default=None):
    global MASTER_CONFIG, MASTER_LOADED
    if not MASTER_LOADED:
        load()
    if key not in MASTER_CONFIG.keys():
        MASTER_CONFIG[key] = default
        save()
    return MASTER_CONFIG[key]


def load_persistent():
    global PERSISTENT_LOADED, PERSISTENT
    PERSISTENT = Utils.fetch_from_disk('persistent')
    PERSISTENT_LOADED = True


def get_persistent_var(key, default=None):
    if not PERSISTENT_LOADED:
        load_persistent()
    return PERSISTENT[key] if key in PERSISTENT else default


def set_persistent_var(key, value):
    PERSISTENT_AIO_QUEUE.put_nowait(PersistentAction(key=key, value=value))


def del_persistent_var(key, tolerate_missing=False):
    PERSISTENT_AIO_QUEUE.put_nowait(PersistentAction(key=key, delete=True, tolerate_missing=tolerate_missing))


def do_persistent_action(action: PersistentAction):
    if action.delete and action.key:
        # DELETE
        try:
            del PERSISTENT[action.key]
            # Logging.info("save persistent delete")
            Utils.save_to_disk("persistent", PERSISTENT)
        except KeyError as e:
            if action.tolerate_missing:
                Logging.info(f'skipping delete for `{action.key}`')
                return
            Logging.info(f'NOT skipping delete for `{action.key}`')
            Utils.get_embed_and_log_exception(f"cannot delete nonexistent persistent var `{action.key}`", e)
        except Exception as e:
            Utils.get_embed_and_log_exception(f"---delete persistent var failed--- key `{action.key}`", e)
    elif not action.delete and action.key:
        # SAVE/CREATE
        PERSISTENT[action.key] = action.value
        # Logging.info("save persistent")
        Utils.save_to_disk("persistent", PERSISTENT)
