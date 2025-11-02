# src/shared/models/__init__.py

from src.core.database import Base
from .user_models import User, technician_service_link_table
from .resource_models import Location, Resource, Service
from .appointment_models import Appointment, AppointmentResourceLink
from .schedule_models import Shift