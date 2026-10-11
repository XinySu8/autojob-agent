"""Print the API's OpenAPI schema (used by `npm run gen:api` to generate TypeScript types)."""

import copy
import json
import tempfile
from pathlib import Path

from autojob.api import create_app
from autojob.config import DEFAULTS, Workspace
from autojob.db import Database

ws = Workspace(root=Path(tempfile.gettempdir()), cfg=copy.deepcopy(DEFAULTS))
print(json.dumps(create_app(ws, db=Database("sqlite://")).openapi(), indent=2))
