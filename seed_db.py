import sqlite3
import json

# Connect to the database (this will create a file named immxrsive.db)
conn = sqlite3.connect('immxrsive.db')
cursor = conn.cursor()

# 1. Create the database tables
cursor.execute('''
CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    name TEXT,
    headline TEXT,
    program TEXT,
    status TEXT,
    availability TEXT,
    skills TEXT,
    github_link TEXT,
    project_ids TEXT
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    domain TEXT,
    technologies TEXT
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS project_contributors (
    project_id TEXT,
    student_id TEXT,
    role TEXT
)''')

# 2. Load the JSON data from your data folder
with open('data/students_2.json', 'r') as f:
    students = json.load(f)
with open('data/projects_2.json', 'r') as f:
    projects = json.load(f)

# 3. Insert Students (ONLY if they are 'published')
for s in students:
    if s['profile_status'] == 'published':
        cursor.execute('''
            INSERT OR REPLACE INTO students 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            s['id'], 
            s['name'], 
            s['headline'], 
            s['program'], 
            s['status'],
            json.dumps(s['availability']), 
            json.dumps(s['skills']),
            s['links'].get('github', ''),
            json.dumps(s['project_ids'])
        ))

# 4. Insert Projects and Contributors
for p in projects:
    cursor.execute('''
        INSERT OR REPLACE INTO projects 
        VALUES (?, ?, ?, ?, ?)
    ''', (
        p['id'], 
        p['title'], 
        p['description'], 
        p['domain'],
        json.dumps(p['technologies'])
    ))
    
    for c in p['contributors']:
        cursor.execute('''
            INSERT OR REPLACE INTO project_contributors 
            VALUES (?, ?, ?)
        ''', (
            p['id'], 
            c['student_id'], 
            c['role']
        ))

# Save all changes and close the connection
conn.commit()
conn.close()
print("Database immxrsive.db successfully created and seeded!")
