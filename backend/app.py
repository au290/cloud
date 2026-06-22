"""Flask application factory for the MiniStack storage portal.

Serves the JSON API under /api/* and the static frontend at /. Run with:
    python app.py            # dev server
    flask --app app run      # alternative
"""
import logging
import os
import traceback

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

from database import engine, db_session, Base

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("iaas")

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


def _migrate():
    """In-place migrations for an existing Postgres DB (create_all won't ALTER).

    Idempotent and Postgres-only — fresh databases already have these via create_all.
    """
    if engine.url.get_backend_name() != "postgresql":
        return
    from sqlalchemy import text
    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS credits NUMERIC(10,2) NOT NULL DEFAULT 0",
        "ALTER TYPE logaction ADD VALUE IF NOT EXISTS 'credit_added'",
        "ALTER TYPE logaction ADD VALUE IF NOT EXISTS 'payment'",
    ]
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                log.warning("Migration step skipped (%s): %s", stmt[:48], e)


def init_db():
    """Create tables, run migrations, then seed packages + admin. Safe to call repeatedly."""
    import models  # noqa: F401 — registers tables on Base.metadata
    Base.metadata.create_all(bind=engine)
    _migrate()
    try:
        from seed import run as seed
        seed()
    except Exception as e:
        log.warning("Seed step skipped: %s", e)

    # If MiniStack is reachable, re-create any buckets it lost on its last restart
    # so the DB and the storage engine agree. Skipped quietly when MiniStack is down.
    try:
        import ministack_client as ms
        ms.list_buckets()  # cheap reachability probe (fast timeout in the client)
        from provisioning import reconcile_buckets
        n = reconcile_buckets()
        if n:
            log.info("Ensured %d bucket(s) exist in MiniStack.", n)
    except Exception as e:
        log.info("Bucket reconcile skipped (MiniStack unavailable): %s", e)
    finally:
        # reconcile_buckets queries via the scoped session; release the connection so
        # we don't leave one idle-in-transaction (which would block later DDL/drops).
        db_session.remove()


def create_app(run_init: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)

    origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": origins or "*"}})

    if run_init:
        with app.app_context():
            init_db()

    # Blueprints
    from routers.auth import bp as auth_bp
    from routers.packages import bp as packages_bp
    from routers.subscriptions import bp as subscriptions_bp
    from routers.credentials import bp as credentials_bp
    from routers.objects import bp as objects_bp
    from routers.logs import bp as logs_bp
    from routers.admin import bp as admin_bp

    for bp in (auth_bp, packages_bp, subscriptions_bp, credentials_bp,
               objects_bp, logs_bp, admin_bp):
        app.register_blueprint(bp)

    # Release the scoped session at the end of every request/app context.
    @app.teardown_appcontext
    def _shutdown_session(exc=None):
        db_session.remove()

    @app.errorhandler(404)
    def _not_found(e):
        from flask import request
        if request.path.startswith("/api/"):
            return jsonify({"detail": "Not found"}), 404
        return _serve_frontend(request.path.lstrip("/"))

    @app.errorhandler(Exception)
    def _unhandled(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({"detail": e.description}), e.code
        log.error("Unhandled error:\n%s", traceback.format_exc())
        db_session.rollback()
        return jsonify({"detail": "Internal server error"}), 500

    @app.get("/api/config")
    def public_config():
        """Public, non-secret config the dashboard needs to render API/CLI examples."""
        import ministack_client as ms
        return jsonify({"ministack_endpoint": ms.ENDPOINT, "region": ms.REGION})

    @app.get("/api/health")
    def health():
        db_ok = ms_ok = False
        try:
            from sqlalchemy import text
            db_session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            log.warning("Health: DB unreachable: %s", e)
        try:
            import ministack_client as ms
            ms.list_buckets()
            ms_ok = True
        except Exception as e:
            log.warning("Health: MiniStack unreachable: %s", e)
        return jsonify({
            "status": "ok" if (db_ok and ms_ok) else "degraded",
            "database": "connected" if db_ok else "unreachable",
            "ministack": "connected" if ms_ok else "unreachable",
        })

    # --- Static frontend ----------------------------------------------------
    @app.get("/")
    def _index():
        return _serve_frontend("index.html")

    @app.get("/<path:path>")
    def _static(path):
        return _serve_frontend(path)

    return app


def _serve_frontend(path: str):
    if not path:
        path = "index.html"
    full = os.path.join(FRONTEND_DIR, path)
    if not os.path.isfile(full):
        # SPA-ish fallback for bare page names
        if os.path.isfile(os.path.join(FRONTEND_DIR, "index.html")):
            return send_from_directory(FRONTEND_DIR, "index.html")
        return jsonify({"detail": "Not found"}), 404
    return send_from_directory(FRONTEND_DIR, path)


app = create_app()


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    # threaded=True so a large upload doesn't block every other request on the
    # single-threaded dev server. For production use a real WSGI server (waitress/gunicorn).
    app.run(host=host, port=port, threaded=True, debug=os.getenv("FLASK_DEBUG") == "1")
