@echo off
echo Running test suite...
python -m pytest tests/ -v --tb=short
pause
