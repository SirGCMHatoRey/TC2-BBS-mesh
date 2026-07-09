"""Runtime settings the conversation needs: menu items and fortunes.

Loaded on first use rather than at import, so importing a module never reads
the filesystem. Tests call ``configure()`` to supply values directly.
"""

import configparser
from dataclasses import dataclass
from typing import List

from js8_db import Js8Database

DEFAULT_CONFIG_FILE = 'config.ini'
FORTUNES_FILE = 'fortunes.txt'

_UNSET = object()


@dataclass(frozen=True)
class Menus:
    """Which letters each menu offers, in order."""

    main: List[str]
    bbs: List[str]
    utilities: List[str]


_config_file = DEFAULT_CONFIG_FILE
_menus = None
_fortunes = None
_js8_db_path = _UNSET
_js8_database = None
_bbs_nodes = None
_allowed_nodes = None


def configure(menus=None, fortunes=None, js8_db_path=_UNSET,
              config_file=None, bbs_nodes=None, allowed_nodes=None):
    """Override what would otherwise be read from disk."""
    global _config_file, _menus, _fortunes, _js8_db_path, _js8_database
    global _bbs_nodes, _allowed_nodes
    if config_file is not None:
        # --config used to reach only the interface and sync sections; menus
        # and the JS8Call settings always came from ./config.ini regardless.
        _config_file = config_file
    if menus is not None:
        _menus = menus
    if fortunes is not None:
        _fortunes = fortunes
    if js8_db_path is not _UNSET:
        _js8_db_path = js8_db_path
        _js8_database = None
    if bbs_nodes is not None:
        _bbs_nodes = list(bbs_nodes)
    if allowed_nodes is not None:
        _allowed_nodes = list(allowed_nodes)


def reset():
    global _config_file, _menus, _fortunes, _js8_db_path, _js8_database
    global _bbs_nodes, _allowed_nodes
    _config_file = DEFAULT_CONFIG_FILE
    _menus = None
    _fortunes = None
    _js8_db_path = _UNSET
    _js8_database = None
    _bbs_nodes = None
    _allowed_nodes = None


def config_file():
    """The config file in force — honours --config, unlike the old hardcoding."""
    return _config_file


def _config():
    config = configparser.ConfigParser()
    config.read(_config_file)
    return config


def _node_list(section, option):
    raw = _config().get(section, option, fallback='')
    return [entry.strip() for entry in raw.split(',') if entry.strip()]


def bbs_nodes():
    """Peer BBS servers to replicate with. Config, not radio."""
    global _bbs_nodes
    if _bbs_nodes is None:
        _bbs_nodes = _node_list('sync', 'bbs_nodes')
    return _bbs_nodes


def allowed_nodes():
    """Nodes permitted to post to the Urgent board. Empty means anyone may."""
    global _allowed_nodes
    if _allowed_nodes is None:
        _allowed_nodes = _node_list('allow_list', 'allowed_nodes')
    return _allowed_nodes


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
        config = _config()
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
