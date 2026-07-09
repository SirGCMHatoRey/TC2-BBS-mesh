"""Runtime settings the conversation needs: menu items and fortunes.

Loaded on first use rather than at import, so importing a module never reads
the filesystem. Tests call ``configure()`` to supply values directly.
"""

import configparser
from dataclasses import dataclass
from typing import List

from js8_db import Js8Database

CONFIG_FILE = 'config.ini'
FORTUNES_FILE = 'fortunes.txt'

_UNSET = object()


@dataclass(frozen=True)
class Menus:
    """Which letters each menu offers, in order."""

    main: List[str]
    bbs: List[str]
    utilities: List[str]


_menus = None
_fortunes = None
_js8_db_path = _UNSET
_js8_database = None


def configure(menus=None, fortunes=None, js8_db_path=_UNSET):
    """Override what would otherwise be read from disk."""
    global _menus, _fortunes, _js8_db_path, _js8_database
    if menus is not None:
        _menus = menus
    if fortunes is not None:
        _fortunes = fortunes
    if js8_db_path is not _UNSET:
        _js8_db_path = js8_db_path
        _js8_database = None


def reset():
    global _menus, _fortunes, _js8_db_path, _js8_database
    _menus = None
    _fortunes = None
    _js8_db_path = _UNSET
    _js8_database = None


def _config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def js8_db_path():
    """Where the JS8Call store lives, or None when the bridge is not set up."""
    global _js8_db_path
    if _js8_db_path is _UNSET:
        _js8_db_path = _config().get('js8call', 'db_file', fallback=None)
    return _js8_db_path


def js8_database():
    """The one Js8Database everything shares — reader and writer alike."""
    global _js8_database
    if _js8_database is None:
        _js8_database = Js8Database(js8_db_path())
    return _js8_database


def menus():
    global _menus
    if _menus is None:
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)
        _menus = Menus(
            main=config['menu']['main_menu_items'].split(','),
            bbs=config['menu']['bbs_menu_items'].split(','),
            utilities=config['menu']['utilities_menu_items'].split(','),
        )
    return _menus


def fortunes():
    global _fortunes
    if _fortunes is None:
        try:
            with open(FORTUNES_FILE, 'r') as handle:
                _fortunes = [line.strip() for line in handle if line.strip()]
        except OSError:
            _fortunes = []
    return _fortunes
