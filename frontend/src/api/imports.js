import{request,post}from'./client.js';export const getBatches=()=>request('/imports');export const getBatch=id=>request('/imports/'+id);export const submitBatch=data=>post('/imports',data);
