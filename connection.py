from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import configparser


config = configparser.ConfigParser()
config.read('config.ini')

db_name = config['database']['db_name']
db_host = config['database']['host']
db_port = config['database']['port']
db_username = config['database']['username']
db_password = config['database']['password']

DATABASE_URL = f"postgresql://{db_username}:{db_password}@{db_host}:{db_port}/{db_name}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency for accessing the database in endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
