import os
from sqlalchemy import create_engine,event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
url=os.environ['DATABASE_URL']
kwargs={'pool_pre_ping':True}
if url.startswith('sqlite'): kwargs['connect_args']={'check_same_thread':False}
engine=create_engine(url,**kwargs)
if url.startswith('sqlite'):
    @event.listens_for(engine,'connect')
    def _sqlite_busy_timeout(conn,_):
        cur=conn.cursor();cur.execute('PRAGMA busy_timeout=8000');cur.close()
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
def get_db():
    with SessionLocal() as db: yield db
