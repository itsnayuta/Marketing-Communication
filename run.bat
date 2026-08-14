@echo off
call .venv\Scripts\activate
python manage.py runserver 127.0.0.1:8000
start http://127.0.0.1:8000