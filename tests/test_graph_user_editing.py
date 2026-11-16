"""User editing acceptance tests; all DB writes and file deletes use pytest temp directories."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config
from app.routers import graph as router
from graph_rag.edit_service import EffectiveGraphService, GraphConflictError, GraphEditService
from graph_rag.types import ExtractedEntity, ExtractedRelation, PageGraph
from repository.graph_repository import GraphEditError, GraphRepository
from repository.graph_migration import migrate_graph_editing
from repository.repo_connect import Database


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = Database(str(tmp_path/'editing.db'))
    graph = GraphRepository(db)
    monkeypatch.setattr(router,'graph_repo',graph)
    monkeypatch.setattr(config,'GRAPH_EDIT_ENABLED',True)
    app = FastAPI()
    app.include_router(router.router)
    return db, graph, GraphEditService(db), EffectiveGraphService(db), TestClient(app)


def entity(service, name='Alpha', kind='product', **kw):
    return service.execute('create_entity',data={'type':kind,'name':name,**kw})


def definition(service, kind='text', **kw):
    return service.execute('create_property_definition',data={
        'key':'custom:'+kind,'label':'속성 '+kind,'value_type':kind,**kw})


def relation_type(service):
    return service.execute('create_relation_type',data={'key':'custom:candidate','label':'대체 후보',
        'source_entity_types':['product'],'target_entity_types':['product']})


def file_page(db, identity='f1'):
    with db.transaction() as conn:
        conn.execute('INSERT INTO file(file_id,original_name,stored_path) VALUES (?,?,?)',(identity,identity+'.pdf','temp.pdf'))
        conn.execute('INSERT INTO file_page(file_id,seq,page,text,original_text) VALUES (?,1,1,?,?)',(identity,'원본 근거','원본 근거'))


def test_isolated_entity_survives_restart_reextract_and_tombstone(env):
    db,graph,edit,read,_ = env
    e = entity(edit,aliases=['Alpha old'])
    file_page(db)
    page = PageGraph(entities=[ExtractedEntity(type='product',name='Alpha old')])
    graph.replace_page('f1',1,page)
    graph.delete_file('f1')
    graph.prune_orphans()
    Database(db.db_path)
    assert graph.find_entities('Alpha')[0]['id']==e['id']
    deleted = edit.execute('delete_entity',e['id'],{'expected_revision':1})
    graph.replace_page('f1',1,page)
    graph.seed_specs()
    assert graph.find_entities('Alpha')==[]
    assert graph.view()['nodes']==[]
    with pytest.raises(GraphConflictError):
        entity(edit,name='Alpha old')
    restored = edit.execute('restore_entity',e['id'],{'expected_revision':deleted['revision']})
    assert restored['id']==e['id']
    assert graph.get_entity(e['id'])['aliases']==['Alpha','Alpha old']
    assert len(read.changes())==3


@pytest.mark.parametrize('kind,value,kwargs',[
    ('text','검토 완료',{}),('number',12.5,{'unit':'점'}),('boolean',False,{}),
    ('date','2024-02-29',{}),('enum','승인',{'allowed_values':['승인','보류']})])
def test_typed_values_roundtrip(env,kind,value,kwargs):
    _,graph,edit,read,_ = env
    e,p = entity(edit),definition(edit,kind,**kwargs)
    edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':value})
    actual = read.facts(e['id'])['properties'][0]
    assert actual['value']==value and type(actual['value']) is type(value)
    assert graph.get_entity(e['id'])['properties'][0]['value']==value
    if kind=='number':
        with pytest.raises(GraphEditError):
            edit.execute('update_property',actual['value_id'],{'entity_id':e['id'],'expected_revision':1,'value':10**400})
        edit.execute('update_property',actual['value_id'],{'entity_id':e['id'],'expected_revision':1,'value':2**80})
        assert read.properties(e['id'])[0]['value']==float(2**80)


@pytest.mark.parametrize('kind,value,kwargs',[
    ('number',float('nan'),{}),('number',float('inf'),{}),('number',True,{}),('number','12',{}),
    ('boolean',1,{}),('boolean','false',{}),('date','2025-02-29',{}),('date','20240101',{}),
    ('enum','invalid',{'allowed_values':['yes']}),('text','x'*4001,{})])
def test_invalid_values_are_atomic(env,kind,value,kwargs):
    db,_,edit,read,_ = env
    e,p = entity(edit),definition(edit,kind,**kwargs)
    before = len(read.changes())
    with pytest.raises(GraphEditError):
        edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':value})
    assert read.properties(e['id'])==[]
    assert len(read.changes())==before
    with db.get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM graph_fact_source').fetchone()[0]==0


def test_concurrent_revision_and_idempotency(env):
    db,graph,edit,read,client = env
    e = entity(edit)
    def update(name):
        try:
            return GraphEditService(db).execute('update_entity',e['id'],{'name':name,'expected_revision':1})
        except GraphConflictError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(update,['Beta','Gamma']))
    assert sum(r is not None for r in rows)==1
    assert graph.get_entity(e['id'])['revision']==2
    assert client.patch(f"/graph/entities/{e['id']}",json={'name':'old client'}).status_code==409
    data = {'type':'standard','name':'Standard'}
    a = client.post('/graph/entities',json=data,headers={'Idempotency-Key':'request-1'})
    b = client.post('/graph/entities',json=data,headers={'Idempotency-Key':'request-1'})
    assert a.status_code==b.status_code==201 and a.json()==b.json()
    assert client.post('/graph/entities',json={**data,'name':'Other'},headers={'Idempotency-Key':'request-1'}).status_code==409
    assert len([r for r in read.changes('entity') if r['action']=='create'])==2


def test_dynamic_relations_property_definition_disable_and_source_deletion(env):
    db,graph,edit,read,client = env
    a,b = entity(edit),entity(edit,'Beta')
    t,p = relation_type(edit),definition(edit)
    file_page(db)
    relation = edit.execute('create_relation',data={'source_id':a['id'],'target_id':b['id'],'type':t['key'],
        'source':{'file_id':'f1','page':1,'reason':'후보로 검토'}})
    value = edit.execute('create_property',a['id'],{'property_id':p['property_id'],'value':'메모',
        'source':{'file_id':'f1','page':1}})
    with db.transaction() as conn:
        conn.execute("DELETE FROM file WHERE file_id='f1'")
    graph.prune_orphans()
    facts = read.facts(a['id'])
    assert facts['relations'][0]['sources'][0]['file_deleted']==1
    assert facts['properties'][0]['sources'][0]['excerpt']=='원본 근거'
    assert facts['relations'][0]['id']==relation['id']
    edit.execute('update_relation_type',t['key'],{'active':False,'expected_revision':1})
    edit.execute('update_property_definition',p['property_id'],{'active':False,'expected_revision':1})
    assert read.properties(a['id'])[0]['value_id']==value['value_id']
    assert len(graph.view()['edges'])==1
    with pytest.raises(GraphEditError):
        edit.execute('create_relation',data={'source_id':a['id'],'target_id':b['id'],'type':t['key']})
    assert client.get('/graph/schema').json()['relation_types'][-1]['key']
    deleted = edit.execute('delete_relation',relation['id'],{'expected_revision':1})
    assert graph.get_entity(a['id'])['relations']==[]
    with pytest.raises(GraphEditError):
        edit.execute('restore_relation',relation['id'],{'expected_revision':deleted['revision']})


def test_single_multiple_limits_and_uncertain(env,monkeypatch):
    _,_,edit,read,_ = env
    e,p = entity(edit),definition(edit)
    v = edit.execute('create_property',e['id'],{'property_id':p['property_id'],'confirmation':'uncertain'})
    with pytest.raises(GraphConflictError):
        edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':'second'})
    edit.execute('update_property',v['value_id'],{'entity_id':e['id'],'value':'confirmed','expected_revision':1})
    p2 = definition(edit,'number',multiple=True)
    monkeypatch.setattr(config,'GRAPH_EDIT_PROPERTY_LIMIT',2)
    edit.execute('create_property',e['id'],{'property_id':p2['property_id'],'value':3})
    with pytest.raises(GraphEditError):
        edit.execute('create_property',e['id'],{'property_id':p2['property_id'],'value':4})
    assert len(read.properties(e['id']))==2


def test_merge_preserves_ids_events_aliases_blocks_and_conflicts(env):
    db,graph,edit,read,_ = env
    a,b,c = entity(edit),entity(edit,'Beta'),entity(edit,'Gamma')
    t,p = relation_type(edit),definition(edit)
    v = edit.execute('create_property',a['id'],{'property_id':p['property_id'],'value':'keep'})
    r = edit.execute('create_relation',data={'source_id':a['id'],'target_id':c['id'],'type':t['key']})
    with db.transaction() as conn:
        conn.execute('INSERT INTO graph_exclusion VALUES (?,?,?,?)',(a['id'],c['id'],'has_number','*'))
    edit.execute('merge_entity',a['id'],{'target_id':b['id'],'expected_revision':1,'target_revision':1})
    assert read.properties(b['id'])[0]['value_id']==v['value_id']
    assert read.facts(b['id'])['relations'][0]['id']==r['id']
    assert graph.find_entities('Alpha')[0]['id']==b['id']
    assert graph.get_entity(a['id']) is None
    file_page(db)
    graph.replace_page('f1',1,PageGraph(entities=[ExtractedEntity(type='product',name='Alpha')]))
    with db.get_conn() as conn:
        assert conn.execute('SELECT lifecycle_state,merged_into_id FROM graph_entity WHERE id=?',(a['id'],)).fetchone()[:]==('merged',b['id'])
        assert conn.execute('SELECT 1 FROM graph_exclusion WHERE src_id=?',(b['id'],)).fetchone()
    edit.execute('create_property',c['id'],{'property_id':p['property_id'],'value':'conflict'})
    with pytest.raises(GraphConflictError):
        edit.execute('merge_entity',c['id'],{'target_id':b['id'],'expected_revision':1,'target_revision':2})


def test_auto_claim_scopes_and_rename_keep_exclusion(env):
    db,graph,edit,_,_ = env
    file_page(db,'f1'); file_page(db,'f2')
    page = PageGraph(entities=[ExtractedEntity(type='product',name='Alpha'),ExtractedEntity(type='component',name='Chip')],
        relations=[ExtractedRelation(source='Alpha',target='Chip',type='has_component')])
    graph.replace_page('f1',1,page); graph.replace_page('f2',1,page)
    a = graph.find_entities('Alpha')[0]
    claims = graph.get_entity(a['id'])['relations']
    edit.execute('delete_relation',claims[0]['id'],{'expected_revision':1,'scope':'source'})
    graph.replace_page('f1',1,page)
    assert len(graph.get_entity(a['id'])['relations'])==1
    remaining = graph.get_entity(a['id'])['relations'][0]
    edit.execute('delete_relation',remaining['id'],{'expected_revision':1,'scope':'all'})
    graph.rename_entity(a['id'],'Renamed Alpha')
    graph.replace_page('f1',1,page); graph.replace_page('f2',1,page)
    assert graph.get_entity(a['id'])['relations']==[]


def test_migration_preserves_manual_duplicates_ids_and_rollback(tmp_path):
    path = tmp_path/'legacy.db'
    db = Database(str(path))
    file_page(db,'f1'); file_page(db,'f2')
    with db.transaction() as conn:
        conn.execute("INSERT INTO graph_entity(id,type,name,norm) VALUES (100,'product','AA','aa'),(101,'product','BB','bb')")
        conn.execute('DROP TRIGGER graph_relation_source_key')
        conn.execute("INSERT INTO graph_relation(id,src_id,dst_id,type,file_id,page,origin) VALUES (501,100,101,'custom:old','f1',1,'manual'),(502,100,101,'custom:old','f2',1,'manual')")
    Database(str(path)); Database(str(path))
    with db.get_conn() as conn:
        rows = conn.execute('SELECT id,file_id,source_key FROM graph_relation ORDER BY id').fetchall()
        assert [tuple(r) for r in rows]==[(501,None,'manual:501'),(502,None,'manual:502')]
        assert conn.execute('SELECT count(*) FROM graph_fact_source').fetchone()[0]==2
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        # Prior releases recreate this incompatible file-based index. Never roll code back blindly.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("CREATE UNIQUE INDEX legacy_compatibility_probe ON graph_relation(src_id,dst_id,type,ifnull(file_id,''),ifnull(page,-1))")
    # Inject a DDL failure inside the savepoint; prior writes and schema changes must roll back.
    fresh = sqlite3.connect(tmp_path/'rollback.db')
    fresh.row_factory = sqlite3.Row
    fresh.executescript("CREATE TABLE graph_entity(id INTEGER PRIMARY KEY); CREATE TABLE graph_relation(id INTEGER PRIMARY KEY); CREATE TABLE graph_alias(entity_id INTEGER);")
    def deny(action,arg1,arg2,db_name,trigger):
        return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_CREATE_TABLE and arg1=='graph_fact_source' else sqlite3.SQLITE_OK
    fresh.set_authorizer(deny)
    with pytest.raises(sqlite3.DatabaseError):
        migrate_graph_editing(fresh)
    fresh.set_authorizer(None)
    assert [r['name'] for r in fresh.execute('PRAGMA table_info(graph_entity)')]==['id']
    assert fresh.execute("SELECT name FROM sqlite_master WHERE name='graph_property_value'").fetchone() is None
    fresh.close()


def test_flag_off_readable_and_all_mutations_denied(env,monkeypatch):
    _,_,edit,_,client = env
    e = entity(edit)
    monkeypatch.setattr(config,'GRAPH_EDIT_ENABLED',False)
    assert client.get(f"/graph/entities/{e['id']}").status_code==200
    assert client.get('/graph/schema').json()['editing_enabled'] is False
    assert client.post('/graph/entities',json={'type':'product','name':'blocked'}).status_code==403
    assert client.delete(f"/graph/entities/{e['id']}?expected_revision=1").status_code==403


def test_read_graph_facts_evidence_and_stale_validation(agent_env):
    from agent.evidence_context import Owner, owner_scope, run_scope
    from agent.validation import validate_answer
    from tools.tool import read_graph_facts
    edit = GraphEditService(agent_env.db)
    e,p = entity(edit),definition(edit)
    value = edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':'first'})
    owner = Owner('session','graph-test')
    run_id = agent_env.evidence_repo.start_run('session','graph-test','test',None)
    with owner_scope(owner),run_scope(run_id):
        read = read_graph_facts.invoke({'entity_id':e['id']})
    evidence_id = read['evidence_id']
    assert evidence_id
    evidence = agent_env.evidence_repo.get(evidence_id)
    assert evidence['origin_type']=='graph_fact' and evidence['file_id'] is None and evidence['page'] is None
    answer = '검토 메모입니다.\n근거: '+evidence_id
    assert validate_answer(run_id,owner,answer).ok
    edit.execute('update_property',value['value_id'],{'entity_id':e['id'],'expected_revision':1,'value':'second'})
    assert not validate_answer(run_id,owner,answer).ok
    assert json.loads(agent_env.evidence_repo.get(evidence_id)['text'])['facts']['properties'][0]['value']=='first'
    edit.execute('delete_entity',e['id'],{'expected_revision':1})
    assert not validate_answer(run_id,owner,answer).ok


def test_alias_edit_audit_retains_historical_identity(env):
    db,graph,edit,read,_ = env
    e = entity(edit,aliases=['Old Alpha'])
    edit.execute('update_entity',e['id'],{'expected_revision':1,'remove_aliases':['Old Alpha'],'aliases':['New Alpha']})
    assert graph.get_entity(e['id'])['aliases']==['Alpha','New Alpha']
    event=read.changes('entity',e['id'])[0]
    assert 'Old Alpha' in json.loads(event['before_json'])['aliases']
    assert 'Old Alpha' not in json.loads(event['after_json'])['aliases']
    file_page(db)
    graph.replace_page('f1',1,PageGraph(entities=[ExtractedEntity(type='product',name='Old Alpha')]))
    assert len(graph.list_entities())==1
    assert graph.find_entities('Old Alpha')[0]['id']==e['id']


def test_property_text_search_and_delete_updates(env):
    _,graph,edit,_,client = env
    e,p=entity(edit),definition(edit)
    v=edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':'전용 검토 분류'})
    assert graph.find_entities('전용 검토')[0]['id']==e['id']
    assert client.get('/graph/entities',params={'q':'전용 검토'}).json()[0]['id']==e['id']
    edit.execute('delete_property',v['value_id'],{'entity_id':e['id'],'expected_revision':1})
    assert graph.find_entities('전용 검토')==[]


def test_spec_exclusion_preserves_source_and_different_refs_cannot_merge(env):
    from repository.spec_repository import SpecRepository
    db,graph,edit,read,_=env
    spec=SpecRepository(db)
    a=spec.create_product(model='Model AA',name='AA',category='other')
    b=spec.create_product(model='Model BB',name='BB',category='other',parent_id=a['id'])
    graph.seed_specs()
    ea=next(e for e in graph.find_entities('Model AA') if e['ref_id']==a['id'])
    eb=next(e for e in graph.find_entities('Model BB') if e['ref_id']==b['id'])
    r=graph.get_entity(eb['id'])['relations'][0]
    edit.execute('delete_relation',r['id'],{'expected_revision':1})
    graph.seed_specs()
    assert graph.get_entity(eb['id'])['relations']==[]
    assert spec.get_product(b['id'])['parent_id']==a['id']
    with pytest.raises(GraphConflictError):
        edit.execute('merge_entity',ea['id'],{'target_id':eb['id'],'expected_revision':1,'target_revision':1})
    edit.execute('update_entity',ea['id'],{'expected_revision':1,'name':'화면 표시용'})
    graph.seed_specs()
    actual=graph.get_entity(ea['id'])
    assert actual['ref_id']==a['id'] and actual['name']=='화면 표시용'
    assert spec.get_product(a['id'])['model']=='Model AA'


def test_same_type_auto_replacement_keeps_original_claim_excluded(env):
    db,graph,edit,_,_=env
    file_page(db)
    page=PageGraph(entities=[ExtractedEntity(type='product',name='Alpha'),ExtractedEntity(type='component',name='Chip')],
        relations=[ExtractedRelation(source='Alpha',target='Chip',type='has_component')])
    graph.replace_page('f1',1,page)
    e=graph.find_entities('Alpha')[0]
    r=graph.get_entity(e['id'])['relations'][0]
    manual=edit.execute('update_relation',r['id'],{'expected_revision':1,'source':{'reason':'담당자 확인'}})
    graph.replace_page('f1',1,page)
    # Original triple exclusion applies only to automated claims; replacement manual fact is effective.
    assert manual['origin']=='manual'
    assert [r['id'] for r in graph.get_entity(e['id'])['relations']]==[manual['id']]


def test_graph_read_budget_uncertain_not_evidence_and_refresh(agent_env):
    from agent.evidence_context import Owner,owner_scope,run_scope
    from tools.tool import read_graph_facts
    edit=GraphEditService(agent_env.db)
    e,p=entity(edit),definition(edit,multiple=True)
    run_id=agent_env.evidence_repo.start_run('session','budget','test',None)
    edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':'미확정 단서','confirmation':'uncertain'})
    with owner_scope(Owner('session','budget')),run_scope(run_id):
        first=read_graph_facts.invoke({'entity_id':e['id']})
        assert first['evidence_id'] is None and len(first['uncertain_clues'])==1
        for i in range(8):
            edit.execute('create_property',e['id'],{'property_id':p['property_id'],'value':str(i)+'가'*3999})
        read=read_graph_facts.invoke({'entity_id':e['id']})
        assert read['next_offset'] and len(json.dumps(read,ensure_ascii=False))<24000
        snapshot=json.loads(agent_env.evidence_repo.get(read['evidence_id'])['text'])
        assert len(snapshot['facts']['properties'])==len(read['properties'])<8
        next_page=read_graph_facts.invoke({'entity_id':e['id'],'offset':read['next_offset']})
        assert {p['value_id'] for p in read['properties']}.isdisjoint({p['value_id'] for p in next_page['properties']})


def test_api_complete_edit_restore_and_validation(env):
    _,_,_,_,client=env
    a=client.post('/graph/entities',json={'type':'product','name':'API Alpha'}).json()
    b=client.post('/graph/entities',json={'type':'product','name':'API Beta'}).json()
    p=client.post('/graph/property-definitions',json={'key':'custom:api','label':'API 점수','value_type':'number','unit':'점'}).json()
    assert client.post(f"/graph/entities/{a['id']}/properties",json={'property_id':p['property_id'],'value':'bad'}).status_code==400
    v=client.post(f"/graph/entities/{a['id']}/properties",json={'property_id':p['property_id'],'value':1}).json()
    assert client.patch(f"/graph/entities/{a['id']}/properties/{v['value_id']}",json={'value':2,'expected_revision':1}).status_code==200
    assert client.patch(f"/graph/entities/{a['id']}/properties/{v['value_id']}",json={'value':3,'expected_revision':1}).status_code==409
    t=client.post('/graph/relation-types',json={'key':'custom:api_relation','label':'API 관계'}).json()
    r=client.post('/graph/relations',json={'source_id':a['id'],'target_id':b['id'],'type':t['key']}).json()
    assert client.patch(f"/graph/relations/{r['id']}",json={'reverse':True,'expected_revision':1}).status_code==200
    deleted=client.delete(f"/graph/relations/{r['id']}?expected_revision=2").json()
    assert client.post(f"/graph/relations/{r['id']}/restore",json={'expected_revision':deleted['revision']}).status_code==200
    impact=client.get(f"/graph/entities/{a['id']}/delete-impact").json()
    assert len(impact['relations'])==len(impact['properties'])==1
    assert client.delete(f"/graph/entities/{a['id']}?expected_revision=1").status_code==200
    assert client.get(f"/graph/entities/{a['id']}/facts").status_code==404
    assert client.post(f"/graph/entities/{a['id']}/restore",json={'expected_revision':2}).status_code==200
    assert client.get(f"/graph/entities/{a['id']}/facts").json()['properties'][0]['value']==2
    assert len(client.get('/graph/changes').json())>=10
