"""
Database module - uses PostgreSQL (Supabase) in production, SQLite locally.
"""
import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, DateTime, Text, Integer, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from loguru import logger

# ============================================================================
# Database Setup - Auto-detects PostgreSQL or SQLite
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./buybox_tracker.db")

# Render/Supabase provide postgres:// but SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

logger.info(f"Using database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================================================
# Models
# ============================================================================

class TrackedASIN(Base):
    __tablename__ = "tracked_asins"

    asin = Column(String(20), primary_key=True, index=True)
    title = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    marketplace = Column(String(50), default="amazon.co.za")
    buybox_price = Column(Float, nullable=True)
    buybox_seller = Column(String(255), nullable=True)
    buybox_status = Column(String(50), nullable=True)
    currency = Column(String(10), default="ZAR")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    availability = Column(String(255), nullable=True)
    is_amazon_seller = Column(Boolean, default=False)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asin = Column(String(20), index=True)
    marketplace = Column(String(50), default="amazon.co.za")
    price = Column(Float, nullable=True)
    seller = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ============================================================================
# Init DB
# ============================================================================

def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")


def get_db():
    """Dependency to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# CRUD Operations
# ============================================================================

def save_asin(db: Session, data: dict):
    """Save or update a tracked ASIN."""
    asin = data.get("asin")
    existing = db.query(TrackedASIN).filter(TrackedASIN.asin == asin).first()

    if existing:
        for key, value in data.items():
            if hasattr(existing, key) and key not in ("asin", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
    else:
        record = TrackedASIN(
            asin=asin,
            title=data.get("title"),
            image_url=data.get("image_url"),
            marketplace=data.get("marketplace", "amazon.co.za"),
            buybox_price=data.get("buybox_price"),
            buybox_seller=data.get("buybox_seller"),
            buybox_status=data.get("buybox_status"),
            currency=data.get("currency", "ZAR"),
            rating=data.get("rating"),
            review_count=data.get("review_count"),
            availability=data.get("availability"),
            is_amazon_seller=data.get("is_amazon_seller", False),
            scraped_at=datetime.utcnow(),
        )
        db.add(record)

    db.commit()


def save_price_history(db: Session, data: dict):
    """Save a price history snapshot."""
    if not data.get("buybox_price"):
        return
    record = PriceHistory(
        asin=data.get("asin"),
        marketplace=data.get("marketplace", "amazon.co.za"),
        price=data.get("buybox_price"),
        seller=data.get("buybox_seller"),
        status=data.get("buybox_status"),
        timestamp=datetime.utcnow(),
    )
    db.add(record)
    db.commit()


def get_all_asins(db: Session):
    """Get all tracked ASINs."""
    return db.query(TrackedASIN).order_by(TrackedASIN.updated_at.desc()).all()


def get_price_history(db: Session, asin: str, limit: int = 100):
    """Get price history for an ASIN."""
    return (
        db.query(PriceHistory)
        .filter(PriceHistory.asin == asin)
        .order_by(PriceHistory.timestamp.desc())
        .limit(limit)
        .all()
    )


def delete_asin(db: Session, asin: str):
    """Delete a tracked ASIN and its history."""
    db.query(PriceHistory).filter(PriceHistory.asin == asin).delete()
    db.query(TrackedASIN).filter(TrackedASIN.asin == asin).delete()
    db.commit()
