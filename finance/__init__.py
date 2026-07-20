from collections.abc import Mapping

from flask import Flask

from .config import Config
from .db import init_app, init_db


def create_app(test_config: Mapping[str, object] | None = None) -> Flask:
    """Create a configured FinFlow application.

    ``test_config`` keeps tests isolated from the personal SQLite database and
    makes the application factory usable by future CLI and deployment entrypoints.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    init_app(app)

    from .routes.api import api_bp
    from .routes.pages import pages_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        init_db(seed_demo=app.config["SEED_DEMO"])

    return app
