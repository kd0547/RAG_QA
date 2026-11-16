"""Isolated graph UI smoke server. No production repository, extraction or mail calls.

Serves the built frontend on localhost:8769 with a disposable SQLite database.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TEMP=Path(tempfile.mkdtemp(prefix='graph-ui-smoke-'))
original_connect=sqlite3.connect


def isolated(database,*args,**kwargs):
    if Path(database).resolve()==(ROOT/'storage/mail.db').resolve():
        database=str(TEMP/'preview.db')
    return original_connect(database,*args,**kwargs)


sqlite3.connect=isolated
for key,value in {'MAIL_ID':'preview@example.com','MAIL_PW':'test','CLIENT_ID':'test','TENANT_ID':'test'}.items():
    os.environ[key]=value
embeddings=ModuleType('repository.embedding_repository')
embeddings.search=lambda **kwargs: []
sys.modules['repository.embedding_repository']=embeddings

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.routers import graph, specs

app=FastAPI()
app.include_router(graph.router)
app.include_router(specs.router)


@app.middleware('http')
async def no_external_calls(request,call_next):
    if request.url.path=='/graph/rebuild':
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'미리보기에서는 추출하지 않습니다.'},status_code=403)
    return await call_next(request)


@app.get('/files')
def files():
    return []


@app.get('/config')
def settings():
    return {}


app.mount('/assets',StaticFiles(directory=ROOT/'frontend/dist/assets'),name='assets')


@app.get('/{path:path}')
def frontend(path: str):
    if path in ('','knowledge','spec'):
        return FileResponse(ROOT/'frontend/dist/index.html')
    raise HTTPException(404)


if __name__=='__main__':
    import uvicorn
    print('Isolated preview DB:',TEMP,flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8769)
