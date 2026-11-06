import os
import hmac
import secrets
import pg8000
import requests

from urllib.parse import urlparse, unquote
from functools import wraps
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)

app = Flask(__name__)

# CONFIGURATION
SECRET_KEY = os.getenv("SECRET_KEY")
API_KEY = os.getenv("TMDB_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY manquant dans Render")

app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True

BASE_URL = "https://api.themoviedb.org/3"


# =========================
# CONNEXION SUPABASE
# =========================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant")

    db = urlparse(DATABASE_URL)

    if not db.hostname or not db.username or not db.path:
        raise RuntimeError("DATABASE_URL invalide")

    return pg8000.connect(
        user=unquote(db.username),
        password=unquote(db.password or ""),
        host=db.hostname,
        port=db.port or 5432,
        database=db.path.lstrip("/"),
        ssl_context=True,
        timeout=20
    )


# =========================
# INITIALISATION DATABASE
# =========================

def init_db():
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                poster TEXT,
                tmdb_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    finally:
        cur.close()
        conn.close()


# =========================
# API TMDB
# =========================

def tmdb(endpoint, params=None):
    if not API_KEY:
        return {}

    params = dict(params or {})
    params["api_key"] = API_KEY
    params["language"] = "fr-FR"

    try:
        response = requests.get(
            BASE_URL + endpoint,
            params=params,
            timeout=15
        )

        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        app.logger.error("Erreur TMDB : %s", error)
        return {}


# =========================
# PROTECTION ADMIN
# =========================

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))

        return func(*args, **kwargs)

    return wrapper


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


def check_csrf():
    token = request.form.get("csrf_token", "")
    saved_token = session.get("csrf_token", "")

    if not saved_token or not hmac.compare_digest(token, saved_token):
        return False

    return True


# =========================
# PAGE ACCUEIL
# =========================

@app.route("/")
def home():
    popular = tmdb("/movie/popular").get("results", [])
    trending = tmdb("/trending/movie/week").get("results", [])
    upcoming = tmdb("/movie/upcoming").get("results", [])

    return render_template(
        "index.html",
        popular=popular,
        trending=trending,
        upcoming=upcoming
    )


# =========================
# DETAILS FILM
# =========================

@app.route("/movie/<int:movie_id>")
def movie(movie_id):
    details = tmdb(
        f"/movie/{movie_id}",
        {"append_to_response": "videos,credits"}
    )

    if not details:
        return "Film introuvable ou API indisponible", 404

    return render_template("movie.html", movie=details)


# =========================
# RECHERCHE
# =========================

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    results = []

    if query:
        results = tmdb(
            "/search/movie",
            {"query": query, "page": 1}
        ).get("results", [])

    return render_template(
        "search.html",
        results=results,
        query=query
    )


# =========================
# CATEGORIES
# =========================

@app.route("/genre/<int:genre_id>")
def genre(genre_id):
    movies = tmdb(
        "/discover/movie",
        {
            "with_genres": genre_id,
            "sort_by": "popularity.desc"
        }
    ).get("results", [])

    return render_template(
        "search.html",
        results=movies,
        query="Catégorie"
    )


# =========================
# CONNEXION ADMIN
# =========================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if (
            ADMIN_USERNAME
            and ADMIN_PASSWORD
            and hmac.compare_digest(username, ADMIN_USERNAME)
            and hmac.compare_digest(password, ADMIN_PASSWORD)
        ):
            session.clear()
            session["admin"] = True
            session["csrf_token"] = secrets.token_hex(32)

            return redirect(url_for("admin_dashboard"))

        flash("Identifiants incorrects")

    return render_template("login.html")


# =========================
# DASHBOARD ADMIN
# =========================

@app.route("/admin")
@admin_required
def admin_dashboard():

    try:
        init_db()

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM movies")
        total = cur.fetchone()[0]

        cur.execute("""
            SELECT id, title, description, poster
            FROM movies
            ORDER BY id DESC
        """)

        movies = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "admin.html",
            total=total,
            movies=movies
        )

    except Exception:
        app.logger.exception("Erreur dashboard")
        return "Erreur de connexion à la base de données", 500


# =========================
# AJOUTER UN FILM
# =========================

@app.route("/admin/add", methods=["POST"])
@admin_required
def add_movie():

    if not check_csrf():
        return "Requête invalide", 400

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    poster = request.form.get("poster", "").strip()

    if not title:
        flash("Le titre est obligatoire")
        return redirect(url_for("admin_dashboard"))

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO movies (title, description, poster)
            VALUES (%s, %s, %s)
            """,
            (title, description, poster)
        )

        conn.commit()
        flash("Film ajouté avec succès")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# SUPPRIMER UN FILM
# =========================

@app.route("/admin/delete/<int:movie_id>", methods=["POST"])
@admin_required
def delete_movie(movie_id):

    if not check_csrf():
        return "Requête invalide", 400

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "DELETE FROM movies WHERE id = %s",
            (movie_id,)
        )

        conn.commit()
        flash("Film supprimé")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for("admin_dashboard"))


# =========================
# DECONNEXION
# =========================

@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():

    if not check_csrf():
        return "Requête invalide", 400

    session.clear()

    return redirect(url_for("admin_login"))


# =========================
# DEMARRAGE LOCAL
# =========================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )
