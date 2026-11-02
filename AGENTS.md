Academic Research Studio — Codex Instructions
Mission
Build a reliable web application for analyzing and improving academic research documents.
Tech stack
Backend: Python, FastAPI
Frontend: React, TypeScript
Database: PostgreSQL
Document processing: python-docx, PDF extraction library with license review
Testing: pytest and frontend tests
Product requirements
Upload and analyze DOCX and PDF files.
Assess academic text against 34 editorial criteria.
Identify unclear argumentation, repetitive language, weak evidence and structural problems.
Check scholarly references using reliable metadata services.
Produce explainable recommendations linked to specific document passages.
Preserve factual meaning, citations and source attribution.
Support DOCX export.
Do not claim to guarantee plagiarism-checker or AI-detector results.
Development rules
Make small, testable changes.
Explain significant architectural decisions.
Never invent citations or research data.
Protect uploaded documents and user data.
Store secrets only in environment variables, never in Git.
Add appropriate automated tests for new functionality.
Check dependencies and licenses before adoption.
Do not introduce unnecessary complexity or dependencies.
Run the relevant available tests before submitting changes and report failures.
Keep README and setup instructions current.
Prefer focused pull requests instead of direct changes to the main branch.
