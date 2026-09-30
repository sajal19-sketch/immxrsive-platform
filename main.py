from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json

app = FastAPI()

# This allows your future frontend to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper function to connect to the database
def get_db():
    conn = sqlite3.connect('immxrsive.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/directory")
def get_directory(q: str = "", skills: list[str] = Query(default=[]), availability: list[str] = Query(default=[])):
    conn = get_db()
    students = conn.execute('SELECT * FROM students').fetchall()
    conn.close()
    
    results = []
    for s in students:
        student = dict(s)
        student['skills'] = json.loads(student['skills'])
        student['availability'] = json.loads(student['availability'])
        
        match = True
        
        # Text Search
        if q:
            search_text = q.lower()
            if search_text not in student['name'].lower() and search_text not in student['headline'].lower():
                match = False
                
        # Skills Filter (AND logic - must have all selected skills)
        if skills:
            for skill in skills:
                if skill not in student['skills']:
                    match = False
                    break
                    
        # Availability Filter (OR logic - must match at least one selected availability)
        if availability:
            has_avail = False
            for avail in availability:
                if avail in student['availability']:
                    has_avail = True
                    break
            if not has_avail:
                match = False
                
        if match:
            # Add a placeholder for project count
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
