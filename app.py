# Flask routes only (AGENTS.md section 7). Owner: Emmanuel.
# Malama's M0 task added just GET /health (docs/MVP_PLAN.md, M0), so Render can see the app is up
# and the database answers. Emmanuel's routes and the startup sandbox guard come in his step 2.3.

import logging

import psycopg
from flask import Flask

import config
import db

logger = logging.getLogger(__name__)

app = Flask(__name__)


# Render (and later an optional pinger) calls this to wake the app and check it works.
# "ok" means the app is running AND the database answered SELECT 1. Otherwise the answer is
# 503 (Service Unavailable) with a short message. The error itself is never shown, because it
# could name the database host (docs/SECURITY.md); only its type is logged.
# The inner try/finally closes the connection even if the query fails.
@app.route("/health")
def health():
    try:
        conn = db.connect(config.DATABASE_URL)
        try:
            db.fetch_one(conn, "SELECT 1")
        finally:
            conn.close()
    except (RuntimeError, psycopg.Error) as error:
        logger.warning("/health: database check failed (%s)", type(error).__name__)
        return "database unavailable", 503
    return "ok"
