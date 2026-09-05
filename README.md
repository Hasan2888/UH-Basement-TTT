# 🏓 UH Table Tennis Leaderboard

A full-stack web application designed to track player rankings, match histories, and monthly statistics for the UH Basement Table Tennis community. Built with Python and Streamlit, featuring secure administrative access control and automated monthly reset countdowns.

🌐 **Live Demo:** [UH Table Tennis Leaderboard](https://uh-basement-ttt-wwbl4xqbhauk6n3ddwhxt.streamlit.app/) *(Replace with your live Streamlit Cloud link)*

---

## 📌 Features

* **Public Leaderboard:** Interactive player rankings, win/loss stats, and dynamic score tracking.
* **Automated Monthly Reset Countdown:** Uses Python's `datetime` and `calendar` modules to dynamically compute and display days remaining in the current month.
* **Role-Based Access Control:** Administrative tools ("Manage App", score resets, player management) are restricted exclusively to authorized accounts via GitHub authentication.
* **Optimized Cloud Deployment:** Configured with custom server options (`fileWatcherType = "none"`) for low overhead and continuous deployment on Streamlit Cloud.

---

## 🛠️ Tech Stack

* **Framework:** Python, Streamlit
* **Authentication:** GitHub OAuth (Streamlit Cloud Auth)
* **Configuration:** TOML
* **Deployment & CI/CD:** GitHub, Streamlit Cloud

---

## 🏗️ Project Architecture

```text
UH_Basement_TTT/
├── .streamlit/
│   └── config.toml          # Server optimizations (Disabled file watcher)
├── app.py                   # Primary application entry point & UI logic
├── requirements.txt         # Python dependency manifest
└── README.md                # Project documentation