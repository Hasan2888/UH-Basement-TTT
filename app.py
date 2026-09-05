import streamlit as st
import pandas as pd
import calendar
import json
import os
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# File path for persistent analytics (or use your main database/json file)
ANALYTICS_FILE = "analytics.json"

def load_analytics():
    """Loads view counts from disk."""
    if os.path.exists(ANALYTICS_FILE):
        try:
            with open(ANALYTICS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_views": 0, "unique_visitors": []}

def save_analytics(data):
    """Saves view counts permanently."""
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Page Setup & UH Branding ---
st.set_page_config(page_title="UH Table Tennis", page_icon="🏓", layout="centered")

# --- TRACK VISITS (Runs once per browser session) ---
if "visited" not in st.session_state:
    st.session_state["visited"] = True
    analytics = load_analytics()

    # 1. Increment total view count
    analytics["total_views"] += 1

    # 2. Extract real client IP from Streamlit Cloud headers
    visitor_ip = None
    try:
        if "X-Forwarded-For" in st.context.headers:
            visitor_ip = st.context.headers["X-Forwarded-For"].split(",")[0].strip()
    except Exception:
        pass

    # Static fallback for local development so refreshes aren't treated as new users
    if not visitor_ip:
        visitor_ip = "local_dev_user"

    # 3. Register unique visitor if unseen
    if visitor_ip not in analytics["unique_visitors"]:
        analytics["unique_visitors"].append(visitor_ip)

    save_analytics(analytics)


# UH Red Custom CSS
st.markdown("""
    <style>
        .stButton>button {
            border-radius: 8px;
        }
        div[data-baseweb="tab-list"] button[aria-selected="true"] {
            color: #C8102E !important;
            border-bottom-color: #C8102E !important;
        }
        h1 {
            color: #C8102E;
        }
    </style>
""", unsafe_allow_html=True)


# --- Database Engine Setup ---
@st.cache_resource
def get_db_engine():
    db_url = URL.create(
        drivername="postgresql+psycopg2",
        username=st.secrets["postgres"]["user"],
        password=st.secrets["postgres"]["password"],
        host=st.secrets["postgres"]["host"],
        port=st.secrets["postgres"]["port"],
        database=st.secrets["postgres"]["database"],
        query={"sslmode": "require"}
    )
    return create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


engine = get_db_engine()


# --- Helper Functions ---
def calculate_elo_delta(winner_elo: int, loser_elo: int, winner_sets: int, loser_sets: int) -> int:
    k_factor = 35 if winner_sets == 2 and loser_sets == 0 else 28
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    delta = round(k_factor * (1 - expected_winner))
    return max(1, delta)


def fetch_players():
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM players ORDER BY elo DESC, wins DESC"), conn)
    return df


# --- UI Header ---
col_logo, col_title = st.columns([1, 5])
with col_logo:
    st.image("UH_logo.jpeg", width=100)  # Matches filename in your project folder
with col_title:
    st.title(" UH Basement Table Tennis Tournament 🏓")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Leaderboard", "Log Match", "Add Player", "Match History", "Admin"])

# --- Tab 1: Leaderboard ---
with tab1:
    st.subheader("🏆 Top 10 Leaderboard")

    # --- Monthly Reset Countdown ---
    today = datetime.now()
    _, last_day = calendar.monthrange(today.year, today.month)
    days_left = last_day - today.day

    st.caption(
        f"⏳ **Monthly Reset:** {days_left} day{'s' if days_left != 1 else ''} remaining"
    )
    # -------------------------------

    # Fetch players from database (keep your working query line here)
    players_df = pd.read_sql("SELECT * FROM players;", engine)

    if not players_df.empty:
        # Map database column names flexibly
        cols_lower = {str(c).lower().replace(" ", "_"): c for c in players_df.columns}

        name_col = cols_lower.get('name') or cols_lower.get('player_name') or players_df.columns[0]
        elo_col = cols_lower.get('elo') or cols_lower.get('rating') or players_df.columns[1]
        wins_col = cols_lower.get('wins')
        losses_col = cols_lower.get('losses')

        streak_col = (
                cols_lower.get('streak') or
                cols_lower.get('win_streak') or
                cols_lower.get('current_streak') or
                cols_lower.get('w_streak')
        )
        win_pct_col = (
                cols_lower.get('win_pct') or
                cols_lower.get('win_%') or
                cols_lower.get('win_rate') or
                cols_lower.get('win_percentage')
        )
        matches_col = (
                cols_lower.get('matches_played') or
                cols_lower.get('matches') or
                cols_lower.get('games')
        )

        sorted_df = players_df.copy()

        # Calculate missing Win % and Matches Played on the fly from Wins & Losses
        if wins_col and losses_col:
            sorted_df[wins_col] = pd.to_numeric(sorted_df[wins_col], errors='coerce').fillna(0).astype(int)
            sorted_df[losses_col] = pd.to_numeric(sorted_df[losses_col], errors='coerce').fillna(0).astype(int)

            if not matches_col:
                sorted_df["matches_played"] = sorted_df[wins_col] + sorted_df[losses_col]
                matches_col = "matches_played"

            if not win_pct_col:
                total_games = sorted_df[wins_col] + sorted_df[losses_col]
                pct_values = (sorted_df[wins_col] / total_games.replace(0, 1) * 100).round(1)
                sorted_df["win_pct"] = [f"{pct:.1f}%" if tot > 0 else "0.0%" for pct, tot in
                                        zip(pct_values, total_games)]
                win_pct_col = "win_pct"

        # Sort players by Elo descending
        sorted_df = sorted_df.sort_values(by=elo_col, ascending=False).reset_index(drop=True)

        # 1. Format Medals for Ranks 1, 2, 3
        ranks = []
        for i in range(1, len(sorted_df) + 1):
            if i == 1:
                ranks.append("🥇 1")
            elif i == 2:
                ranks.append("🥈 2")
            elif i == 3:
                ranks.append("🥉 3")
            else:
                ranks.append(str(i))

        sorted_df["Rank"] = ranks

        # 2. Build full statistical table
        display_cols = ["Rank", name_col, elo_col]
        rename_dict = {"Rank": "Rank", name_col: "Player", elo_col: "Elo Rating"}

        if wins_col:
            display_cols.append(wins_col)
            rename_dict[wins_col] = "Wins"
        if losses_col:
            display_cols.append(losses_col)
            rename_dict[losses_col] = "Losses"
        if win_pct_col:
            display_cols.append(win_pct_col)
            rename_dict[win_pct_col] = "Win %"
        if streak_col:
            display_cols.append(streak_col)
            rename_dict[streak_col] = "Win Streak"
        if matches_col:
            display_cols.append(matches_col)
            rename_dict[matches_col] = "Matches Played"

        top_10_df = sorted_df.head(10)[display_cols].rename(columns=rename_dict)


        # 3. Bold Top 3 Rows cleanly using CSS Styler
        def highlight_top3(row):
            if row.name < 3:
                return ['font-weight: bold'] * len(row)
            return [''] * len(row)


        styled_top_10 = top_10_df.style.apply(highlight_top3, axis=1)

        st.dataframe(
            styled_top_10,
            use_container_width=True,
            hide_index=True
        )

        # 4. Dropdown for Players Ranked 11+
        if len(sorted_df) > 10:
            st.divider()
            st.markdown("### 📊 Lower Rankings (Ranks 11+)")

            remaining_df = sorted_df.iloc[10:].copy()

            dropdown_options = [
                f"Rank #{i + 11} — {row[name_col]} ({row[elo_col]} Elo)"
                for i, (_, row) in enumerate(remaining_df.iterrows())
            ]

            selected_player = st.selectbox(
                "Select a player to view details:",
                options=dropdown_options
            )

            if selected_player:
                selected_idx = dropdown_options.index(selected_player)
                player_info = remaining_df.iloc[selected_idx]

                info_items = [
                    f"**Player:** {player_info[name_col]}",
                    f"**Rank:** #{selected_idx + 11}",
                    f"**Elo:** {player_info[elo_col]}"
                ]
                if wins_col:
                    info_items.append(f"**Wins:** {player_info[wins_col]}")
                if losses_col:
                    info_items.append(f"**Losses:** {player_info[losses_col]}")
                if win_pct_col:
                    info_items.append(f"**Win %:** {player_info[win_pct_col]}")
                if streak_col:
                    info_items.append(f"**Streak:** {player_info[streak_col]}")
                if matches_col:
                    info_items.append(f"**Matches Played:** {player_info[matches_col]}")

                st.info(" | ".join(info_items))
    else:
        st.info("No players registered yet. Head to the Registration tab to add players!")

# --- Tab 2: Log Match ---
with tab2:
    players_df = fetch_players()
    player_names = players_df["full_name"].tolist() if not players_df.empty else []

    if len(player_names) < 2:
        st.warning("At least two players must be registered to log a match.")
    else:
        with st.form("log_match_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                winner = st.selectbox("Winner", player_names, index=0)
            with col2:
                loser = st.selectbox("Loser", player_names, index=1 if len(player_names) > 1 else 0)

            score_choice = st.radio(
                "Set Score Outcome",
                options=["2-0 (Sweep)", "2-1 (Decider)"],
                help="Select 2-0 if unmonitored or exact breakdown is unknown."
            )

            submitted = st.form_submit_button("Submit Match Result")

            if submitted:
                if winner == loser:
                    st.error("Winner and Loser cannot be the same person.")
                else:
                    winner_sets, loser_sets = (2, 0) if "2-0" in score_choice else (2, 1)
                    winner_row = players_df[players_df["full_name"] == winner].iloc[0]
                    loser_row = players_df[players_df["full_name"] == loser].iloc[0]

                    delta = calculate_elo_delta(winner_row["elo"], loser_row["elo"], winner_sets, loser_sets)

                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO matches (winner_name, loser_name, winner_sets, loser_sets, elo_delta)
                                VALUES (:w, :l, :ws, :ls, :d)
                            """),
                            {"w": winner, "l": loser, "ws": winner_sets, "ls": loser_sets, "d": delta}
                        )
                        conn.execute(
                            text("""
                                UPDATE players 
                                SET elo = elo + :d, wins = wins + 1, games_played = games_played + 1, current_streak = current_streak + 1
                                WHERE full_name = :name
                            """),
                            {"d": delta, "name": winner}
                        )
                        conn.execute(
                            text("""
                                UPDATE players 
                                SET elo = elo - :d, losses = losses + 1, games_played = games_played + 1, current_streak = 0
                                WHERE full_name = :name
                            """),
                            {"d": delta, "name": loser}
                        )

                    st.success(f"Match Logged! {winner} (+{delta}) defeated {loser} (-{delta}).")
                    st.rerun()

# --- Tab 3: Add Player ---
with tab3:
    with st.form("add_player_form", clear_on_submit=True):
        new_player_name = st.text_input("Player Full Name").strip()
        add_submitted = st.form_submit_button("Register Player")

        if add_submitted:
            if not new_player_name:
                st.error("Player name cannot be empty.")
            else:
                players_df = fetch_players()
                existing_names = [name.lower() for name in
                                  players_df["full_name"].tolist()] if not players_df.empty else []

                if new_player_name.lower() in existing_names:
                    st.error("A player with this name already exists.")
                else:
                    with engine.begin() as conn:
                        conn.execute(
                            text("INSERT INTO players (full_name) VALUES (:name)"),
                            {"name": new_player_name}
                        )
                    st.success(f"Registered {new_player_name} with baseline Elo of 1000!")
                    st.rerun()

# --- Tab 4: Match History ---
with tab4:
    with engine.connect() as conn:
        matches_df = pd.read_sql(
            text("""
                SELECT 
                    id AS "Match ID",
                    winner_name AS "Winner",
                    loser_name AS "Loser",
                    CONCAT(winner_sets, ' - ', loser_sets) AS "Score",
                    elo_delta AS "Elo Delta",
                    to_char(created_at, 'YYYY-MM-DD HH12:MI AM') AS "Timestamp"
                FROM matches 
                ORDER BY created_at DESC
            """),
            conn
        )

    if matches_df.empty:
        st.info("No matches played yet.")
    else:
        st.dataframe(matches_df, use_container_width=True, hide_index=True)

# --- Tab 5: Admin Panel ---
with tab5:
    st.subheader("⚙️ Admin Management")

    # --- ADMIN LOGIN WITH SESSION PERSISTENCE ---
    if "admin_logged_in" not in st.session_state:
        st.session_state["admin_logged_in"] = False

    if not st.session_state["admin_logged_in"]:
        input_pw = st.text_input("Enter Admin Password", type="password", key="admin_pw_input")

        if st.button("Login"):
            # .strip() removes any accidental leading/trailing spaces
            if input_pw.strip() == "Hasan2888":
                st.session_state["admin_logged_in"] = True
                st.rerun()
            else:
                st.error("Incorrect Password")

    else:
        # --- AUTHENTICATED ADMIN CONTENT STARTS HERE ---
        col_status, col_logout = st.columns([4, 1])
        with col_status:
            st.success("Admin Access Granted")
        with col_logout:
            if st.button("Log Out"):
                st.session_state["admin_logged_in"] = False
                st.rerun()

        st.divider()

        # =========================================================
        # 📊 APP TRAFFIC ANALYTICS
        # =========================================================
        st.subheader("📊 App Traffic Analytics")
        analytics = load_analytics()
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Total App Views (All-Time)", value=analytics.get("total_views", 0))
        with col2:
            st.metric(label="Unique Visitors (All-Time)", value=len(analytics.get("unique_visitors", [])))
        st.divider()

        # =========================================================
        # ↩️ FEATURE 1: UNDO LAST MATCH
        # =========================================================
        st.markdown("### ↩️ Undo Last Match")
        with engine.connect() as conn:
            last_match = conn.execute(
                text("SELECT id, winner_name, loser_name, elo_delta FROM matches ORDER BY created_at DESC LIMIT 1")
            ).fetchone()

        if last_match:
            match_id, winner, loser, delta = last_match
            st.info(f"Most Recent Match: **{winner}** defeated **{loser}** (+/- {delta} Elo)")

            if st.button("Undo This Match"):
                with engine.begin() as conn:
                    # Revert Winner Stats
                    conn.execute(
                        text("""
                            UPDATE players 
                            SET elo = elo - :d, wins = wins - 1, games_played = games_played - 1, current_streak = GREATEST(0, current_streak - 1)
                            WHERE full_name = :name
                        """),
                        {"d": delta, "name": winner}
                    )
                    # Revert Loser Stats
                    conn.execute(
                        text("""
                            UPDATE players 
                            SET elo = elo + :d, losses = losses - 1, games_played = games_played - 1
                            WHERE full_name = :name
                        """),
                        {"d": delta, "name": loser}
                    )
                    # Delete Match Record
                    conn.execute(text("DELETE FROM matches WHERE id = :id"), {"id": match_id})

                st.success("Last match undone and ratings updated!")
                st.rerun()
        else:
            st.write("No recorded matches to undo.")

        st.divider()

        # =========================================================
        # 🔄 FEATURE 2: MONTHLY RESET
        # =========================================================
        st.markdown("### 🔄 End of Month Reset")
        st.caption("Clears all match logs and resets all player ratings back to 1000.")

        confirm_reset = st.checkbox("Confirm season wipe")
        if st.button("Reset Monthly Tournament", type="primary", disabled=not confirm_reset):
            with engine.begin() as conn:
                conn.execute(text("TRUNCATE TABLE matches;"))
                conn.execute(text("""
                        UPDATE players
                        SET elo = 1000, wins = 0, losses = 0, games_played = 0, current_streak = 0;
                    """))
            st.success("Month successfully reset!")
            st.rerun()