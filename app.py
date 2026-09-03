import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# --- Page Setup & UH Branding ---
st.set_page_config(page_title="UH Table Tennis", page_icon="🏓", layout="centered")

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
    players_df = fetch_players()
    if players_df.empty:
        st.info("No players registered yet. Add players in the 'Add Player' tab.")
    else:
        players_df["win_pct"] = players_df.apply(
            lambda r: f"{(r['wins'] / r['games_played'] * 100):.1f}%" if r["games_played"] > 0 else "0.0%",
            axis=1
        )

        display_df = players_df[[
            "full_name", "elo", "wins", "losses", "games_played", "win_pct", "current_streak"
        ]].rename(columns={
            "full_name": "Player",
            "elo": "Elo Rating",
            "wins": "Wins",
            "losses": "Losses",
            "games_played": "Played",
            "win_pct": "Win %",
            "current_streak": "Win Streak"
        })

        st.subheader("🏆 Top 10 Rankings")
        top_10_df = display_df.head(10).copy()
        top_10_df.index = range(1, len(top_10_df) + 1)
        st.dataframe(top_10_df, use_container_width=True)

        if len(display_df) > 10:
            with st.expander("See Full Standings"):
                full_df = display_df.copy()
                full_df.index = range(1, len(full_df) + 1)
                st.dataframe(full_df, use_container_width=True)

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

    # Password Protection
    # Updated direct lookup
    admin_pw = st.secrets.get("ADMIN_PASSWORD", "cougars123")
    input_pw = st.text_input("Enter Admin Password", type="password")

    if input_pw == admin_pw:
        st.success("Admin Access Granted")
        st.divider()

        # Feature 1: Undo Last Match
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

        # Feature 2: Monthly Reset
        st.markdown("### 🔄 End of Month Reset")
        st.caption(
            "Clears all match logs and resets all player ratings back to 1000. Player names will remain registered.")

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

    elif input_pw:
        st.error("Incorrect Password")