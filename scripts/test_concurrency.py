"""Feature 4 concurrency test.

Fires parallel HTTP booking requests at the SAME seat, on the SAME train and
date, from TWO groups of station-range requests:

  - Group "overlap": everyone requests the exact same A->D range.
    Expectation: exactly one succeeds, the rest get a conflict.
  - Group "no-overlap": half request A->B, half request B->C (adjacent, non-
    overlapping ranges) on a *different* seat.
    Expectation: one from each half succeeds (they don't conflict with each
    other), demonstrating overlapping segments can share a physical seat.

Run the server first (`uvicorn app.main:app`), then:
    python scripts/test_concurrency.py
"""
import asyncio
import sys
from datetime import date, timedelta

import httpx

BASE_URL = "http://127.0.0.1:8000"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "password123"


async def login(client: httpx.AsyncClient):
    resp = await client.post(
        f"{BASE_URL}/login", data={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}, follow_redirects=False
    )
    if resp.status_code != 303:
        resp.raise_for_status()


async def find_first_train_and_seat(client: httpx.AsyncClient):
    """Look up the first seeded train/route/seat via a quick DB-free trick:
    we just hit /search/results for a known station pair from the seed data
    (New Delhi -> Howrah) and parse nothing -- instead we hardcode ids that
    match app/seed.py's insertion order for simplicity in this demo script.
    """
    # These ids match a fresh `python -m app.seed` run: train 1 = Howrah
    # Rajdhani, stations 1=NDLS .. 6=HWH, first seat of coach A1 = seat id 1.
    return {
        "train_id": 1,
        "seat_id": 1,
        "from_station_id": 1,  # NDLS
        "mid_station_id": 3,   # ALD
        "to_station_id": 6,    # HWH
    }


async def attempt_booking(client: httpx.AsyncClient, seat_id, from_id, to_id, journey_date, label):
    resp = await client.post(
        f"{BASE_URL}/book",
        data={
            "train_id": 1,
            "seat_id": seat_id,
            "from_station_id": from_id,
            "to_station_id": to_id,
            "journey_date": journey_date,
            "ticket_type": "general",
        },
        follow_redirects=False,
    )
    location = resp.headers.get("location", "")
    ok = resp.status_code == 303 and "/bookings/" in location
    print(f"[{label}] status={resp.status_code} -> {location or '(no redirect)'} {'OK' if ok else 'CONFLICT/other'}")
    return ok


async def main():
    journey_date = (date.today() + timedelta(days=30)).isoformat()
    ids = await find_first_train_and_seat(None)

    print("=== Test 1: overlapping ranges on the SAME seat (should be exactly 1 success) ===")
    async with httpx.AsyncClient() as client:
        await login(client)
        cookies = client.cookies
        clients = [httpx.AsyncClient(cookies=cookies) for _ in range(10)]
        results = await asyncio.gather(
            *[
                attempt_booking(c, ids["seat_id"], ids["from_station_id"], ids["to_station_id"], journey_date, f"req-{i}")
                for i, c in enumerate(clients)
            ]
        )
        for c in clients:
            await c.aclose()
        successes = sum(results)
        print(f"Successes: {successes} / {len(results)} (expected exactly 1)\n")

    print("=== Test 2: non-overlapping ranges on the SAME seat, different date (both should succeed) ===")
    journey_date_2 = (date.today() + timedelta(days=31)).isoformat()
    async with httpx.AsyncClient() as client:
        await login(client)
        cookies = client.cookies
        c1 = httpx.AsyncClient(cookies=cookies)
        c2 = httpx.AsyncClient(cookies=cookies)
        r1, r2 = await asyncio.gather(
            attempt_booking(c1, ids["seat_id"], ids["from_station_id"], ids["mid_station_id"], journey_date_2, "A->mid"),
            attempt_booking(c2, ids["seat_id"], ids["mid_station_id"], ids["to_station_id"], journey_date_2, "mid->B"),
        )
        await c1.aclose()
        await c2.aclose()
        print(f"Both succeeded: {r1 and r2} (expected True)")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
