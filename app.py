import calendar
import json
import os
from datetime import datetime
import pandas as pd
from sqlalchemy import URL, create_engine, text
import streamlit as st
from sqlalchemy import text
from datetime import datetime, timezone


def apply_elo_decay():
    """Applies -10 Elo per week to players above 1000 Elo who are inactive for > 7 days."""
    with engine.begin() as conn:
        # Fetch last match timestamp per player
        df = pd.read_sql(
            text("""
                SELECT 
                    p.full_name, 
                    p.elo, 
                    MAX(m.created_at) AS last_match_time
                FROM players p
                LEFT JOIN matches m 
                    ON p.full_name = m.winner_name OR p.full_name = m.loser_name
                GROUP BY p.full_name, p.elo;
            """),
            conn
        )

        now = datetime.now(timezone.utc)

        for _, row in df.iterrows():
            if row["elo"] <= 1000:
                continue  # Never decay at or below starting baseline

            last_active = row["last_match_time"]
            if pd.isna(last_active):
                continue  # Skip players who haven't played any matches yet

            # Ensure timezone awareness
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)

            days_inactive = (now - last_active).days

            # Decay applies after 7 days (10 Elo per full week of inactivity)
            if days_inactive >= 7:
                weeks_inactive = days_inactive // 7
                target_elo = max(1000, row["elo"] - (weeks_inactive * 10))

                if target_elo < row["elo"]:
                    conn.execute(
                        text("UPDATE players SET elo = :new_elo WHERE full_name = :name;"),
                        {"new_elo": target_elo, "name": row["full_name"]}
                    )

ANALYTICS_FILE = "analytics.json"

def get_k_factor(games_played: int) -> int:
    if games_played < 5:
        return 50
    elif games_played < 15:
        return 35
    return 20

def calculate_asymmetric_elo(winner_elo, loser_elo, winner_games, loser_games, winner_sets, loser_sets):
    # Calculate expected win probability
    exp_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    exp_loser = 1 - exp_winner

    # Fetch individual K-factors
    k_winner = get_k_factor(winner_games)
    k_loser = get_k_factor(loser_games)

    # Optional outcome multiplier (1-0 standard, 2-0 sweep bonus, 2-1 decider penalty)
    mult = 1.0
    if winner_sets == 2 and loser_sets == 0:
        mult = 1.1
    elif winner_sets == 2 and loser_sets == 1:
        mult = 0.9

    # Calculate individual deltas
    winner_delta = max(1, round(k_winner * (1 - exp_winner) * mult))
    loser_delta = max(1, round(k_loser * exp_loser * mult))

    return winner_delta, loser_delta


def load_analytics():
    """Loads view counts from disk."""
    if os.path.exists(ANALYTICS_FILE):
        try:
            with open(ANALYTICS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_views": 0}

def save_analytics(data):
    """Saves view counts permanently."""
    with open(ANALYTICS_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- Page Setup & UH Branding ---
st.set_page_config(
    page_title="UH Table Tennis", page_icon="🏓", layout="centered"
)

# --- TRACK VISITS (Runs once per browser session) ---
if "visited" not in st.session_state:
    st.session_state["visited"] = True
    analytics = load_analytics()
    analytics["total_views"] = analytics.get("total_views", 0) + 1
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
    st.title(" UH Basement Table Tennis Rankings 🏓")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Leaderboard", "Log Match", "Add Player", "Match History", "Admin"])

# --- Tab 1: Leaderboard ---
with tab1:
    st.subheader("🏆 Top 10 Leaderboard")

    # Run automated decay check
    try:
        apply_elo_decay()
    except Exception as e:
        st.error(f"Error running Elo decay check: {e}")

    # --- Monthly Reset Countdown ---
    today = datetime.now()
    _, last_day = calendar.monthrange(today.year, today.month)
    days_left = last_day - today.day

    st.caption(
        f"⏳ **Monthly Reset:** {days_left} day{'s' if days_left != 1 else ''} remaining"
    )
    # -------------------------------

    players_df = pd.read_sql("SELECT * FROM players;", engine)
    matches_df = pd.read_sql("SELECT * FROM matches;", engine)

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
                cols_lower.get('games') or
                cols_lower.get('games_played')
        )

        sorted_df = players_df.copy()

        # Enforce numeric types across statistics to prevent NaN filtering bugs
        sorted_df[elo_col] = pd.to_numeric(sorted_df[elo_col], errors='coerce').fillna(1000).astype(int)

        if wins_col and losses_col:
            sorted_df[wins_col] = pd.to_numeric(sorted_df[wins_col], errors='coerce').fillna(0).astype(int)
            sorted_df[losses_col] = pd.to_numeric(sorted_df[losses_col], errors='coerce').fillna(0).astype(int)

            if not matches_col or matches_col not in sorted_df.columns:
                sorted_df["matches_played"] = sorted_df[wins_col] + sorted_df[losses_col]
                matches_col = "matches_played"
            else:
                sorted_df[matches_col] = pd.to_numeric(sorted_df[matches_col], errors='coerce').fillna(0).astype(int)

            if not win_pct_col or win_pct_col not in sorted_df.columns:
                total_games = sorted_df[wins_col] + sorted_df[losses_col]
                pct_values = (sorted_df[wins_col] / total_games.replace(0, 1) * 100).round(1)
                sorted_df["win_pct"] = [f"{pct:.1f}%" if tot > 0 else "0.0%" for pct, tot in
                                        zip(pct_values, total_games)]
                win_pct_col = "win_pct"

        # Calculate last match time per player
        now_utc = datetime.now(timezone.utc)
        last_match_dict = {}
        if not matches_df.empty and 'created_at' in matches_df.columns:
            matches_df['created_at'] = pd.to_datetime(matches_df['created_at'])
            for _, m in matches_df.iterrows():
                t = m.get('created_at')
                if pd.notna(t):
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    for p in [m.get('winner_name'), m.get('loser_name')]:
                        if p:
                            last_match_dict[p] = max(last_match_dict.get(p, t), t)


        # Evaluate Status safely
        def evaluate_player_status(row):
            p_name = row[name_col]
            g_count = int(row.get(matches_col, 0))
            last_t = last_match_dict.get(p_name)

            if g_count < 5:
                return f"Calibrating ({g_count}/5)"
            if last_t is None:
                return "Inactive"

            days_since = (now_utc - last_t).days
            return "Inactive" if days_since >= 7 else "Active"


        sorted_df["Status"] = sorted_df.apply(evaluate_player_status, axis=1)

        # 1. Active Calibrated Players (5+ games)
        active_calibrated_df = sorted_df[sorted_df["Status"] == "Active"].sort_values(by=elo_col,
                                                                                      ascending=False).reset_index(
            drop=True)
        top_10_active = active_calibrated_df.head(10).copy()
        lower_active = active_calibrated_df.iloc[10:].copy()

        # 2. Calibrating Players (< 5 games)
        calibrating_df = sorted_df[sorted_df["Status"].str.startswith("Calibrating", na=False)].copy()

        # 3. Combine 11+ Active Players and Calibrating Players sorted strictly by Elo
        lower_rankings_df = pd.concat([lower_active, calibrating_df], ignore_index=True)
        if not lower_rankings_df.empty:
            lower_rankings_df = lower_rankings_df.sort_values(by=elo_col, ascending=False).reset_index(drop=True)

        # 4. Inactive Players
        inactive_df = sorted_df[sorted_df["Status"] == "Inactive"].sort_values(by=elo_col, ascending=False).reset_index(
            drop=True)

        # Configure Display Columns
        display_cols = [name_col, elo_col, "Status"]
        rename_dict = {name_col: "Player", elo_col: "Elo Rating", "Status": "Status"}

        if wins_col: display_cols.append(wins_col); rename_dict[wins_col] = "Wins"
        if losses_col: display_cols.append(losses_col); rename_dict[losses_col] = "Losses"
        if win_pct_col: display_cols.append(win_pct_col); rename_dict[win_pct_col] = "Win %"
        if streak_col: display_cols.append(streak_col); rename_dict[streak_col] = "Win Streak"
        if matches_col: display_cols.append(matches_col); rename_dict[matches_col] = "Matches Played"

        # --- DISPLAY 1: TOP 10 LEADERBOARD ---
        if not top_10_active.empty:
            ranks = []
            for i in range(1, len(top_10_active) + 1):
                if i == 1:
                    ranks.append("🥇 1")
                elif i == 2:
                    ranks.append("🥈 2")
                elif i == 3:
                    ranks.append("🥉 3")
                else:
                    ranks.append(str(i))

            top_10_active["Rank"] = ranks
            active_display_cols = ["Rank"] + display_cols
            active_rename = {"Rank": "Rank", **rename_dict}

            top_10_display = top_10_active[active_display_cols].rename(columns=active_rename)


            def highlight_top3(row):
                if row.name < 3:
                    return ['font-weight: bold'] * len(row)
                return [''] * len(row)


            styled_top_10 = top_10_display.style.apply(highlight_top3, axis=1)
            st.dataframe(styled_top_10, use_container_width=True, hide_index=True)
        else:
            st.info("No fully calibrated active players yet (requires 5+ games).")

        # --- DISPLAY 2: LOWER RANKINGS & CALIBRATING PLAYERS ---
        st.divider()
        st.markdown("### 📊 Lower Rankings & Calibrating Players")
        st.caption("Active players ranked 11+ and calibrating players (< 5 games), ordered by Elo.")

        if not lower_rankings_df.empty:
            lower_rankings_df["Rank"] = range(11, 11 + len(lower_rankings_df))
            lower_display_cols = ["Rank"] + display_cols
            lower_rename = {"Rank": "Rank", **rename_dict}
            lower_display = lower_rankings_df[lower_display_cols].rename(columns=lower_rename)

            st.dataframe(lower_display, use_container_width=True, hide_index=True)
        else:
            st.caption("No players currently in lower rankings or calibration.")

        # --- DISPLAY 3: INACTIVE PLAYERS ---
        if not inactive_df.empty:
            st.write("")
            with st.expander("💤 Inactive Players (>7 Days No Matches)", expanded=False):
                st.caption("Players move here after 7 days without a logged match.")
                inactive_display = inactive_df[display_cols].rename(columns=rename_dict)
                st.dataframe(inactive_display, use_container_width=True, hide_index=True)

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
                winner = st.selectbox(
                    "Winner",
                    player_names,
                    index=None,
                    placeholder="Select winner..."
                )
            with col2:
                loser = st.selectbox(
                    "Loser",
                    player_names,
                    index=None,
                    placeholder="Select loser..."
                )

            score_choice = st.radio(
                "Set Score Outcome",
                options=["1-0 (Single Game)", "2-0 (Sweep)", "2-1 (Decider)"]
            )

            submitted = st.form_submit_button("Submit Match Result")

            if submitted:
                if not winner or not loser:
                    st.error("Please select both a winner and a loser before submitting.")
                elif winner == loser:
                    st.error("Winner and Loser cannot be the same person.")
                else:
                    if "1-0" in score_choice:
                        winner_sets, loser_sets = (1, 0)
                    elif "2-0" in score_choice:
                        winner_sets, loser_sets = (2, 0)
                    else:
                        winner_sets, loser_sets = (2, 1)

                    winner_row = players_df[players_df["full_name"] == winner].iloc[0]
                    loser_row = players_df[players_df["full_name"] == loser].iloc[0]

                    # Calculate dynamic Elo for each player independently
                    w_delta, l_delta = calculate_asymmetric_elo(
                        winner_elo=winner_row["elo"],
                        loser_elo=loser_row["elo"],
                        winner_games=winner_row["games_played"],
                        loser_games=loser_row["games_played"],
                        winner_sets=winner_sets,
                        loser_sets=loser_sets
                    )

                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO matches (winner_name, loser_name, winner_sets, loser_sets, elo_delta)
                                VALUES (:w, :l, :ws, :ls, :d)
                            """),
                            {"w": winner, "l": loser, "ws": winner_sets, "ls": loser_sets, "d": w_delta}
                        )
                        conn.execute(
                            text("""
                                UPDATE players 
                                SET elo = elo + :d, wins = wins + 1, games_played = games_played + 1, current_streak = current_streak + 1
                                WHERE full_name = :name
                            """),
                            {"d": w_delta, "name": winner}
                        )
                        conn.execute(
                            text("""
                                UPDATE players 
                                SET elo = elo - :d, losses = losses + 1, games_played = games_played + 1, current_streak = 0
                                WHERE full_name = :name
                            """),
                            {"d": l_delta, "name": loser}
                        )

                    st.success(f"Match Logged! {winner} (+{w_delta}) defeated {loser} (-{l_delta}).")
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
                    created_at
                FROM matches 
                ORDER BY id DESC
            """),
            conn
        )

    if matches_df.empty:
        st.info("No matches played yet.")
    else:
        # Convert timestamp column to datetime
        matches_df["created_at"] = pd.to_datetime(matches_df["created_at"])

        # Convert from UTC to local time (America/Chicago = Central Time)
        if matches_df["created_at"].dt.tz is None:
            matches_df["created_at"] = matches_df["created_at"].dt.tz_localize("UTC")
        matches_df["created_at"] = matches_df["created_at"].dt.tz_convert("America/Chicago")

        # Format left-to-right: Time, Date, Month, Year
        matches_df["Timestamp"] = matches_df["created_at"].dt.strftime("%I:%M %p, %d-%m-%Y")

        # Select and order columns for display
        display_df = matches_df[["Match ID", "Winner", "Loser", "Score", "Elo Delta", "Timestamp"]]

        st.dataframe(display_df, use_container_width=True, hide_index=True)

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

        # 📊 APP STATS
        st.subheader("📊 App Stats")

        # Load total views from JSON
        analytics = load_analytics()
        total_views = analytics.get("total_views", 0)

        # Query total registered players from database
        try:
            with engine.connect() as conn:
                total_players = conn.execute(
                    text("SELECT COUNT(*) FROM players;")
                ).scalar()
        except Exception:
            total_players = 0

        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Total App Views (All-Time)", value=total_views)
        with col2:
            st.metric(label="Total Registered Players", value=total_players)

        st.divider()

        # --- Admin Tool: Undo / Delete Any Match ---
        st.subheader("🚨 Undo / Delete Match")
        st.caption(
            "Select any recent match to revert. Reverting subtracts Elo from the winner, restores Elo to the loser, and adjusts win/loss totals.")

        with engine.connect() as conn:
            recent_matches = pd.read_sql(
                text("""
                    SELECT 
                        id, 
                        winner_name, 
                        loser_name, 
                        elo_delta, 
                        CONCAT('Match #', id, ': ', winner_name, ' def. ', loser_name, ' (Delta: ', elo_delta, ')') AS display_label
                    FROM matches 
                    ORDER BY id DESC 
                    LIMIT 50;
                """),
                conn
            )

        if recent_matches.empty:
            st.info("No matches recorded yet to undo.")
        else:
            selected_label = st.selectbox(
                "Select a match to revert:",
                options=recent_matches["display_label"].tolist(),
                index=0
            )

            confirm_undo = st.checkbox(
                f"Confirm revert of '{selected_label}'"
            )

            if st.button("Delete Selected Match & Rollback Stats", disabled=not confirm_undo):
                match_info = recent_matches[recent_matches["display_label"] == selected_label].iloc[0]
                m_id = int(match_info["id"])
                winner = match_info["winner_name"]
                loser = match_info["loser_name"]
                delta = int(match_info["elo_delta"])

                with engine.begin() as conn:
                    # 1. Rollback Winner stats
                    conn.execute(
                        text("""
                            UPDATE players 
                            SET elo = elo - :d, 
                                wins = GREATEST(0, wins - 1), 
                                games_played = GREATEST(0, games_played - 1)
                            WHERE full_name = :name
                        """),
                        {"d": delta, "name": winner}
                    )
                    # 2. Rollback Loser stats
                    conn.execute(
                        text("""
                            UPDATE players 
                            SET elo = elo + :d, 
                                losses = GREATEST(0, losses - 1), 
                                games_played = GREATEST(0, games_played - 1)
                            WHERE full_name = :name
                        """),
                        {"d": delta, "name": loser}
                    )
                    # 3. Remove match record
                    conn.execute(
                        text("DELETE FROM matches WHERE id = :id;"),
                        {"id": m_id}
                    )

                st.success(
                    f"Match #{m_id} reverted! Subtracted {delta} Elo from {winner} and restored {delta} Elo to {loser}.")
                st.rerun()

        st.divider()

        # --- Admin Tool: Change Player Name ---
        st.subheader("✏️ Change Player Name")
        st.caption("Update a player's display name across all database records and historical matches.")

        with engine.connect() as conn:
            all_players_df = pd.read_sql(text("SELECT full_name FROM players ORDER BY full_name ASC;"), conn)

        if all_players_df.empty:
            st.info("No players registered yet.")
        else:
            selected_old_name = st.selectbox(
                "Select player to rename:",
                options=all_players_df["full_name"].tolist(),
                key="rename_select"
            )
            new_player_name = st.text_input("Enter new full name:", placeholder="e.g. John Doe").strip()

            confirm_rename = st.checkbox(
                f"Confirm renaming '{selected_old_name}' to '{new_player_name}'" if new_player_name else "Confirm name change"
            )

            if st.button("Update Player Name", disabled=(not confirm_rename or not new_player_name)):
                if new_player_name in all_players_df["full_name"].tolist():
                    st.error(f"A player named '{new_player_name}' already exists!")
                else:
                    with engine.begin() as conn:
                        # 1. Update player table entry
                        conn.execute(
                            text("UPDATE players SET full_name = :new WHERE full_name = :old;"),
                            {"new": new_player_name, "old": selected_old_name}
                        )
                        # 2. Update historical match records where they won
                        conn.execute(
                            text("UPDATE matches SET winner_name = :new WHERE winner_name = :old;"),
                            {"new": new_player_name, "old": selected_old_name}
                        )
                        # 3. Update historical match records where they lost
                        conn.execute(
                            text("UPDATE matches SET loser_name = :new WHERE loser_name = :old;"),
                            {"new": new_player_name, "old": selected_old_name}
                        )

                    st.success(f"Successfully renamed '{selected_old_name}' to '{new_player_name}' across all records!")
                    st.rerun()

        st.divider()

        # =========================================================
        # 🗑️ FEATURE 3: REMOVE PLAYER
        # =========================================================
        st.markdown("### 🗑️ Remove Player")
        st.caption("Permanently delete duplicate, misspelled, or fraudulent player entries.")

        player_list = []
        name_col = None

        try:
            with engine.connect() as conn:
                # Query all columns to avoid hardcoded column errors
                players_df = pd.read_sql(text("SELECT * FROM players;"), conn)

                if not players_df.empty:
                    # Detect which column holds the player names
                    for col in ["player_name", "name", "username", "player", "full_name"]:
                        if col in players_df.columns:
                            name_col = col
                            break
                    if not name_col:
                        name_col = players_df.columns[0]  # Fallback to first column

                    player_list = sorted(players_df[name_col].dropna().unique().tolist())
        except Exception as e:
            st.error(f"Error loading player list: {e}")

        if player_list and name_col:
            selected_player = st.selectbox("Select player to remove:", player_list)
            confirm_delete = st.checkbox(f"Confirm permanent deletion of '{selected_player}'")

            if st.button("Remove Player", type="primary", disabled=not confirm_delete):
                try:
                    with engine.connect() as conn:
                        # Check actual column names in matches table first to prevent SQL errors
                        matches_df = pd.read_sql(text("SELECT * FROM matches LIMIT 0;"), conn)
                        possible_cols = ["winner", "loser", "player1", "player2", "winner_name", "loser_name"]
                        valid_match_cols = [col for col in possible_cols if col in matches_df.columns]

                    with engine.begin() as conn:
                        # Clean up related matches only for columns that exist
                        for match_col in valid_match_cols:
                            conn.execute(
                                text(f"DELETE FROM matches WHERE {match_col} = :name;"),
                                {"name": selected_player}
                            )

                        # Delete the player record from players table
                        conn.execute(
                            text(f"DELETE FROM players WHERE {name_col} = :name;"),
                            {"name": selected_player}
                        )

                    st.success(f"Player '{selected_player}' was successfully removed!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to remove player: {e}")
        else:
            st.info("No players currently registered in the database.")

        st.divider()
        # =========================================================
        # 🔄 FEATURE 3: MONTHLY RESET
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