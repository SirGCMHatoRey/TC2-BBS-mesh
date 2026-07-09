"""Runtime settings the conversation needs: menu items and fortunes.

Loaded on first use rather than at import, so importing a module never reads
the filesystem. Tests call ``configure()`` to supply values directly.
"""

import configparser
from dataclasses import dataclass
from typing import List

CONFIG_FILE = 'config.ini'
FORTUNES_FILE = 'fortunes.txt'


@dataclass(frozen=True)
class Menus:
    """Which letters each menu offers, in order."""

    main: List[str]
    bbs: List[str]
    utilities: List[str]


_menus = None
_fortunes = None


def configure(menus=None, fortunes=None):
    """Override what would otherwise be read from disk."""
    global _menus, _fortunes
    if menus is not None:
        _menus = menus
    if fortunes is not None:
        _fortunes = fortunes


def reset():
    global _menus, _fortunes
    _menus = None
    _fortunes = None


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
