"""
Shared Jinja2 templates configuration.
All routers import from here to get consistent filters and globals.
"""
from fastapi.templating import Jinja2Templates
from app.date_format import format_date, format_datetime

templates = Jinja2Templates(directory="app/templates")

# Register date formatting functions as Jinja2 globals
templates.env.globals["format_date"] = format_date
templates.env.globals["format_datetime"] = format_datetime
