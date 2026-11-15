import random,json
from datetime import datetime,timezone
from sqlalchemy import select,func
from src.config.database import Base,engine,SessionLocal
from src.models.entities import User,Student,Plan,Report,ImportBatch
from src.utils.security import hash_password
from src.services.statistics import welch

def _seed_imports(db):
    '''演示补发批次：覆盖新增、修订、过期、同版冲突、未知学号与重复六类裁决。按批号幂等，重跑不重复合并。'''
    from src.services.imports import submit_batch
    from src.schemas.business import ImportInput
    demos=[
        ('ENR-2026-11-RE01','enrollment',[
            {'code':'ZX-2026-005','version':2,'name':'学员005','campus':'城东','group':'intervention'},
            {'code':'ZX-2026-006','version':2,'name':'学员006','campus':'滨江','group':'control'},
            {'code':'ZX-2026-005','version':1,'name':'学员005','campus':'城东','group':'control'},
            {'code':'ZX-2026-006','version':2,'name':'学员006','campus':'高新','group':'control'},
        ]),
        ('EXM-2026-11-RE01','exam',[
            {'code':'ZX-2026-081','version':2,'score':88.5,'absent':False},
            {'code':'ZX-2026-082','version':2,'score':91.0,'absent':False},
            {'code':'ZX-2026-999','version':1,'score':77.0,'absent':False},
        ]),
        ('ENR-2026-11-RE02','enrollment',[
            {'code':'ZX-2026-005','version':3,'name':'学员005','campus':'高新','group':'intervention'},
            {'code':'ZX-2026-006','version':2,'name':'学员006','campus':'滨江','group':'control'},
        ]),
    ]
    for no,source,rows in demos:
        if db.scalar(select(ImportBatch).where(ImportBatch.batch_no==no)): continue
        submit_batch(db,ImportInput(batch_no=no,source=source,rows=rows),'seed')

def seed():
    Base.metadata.create_all(engine)
    rng=random.Random(20261115)
    with SessionLocal() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Demo123!')))
        for i in range(160):
            code=f'ZX-2026-{i+1:03}'
            group='control' if i<80 else 'intervention'
            score=round(min(100,max(0,rng.gauss(72 if group=='control' else 78,8))),1)
            absent=i%23==0
            if not db.scalar(select(Student).where(Student.code==code)):
                db.add(Student(code=code,name=f'学员{i+1:03}',campus=['城东','城西','滨江','高新'][i%4],group=group,score=None if absent else score,absent=absent))
        title='2026秋季 · 晚间小组辅导'
        plan=db.scalar(select(Plan).where(Plan.title==title))
        if not plan:
            plan=Plan(title=title,campus='全部',exclude_absent=True,description='评估每周两次小组辅导与常规自习的期末成绩差异。缺考学员排除；观察性结果不直接证明因果。');db.add(plan);db.flush()
        db.commit()
        if not db.scalar(select(Report).where(Report.plan_id==plan.id)):
            result=welch(db.scalars(select(Student).order_by(Student.code)).all(),plan)
            db.add(Report(plan_id=plan.id,status='completed',result=result,created_at=datetime.now(timezone.utc).isoformat(),conclusion='干预组均分较高。建议保留教学点分层观察，并在下一轮随机分组验证。',published=True));db.commit()
        _seed_imports(db)
        print(json.dumps({table:db.scalar(select(func.count()).select_from(model)) for table,model in [('users',User),('students',Student),('plans',Plan),('reports',Report),('batches',ImportBatch)]}))
if __name__=='__main__': seed()
