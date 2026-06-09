import streamlit as st
import streamlit.components.v1 as components
import pickle
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random
import time

# Load data
movie_list = pickle.load(open("movie.pkl", "rb"))
similarity = pickle.load(open("similarity.pkl", "rb"))

st.set_page_config(layout="wide")

# ─── Robust HTTP Session with retry + timeout ───────────────────────────────
@st.cache_resource
def get_http_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,          # waits 0.5s, 1s, 2s between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

API_KEY = "8265bd1679663a7ea12ac168da84d2e8"
BASE_URL = "https://api.themoviedb.org/3"
TIMEOUT  = 8   # seconds per request

# ─── Cached API helpers ──────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_movie_details(movie_id):
    """Returns movie detail dict or {} on failure. Errors are silent."""
    try:
        session = get_http_session()
        r = session.get(
            f"{BASE_URL}/movie/{movie_id}",
            params={"api_key": API_KEY, "language": "en-US"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_poster(movie_id):
    data = fetch_movie_details(movie_id)
    path = data.get("poster_path")
    if path:
        return f"https://image.tmdb.org/t/p/w500{path}"
    # Use a reliable placeholder (placehold.co works without JS)
    return "https://placehold.co/500x750/1a1a2e/ffffff?text=No+Poster"

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_trailer(movie_id):
    try:
        session = get_http_session()
        r = session.get(
            f"{BASE_URL}/movie/{movie_id}/videos",
            params={"api_key": API_KEY, "language": "en-US"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for video in r.json().get("results", []):
            if video["site"] == "YouTube" and video["type"] == "Trailer":
                return f"https://www.youtube.com/embed/{video['key']}"
    except Exception:
        pass
    return None

# ─── App Title ───────────────────────────────────────────────────────────────
st.markdown("""
    <div style='text-align: center; padding: 20px 0 40px 0;'>
        <h1 style='
            font-size: 3.5em;
            font-weight: 900;
            background: -webkit-linear-gradient(45deg, #ff4b1f, #1fddff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.1em;
        '>CouchCritic</h1>
        <h3 style='
            font-style: italic;
            color: #888;
            font-weight: 400;
            letter-spacing: 0.5px;
        '>Lazy picks, smart choices 🎥🍿</h3>
    </div>
""", unsafe_allow_html=True)

# ─── Banner (cached so it doesn't re-fire on every interaction) ──────────────
# Pick a random movie ID once per session and store it
if "banner_movie_id" not in st.session_state:
    st.session_state.banner_movie_id = random.choice(movie_list["id"].tolist())

banner_id   = st.session_state.banner_movie_id
banner_data = fetch_movie_details(banner_id)

if banner_data:
    title    = banner_data.get("title", "Unknown Title")
    rating   = round(banner_data.get("vote_average", 0), 2)
    overview = banner_data.get("overview", "No description available.")[:200] + "…"
    trailer  = fetch_trailer(banner_id)

    if trailer:
        st.markdown(f"## 🎬 {title} &nbsp; (IMDb: {rating} ⭐)")
        st.markdown(f"**{overview}**")
        components.html(
            f'<iframe width="100%" height="500" src="{trailer}?autoplay=0&mute=1&controls=1" '
            f'frameborder="0" allow="accelerometer; autoplay; clipboard-write; '
            f'encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>',
            height=500,
        )
    else:
        st.info("🎬 Trailer not available for the featured movie.")
else:
    st.info("🎬 Featured movie could not be loaded right now.")

# ─── Session state ───────────────────────────────────────────────────────────
for key, default in [("show_recommendations", False), ("trailer_to_play", None),
                     ("last_movie", None), ("cached_recs", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─── Movie selector ──────────────────────────────────────────────────────────
st.markdown("## 🎯 Select a Movie to Get Recommendations")
selected_movie = st.selectbox("Choose a movie", movie_list["title"].values)

if st.button("Get Recommendations 🎯"):
    st.session_state.show_recommendations = True
    st.session_state.trailer_to_play      = None
    # Clear cache only when the movie changes, so repeated clicks don't re-fetch
    if st.session_state.last_movie != selected_movie:
        st.session_state.last_movie   = selected_movie
        st.session_state.cached_recs  = None

# ─── Recommend function ──────────────────────────────────────────────────────
def recommend(movie):
    index       = movie_list[movie_list["title"] == movie].index[0]
    distances   = similarity[index]
    recommended = sorted(enumerate(distances), reverse=True, key=lambda x: x[1])[1:6]

    titles, posters, ids = [], [], []
    for idx, _ in recommended:
        mid = movie_list.iloc[idx].id
        ids.append(mid)
        titles.append(movie_list.iloc[idx].title)

    # Fetch posters with a small delay between calls to avoid rate-limiting
    for mid in ids:
        posters.append(fetch_poster(mid))
        time.sleep(0.1)   # 100 ms gap — gentle on the API

    return titles, posters, ids

# ─── Display recommendations ─────────────────────────────────────────────────
if st.session_state.show_recommendations:
    # Use cached results when available so trailer clicks don't re-fetch
    if st.session_state.cached_recs is None:
        with st.spinner("Fetching recommendations…"):
            names, images, movie_ids = recommend(selected_movie)
            st.session_state.cached_recs = (names, images, movie_ids)
    else:
        names, images, movie_ids = st.session_state.cached_recs

    st.markdown("### 🍿 You Might Also Like")
    cols = st.columns(len(names))

    for i in range(len(names)):
        with cols[i]:
            st.image(images[i], use_container_width=True)
            st.caption(names[i])
            with st.form(f"form_{i}"):
                if st.form_submit_button("▶ Watch Trailer"):
                    st.session_state.trailer_to_play = movie_ids[i]

    # Trailer preview
    if st.session_state.trailer_to_play:
        trailer_url = fetch_trailer(st.session_state.trailer_to_play)
        if trailer_url:
            st.markdown("### 🎞️ Trailer Preview")
            components.html(
                f'<iframe width="100%" height="400" src="{trailer_url}?autoplay=1&mute=0&controls=1" '
                f'frameborder="0" allow="accelerometer; autoplay; clipboard-write; '
                f'encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>',
                height=400,
            )
        else:
            st.warning("Trailer not found for the selected movie.")
