# Railway Travel and Booking Management System

A beginner-friendly, server-rendered railway booking system built with **FastAPI**,
**MySQL (InnoDB)**, **SQLAlchemy**.

## Features

1. Accounts, train search, booking, cancellation with refund (status transition)
2. Multiple ticket categories (general / Sleeper / AC)
3. Live seat map with adjacency ("sit together") detection
4. Concurrency-safe booking — two passengers can hold the same physical seat as
   long as their station ranges don't overlap (e.g. A→C and C→B)
5. Split-ticket booking (mid-journey vacancy detection, single train)
6. Graph-based fallback routing (direct + 1-transfer only)
7. Multi-city trip planner with atomic multi-leg booking

## Tech stack

- **Backend:** FastAPI + Uvicorn
- **DB:** MySQL 8 / MariaDB (InnoDB), accessed via SQLAlchemy Core+ORM with
  explicit `SELECT ... FOR UPDATE` for concurrency control
- **Frontend:** Jinja2 templates, plain CSS, a little vanilla JS for the seat map
- **Auth:** Signed server-side session cookie (Starlette `SessionMiddleware`) +
  `passlib[bcrypt]` for password hashing

## Project layout

```
railway-management-system/
├── README.md
├── requirements.txt
├── .env.example
├── app/
│   ├── main.py            # FastAPI app, mounts routers, static files
│   ├── config.py          # settings from environment
│   ├── database.py        # engine, session factory, Base
│   ├── models.py          # SQLAlchemy models (the schema)
│   ├── security.py        # password hashing, current-user dependency
│   ├── dependencies.py    # get_db, require_login
│   ├── seed.py             # populates demo stations/trains/routes/seats
│   ├── routers/
│   │   ├── auth.py         # signup / login / logout
│   │   ├── search.py       # train search
│   │   ├── booking.py      # hold / confirm / cancel a booking
│   │   ├── seatmap.py      # live seat grid
│   │   └── trips.py        # multi-city trip planner
│   ├── services/
│   │   ├── availability.py # THE core segment-overlap query (everything uses this)
│   │   ├── booking_service.py
│   │   ├── split_ticket.py
│   │   ├── routing.py      # 1-hop graph fallback
│   │   └── trip_service.py
│   ├── templates/          # Jinja2 HTML
│   └── static/             # style.css, seatmap.js
├── scripts/
│   └── test_concurrency.py # fires parallel booking requests at one seat
└── tests/
    └── test_availability.py # pure-python unit tests for the overlap logic
```

## Setup

### 1. Install MySQL/MariaDB locally

```bash
# Ubuntu/Debian
sudo apt install mysql-server
sudo mysql -e "CREATE DATABASE railway; CREATE USER 'railway'@'localhost' IDENTIFIED BY 'railway'; GRANT ALL ON railway.* TO 'railway'@'localhost';"
```

### 2. Python environment

```bash
cd railway-management-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL / SESSION_SECRET if needed
```

### 3. Seed demo data

```bash
python -m app.seed
```

This creates ~6 stations, 4 trains with multi-stop routes, coaches, seats, and
one demo user (`demo@example.com` / `password123`).

### 4. Run

```bash
uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000

### 5. Concurrency test (Feature 4)

With the server running:

```bash
python scripts/test_concurrency.py
```

Fires 10 parallel booking requests at the same seat/train/date with overlapping
and non-overlapping station ranges, and prints which succeeded — overlapping
ones should conflict, non-overlapping ones should both succeed.

### 6. Unit tests

```bash
pytest tests/
```

## Explicitly out of scope

- Multi-hop routing beyond 1 transfer
- Real payment processing
- Seat swapping between passengers
- Cross-leg cascading cancellation (cancellation is per-leg)
- SMS/email notifications (in-app only)
- Cloud deployment (local demo only)
