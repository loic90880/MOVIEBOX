import os
import requests

from flask import Flask, render_template, request

app = Flask(__name__)

API_KEY = os.getenv("TMDB_API_KEY", "")
BASE_URL = "https://api.themoviedb.org/3"

def tmdb(endpoint, params=None):
    if not API_KEY:
        return {}

    params = params or {}
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
    except requests.RequestException:
        return {}


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


@app.route("/movie/<int:movie_id>")
def movie(movie_id):
    details = tmdb(f"/movie/{movie_id}", {
        "append_to_response": "videos,credits"
    })

    if not details:
        return "Film introuvable ou API indisponible", 404

    return render_template("movie.html", movie=details)


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    results = []

    if query:
        results = tmdb("/search/movie", {
            "query": query,
            "page": 1
        }).get("results", [])

    return render_template(
        "search.html",
        results=results,
        query=query
    )


@app.route("/genre/<int:genre_id>")
def genre(genre_id):
    movies = tmdb("/discover/movie", {
        "with_genres": genre_id,
        "sort_by": "popularity.desc"
    }).get("results", [])

    return render_template(
        "search.html",
        results=movies,
        query="Catégorie"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
