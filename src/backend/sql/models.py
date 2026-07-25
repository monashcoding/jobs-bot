from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class ExampleRecord(SQLModel, table=True):
    __tablename__ = "example_records"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_type=BigInteger)
    value: str = Field(default="")
