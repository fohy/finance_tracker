from collections.abc import Mapping
from pathlib import Path

from flask import Flask, url_for

from .auth import init_auth
from .cli import init_cli
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

    if app.config["APP_ENV"] == "production" and app.config["SECRET_KEY"] == "local-finance-secret":
        raise RuntimeError("В production необходимо задать уникальный SECRET_KEY")

    init_app(app)
    init_auth(app)
    init_cli(app)

    from .routes.api import api_bp
    from .routes.auth import auth_bp
    from .routes.insights_api import insights_api_bp
    from .routes.pages import pages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(insights_api_bp, url_prefix="/api")

    @app.template_global()
    def asset_url(filename: str) -> str:
        """Return a static URL versioned by the asset modification time."""
        static_folder = Path(app.static_folder or "")
        try:
            version = static_folder.joinpath(filename).stat().st_mtime_ns
        except OSError:
            version = "missing"
        return url_for("static", filename=filename, v=version)

    with app.app_context():
        init_db(seed_demo=app.config["SEED_DEMO"])

    return app
