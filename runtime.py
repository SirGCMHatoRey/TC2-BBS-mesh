"""The resolved application: configuration and the stores built from it.

Assembled once at startup in `server.main()` and handed to the router. It is
frozen and passed, never reached for — the opposite of the interface global
that candidate 01 removed. Bundling the three keeps the router's signatures
small; a flow still receives only what it needs, through `Deps`.
"""

from dataclasses import dataclass

from database import Database
from js8_db import Js8Database
from settings import Config


@dataclass(frozen=True)
class Runtime:
    config: Config
    database: Database
    js8_database: Js8Database
