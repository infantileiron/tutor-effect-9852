import hashlib,json
from datetime import datetime,timezone
from sqlalchemy import select,update,delete
from sqlalchemy.exc import IntegrityError,OperationalError
from fastapi import HTTPException
from pydantic import ValidationError
from src.constants.enums import SOURCE_FIELDS,SOURCE_LABELS,ROW_DECISIONS
from src.models.entities import Student,ImportBatch,ImportRow,SourceState
from src.schemas.business import EnrollmentRow,ExamRow
ROW_SCHEMAS={'enrollment':EnrollmentRow,'exam':ExamRow}
def _now(): return datetime.now(timezone.utc).isoformat()
def _validate_rows(source,rows):
    schema=ROW_SCHEMAS[source];parsed=[]
    for i,raw in enumerate(rows,1):
        try: parsed.append(schema(**raw))
        except ValidationError as e:
            msg='；'.join('.'.join(str(p) for p in err['loc'])+' '+err['msg'] for err in e.errors())
            raise HTTPException(422,f'第 {i} 行数据无效：{msg}')
    return parsed
def _digest(source,rows):
    canonical=json.dumps({'source':source,'rows':[r.model_dump(mode='json') for r in rows]},ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(canonical.encode()).hexdigest()
def _fields(source,row): return {k:getattr(row,k) for k in SOURCE_FIELDS[source]}
def list_batches(db): return db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())).all()
def get_batch(db,id):
    batch=db.get(ImportBatch,id)
    if not batch: raise HTTPException(404,'导入批次不存在')
    return batch
def batch_rows(db,id): return db.scalars(select(ImportRow).where(ImportRow.batch_id==id).order_by(ImportRow.row_no)).all()
def submit_batch(db,data,actor):
    '''提交补发批次。同批号同内容幂等重放；同批号异内容拒绝；并发下同批号只有一个处理者。'''
    rows=_validate_rows(data.source,data.rows)
    digest=_digest(data.source,rows)
    batch=None;last_err=None
    for _ in range(8):
        batch=_find_or_create(db,data,digest,actor,len(rows))
        if batch.content_hash!=digest:
            raise HTTPException(409,f'批号 {data.batch_no} 已使用且内容不一致；同批号更换内容被拒绝，请换新批号')
        if batch.status=='completed':
            return batch,False  # 幂等重放：不重新合并、不重复计账
        claimed=db.execute(update(ImportBatch).where(ImportBatch.id==batch.id,ImportBatch.status.in_(['pending','failed'])).values(status='processing')).rowcount
        if not claimed:
            db.commit();db.refresh(batch)
            if batch.status=='completed': return batch,False
            raise HTTPException(409,f'批次 {batch.batch_no} 正在处理中，请稍后查询结果')
        try:
            _process(db,batch,data.source,data.rows,rows)
            return batch,True
        except OperationalError as e:  # 锁冲突 / 死锁：回滚后整体重试，合并按学号有序且幂等
            db.rollback();last_err=e
        except Exception as e:
            _mark_failed(db,batch,e)
            raise HTTPException(500,f'批次 {batch.batch_no} 处理失败：{e}')
    _mark_failed(db,batch,last_err)
    raise HTTPException(503,f'批次 {batch.batch_no} 处理反复冲突，请稍后重试')
def _find_or_create(db,data,digest,actor,total):
    batch=db.scalar(select(ImportBatch).where(ImportBatch.batch_no==data.batch_no))
    if batch is None:
        batch=ImportBatch(batch_no=data.batch_no,source=data.source,content_hash=digest,status='pending',total_rows=total,actor=actor,created_at=_now())
        db.add(batch)
        try: db.commit()  # 批次进入待处理；并发同批号由唯一约束兜底
        except IntegrityError:
            db.rollback()
            batch=db.scalar(select(ImportBatch).where(ImportBatch.batch_no==data.batch_no))
    return batch
def _mark_failed(db,batch,error):
    db.rollback()
    batch.status='failed';batch.error=str(error)[:500];batch.finished_at=_now()
    db.commit()
def _process(db,batch,source,raw_rows,rows):
    db.execute(delete(ImportRow).where(ImportRow.batch_id==batch.id))  # 失败重试时重建裁决，合并本身幂等
    counts={d:0 for d in ROW_DECISIONS};decisions={}
    for i in sorted(range(len(rows)),key=lambda j:(rows[j].code,j)):  # 同学号保持提交顺序，降低并发死锁
        decision,reason=_merge_row(db,source,rows[i])
        decisions[i]=(decision,reason);counts[decision]+=1
    for i,(decision,reason) in decisions.items():
        db.add(ImportRow(batch_id=batch.id,row_no=i+1,code=rows[i].code,version=rows[i].version,payload=raw_rows[i],decision=decision,reason=reason))
    for k,v in counts.items(): setattr(batch,k,v)
    batch.status='completed';batch.error='';batch.finished_at=_now()
    db.commit()
def _merge_row(db,source,row):
    '''合并单行：只应用本来源管辖的字段，按版本取新。返回 (裁决, 依据)。'''
    fields=_fields(source,row);label=SOURCE_LABELS[source]
    student=db.scalar(select(Student).where(Student.code==row.code))
    if student is None and source=='exam':
        return 'quarantined',f'未知学号 {row.code}：考试成绩不能注册新学员，已隔离；等待学籍批次到达后以新批号重新补发'
    state=db.scalar(select(SourceState).where(SourceState.code==row.code,SourceState.source==source).with_for_update())
    if state is None:
        created=False
        if student is None:
            student=Student(code=row.code,score=None,absent=False,**fields)
            db.add(student)
            try:
                with db.begin_nested(): db.flush()
            except IntegrityError:  # 并发已建同学员：改用既有学员
                db.expunge(student)
                student=db.scalar(select(Student).where(Student.code==row.code))
            else: created=True
        state=SourceState(code=row.code,source=source,version=row.version,payload=fields)
        db.add(state)
        try:
            with db.begin_nested(): db.flush()
        except IntegrityError:  # 并发已建同来源状态：转为版本比较
            db.expunge(state)
            state=db.scalar(select(SourceState).where(SourceState.code==row.code,SourceState.source==source).with_for_update())
            return _decide(db,state,student,source,row,fields)
        for k,v in fields.items(): setattr(student,k,v)
        return 'added',f'首次合并{label} v{row.version}'+('，新建学员' if created else '')
    return _decide(db,state,student,source,row,fields)
def _decide(db,state,student,source,row,fields):
    label=SOURCE_LABELS[source]
    if row.version<state.version:
        return 'stale',f'晚到旧版：{label}已应用 v{state.version}，忽略 v{row.version}'
    if row.version==state.version:
        if state.payload==fields: return 'duplicate',f'{label} v{row.version} 与已应用值一致，幂等跳过'
        diff='；'.join(f'{k} 已应用「{state.payload.get(k)}」≠ 本次「{v}」' for k,v in fields.items() if state.payload.get(k)!=v)
        return 'quarantined',f'同版本 v{row.version} 值冲突：{diff}；已隔离待人工核对'
    old=state.version
    won=db.execute(update(SourceState).where(SourceState.id==state.id,SourceState.version==old).values(version=row.version,payload=fields)).rowcount
    if not won:  # 并发下版本已被别人推进：重新裁决
        db.refresh(state)
        return _decide(db,state,student,source,row,fields)
    for k,v in fields.items(): setattr(student,k,v)
    return 'revised',f'{label}版本 v{old} → v{row.version}，应用新值'
