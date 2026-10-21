from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import json
import html
from pypdf import PdfReader
import io
import uuid
import httpx

# IMPORTS FOR VERIFICATION
import random
import string
from datetime import datetime, timedelta, timezone
import bcrypt
from schemas import VerificationRequest, VerificationSubmit
from email_service import send_verification_email

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect('immxrsive.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_otp() -> str:
    """Generate a secure 6-digit OTP."""
    return ''.join(random.choices(string.digits, k=6))

@app.on_event("startup")
def setup_db():
    """Automatically updates the SQLite DB schema when the server starts."""
    conn = get_db()
    
    # Add verification column to students table if it doesn't exist
    try:
        conn.execute('ALTER TABLE students ADD COLUMN is_algoma_verified BOOLEAN DEFAULT FALSE')
    except sqlite3.OperationalError:
        pass 
        
    # Ensure students table has an email column
    try:
        conn.execute('ALTER TABLE students ADD COLUMN email TEXT')
    except sqlite3.OperationalError:
        pass 

    # Ensure students table has a github_id column
    try:
        conn.execute('ALTER TABLE students ADD COLUMN github_id TEXT')
    except sqlite3.OperationalError:
        pass

    # Add published status for R2.10 Private Drafts
    try:
        conn.execute('ALTER TABLE students ADD COLUMN is_published BOOLEAN DEFAULT FALSE')
    except sqlite3.OperationalError:
        pass

    # Create OTP tracking table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS otp_verifications (
            email TEXT PRIMARY KEY,
            otp_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempt_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


# --- GITHUB OAUTH (R2.01 - R2.03) ---

GITHUB_CLIENT_ID = "Ov23liiC0UQjKQQiriL8"
GITHUB_CLIENT_SECRET = "830635d01d68019518b15fe34949acf49c28906f"

@app.get("/api/auth/github")
async def github_login():
    """Redirects the user to GitHub's authorization page."""
    github_auth_url = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&scope=user:email"
    return RedirectResponse(url=github_auth_url)

@app.get("/api/auth/callback")
async def github_callback(code: str):
    """Handles the return from GitHub, exchanges the code for a token, and gets user info."""
    token_url = "https://github.com/login/oauth/access_token"
    headers = {"Accept": "application/json"}
    data = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "code": code
    }
    
    async with httpx.AsyncClient() as client:
        token_response = await client.post(token_url, data=data, headers=headers)
        token_data = token_response.json()
        
        if "access_token" not in token_data:
            raise HTTPException(status_code=400, detail="Failed to retrieve access token from GitHub")
            
        access_token = token_data["access_token"]
        
        user_url = "https://api.github.com/user"
        user_headers = {"Authorization": f"Bearer {access_token}"}
        user_response = await client.get(user_url, headers=user_headers)
        user_data = user_response.json()
        
        github_username = user_data.get("login")
        github_id = str(user_data.get("id"))
        
        conn = get_db()
        existing_user = conn.execute('SELECT * FROM students WHERE github_id = ?', (github_id,)).fetchone()
        
        if not existing_user:
            conn.execute('''
                INSERT INTO students (id, github_id, is_published, name, headline, skills, availability, project_ids) 
                VALUES (?, ?, 0, ?, 'New GitHub User', '[]', '[]', '[]')
            ''', (github_id[:8], github_id, github_username))
            conn.commit()
            
        conn.close()
        
        return RedirectResponse(url="https://sajal19-sketch.github.io/immxrsive-platform/index.html?login=success")


# --- VERIFICATION ENDPOINTS (R2.04 - R2.09) ---

@app.post("/api/request-verification")
async def request_verification(req: VerificationRequest):
    raw_code = generate_otp()
    hashed_code = bcrypt.hashpw(raw_code.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    
    conn = get_db()
    conn.execute('''
        INSERT INTO otp_verifications (email, otp_hash, expires_at, attempt_count)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(email) DO UPDATE SET
        otp_hash=excluded.otp_hash,
        expires_at=excluded.expires_at,
        attempt_count=0
    ''', (req.email, hashed_code, expires))
    conn.commit()
    conn.close()
    print(f"DEBUG OTP: {raw_code}")
    send_verification_email(req.email, raw_code)
    return {"message": "Verification code sent."}

@app.post("/api/verify-code")
async def verify_code(req: VerificationSubmit):
    conn = get_db()
    record = conn.execute('SELECT * FROM otp_verifications WHERE email = ?', (req.email,)).fetchone()
    
    if not record:
        conn.close()
        raise HTTPException(status_code=400, detail="No verification requested for this email.")
        
    record = dict(record)
    
    if record["attempt_count"] >= 5:
        conn.execute('DELETE FROM otp_verifications WHERE email = ?', (req.email,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=429, detail="Too many failed attempts. Request a new code.")
        
    expires_at = datetime.fromisoformat(record["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        conn.execute('DELETE FROM otp_verifications WHERE email = ?', (req.email,))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=400, detail="Code expired. Request a new code.")
        
    if not bcrypt.checkpw(req.code.encode('utf-8'), record["otp_hash"].encode('utf-8')):
        new_count = record["attempt_count"] + 1
        conn.execute('UPDATE otp_verifications SET attempt_count = ? WHERE email = ?', (new_count, req.email))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Invalid code. {5 - new_count} attempts remaining.")
        
    student = conn.execute('SELECT * FROM students WHERE email = ?', (req.email,)).fetchone()
    
    if not student:
        new_id = str(uuid.uuid4())[:8]
        conn.execute('''
            INSERT INTO students (id, email, is_algoma_verified, is_published, name, headline, skills, availability, project_ids) 
            VALUES (?, ?, 1, 0, ?, 'Newly verified Algoma student', '[]', '[]', '[]')
        ''', (new_id, req.email, "New Student"))
    else:
        conn.execute('UPDATE students SET is_algoma_verified = 1 WHERE email = ?', (req.email,))
        
    conn.execute('DELETE FROM otp_verifications WHERE email = ?', (req.email,))
    conn.commit()
    conn.close()
    
    return {"message": "Email successfully verified."}

@app.put("/api/students/update")
async def update_profile(profile: ProfileUpdate):
    conn = get_db()
    
    # Check if the user exists
    student = conn.execute('SELECT * FROM students WHERE email = ?', (profile.email,)).fetchone()
    if not student:
        conn.close()
        raise HTTPException(status_code=404, detail="Student not found.")
        
    # Convert Python lists to JSON strings for SQLite storage
    skills_json = json.dumps(profile.skills)
    avail_json = json.dumps(profile.availability)
    
    # Update the database record
    conn.execute('''
        UPDATE students 
        SET name = ?, headline = ?, skills = ?, availability = ?
        WHERE email = ?
    ''', (profile.name, profile.headline, skills_json, avail_json, profile.email))
    
    conn.commit()
    conn.close()
    
    return {"message": "Profile saved successfully."}


# --- EXISTING ENDPOINTS ---

@app.get("/api/directory")
def get_directory(q: str = "", skills: list[str] = Query(default=[]), availability: list[str] = Query(default=[])):
    conn = get_db()
    # R2.10: Only show published profiles in the public directory
    students = conn.execute('SELECT * FROM students WHERE is_published = 1').fetchall()
    conn.close()
    
    results = []
    for s in students:
        student = dict(s)
        student['skills'] = json.loads(student['skills'])
        student['availability'] = json.loads(student['availability'])
        
        match = True
        if q:
            search_text = q.lower()
            if search_text not in student['name'].lower() and search_text not in student['headline'].lower():
                match = False
                
        if skills:
            for skill in skills:
                if skill not in student['skills']:
                    match = False
                    break
                    
        if availability:
            has_avail = False
            for avail in availability:
                if avail in student['availability']:
                    has_avail = True
                    break
            if not has_avail:
                match = False
                
        if match:
            student['project_count'] = len(json.loads(student['project_ids']))
            results.append(student)
            
    return results

@app.get("/api/students/{student_id}")
def get_student(student_id: str):
    conn = get_db()
    student = conn.execute('SELECT * FROM students WHERE id = ?', (student_id,)).fetchone()
    conn.close()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    result = dict(student)
    result['skills'] = json.loads(result['skills'])
    result['availability'] = json.loads(result['availability'])
    result['project_ids'] = json.loads(result['project_ids'])
    return result

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    if not project:
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found")
        
    contributors = conn.execute('SELECT student_id, role FROM project_contributors WHERE project_id = ?', (project_id,)).fetchall()
    conn.close()
    
    result = dict(project)
    result['technologies'] = json.loads(result['technologies'])
    result['contributors'] = [dict(c) for c in contributors]
    return result

# --- RELEASE 2: RESUME PARSING ---
@app.post("/api/resumes/parse")
async def parse_resume(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    
    try:
        pdf_bytes = await file.read()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        
        extracted_text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                extracted_text += page_text + "\n"
        
        sanitized_text = html.escape(extracted_text.strip())
        text_lower = sanitized_text.lower()
        
        # Simple extraction logic: check for common skills in the text
        possible_skills = ["python", "javascript", "react", "sql", "fastapi", "html", "css", "git", "postgresql"]
        found_skills = [skill for skill in possible_skills if skill in text_lower]
        
        # Try to guess the name from the first line
        first_line = sanitized_text.split('\n')[0] if '\n' in sanitized_text else ""
        
        parsed_data = {
            "raw_text": sanitized_text,
            "filename": file.filename,
            "extracted_name": first_line,
            "extracted_skills": found_skills
        }
        
        return parsed_data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing PDF: {str(e)}")
    
# Must be completely unindented at the very bottom to serve the HTML files
app.mount("/", StaticFiles(directory=".", html=True), name="static")