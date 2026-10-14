import os
from sqlalchemy import create_engine
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://shahid:Shahid%40321@localhost:3306/railway_management_system",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
