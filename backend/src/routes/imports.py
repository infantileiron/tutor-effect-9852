from fastapi import APIRouter,Depends,Response
from src.config.database import get_db
from src.utils.security import current_user,editor
from src.schemas.business import ImportInput
from src.services import imports
from src.controllers.business import serialize,serialize_many
router=APIRouter()
def _detail(db,batch):
    return {**serialize(batch),'rows':serialize_many(imports.batch_rows(db,batch.id)),'reconciled':batch.total_rows==batch.added+batch.revised+batch.stale+batch.quarantined+batch.duplicate}
@router.get('/imports')
def listing(db=Depends(get_db),user=Depends(current_user)): return serialize_many(imports.list_batches(db))
@router.post('/imports',status_code=201)
def create(data:ImportInput,response:Response,db=Depends(get_db),user=Depends(editor)):
    batch,created=imports.submit_batch(db,data,user.email)
    if not created: response.status_code=200
    return {**_detail(db,batch),'replayed':not created}
@router.get('/imports/{id}')
def detail(id:int,db=Depends(get_db),user=Depends(current_user)): return _detail(db,imports.get_batch(db,id))
