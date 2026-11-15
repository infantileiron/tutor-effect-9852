import os,sys,tempfile
BACKEND=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,BACKEND)
_DIR=tempfile.mkdtemp(prefix='tutor-imports-test-')
os.environ['DATABASE_URL']=f'sqlite:///{_DIR}/test.db'
os.environ['JWT_SECRET']='imports-test-secret'
os.environ['REDIS_URL']='redis://localhost:6379/15'
os.environ['SEED_DEMO']='false'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from src.config.database import SessionLocal
from src.models.entities import User,Student,Plan,Report,Audit,ImportBatch,ImportRow,SourceState
from src.utils.security import hash_password,token_for

@pytest.fixture(scope='session')
def client():
    from src.main import app
    with TestClient(app) as c: yield c

@pytest.fixture()
def db():
    with SessionLocal() as s:
        for model in (ImportRow,ImportBatch,SourceState,Audit,Report,Plan,Student,User):
            s.execute(delete(model))
        s.commit()
        yield s

@pytest.fixture()
def make_user(db):
    def _make(role='admin'):
        user=User(email=f'{role}@test.local',role=role,password_hash=hash_password('Test123!'))
        db.add(user);db.commit();db.refresh(user)
        return user
    return _make

@pytest.fixture()
def auth_headers():
    return lambda user:{'Authorization':'Bearer '+token_for(user)}

@pytest.fixture()
def admin_headers(make_user,auth_headers): return auth_headers(make_user('admin'))
