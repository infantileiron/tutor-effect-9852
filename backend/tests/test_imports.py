from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func
from src.config.database import SessionLocal
from src.models.entities import Student,Plan,ImportBatch,ImportRow,SourceState
from src.services import imports
from src.services.statistics import welch
from src.schemas.business import ImportInput

def enr(no,rows): return {'batch_no':no,'source':'enrollment','rows':rows}
def exm(no,rows): return {'batch_no':no,'source':'exam','rows':rows}
def fetch_student(code):
    with SessionLocal() as s:
        st=s.scalar(select(Student).where(Student.code==code))
        return None if st is None else {c.name:getattr(st,c.name) for c in st.__table__.columns}

def test_interleaved_redelivery_merges_latest_per_source(client,db,admin_headers):
    '''交错补发：学籍 v1 → 考试 v2 → 学籍 v3 → 考试 v1（晚到）→ 学籍 v2（晚到）；各来源只保留各自最新版。'''
    r=client.post('/imports',json=enr('T-I-ENR1',[{'code':'ZX-I-1','version':1,'name':'交错','campus':'城东','group':'control'}]),headers=admin_headers)
    assert r.status_code==201 and r.json()['added']==1
    r=client.post('/imports',json=exm('T-I-EXM1',[{'code':'ZX-I-1','version':2,'score':80.0,'absent':False}]),headers=admin_headers)
    assert r.json()['added']==1
    r=client.post('/imports',json=enr('T-I-ENR2',[{'code':'ZX-I-1','version':3,'name':'交错','campus':'滨江','group':'intervention'}]),headers=admin_headers)
    assert r.json()['revised']==1
    r=client.post('/imports',json=exm('T-I-EXM2',[{'code':'ZX-I-1','version':1,'score':55.0,'absent':False}]),headers=admin_headers)
    assert r.json()['stale']==1,'晚到旧版考试应判过期'
    r=client.post('/imports',json=enr('T-I-ENR3',[{'code':'ZX-I-1','version':2,'name':'交错','campus':'城西','group':'control'}]),headers=admin_headers)
    assert r.json()['stale']==1,'晚到旧版学籍应判过期'
    s=fetch_student('ZX-I-1')
    assert (s['name'],s['campus'],s['group'])==('交错','滨江','intervention'),'学籍只保留 v3，旧版不得回退分组'
    assert s['score']==80.0 and s['absent'] is False,'考试只保留 v2，旧版不得回退补考成绩'

def test_exam_for_unknown_code_quarantined_until_enrollment(client,db,admin_headers):
    '''未知学号成绩隔离；学籍到达后以新批号重发即可合并。'''
    r=client.post('/imports',json=exm('T-U-EXM',[{'code':'ZX-U-1','version':1,'score':70.0,'absent':False}]),headers=admin_headers)
    body=r.json()
    assert body['quarantined']==1 and '未知学号' in body['rows'][0]['reason']
    assert fetch_student('ZX-U-1') is None,'隔离行不得注册学员或成绩'
    client.post('/imports',json=enr('T-U-ENR',[{'code':'ZX-U-1','version':1,'name':'后到','campus':'城东','group':'control'}]),headers=admin_headers)
    r=client.post('/imports',json=exm('T-U-EXM2',[{'code':'ZX-U-1','version':1,'score':70.0,'absent':False}]),headers=admin_headers)
    assert r.json()['added']==1
    assert fetch_student('ZX-U-1')['score']==70.0

def test_same_version_conflict_quarantined_and_duplicate_skipped(client,db,admin_headers):
    '''同版异值隔离并说明原因；同版同值幂等跳过不计账。'''
    client.post('/imports',json=enr('T-C-1',[{'code':'ZX-C-1','version':2,'name':'冲突','campus':'城东','group':'control'}]),headers=admin_headers)
    r=client.post('/imports',json=enr('T-C-2',[{'code':'ZX-C-1','version':2,'name':'冲突','campus':'高新','group':'control'}]),headers=admin_headers)
    body=r.json()
    assert body['quarantined']==1
    reason=body['rows'][0]['reason']
    assert '同版本 v2' in reason and 'campus' in reason,'裁决依据需指出版本与冲突字段'
    assert fetch_student('ZX-C-1')['campus']=='城东','冲突行不得改账'
    r=client.post('/imports',json=enr('T-C-3',[{'code':'ZX-C-1','version':2,'name':'冲突','campus':'城东','group':'control'}]),headers=admin_headers)
    body=r.json()
    assert body['duplicate']==1 and body['added']==0 and body['revised']==0,'同版同值只计重复，不重复计账'

def test_idempotent_retry_same_batch(client,db,admin_headers):
    '''重试同一批：不新增样本、不重复计账，返回原裁决。'''
    payload=enr('T-R-1',[{'code':'ZX-R-1','version':1,'name':'重试','campus':'城东','group':'control'},{'code':'ZX-R-2','version':1,'name':'重试二','campus':'城西','group':'intervention'}])
    first=client.post('/imports',json=payload,headers=admin_headers)
    assert first.status_code==201 and first.json()['added']==2
    def counts():
        with SessionLocal() as s:
            return (s.scalar(select(func.count()).select_from(Student)),s.scalar(select(func.count()).select_from(ImportRow)))
    before=counts()
    second=client.post('/imports',json=payload,headers=admin_headers)
    assert second.status_code==200 and second.json()['replayed'] is True
    assert counts()==before,'重试不得新增学员或裁决行'
    assert second.json()['added']==2 and second.json()['reconciled'] is True

def test_same_batch_no_different_content_rejected(client,db,admin_headers):
    '''同批号换内容拒绝。'''
    client.post('/imports',json=enr('T-409',[{'code':'ZX-D-1','version':1,'name':'甲','campus':'城东','group':'control'}]),headers=admin_headers)
    r=client.post('/imports',json=enr('T-409',[{'code':'ZX-D-1','version':1,'name':'乙','campus':'城东','group':'control'}]),headers=admin_headers)
    assert r.status_code==409 and '批号' in r.json()['detail']
    assert fetch_student('ZX-D-1')['name']=='甲','被拒批次不得改账'

def test_all_decisions_reconciled_in_one_batch(client,db,admin_headers):
    '''单批覆盖新增/修订/过期/异常/重复，数量对齐，页面可查原文与依据。'''
    rows=[
        {'code':'ZX-M-1','version':1,'name':'对账','campus':'城东','group':'control'},
        {'code':'ZX-M-1','version':2,'name':'对账','campus':'滨江','group':'intervention'},
        {'code':'ZX-M-1','version':1,'name':'对账','campus':'城东','group':'control'},
        {'code':'ZX-M-1','version':2,'name':'对账','campus':'高新','group':'control'},
        {'code':'ZX-M-1','version':2,'name':'对账','campus':'滨江','group':'intervention'},
    ]
    r=client.post('/imports',json=enr('T-M-1',rows),headers=admin_headers)
    body=r.json()
    assert [row['decision'] for row in body['rows']]==['added','revised','stale','quarantined','duplicate']
    assert (body['added'],body['revised'],body['stale'],body['quarantined'],body['duplicate'])==(1,1,1,1,1)
    assert body['total_rows']==5 and body['reconciled'] is True,'新增+修订+过期+异常+重复 须对齐总行数'
    assert body['status']=='completed' and body['finished_at'],'批次应从待处理流转到完成'
    s=fetch_student('ZX-M-1')
    assert (s['campus'],s['group'])==('滨江','intervention')
    detail=client.get(f"/imports/{body['id']}",headers=admin_headers).json()
    assert detail['rows'][3]['payload']['campus']=='高新','详情须保留行原文'
    assert '冲突' in detail['rows'][3]['reason'],'详情须保留裁决依据'
    listing=client.get('/imports',headers=admin_headers).json()
    assert listing[0]['batch_no']=='T-M-1' and listing[0]['status']=='completed'

def test_statistics_only_count_merged_ledger(client,db,admin_headers):
    '''检验只纳入已合并样本：隔离行不进台账，有效修订才改变检验输入。'''
    enr_rows=[{'code':f'ZX-S-{i}','version':1,'name':f'统计{i}','campus':'城东','group':'control' if i<3 else 'intervention'} for i in range(6)]
    client.post('/imports',json=enr('T-S-ENR',enr_rows),headers=admin_headers)
    scores=[60,70,80,75,85,95]
    client.post('/imports',json=exm('T-S-EXM',[{'code':f'ZX-S-{i}','version':1,'score':float(scores[i]),'absent':False} for i in range(6)]),headers=admin_headers)
    plan=Plan(title='统计口径',campus='全部',exclude_absent=True,description='')
    def current():
        db.expire_all()
        return welch(db.scalars(select(Student)).all(),plan)
    before=current()
    assert before['control_n']==3 and before['intervention_n']==3
    client.post('/imports',json=exm('T-S-Q1',[{'code':'ZX-S-99','version':1,'score':100.0,'absent':False}]),headers=admin_headers)
    client.post('/imports',json=exm('T-S-Q2',[{'code':'ZX-S-0','version':1,'score':100.0,'absent':False}]),headers=admin_headers)
    after=current()
    assert after['checksum']==before['checksum'],'未知学号与同版冲突的隔离行不得进入检验'
    client.post('/imports',json=exm('T-S-REV',[{'code':'ZX-S-0','version':2,'score':100.0,'absent':False}]),headers=admin_headers)
    assert current()['checksum']!=before['checksum'],'已合并的修订才改变检验输入'

def test_permissions(client,db,make_user,auth_headers,admin_headers):
    payload=enr('T-PERM',[{'code':'ZX-Z-1','version':1,'name':'权限','campus':'城东','group':'control'}])
    assert client.post('/imports',json=payload,headers=auth_headers(make_user('viewer'))).status_code==403
    assert client.post('/imports',json=payload).status_code==401
    assert client.post('/imports',json=payload,headers=auth_headers(make_user('analyst'))).status_code==201
    viewer=auth_headers(make_user('viewer2'))
    assert client.get('/imports',headers=viewer).status_code==200
    bid=client.get('/imports',headers=viewer).json()[0]['id']
    assert client.get(f'/imports/{bid}',headers=viewer).status_code==200

def test_row_validation_rejects_bad_rows_without_trace(client,db,admin_headers):
    assert client.post('/imports',json=exm('T-V-1',[{'code':'ZX-V-1','version':1,'score':90.0,'absent':True}]),headers=admin_headers).status_code==422,'缺考须空成绩'
    assert client.post('/imports',json=exm('T-V-2',[{'code':'ZX-V-1','version':1,'absent':False}]),headers=admin_headers).status_code==422,'非缺考须成绩'
    assert client.post('/imports',json=enr('T-V-3',[{'code':'ZX-V-1','version':0,'name':'x','campus':'城东','group':'control'}]),headers=admin_headers).status_code==422,'版本须≥1'
    assert client.post('/imports',json=enr('T-V-4',[]),headers=admin_headers).status_code==422,'空批拒绝'
    assert client.post('/imports',json={'batch_no':'T-V-5','source':'other','rows':[{'a':1}]},headers=admin_headers).status_code==422
    assert db.scalar(select(func.count()).select_from(ImportBatch))==0,'无效批次不留痕'

def _submit(no,source,rows):
    with SessionLocal() as s:
        batch,created=imports.submit_batch(s,ImportInput(batch_no=no,source=source,rows=rows),'concurrency-test')
        return batch.id,created

def test_concurrent_imports_keep_latest_version(db):
    '''并发导入不同版本：最终保留各来源最新值，每行恰有一条裁决，对账一致。'''
    def row(i): return [{'code':'ZX-P-1','version':i,'name':'并发','campus':f'点{i}','group':'control'}]
    with ThreadPoolExecutor(6) as pool:
        results=list(pool.map(lambda i:_submit(f'T-P-{i}','enrollment',row(i)),[1,2,3,4,5]))
    with SessionLocal() as s:
        st=s.scalar(select(Student).where(Student.code=='ZX-P-1'))
        assert st.campus=='点5','并发导入仍保留最新版本值'
        state=s.scalar(select(SourceState).where(SourceState.code=='ZX-P-1'))
        assert state.version==5
        rows=s.scalars(select(ImportRow)).all()
        assert len(rows)==5,'每批一行裁决，无重复计账'
        counts=Counter(r.decision for r in rows)
        assert counts['added']==1
        assert counts['added']+counts['revised']+counts['stale']==5
        for bid,_ in results:
            b=s.get(ImportBatch,bid)
            assert b.status=='completed'
            assert b.total_rows==b.added+b.revised+b.stale+b.quarantined+b.duplicate

def test_concurrent_retry_same_batch_counts_once(db):
    '''并发重试同一批：只有一个处理者，其余幂等重放；不新增样本、不重复计账。'''
    payload=[{'code':'ZX-Q-1','version':1,'name':'并发重试','campus':'城东','group':'control'},{'code':'ZX-Q-2','version':1,'name':'并发重试二','campus':'城西','group':'intervention'}]
    with ThreadPoolExecutor(6) as pool:
        results=list(pool.map(lambda _:_submit('T-Q-1','enrollment',payload),range(6)))
    assert {bid for bid,_ in results}=={results[0][0]},'同批号应收敛到同一批次'
    assert sum(1 for _,created in results if created)==1,'并发下只能有一个处理者'
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(Student))==2,'并发重试不得重复注册学员'
        assert s.scalar(select(func.count()).select_from(ImportRow))==2,'裁决行不得因重试翻倍'
        batch=s.get(ImportBatch,results[0][0])
        assert batch.added==2 and batch.status=='completed'

def test_concurrent_same_batch_no_different_content_single_winner(db):
    '''并发下同批号异内容：一个成功，其余拒绝。'''
    def attempt(i):
        try:
            _submit('T-X-1','enrollment',[{'code':'ZX-X-1','version':1,'name':f'内容{i}','campus':'城东','group':'control'}])
            return 'ok'
        except HTTPException as e:
            return str(e.status_code)
    with ThreadPoolExecutor(2) as pool:
        outcomes=pool.map(attempt,[1,2])
    assert sorted(outcomes)==['409','ok']
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).select_from(ImportBatch))==1
