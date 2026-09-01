"""Populate the database with demo data.

Run with: python -m app.seed
Safe to re-run: it wipes and recreates all tables first.
"""
from app.database import Base, engine, SessionLocal
from app.models import Station, Train, Route, Coach, Seat, User, SeatPosition
from app.security import hash_password

STATIONS = [
    ("New Delhi", "NDLS"),
    ("Kanpur Central", "CNB"),
    ("Allahabad Jn", "ALD"),
    ("Mughalsarai Jn", "MGS"),
    ("Patna Jn", "PNBE"),
    ("Howrah Jn", "HWH"),
]

# (name, number, [(station_code, arrival, departure), ...] in travel order)
TRAINS = [
    (
        "Howrah Rajdhani", "12302",
        [
            ("NDLS", None, "16:55"),
            ("CNB", "20:23", "20:28"),
            ("ALD", "22:03", "22:08"),
            ("MGS", "23:30", "23:40"),
            ("PNBE", "01:05", "01:15"),
            ("HWH", "10:00", None),
        ],
    ),
    (
        "Poorva Express", "12304",
        [
            ("NDLS", None, "19:10"),
            ("CNB", "23:05", "23:10"),
            ("MGS", "02:40", "02:50"),
            ("HWH", "11:30", None),
        ],
    ),
    (
        "Kanpur Shatabdi", "12034",
        [
            ("NDLS", None, "06:10"),
            ("CNB", "11:40", None),
        ],
    ),
    (
        "Magadh Express", "20802",
        [
            ("CNB", None, "23:55"),
            ("ALD", "01:20", "01:30"),
            ("MGS", "03:10", "03:20"),
            ("PNBE", "05:15", None),
        ],
    ),
]

COACH_LAYOUT = [
    ("A1", "AC"),
    ("A2", "AC"),
    ("S1", "sleeper"),
    ("S2", "sleeper"),
]
SEATS_PER_ROW = 3  # window / middle / aisle
ROWS_PER_COACH = 6
POSITIONS = [SeatPosition.window, SeatPosition.middle, SeatPosition.aisle]


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        code_to_station = {}
        for name, code in STATIONS:
            s = Station(name=name, code=code)
            db.add(s)
            db.flush()
            code_to_station[code] = s

        for name, number, stops in TRAINS:
            total_seats = len(COACH_LAYOUT) * ROWS_PER_COACH * SEATS_PER_ROW
            train = Train(name=name, number=number, total_seats=total_seats)
            db.add(train)
            db.flush()

            for seq, (code, arr, dep) in enumerate(stops, start=1):
                db.add(
                    Route(
                        train_id=train.id,
                        station_id=code_to_station[code].id,
                        stop_sequence=seq,
                        arrival_time=arr,
                        departure_time=dep,
                    )
                )

            for coach_number, coach_type in COACH_LAYOUT:
                coach = Coach(train_id=train.id, coach_number=coach_number, coach_type=coach_type)
                db.add(coach)
                db.flush()
                for row in range(1, ROWS_PER_COACH + 1):
                    for col, position in enumerate(POSITIONS, start=1):
                        db.add(
                            Seat(
                                coach_id=coach.id,
                                seat_number=f"{row}{chr(64 + col)}",  # 1A, 1B, 1C...
                                row_number=row,
                                position=position,
                            )
                        )

        demo_user = User(
            name="Demo User", email="demo@example.com", password_hash=hash_password("password123")
        )
        db.add(demo_user)

        db.commit()
        print("Seeded:", len(STATIONS), "stations,", len(TRAINS), "trains.")
        print("Demo login: demo@example.com / password123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
