"""LocaPlay API: server-side demo of game/console inventory, scheduling and simulated sessions.
NOT production auth, billing, webhook or hardware control. Those endpoints remain disabled.
"""
import os, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .adapters import ADAPTERS, AdapterKind, AdapterError

DB_PATH = os.getenv('LOCAPLAY_DB', str(Path(__file__).resolve().parents[1] / 'locaplay_demo.db'))
app = FastAPI(title='LocaPlay API (demo)', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('LOCAPLAY_CORS','http://localhost:3000').split(','),allow_credentials=False,allow_methods=['GET','POST','PUT'],allow_headers=['Content-Type'])

def now(): return datetime.now(timezone.utc)
@contextmanager
def db():
    conn=sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try: yield conn
    finally: conn.close()

def init_db():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,title TEXT NOT NULL,platform TEXT NOT NULL,licensed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS consoles(id TEXT PRIMARY KEY,name TEXT NOT NULL,platform TEXT NOT NULL,adapter TEXT NOT NULL DEFAULT 'unconfigured',validated INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY,game_id TEXT NOT NULL REFERENCES games(id),console_id TEXT NOT NULL REFERENCES consoles(id),start_at TEXT NOT NULL,end_at TEXT NOT NULL, CHECK(start_at<end_at));
        CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,assignment_id TEXT NOT NULL REFERENCES assignments(id),user_public_name TEXT NOT NULL,start_at TEXT NOT NULL,end_at TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,reservation_id TEXT NOT NULL UNIQUE REFERENCES reservations(id),started_at TEXT NOT NULL,ends_at TEXT NOT NULL,status TEXT NOT NULL);''')
        if not c.execute('SELECT 1 FROM games LIMIT 1').fetchone():
            c.executemany('INSERT INTO games(id,title,platform,licensed) VALUES (?,?,?,0)', [('gta','GTA VI','PS5'),('gow','God of War','PS5'),('zelda','Zelda','Switch')])
            c.executemany('INSERT INTO consoles(id,name,platform,adapter,validated) VALUES (?,?,?,?,?)',[('ps5-01','PS5 nº 01','PS5','simulated',1),('ps5-02','PS5 nº 02','PS5','unconfigured',0)])

@app.on_event('startup')
def startup():init_db()

class ConsoleInput(BaseModel):
    name:str=Field(min_length=2,max_length=100)
    platform:str
    adapter:str='unconfigured'
class AssignmentInput(BaseModel):
    game_id:str
    console_id:str
    start_at:datetime
    end_at:datetime
class ReservationInput(BaseModel):
    assignment_id:str
    user_public_name:str=Field(min_length=2,max_length=50)
    start_at:datetime
    minutes:int=Field(ge=1,le=240)
class InputCommand(BaseModel):
    command:str

@app.get('/health')
def health():return {'status':'ok','mode':'demo','real_payments':False,'real_consoles':False}
@app.get('/games')
def games():
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM games ORDER BY title')]
@app.get('/consoles')
def consoles():
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM consoles ORDER BY name')]
@app.post('/consoles',status_code=201)
def create_console(payload:ConsoleInput):
    if payload.adapter not in [x.value for x in AdapterKind]+['unconfigured']:raise HTTPException(422,'Unknown adapter')
    cid=str(uuid.uuid4())
    with db() as c:c.execute('INSERT INTO consoles VALUES(?,?,?,?,0)',(cid,payload.name,payload.platform,payload.adapter))
    return {'id':cid,'validated':False,'note':'Hardware not validated'}
@app.get('/adapters')
def adapters():return {'available':[x.value for x in AdapterKind],'hardware_ready':False,'simulator_ready':True}
@app.get('/assignments')
def assignments():
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM assignments ORDER BY start_at')]
@app.post('/assignments',status_code=201)
def create_assignment(payload:AssignmentInput):
    a,b=payload.start_at,payload.end_at
    if a.tzinfo is None or b.tzinfo is None:raise HTTPException(422,'Timezone required')
    a,b=a.astimezone(timezone.utc),b.astimezone(timezone.utc)
    if a>=b:raise HTTPException(422,'Invalid interval')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM consoles WHERE id=?',(payload.console_id,)).fetchone():raise HTTPException(404,'Console missing')
        if not c.execute('SELECT 1 FROM games WHERE id=?',(payload.game_id,)).fetchone():raise HTTPException(404,'Game missing')
        if c.execute('SELECT 1 FROM assignments WHERE console_id=? AND start_at<? AND end_at>?',(payload.console_id,b.isoformat(),a.isoformat())).fetchone():raise HTTPException(409,'Overlapping console assignment')
        aid=str(uuid.uuid4());c.execute('INSERT INTO assignments VALUES(?,?,?,?,?)',(aid,payload.game_id,payload.console_id,a.isoformat(),b.isoformat()));c.commit()
    return {'id':aid,'start_at':a,'end_at':b}
@app.post('/reservations',status_code=201)
def reserve(payload:ReservationInput):
    if payload.start_at.tzinfo is None:raise HTTPException(422,'Timezone required')
    start=payload.start_at.astimezone(timezone.utc);end=start+timedelta(minutes=payload.minutes)
    if start<now():raise HTTPException(409,'Cannot reserve past time')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        assignment=c.execute('SELECT a.*,c.adapter,c.validated FROM assignments a JOIN consoles c ON a.console_id=c.id WHERE a.id=?',(payload.assignment_id,)).fetchone()
        if not assignment:raise HTTPException(404,'Assignment missing')
        if assignment['adapter']!='simulated' or not assignment['validated']:raise HTTPException(409,'Console not validated for demo operation')
        if start.isoformat()<assignment['start_at'] or end.isoformat()>assignment['end_at']:raise HTTPException(409,'Requested duration exceeds availability window')
        conflict=c.execute('SELECT 1 FROM reservations WHERE assignment_id=? AND status IN (\'confirmed\',\'active\') AND start_at<? AND end_at>?',(payload.assignment_id,end.isoformat(),start.isoformat())).fetchone()
        if conflict:raise HTTPException(409,'Schedule conflict')
        rid=str(uuid.uuid4());c.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?)',(rid,payload.assignment_id,payload.user_public_name,start.isoformat(),end.isoformat(),'confirmed',now().isoformat()));c.commit()
    return {'id':rid,'start_at':start,'end_at':end,'status':'confirmed','payment':'not charged — demo'}
@app.get('/reservations')
def reservations():
    # Demo only; NEVER expose this unauthenticated in production.
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM reservations ORDER BY created_at DESC')]
@app.post('/sessions/{reservation_id}/start')
async def start_session(reservation_id:str):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        reservation=c.execute('SELECT r.*,a.console_id FROM reservations r JOIN assignments a ON r.assignment_id=a.id WHERE r.id=?',(reservation_id,)).fetchone()
        if not reservation:raise HTTPException(404,'Reservation not found')
        if reservation['status']!='confirmed':raise HTTPException(409,'Already started or ended')
        current=now()
        if not (datetime.fromisoformat(reservation['start_at'])<=current<datetime.fromisoformat(reservation['end_at'])):raise HTTPException(409,'Outside confirmed session time')
        if c.execute('''SELECT 1 FROM sessions s JOIN reservations r ON s.reservation_id=r.id JOIN assignments a ON r.assignment_id=a.id WHERE a.console_id=? AND s.status='active' ''',(reservation['console_id'],)).fetchone():raise HTTPException(409,'Console already controlled')
        sid=str(uuid.uuid4());c.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(sid,reservation_id,current.isoformat(),reservation['end_at'],'active'));c.execute('UPDATE reservations SET status=? WHERE id=?',('active',reservation_id));c.commit()
    await ADAPTERS[AdapterKind.SIMULATED].start_stream(sid)
    return {'session_id':sid,'simulated':True,'ends_at':reservation['end_at']}
@app.post('/sessions/{session_id}/input')
async def session_input(session_id:str,payload:InputCommand):
    with db() as c:
        s=c.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
        if not s or s['status']!='active' or now()>=datetime.fromisoformat(s['ends_at']):raise HTTPException(403,'Session expired')
    try:return await ADAPTERS[AdapterKind.SIMULATED].send_input(session_id,{'command':payload.command})
    except AdapterError as e:raise HTTPException(403,str(e))
@app.post('/sessions/{session_id}/end')
async def end_session(session_id:str):
    with db() as c:
        c.execute('BEGIN IMMEDIATE');s=c.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
        if not s:raise HTTPException(404,'Session missing')
        c.execute('UPDATE sessions SET status=? WHERE id=?',('ended',session_id));c.execute('UPDATE reservations SET status=? WHERE id=?',('ended',s['reservation_id']));c.commit()
    await ADAPTERS[AdapterKind.SIMULATED].revoke_input(session_id)
    await ADAPTERS[AdapterKind.SIMULATED].stop_stream(session_id)
    return {'status':'ended'}
