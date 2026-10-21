"""ImmXrsive Release 2 working-branch backend.
Deploy with HTTPS. Requires GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET.
Cross-origin static frontend uses short-lived OAuth exchange tickets and bearer sessions.
"""
import io
import json
import os
import re
import secrets
import sqlite3
import hashlib
import hmac
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import bcrypt
import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader

from schemas import VerificationRequest, VerificationSubmit
from email_service import send_verification_email

FRONTEND = os.environ.get('FRONTEND_URL', 'https://sajal19-sketch.github.io/immxrsive-platform').rstrip('/')
DB_PATH = os.environ.get('DATABASE_PATH', 'immxrsive.db')
GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID', '')
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '')
APPROVED_DOMAINS = set(x.strip().lower() for x in os.environ.get('APPROVED_EMAIL_DOMAINS', 'algomau.ca').split(',') if x.strip())
OTP_MINUTES = min(30, max(1, int(os.environ.get('OTP_EXPIRY_MINUTES', '10'))))
app = FastAPI(title='ImmXrsive API')
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND], allow_methods=['GET','POST','PUT','OPTIONS'], allow_headers=['Authorization','Content-Type'], allow_credentials=False)

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        conn.close()

def now():
    return datetime.now(timezone.utc)

def stamp(dt):
    return dt.isoformat()

def parse_time(value):
    return datetime.fromisoformat(value)

def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def parsed(value, fallback=None):
    try: return json.loads(value) if value else (fallback if fallback is not None else [])
    except (ValueError, TypeError): return fallback if fallback is not None else []

def setup_db():
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS students (
          id TEXT PRIMARY KEY, name TEXT, headline TEXT, program TEXT, status TEXT,
          availability TEXT, skills TEXT, github_link TEXT, project_ids TEXT)''')
        cols = {x['name'] for x in conn.execute('PRAGMA table_info(students)')}
        extras = {
          'email':'TEXT', 'github_id':'TEXT', 'is_algoma_verified':'INTEGER DEFAULT 0',
          'is_published':'INTEGER', 'bio':'TEXT DEFAULT ""', 'education':'TEXT DEFAULT ""',
          'experience':'TEXT DEFAULT ""', 'portfolio_link':'TEXT DEFAULT ""',
          'linkedin_link':'TEXT DEFAULT ""', 'location':'TEXT DEFAULT ""',
          'show_availability':'INTEGER DEFAULT 1', 'show_links':'INTEGER DEFAULT 1'
        }
        for key, spec in extras.items():
            if key not in cols: conn.execute(f'ALTER TABLE students ADD COLUMN {key} {spec}')
        # Keep seeded public R1 profiles visible; mark only newly created OAuth profiles private.
        conn.execute('UPDATE students SET is_published=1 WHERE is_published IS NULL AND github_id IS NULL')
        conn.execute('UPDATE students SET is_published=0 WHERE is_published IS NULL')
        conn.execute('''CREATE TABLE IF NOT EXISTS auth_tickets(
           ticket_hash TEXT PRIMARY KEY, student_id TEXT NOT NULL, expires_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS auth_sessions(
           token_hash TEXT PRIMARY KEY, student_id TEXT NOT NULL, expires_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS oauth_states(
           state_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS otp_challenges(
           student_id TEXT PRIMARY KEY, email TEXT NOT NULL, otp_hash TEXT NOT NULL,
           expires_at TEXT NOT NULL, attempts INTEGER DEFAULT 0, requested_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS verification_rate(
           student_id TEXT PRIMARY KEY, window_start TEXT NOT NULL, requests INTEGER NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS projects(
           id TEXT PRIMARY KEY, title TEXT, description TEXT, domain TEXT, technologies TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS project_contributors(
           project_id TEXT, student_id TEXT, role TEXT)''')

@app.on_event('startup')
def startup(): setup_db()

def authenticated(request: Request):
    header = request.headers.get('authorization','')
    if not header.startswith('Bearer '):
        raise HTTPException(401,'Please sign in with GitHub.')
    with db() as conn:
        s = conn.execute('SELECT student_id,expires_at FROM auth_sessions WHERE token_hash=?', (hash_token(header[7:]),)).fetchone()
        if not s or parse_time(s['expires_at']) < now(): raise HTTPException(401,'Session expired. Sign in again.')
        student = conn.execute('SELECT * FROM students WHERE id=?', (s['student_id'],)).fetchone()
        if not student: raise HTTPException(401,'Account not found')
        return dict(student)

def verified(student=Depends(authenticated)):
    if not student['is_algoma_verified']: raise HTTPException(403,'Verify your Algoma email before editing your profile.')
    return student

@app.get('/api/auth/github')
def github_login(state: str):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET: raise HTTPException(503,'GitHub OAuth not configured')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{24,128}', state): raise HTTPException(400,'Invalid sign-in state')
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO oauth_states VALUES (?,?)',(hash_token(state),stamp(now()+timedelta(minutes=10))))
    url = 'https://github.com/login/oauth/authorize?' + urlencode({'client_id': GITHUB_CLIENT_ID, 'scope':'read:user','state':state})
    return RedirectResponse(url)

@app.get('/api/auth/callback')
async def github_callback(code: str, state: str):
    with db() as conn:
        rec=conn.execute('SELECT expires_at FROM oauth_states WHERE state_hash=?',(hash_token(state),)).fetchone()
        conn.execute('DELETE FROM oauth_states WHERE state_hash=?',(hash_token(state),))
        if not rec or parse_time(rec['expires_at'])<now(): raise HTTPException(400,'Invalid/expired OAuth state')
    async with httpx.AsyncClient(timeout=15) as client:
        t=await client.post('https://github.com/login/oauth/access_token',data={'client_id':GITHUB_CLIENT_ID,'client_secret':GITHUB_CLIENT_SECRET,'code':code},headers={'Accept':'application/json'})
        if t.status_code!=200: raise HTTPException(502,'GitHub token exchange failed')
        access=t.json().get('access_token')
        if not access: raise HTTPException(400,'GitHub sign-in was not completed')
        response=await client.get('https://api.github.com/user',headers={'Authorization':f'Bearer {access}','Accept':'application/vnd.github+json'})
        if response.status_code!=200: raise HTTPException(502,'Could not retrieve GitHub identity')
        identity=response.json()
    gh_id=str(identity.get('id') or '')
    if not gh_id.isdigit(): raise HTTPException(502,'Invalid GitHub identity')
    with db() as conn:
        student=conn.execute('SELECT id FROM students WHERE github_id=?',(gh_id,)).fetchone()
        if student: sid=student['id']
        else:
            sid='u_'+secrets.token_hex(10)
            conn.execute('''INSERT INTO students (id,github_id,name,headline,skills,availability,project_ids,status,is_published,github_link)
             VALUES (?,?,?,?,'[]','[]','[]','Current',0,?)''',(sid,gh_id,identity.get('name') or identity.get('login') or 'Student','Student profile draft',identity.get('html_url') or ''))
        ticket=secrets.token_urlsafe(40)
        conn.execute('INSERT INTO auth_tickets VALUES (?,?,?)',(hash_token(ticket),sid,stamp(now()+timedelta(minutes=2))))
    return RedirectResponse(FRONTEND+'/login.html#ticket='+ticket+'&state='+state)

class TicketExchange(BaseModel): ticket: str
@app.post('/api/auth/exchange')
def exchange(payload: TicketExchange):
    with db() as conn:
        rec=conn.execute('SELECT * FROM auth_tickets WHERE ticket_hash=?',(hash_token(payload.ticket),)).fetchone()
        conn.execute('DELETE FROM auth_tickets WHERE ticket_hash=?',(hash_token(payload.ticket),))
        if not rec or parse_time(rec['expires_at'])<now(): raise HTTPException(401,'Sign-in ticket expired; try again')
        token=secrets.token_urlsafe(48)
        conn.execute('INSERT INTO auth_sessions VALUES (?,?,?)',(hash_token(token),rec['student_id'],stamp(now()+timedelta(hours=12))))
        return {'access_token':token,'token_type':'bearer','expires_in':43200}

@app.get('/api/auth/me')
def current_student(student=Depends(authenticated)):
    return {'id':student['id'],'name':student['name'],'email':student['email'],'verified':bool(student['is_algoma_verified']), 'published':bool(student['is_published'])}

@app.post('/api/auth/logout')
def logout(request:Request,student=Depends(authenticated)):
    with db() as conn:conn.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hash_token(request.headers['authorization'][7:]),))
    return {'message':'Signed out'}

def require_domain(email):
    email=email.strip().lower()
    if email.count('@') != 1 or email.rsplit('@',1)[1] not in APPROVED_DOMAINS:
        raise HTTPException(400,'Use an approved Algoma university email address.')
    return email

@app.post('/api/request-verification')
def request_verification(req:VerificationRequest,student=Depends(authenticated)):
    if student['is_algoma_verified']: return {'message':'Your affiliation is already verified.'}
    email=require_domain(str(req.email))
    with db() as conn:
        existing=conn.execute('SELECT id FROM students WHERE lower(email)=? AND id<>?',(email,student['id'])).fetchone()
        if existing: raise HTTPException(409,'This email is linked to another account. Contact support.')
        rate=conn.execute('SELECT * FROM verification_rate WHERE student_id=?',(student['id'],)).fetchone()
        if rate and parse_time(rate['window_start'])>now()-timedelta(hours=1):
            if rate['requests']>=5: raise HTTPException(429,'Too many messages. Try again in an hour.')
            conn.execute('UPDATE verification_rate SET requests=requests+1 WHERE student_id=?',(student['id'],))
        else: conn.execute('INSERT OR REPLACE INTO verification_rate VALUES (?,?,1)',(student['id'],stamp(now())))
        raw=f'{secrets.randbelow(1000000):06d}'
        pwd=bcrypt.hashpw(raw.encode(),bcrypt.gensalt()).decode()
        conn.execute('INSERT OR REPLACE INTO otp_challenges VALUES (?,?,?,?,0,?)',(student['id'],email,pwd,stamp(now()+timedelta(minutes=OTP_MINUTES)),stamp(now())))
    # Send only after commit, never print OTP. Delivery errors must be visible to user.
    send_verification_email(email,raw)
    return {'message':'Verification email requested. Check your university inbox.'}

@app.post('/api/verify-code')
def verify_code(req: VerificationSubmit,student=Depends(authenticated)):
    email=require_domain(str(req.email))
    with db() as conn:
        rec=conn.execute('SELECT * FROM otp_challenges WHERE student_id=?',(student['id'],)).fetchone()
        if not rec or rec['email']!=email: raise HTTPException(400,'Request a code for this email first.')
        if parse_time(rec['expires_at'])<now():
            conn.execute('DELETE FROM otp_challenges WHERE student_id=?',(student['id'],))
            raise HTTPException(400,'Code expired. Request a new one.')
        if rec['attempts']>=5: raise HTTPException(429,'Too many attempts. Request a fresh code.')
        if not bcrypt.checkpw(req.code.encode(),rec['otp_hash'].encode()):
            conn.execute('UPDATE otp_challenges SET attempts=attempts+1 WHERE student_id=?',(student['id'],))
            return_error='Invalid code. Please try again.'
        else:
            conn.execute('UPDATE students SET email=?,is_algoma_verified=1 WHERE id=?',(email,student['id']))
            conn.execute('DELETE FROM otp_challenges WHERE student_id=?',(student['id'],))
            return_error=None
    if return_error: raise HTTPException(400,return_error)
    return {'message':'Algoma affiliation verified.'}

class ProfileUpdate(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    headline:str=Field(default='',max_length=250)
    bio:str=Field(default='',max_length=5000)
    education:str=Field(default='',max_length=3000)
    experience:str=Field(default='',max_length=5000)
    location:str=Field(default='',max_length=120)
    linkedin_link:str=Field(default='',max_length=500)
    portfolio_link:str=Field(default='',max_length=500)
    skills:list[str]=Field(default_factory=list,max_length=50)
    availability:list[str]=Field(default_factory=list,max_length=3)
    show_availability:bool=True
    show_links:bool=True

def validate_links(data):
    for label in ('linkedin_link','portfolio_link'):
        value=getattr(data,label)
        if value and not re.match(r'^https://[^\s<>"\']+$',value,re.I):raise HTTPException(422,f'{label} must start with https://')
    if any(x not in {'internship','contract','full-time'} for x in data.availability):
        raise HTTPException(422,'Availability must be internship, contract or full-time.')

def private_profile(row):
    x=dict(row)
    for key in ('skills','availability','project_ids'):x[key]=parsed(x.get(key))
    return {k:x.get(k) for k in ('id','email','name','headline','bio','education','experience','location','linkedin_link','portfolio_link','skills','availability','project_ids','is_published','is_algoma_verified','show_availability','show_links','github_link')}

def public_profile(row):
    p=private_profile(row)
    # Never expose auth identity, email, draft state, or private fields.
    out={k:p[k] for k in ('id','name','headline','bio','education','experience','location','skills','project_ids')}
    out['status']=row['status'];out['program']=row['program']
    out['availability']=p['availability'] if row['show_availability'] else []
    out['github_link']=p['github_link'] if row['show_links'] else ''
    out['linkedin_link']=p['linkedin_link'] if row['show_links'] else ''
    out['portfolio_link']=p['portfolio_link'] if row['show_links'] else ''
    out['project_count']=len(p['project_ids'])
    return out

@app.get('/api/profile/me')
def own_profile(student=Depends(verified)):return private_profile(student)

@app.put('/api/students/update')
def update_profile(profile:ProfileUpdate,student=Depends(verified)):
    validate_links(profile)
    # Ownership is derived exclusively from the bearer token; no student_id/email input.
    with db() as conn:
        conn.execute('''UPDATE students SET name=?,headline=?,bio=?,education=?,experience=?,location=?,linkedin_link=?,portfolio_link=?,skills=?,availability=?,show_availability=?,show_links=? WHERE id=?''',
         (profile.name,profile.headline,profile.bio,profile.education,profile.experience,profile.location,profile.linkedin_link,profile.portfolio_link,json.dumps(profile.skills),json.dumps(profile.availability),int(profile.show_availability),int(profile.show_links),student['id']))
    return {'message':'Private profile saved','id':student['id']}

@app.get('/api/profile/preview')
def preview(student=Depends(verified)):
    return public_profile(student)

@app.post('/api/profile/publish')
def publish(student=Depends(verified)):
    with db() as conn:conn.execute('UPDATE students SET is_published=1 WHERE id=?',(student['id'],))
    return {'message':'Profile published','public_url':f'{FRONTEND}/student.html?id={student["id"]}'}

@app.post('/api/profile/unpublish')
def unpublish(student=Depends(verified)):
    with db() as conn:conn.execute('UPDATE students SET is_published=0 WHERE id=?',(student['id'],))
    return {'message':'Profile removed from public discovery; draft retained'}

@app.get('/api/directory')
def directory(q:str='',skills:list[str]=Query(default=[]),availability:list[str]=Query(default=[]),status:list[str]=Query(default=[])):
    with db() as conn:rows=conn.execute('SELECT * FROM students WHERE is_published=1 ORDER BY id').fetchall()
    results=[]
    for row in rows:
        s=public_profile(row)
        corpus=' '.join([s['name'] or '',s['headline'] or '',*s['skills']]).lower()
        if q.lower() not in corpus:continue
        if any(skill.lower() not in {v.lower() for v in s['skills']} for skill in skills):continue
        if availability and not (set(x.lower() for x in availability)&set(x.lower() for x in s['availability'])):continue
        if status and (s['status'] or '').lower() not in {x.lower() for x in status}:continue
        results.append(s)
    return results

@app.get('/api/students/{student_id}')
def student_detail(student_id:str):
    with db() as conn:student=conn.execute('SELECT * FROM students WHERE id=? AND is_published=1',(student_id,)).fetchone()
    if not student:raise HTTPException(404,'Student not found')
    return public_profile(student)

@app.get('/api/projects/{project_id}')
def project_detail(project_id:str):
    with db() as conn:
        project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        if not project:raise HTTPException(404,'Project not found')
        contributors=conn.execute('SELECT student_id,role FROM project_contributors WHERE project_id=?',(project_id,)).fetchall()
    out=dict(project);out['technologies']=parsed(out['technologies']);out['contributors']=[dict(x) for x in contributors]
    return out

@app.post('/api/resumes/parse')
async def parse_resume(file:UploadFile=File(...),student=Depends(verified)):
    if not (file.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'Upload a PDF file')
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise HTTPException(413,'PDF must be smaller than 5 MB')
    if not raw.startswith(b'%PDF-'):raise HTTPException(400,'Invalid PDF format')
    try:
        reader=PdfReader(io.BytesIO(raw))
        lines='\n'.join(page.extract_text() or '' for page in reader.pages[:12]).splitlines()
        text='\n'.join(lines)
    except Exception:raise HTTPException(422,'This PDF could not be read. You can still edit your profile manually.')
    # Extraction is data-only; do not execute instructions embedded in the PDF.
    known=['Python','JavaScript','React','SQL','FastAPI','HTML','CSS','Git','PostgreSQL','Unity','C#','TypeScript','WebXR']
    found=[skill for skill in known if re.search(r'(?<!\w)'+re.escape(skill)+r'(?!\w)',text,re.I)]
    links=list(dict.fromkeys(re.findall(r'https?://[^\s<>"\']+',text)))[:8]
    candidates={'name':next((x.strip() for x in lines if x.strip()),''),'skills':found,'education':'','experience':'','links':links}
    # Uploaded original bytes are only in memory; do not store or serve original PDFs.
    return {'filename':file.filename,'extracted_name':candidates['name'],'extracted_skills':found,'candidates':candidates,'message':'Review all suggestions before applying. Uploaded original PDF is not stored.'}
