import os, tempfile
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app import main

def test_window_boundaries_and_overlap():
    with tempfile.TemporaryDirectory() as tmp:
        main.DB_PATH=os.path.join(tmp,'test.db')
        main.init_db()
        client=TestClient(main.app)
        start=datetime.now(timezone.utc)+timedelta(days=2)
        start=start.replace(hour=8,minute=0,second=0,microsecond=0)
        end=start+timedelta(hours=2)
        a={'game_id':'gta','console_id':'ps5-01','start_at':start.isoformat(),'end_at':end.isoformat()}
        r=client.post('/assignments',json=a)
        assert r.status_code==201,r.text
        assert client.post('/assignments',json=a).status_code==409
        aid=r.json()['id']
        def book(minute,duration):return client.post('/reservations',json={'assignment_id':aid,'user_public_name':'Tester','start_at':(start+timedelta(minutes=minute)).isoformat(),'minutes':duration})
        assert book(90,30).status_code==201
        assert book(110,10).status_code==409  # overlap
        assert book(120,10).status_code==409 # begin at exclusive end
        assert book(70,30).status_code==409 # overlaps existing booking
        assert book(70,10).status_code==201
        assert book(110,30).status_code==409 # extends beyond end

def test_non_simulated_console_cannot_sell():
    with tempfile.TemporaryDirectory() as tmp:
        main.DB_PATH=os.path.join(tmp,'test.db')
        main.init_db()
        c=TestClient(main.app)
        s=datetime.now(timezone.utc)+timedelta(days=3);e=s+timedelta(hours=1)
        aid=c.post('/assignments',json={'game_id':'gow','console_id':'ps5-02','start_at':s.isoformat(),'end_at':e.isoformat()}).json()['id']
        assert c.post('/reservations',json={'assignment_id':aid,'user_public_name':'Tester','start_at':s.isoformat(),'minutes':10}).status_code==409
