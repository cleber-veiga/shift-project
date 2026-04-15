"""
Classe base declarativa do SQLAlchemy 2.0.
Todos os models ORM devem herdar desta Base.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
