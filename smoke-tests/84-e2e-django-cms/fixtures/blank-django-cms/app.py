"""
Content Management API — Django + Django REST Framework

No observability. Run `Observe this project.` to add it.

A RESTful CMS API for managing articles. Supports CRUD operations on articles
with author management and publish/draft workflow. Uses SQLite for storage.
"""

import os
import sys
import django
from django.conf import settings

# ── Django configuration (standalone mode) ─────────────────────────────────────
if not settings.configured:
    settings.configure(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME":   os.environ.get("DB_PATH", ":memory:"),
            }
        },
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
        ],
        MIDDLEWARE=[
            "django.middleware.common.CommonMiddleware",
        ],
        ROOT_URLCONF=__name__,
        SECRET_KEY="dev-secret-change-in-production",
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        ALLOWED_HOSTS=["*"],
        DEBUG=False,
    )
    django.setup()

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Bootstrap DB ───────────────────────────────────────────────────────────────
def _bootstrap_db():
    with connection.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cms_article (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL DEFAULT '',
                author      TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'draft',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


_bootstrap_db()


# ── Views ──────────────────────────────────────────────────────────────────────

@csrf_exempt
def articles_list(request):
    if request.method == "GET":
        with connection.cursor() as cur:
            cur.execute("SELECT id, title, author, status, created_at FROM cms_article ORDER BY id DESC")
            rows = cur.fetchall()
        articles = [
            {"id": r[0], "title": r[1], "author": r[2], "status": r[3], "created_at": r[4]}
            for r in rows
        ]
        return JsonResponse({"articles": articles, "count": len(articles)})

    elif request.method == "POST":
        try:
            body   = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid JSON"}, status=400)

        title  = body.get("title", "").strip()
        text   = body.get("body", "")
        author = body.get("author", "anonymous")
        status = body.get("status", "draft")

        if not title:
            return JsonResponse({"error": "title is required"}, status=400)

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO cms_article (title, body, author, status) VALUES (?, ?, ?, ?)",
                [title, text, author, status]
            )
            article_id = cur.lastrowid

        logger.info(f"Article created: id={article_id} title={title!r} author={author}")
        return JsonResponse({"id": article_id, "title": title, "author": author,
                             "status": status}, status=201)

    return JsonResponse({"error": "method not allowed"}, status=405)


@csrf_exempt
def article_detail(request, article_id):
    if request.method == "GET":
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, title, body, author, status, created_at FROM cms_article WHERE id = ?",
                [article_id]
            )
            row = cur.fetchone()
        if not row:
            return JsonResponse({"error": "article not found"}, status=404)
        return JsonResponse({
            "id": row[0], "title": row[1], "body": row[2],
            "author": row[3], "status": row[4], "created_at": row[5],
        })

    elif request.method == "PUT":
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid JSON"}, status=400)
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE cms_article SET title=?, body=?, status=? WHERE id=?",
                [body.get("title"), body.get("body", ""), body.get("status", "draft"), article_id]
            )
            if cur.rowcount == 0:
                return JsonResponse({"error": "article not found"}, status=404)
        return JsonResponse({"id": article_id, "status": body.get("status", "draft")})

    elif request.method == "DELETE":
        with connection.cursor() as cur:
            cur.execute("DELETE FROM cms_article WHERE id = ?", [article_id])
            if cur.rowcount == 0:
                return JsonResponse({"error": "article not found"}, status=404)
        return JsonResponse({"deleted": True, "id": article_id})

    return JsonResponse({"error": "method not allowed"}, status=405)


def health(request):
    return JsonResponse({"status": "ok"})


# ── URL configuration ──────────────────────────────────────────────────────────
from django.urls import path

urlpatterns = [
    path("api/articles/",                  articles_list),
    path("api/articles/<int:article_id>/", article_detail),
    path("health/",                        health),
]


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    port = os.environ.get("PORT", "5000")
    execute_from_command_line(["manage.py", "runserver", f"0.0.0.0:{port}", "--noreload"])
