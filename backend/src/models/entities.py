from sqlalchemy import String,Float,Boolean,Integer,ForeignKey,JSON,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class User(Base):
    __tablename__='users'
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(120),unique=True)
    role:Mapped[str]=mapped_column(String(20))
    password_hash:Mapped[str]=mapped_column(String(200))
class Student(Base):
    __tablename__='students'
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    name:Mapped[str]=mapped_column(String(80))
    campus:Mapped[str]=mapped_column(String(50))
    group:Mapped[str]=mapped_column(String(20))
    score:Mapped[float|None]=mapped_column(Float,nullable=True)
    absent:Mapped[bool]=mapped_column(Boolean,default=False)
class Plan(Base):
    __tablename__='plans'
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(120),unique=True)
    campus:Mapped[str]=mapped_column(String(50),default='全部')
    exclude_absent:Mapped[bool]=mapped_column(Boolean,default=True)
    description:Mapped[str]=mapped_column(Text,default='')
class Report(Base):
    __tablename__='reports'
    id:Mapped[int]=mapped_column(primary_key=True)
    plan_id:Mapped[int]=mapped_column(ForeignKey('plans.id'))
    status:Mapped[str]=mapped_column(String(20),default='queued')
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    error:Mapped[str]=mapped_column(Text,default='')
    conclusion:Mapped[str]=mapped_column(Text,default='')
    published:Mapped[bool]=mapped_column(Boolean,default=False)
    created_at:Mapped[str]=mapped_column(String(40))
class Audit(Base):
    __tablename__='audit_logs'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(120))
    action:Mapped[str]=mapped_column(String(200))
    status:Mapped[int]=mapped_column(Integer)
    created_at:Mapped[str]=mapped_column(String(40))
class ImportBatch(Base):
    __tablename__='import_batches'
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_no:Mapped[str]=mapped_column(String(64),unique=True)
    source:Mapped[str]=mapped_column(String(20))
    content_hash:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(20),default='pending')
    total_rows:Mapped[int]=mapped_column(Integer,default=0)
    added:Mapped[int]=mapped_column(Integer,default=0)
    revised:Mapped[int]=mapped_column(Integer,default=0)
    stale:Mapped[int]=mapped_column(Integer,default=0)
    quarantined:Mapped[int]=mapped_column(Integer,default=0)
    duplicate:Mapped[int]=mapped_column(Integer,default=0)
    error:Mapped[str]=mapped_column(Text,default='')
    actor:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[str]=mapped_column(String(40))
    finished_at:Mapped[str]=mapped_column(String(40),default='')
class ImportRow(Base):
    __tablename__='import_rows'
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('import_batches.id'))
    row_no:Mapped[int]=mapped_column(Integer)
    code:Mapped[str]=mapped_column(String(50))
    version:Mapped[int]=mapped_column(Integer)
    payload:Mapped[dict]=mapped_column(JSON)
    decision:Mapped[str]=mapped_column(String(20))
    reason:Mapped[str]=mapped_column(Text,default='')
class SourceState(Base):
    __tablename__='source_states'
    __table_args__=(UniqueConstraint('code','source'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50))
    source:Mapped[str]=mapped_column(String(20))
    version:Mapped[int]=mapped_column(Integer)
    payload:Mapped[dict]=mapped_column(JSON)
