# Railway Management System

A beginner-friendly, server-rendered railway booking system built with **FastAPI**,
**MySQL (InnoDB)**, **SQLAlchemy**, and **Jinja2**. No React, no build tooling, no
Docker — just `pip install`, seed the DB, and `uvicorn`.

## Features

1. Accounts, train search, booking, cancellation with refund (status transition)
2. Multiple ticket categories (general / tatkal / ladies / senior)
3. Live seat map with adjacency ("sit together") detection
4. Concurrency-safe booking — two passengers can hold the same physical seat as
   long as their station ranges don't overlap (e.g. A→C and C→B)
5. Split-ticket booking (mid-journey vacancy detection, single train)
6. Graph-based fallback routing (direct + 1-transfer only)
7. Multi-city trip planner with atomic multi-leg booking

## One deliberate deviation from the original spec

The original schema has no `journey_date` on `Bookings`. Without it, a booking made
today would block that seat **forever**, on every future date the train runs —
trains run daily, so this breaks the app immediately. I added `journey_date` to
`Bookings` (and thread it through every availability/search query) so the segment-
overlap logic is scoped to a single day's run of the train, which is what the
schema was clearly meant to do. Everything else follows the plan as written.

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

## Design notes / what to say in your report

- **Segment overlap is the one query everything is built on.** `services/availability.py`
  has a single function, `segments_overlap`, that every other feature (search,
  seat map, booking, split-ticket, routing) calls into.
- **Concurrency safety:** booking transactions run at `READ COMMITTED` isolation
  (explicitly set — InnoDB defaults to `REPEATABLE READ`, which can serve stale
  reads mid-transaction) and lock the seat's existing bookings with
  `SELECT ... FOR UPDATE` before checking overlap, so two concurrent requests for
  overlapping ranges can't both slip through. Non-overlapping ranges on the same
  seat are still both allowed — that's a business rule, not a race condition.
- **Soft holds, no worker process:** a `held` booking blocks the segment until
  `hold_expires_at`. Expiry is checked lazily at read time (every availability
  query filters out expired holds) instead of running a background job.
- **Refunds** are a `refund_status` state transition (`none → refunded`) on
  cancellation — there's no real payment integration, by design.
- **Routing is direct + 1-transfer only.** No general graph search (Dijkstra/BFS)
  — intentionally out of scope for the timeline.
- **Scalability:** the app runs on a single MySQL instance, which is fine at this
  scale. At production scale you'd add read replicas for search/seat-map traffic,
  connection pooling (SQLAlchemy's built-in pool — cheap, worth doing even here),
  and eventually shard by geographic zone, with a caching layer (e.g. Redis) in
  front of high-read endpoints like seat availability.

## Explicitly out of scope

- Multi-hop routing beyond 1 transfer
- Real payment processing
- Seat swapping between passengers
- Cross-leg cascading cancellation (cancellation is per-leg)
- SMS/email notifications (in-app only)
- Cloud deployment (local demo only)
