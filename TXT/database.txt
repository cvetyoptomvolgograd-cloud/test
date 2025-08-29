from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, ForeignKey, select, func, Text
import os

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    media_limit = Column(Integer, default=6)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)
    product_type = Column(String, default="другое")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    category = relationship("Category", backref="products")


class Bouquet(Base):
    __tablename__ = "bouquets"

    id = Column(Integer, primary_key=True)
    bouquet_id = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    short_title = Column(String(40), nullable=False)
    title_display = Column(String, nullable=False)
    photos = Column(JSON, nullable=False)
    video_path = Column(String, nullable=True)
    description = Column(String(800), nullable=False)
    composition = Column(JSON, nullable=True)
    price_minor = Column(Integer, nullable=False)
    currency = Column(String, default="RUB")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", backref="bouquets")


# Настройка подключения к БД
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bouquets.db")
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncSession:
    return AsyncSessionLocal()


async def get_or_create_user(session, telegram_id):
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def create_bouquet(session, bouquet_data):
    bouquet = Bouquet(**bouquet_data)
    session.add(bouquet)
    await session.commit()
    await session.refresh(bouquet)
    return bouquet


async def get_user_bouquets(session, user_id, page=1, per_page=10):
    offset = (page - 1) * per_page
    result = await session.execute(
        select(Bouquet)
        .where(Bouquet.user_id == user_id)
        .order_by(Bouquet.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    return result.scalars().all()


async def get_bouquet_by_id(session, bouquet_id):
    result = await session.execute(
        select(Bouquet).where(Bouquet.bouquet_id == bouquet_id)
    )
    return result.scalar_one_or_none()


async def update_bouquet(session, bouquet_id, update_data):
    bouquet = await get_bouquet_by_id(session, bouquet_id)
    if bouquet:
        for key, value in update_data.items():
            setattr(bouquet, key, value)
        await session.commit()
        await session.refresh(bouquet)
    return bouquet


async def delete_bouquet(session, bouquet_id):
    bouquet = await get_bouquet_by_id(session, bouquet_id)
    if bouquet:
        await session.delete(bouquet)
        await session.commit()
        return True
    return False


async def count_user_bouquets(session, user_id):
    result = await session.execute(
        select(func.count(Bouquet.id)).where(Bouquet.user_id == user_id)
    )
    return result.scalar()