from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import uvicorn
import requests
import io
from typing import Optional, List
import re

# Import parsing libraries
try:
    import pdfplumber  # For PDF parsing
    import docx  # For DOCX parsing
except ImportError:
    print("Warning: Missing libraries. Please install with:")
    print("pip install pdfplumber python-docx requests")

app = FastAPI()

PORT= PORT = int(os.environ.get("PORT", 8000))

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

# Enable CORS for communication with React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], # React app URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Input model for resume URL
class ResumeURL(BaseModel):
    url: str



# Home endpoint to verify the API is running
@app.get("/")
@app.head("/")
def read_root():
    return {"status": "ok", "message": "Resume parser service is running"}

# File type detection functions
def is_pdf(file_bytes):
    # PDF files start with %PDF
    return file_bytes[:4] == b'%PDF'

def is_docx(file_bytes):
    # DOCX files are ZIP files with specific patterns
    return file_bytes[:4] == b'PK\x03\x04'

# Text extraction functions
def extract_text_from_pdf(file_bytes):
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            text = ""
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        print(f"Extracted {len(text)} characters from PDF")
        return text
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return ""

# Add these new extraction functions to main.py

def extract_education(text):
    """Extract education information from resume text"""
    education = []
    
    # Keywords that indicate education sections
    education_indicators = ['education', 'academic', 'degree', 'university', 'college', 'school', 'institute']
    degree_indicators = ['bachelor', 'master', 'phd', 'b.tech', 'm.tech', 'b.e', 'm.e', 'mba', 'b.sc', 'm.sc', 'b.com', 'm.com', 'b.a', 'm.a']
    
    # Find education section
    lines = text.split('\n')
    in_education_section = False
    education_section_text = ""
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        
        # Detect education section header
        if any(edu_ind in line_lower for edu_ind in education_indicators) and len(line_lower) < 30:
            in_education_section = True
            education_section_text += line + "\n"
            continue
            
        # Detect end of education section by checking for other section headers
        if in_education_section and line_lower and len(line_lower) < 30:
            if any(x in line_lower for x in ['experience', 'work', 'employment', 'professional', 'projects', 'skills']):
                in_education_section = False
                break
                
        # Add lines to education section
        if in_education_section and line.strip():
            education_section_text += line + "\n"
    
    # Process education section
    if education_section_text:
        # Try to extract individual education entries
        entries = re.split(r'\n(?=\d{4}|\b(?:' + '|'.join(degree_indicators) + r')\b)', education_section_text)
        
        for entry in entries:
            if len(entry.strip()) < 10:
                continue
                
            # Try to extract degree
            degree = None
            for indicator in degree_indicators:
                match = re.search(r'\b' + indicator + r'[s]?\b.*?(?:\n|$)', entry, re.IGNORECASE)
                if match:
                    degree = match.group(0).strip()
                    break
            
            # Try to extract institution
            institution_patterns = [
                r'\b(?:university|college|institute|school) of [\w\s]+',
                r'[\w\s]+ (?:university|college|institute|school)\b'
            ]
            institution = None
            for pattern in institution_patterns:
                match = re.search(pattern, entry, re.IGNORECASE)
                if match:
                    institution = match.group(0).strip()
                    break
            
            # Try to extract year
            year_pattern = r'(\b20\d{2}\b|\b19\d{2}\b)(?:\s*-\s*(?:\b20\d{2}\b|\b19\d{2}\b|present|current|now))?'
            year_match = re.search(year_pattern, entry, re.IGNORECASE)
            year = year_match.group(0) if year_match else None
            
            if degree or institution:
                education.append({
                    "degree": degree or "Degree not specified",
                    "institution": institution or "Institution not specified",
                    "year": year or "Year not specified"
                })
    
    return education

def extract_experience(text):
    """Extract work experience from resume text"""
    experience = []
    
    # Keywords that indicate experience sections
    experience_indicators = ['experience', 'employment', 'work history', 'professional experience', 'career']
    
    # Find experience section
    lines = text.split('\n')
    in_experience_section = False
    experience_section_text = ""
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        
        # Detect experience section header
        if any(exp_ind in line_lower for exp_ind in experience_indicators) and len(line_lower) < 30:
            in_experience_section = True
            experience_section_text += line + "\n"
            continue
            
        # Detect end of experience section
        if in_experience_section and line_lower and len(line_lower) < 30:
            if any(x in line_lower for x in ['education', 'projects', 'skills', 'certifications']):
                in_experience_section = False
                break
                
        # Add lines to experience section
        if in_experience_section and line.strip():
            experience_section_text += line + "\n"
    
    # Process experience section
    if experience_section_text:
        # Date pattern to split entries
        date_pattern = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}\s*[-–—]\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}|\b\d{4}\s*[-–—]\s*\d{4}|\b\d{4}\s*[-–—]\s*(present|current|now)\b'
        
        # Try to split by dates or company names
        entries = re.split(date_pattern, experience_section_text, flags=re.IGNORECASE)
        
        # If that didn't work well, try splitting by newlines with year patterns
        if len(entries) <= 1:
            entries = re.split(r'\n(?=.*\b(?:19|20)\d{2}\b)', experience_section_text)
        
        for entry in entries:
            if len(entry.strip()) < 15 or entry.strip().lower() in ['experience', 'work experience', 'employment history']:
                continue
                
            # Try to extract job title
            title = None
            title_candidates = re.findall(r'^([A-Z][A-Za-z\s]{2,30}(?:Developer|Engineer|Manager|Designer|Analyst|Consultant|Director|Lead|Architect|Specialist|Intern))', entry)
            if title_candidates:
                title = title_candidates[0].strip()
            
            # Try to extract company
            company = None
            company_patterns = [
                r'(?:at|with|for) ([\w\s]+)',
                r'^([\w\s]+) (?:Inc\.|LLC|Ltd\.)',
                r'^([\w\s,]+)(?:\n|$)'
            ]
            for pattern in company_patterns:
                company_matches = re.search(pattern, entry)
                if company_matches:
                    company = company_matches.group(1).strip()
                    break
            
            # Try to extract duration
            duration = None
            duration_pattern = r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}\s*[-–—]\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{4}|\b\d{4}\s*[-–—]\s*\d{4}|\b\d{4}\s*[-–—]\s*(?:present|current|now)\b'
            duration_match = re.search(duration_pattern, entry, re.IGNORECASE)
            if duration_match:
                duration = duration_match.group(0)
            
            if title or company:
                experience.append({
                    "title": title or "Position not specified",
                    "company": company or "Company not specified",
                    "duration": duration or "Duration not specified"
                })
    
    return experience

def extract_projects(text):
    """Extract project information from resume text"""
    projects = []
    
    # Keywords that indicate projects sections
    project_indicators = ['projects', 'personal projects', 'academic projects']
    
    # Find projects section
    lines = text.split('\n')
    in_project_section = False
    project_section_text = ""
    
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        
        # Detect projects section header
        if any(proj_ind in line_lower for proj_ind in project_indicators) and len(line_lower) < 30:
            in_project_section = True
            project_section_text += line + "\n"
            continue
            
        # Detect end of projects section
        if in_project_section and line_lower and len(line_lower) < 30:
            if any(x in line_lower for x in ['experience', 'education', 'skills', 'certifications']):
                in_project_section = False
                break
                
        # Add lines to project section
        if in_project_section and line.strip():
            project_section_text += line + "\n"
    
    # Process project section
    if project_section_text:
        # Try to split by project names (often start with bullet points or numbers)
        entries = re.split(r'\n(?=•|\*|\-|\d+\.|\d+\)|\w+:)', project_section_text)
        
        for entry in entries:
            entry = entry.strip()
            if len(entry) < 15 or entry.lower() in ['projects', 'personal projects', 'academic projects']:
                continue
            
            # Try to extract project name (usually the first line)
            lines = entry.split('\n')
            name = lines[0].strip('•*-\t .)')
            
            # Description is the rest
            description = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
            
            if name:
                projects.append({
                    "name": name,
                    "description": description
                })
    
    return projects

def extract_text_from_docx(file_bytes):
    try:
        doc = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text])
        print(f"Extracted {len(text)} characters from DOCX")
        return text
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""

# Information extraction functions
def extract_name(text):
    # Simplified name extraction - first few lines often contain the name
    lines = text.split('\n')
    for line in lines[:5]:  # Check first 5 lines
        # If line is short and doesn't contain common words, it might be a name
        if 5 < len(line) < 40 and not any(x in line.lower() for x in ['@', 'http', 'resume', 'cv', 'email', 'phone']):
            return line.strip()
    return None

def extract_email(text):
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(email_pattern, text)
    return match.group(0) if match else None

def extract_phone(text):
    # Match various phone number formats
    phone_pattern = r'(\+\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})'
    match = re.search(phone_pattern, text)
    return match.group(0) if match else None

def extract_skills(text):
    # Common skills to look for - expand as needed
    skill_keywords = [
        "python", "javascript", "react", "angular", "vue", "node.js", "express", 
        "mongodb", "sql", "mysql", "postgresql", "nosql", "firebase", "aws", "azure",
        "gcp", "docker", "kubernetes", "ci/cd", "jenkins", "git", "github", "gitlab",
        "html", "css", "sass", "less", "bootstrap", "tailwind", "typescript",
        "java", "c++", "c#", ".net", "php", "ruby", "go", "rust", "swift",
        "android", "ios", "flutter", "react native", "electron",
        "machine learning", "deep learning", "ai", "data science", "data analysis",
        "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy",
        "agile", "scrum", "kanban", "jira", "confluence",
        "communication", "leadership", "project management", "team work",
        "problem solving", "critical thinking", "time management"
    ]
    
    found_skills = []
    for skill in skill_keywords:
        if re.search(r'\b' + re.escape(skill) + r'\b', text.lower()):
            found_skills.append(skill)
    
    return found_skills



# Resume parsing endpoint
@app.post("/parse-resume")
async def parse_resume(resume_url: ResumeURL):
    try:
        print(f"Received URL: {resume_url.url}")
        
        # Download the file from the URL
        response = requests.get(resume_url.url)
        response.raise_for_status()
        file_bytes = response.content
        print(f"Downloaded {len(file_bytes)} bytes")
        
        # Determine file type by examining file content
        if is_pdf(file_bytes):
            print("Detected PDF file")
            text = extract_text_from_pdf(file_bytes)
        elif is_docx(file_bytes):
            print("Detected DOCX file")
            text = extract_text_from_docx(file_bytes)
        else:
            print("Unknown file format - examining content type")
            content_type = response.headers.get('Content-Type', '').lower()
            
            if 'pdf' in content_type:
                print("Content-Type indicates PDF")
                text = extract_text_from_pdf(file_bytes)
            elif 'word' in content_type or 'docx' in content_type:
                print("Content-Type indicates DOCX")
                text = extract_text_from_docx(file_bytes)
            else:
                print(f"Unsupported format: {content_type} - returning dummy data")
                
                # For testing purposes, return dummy data
                parsed_data = {
                    "name": "John Doe",
                    "email": "john.doe@example.com",
                    "phone": "555-123-4567",
                    "skills": ["Python", "JavaScript", "React", "SQL"],
                    "experience": [
                        {"title": "Software Developer", "company": "Tech Corp", "duration": "2020-Present"}
                    ],
                    "education": [
                        {"degree": "BS Computer Science", "institution": "University of Technology", "year": "2019"}
                    ]
                }
                return {"parsedData": parsed_data}
        
        # If we got here, we have extracted text
        if not text or len(text) < 10:
            print("Failed to extract meaningful text from document")
            raise HTTPException(status_code=422, detail="Could not extract text from document")
        
        # Extract information from the text
        name = extract_name(text)
        email = extract_email(text)
        phone = extract_phone(text)
        skills = extract_skills(text)
        education = extract_education(text)
        experience = extract_experience(text)
        projects = extract_projects(text)
        
        # Create response
        parsed_data = {
            "name": name,
            "email": email,
            "phone": phone,
            "skills": skills,
            "education": education,
            "experience": experience,
            "projects": projects
        }
        
        print(f"Successfully parsed resume: {name}, {email}, {len(skills)} skills , {len(education)} edu, {len(experience)} exp, {len(projects)} proj")
        return {"parsedData": parsed_data}
        
    except requests.RequestException as e:
        print(f"Request error: {e}")
        raise HTTPException(status_code=400, detail=f"Error downloading file: {str(e)}")
    except Exception as e:
        print(f"Processing error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error parsing resume: {str(e)}")
    

@app.post("/view-resume")
async def view_resume(data: ResumeURL):
    try:
        # Fetch the resume from the given URL
        response = requests.get(data.url)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not fetch resume from URL")

        file_bytes = response.content

        # Determine file type and extract text
        if is_pdf(file_bytes):
            extracted_text = extract_text_from_pdf(file_bytes)
        elif is_docx(file_bytes):
            extracted_text = extract_text_from_docx(file_bytes)
        else:
            raise HTTPException(status_code=415, detail="Unsupported file format")

        if not extracted_text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from the resume")

        # Return the raw extracted text
        return {"text": extracted_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Resume viewer error: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
