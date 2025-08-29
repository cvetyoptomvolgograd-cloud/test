from sqlalchemy import (
    Column, Integer, String, DateTime, JSON, Boolean, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

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

    # products: relationship создаётся обратным backref в Product


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)
    product_type = Column(String, nullable=True, default="другое")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    category = relationship("Category", backref="products")


class Bouquet(Base):
    __tablename__ = "bouquets"

    id = Column(Integer, primary_key=True)
    bouquet_id = Column(String, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # названия
    short_title = Column(String(40), nullable=False)
    title_display = Column(String, nullable=False)

    # медиа
    photos = Column(JSON, nullable=False)          # список URL
    video_path = Column(String, nullable=True)     # URL видео (или None)

    # описание / состав
    description = Column(String(800), nullable=False)
    composition = Column(JSON, nullable=True)      # список элементов состава

    # цена
    price_minor = Column(Integer, nullable=False)  # цена в копейках
    currency = Column(String, default="RUB")

    # аудиты
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
