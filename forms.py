from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField, DateTimeLocalField, EmailField, PasswordField, RadioField,
    SelectField, StringField, SubmitField, TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


def make_choices(*items):
    """Build (value, label) choices from plain strings."""
    return [(item, item) for item in items]


VEHICLE_TYPES = ("Car", "Bike", "SUV", "Van", "Truck", "Bus", "Other")
REQUEST_STATUSES = ("Received", "Dispatched", "In Progress", "Completed", "Cancelled")


# ACCOUNT FORMS
class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()], render_kw={"autocomplete": "email"})
    password = PasswordField("Password", validators=[DataRequired()], render_kw={"autocomplete": "current-password"})
    submit = SubmitField("Login")


class RegisterForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=100)],
                            render_kw={"autocomplete": "name"})
    email = EmailField("Email Address", validators=[DataRequired(), Email()], render_kw={"autocomplete": "email"})
    phone = StringField("Phone Number", validators=[DataRequired(), Length(min=7, max=20)],
                        render_kw={"autocomplete": "tel", "inputmode": "tel"})
    vehicle_type = SelectField("Vehicle Type", choices=[("", "Select Vehicle")] + make_choices(*VEHICLE_TYPES),
                               validators=[DataRequired()])
    vehicle_number = StringField("Vehicle Number", validators=[DataRequired(), Length(max=30)],
                                 render_kw={"placeholder": "e.g. KA01AB1234", "autocapitalize": "characters"})
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6, max=100)],
                             render_kw={"autocomplete": "new-password"})
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")],
                                     render_kw={"autocomplete": "new-password"})
    submit = SubmitField("Register")


class ProfileForm(FlaskForm):
    name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=100)],
                            render_kw={"autocomplete": "name"})
    phone = StringField("Phone Number", validators=[DataRequired(), Length(min=7, max=20)],
                        render_kw={"autocomplete": "tel", "inputmode": "tel"})
    vehicle_type = SelectField("Vehicle Type", choices=[("", "Select Vehicle")] + make_choices(*VEHICLE_TYPES),
                               validators=[DataRequired()])
    vehicle_number = StringField("Vehicle Number", validators=[DataRequired(), Length(max=30)],
                                 render_kw={"placeholder": "e.g. KA01AB1234", "autocapitalize": "characters"})
    submit = SubmitField("Save Profile")


class FeedbackForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=100)], render_kw={"autocomplete": "name"})
    email = EmailField("Email", validators=[DataRequired(), Email()], render_kw={"autocomplete": "email"})
    category = SelectField(
        "Category",
        choices=[("", "Select Category")] + make_choices(
            "Service Quality", "Vehicle Towing", "Fuel Delivery", "Flat Tire",
            "Lockout Services", "Minor Repairs", "Battery Jump Start",
        ),
        validators=[DataRequired()],
    )
    rating = RadioField("Rating", choices=[(str(i), "★") for i in range(1, 6)], validators=[DataRequired()])
    feedback = TextAreaField("Feedback", validators=[DataRequired(), Length(max=2000)],
                             render_kw={"maxlength": 2000})
    submit = SubmitField("Submit Feedback")


class TrackForm(FlaskForm):
    request_id = StringField("Request ID", validators=[DataRequired(), Length(min=3, max=30)],
                             render_kw={"placeholder": "e.g. RA-483920", "autocomplete": "off"})
    submit = SubmitField("Track Request")


# SERVICE REQUEST FORMS
# Name, phone and vehicle details come from the logged-in user's profile (collected
# at registration), so these forms only ask what is specific to this breakdown.
# Each subclass defines its own `submit` last so the button renders at the bottom.
class BaseServiceForm(FlaskForm):
    location = StringField("Current Location", validators=[DataRequired(), Length(max=250)],
                           render_kw={"placeholder": "Landmark, road or area where you are now"})


class TowingForm(BaseServiceForm):
    vehicle_model = StringField("Vehicle Make & Model", validators=[Optional(), Length(max=100)])
    reason = SelectField(
        "Reason for Towing",
        choices=[("", "Select Reason")] + make_choices(
            "Vehicle Breakdown", "Accident", "Engine Problem", "Flat Tire", "Battery Failure",
            "Overheating", "Vehicle Will Not Start", "Other",
        ),
        validators=[DataRequired()],
    )
    pickup = StringField("Pickup Location", validators=[DataRequired(), Length(max=250)])
    destination = StringField("Destination", validators=[DataRequired(), Length(max=250)])
    towing_type = SelectField(
        "Towing Type",
        choices=make_choices("Not Sure", "Flatbed Tow Truck", "Wheel Lift", "Heavy Duty Towing"),
    )
    drivable = SelectField("Is the vehicle drivable?", choices=make_choices("Yes", "No", "Not Sure"))
    injured = SelectField("Is anyone injured?", choices=make_choices("No", "Yes"))
    hazard = SelectField("Is there an immediate hazard?", choices=make_choices("No", "Yes"))
    description = TextAreaField("Additional Information", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit Towing Request")


class FuelForm(BaseServiceForm):
    fuel_type = SelectField(
        "Fuel Type",
        choices=[("", "Select Fuel")] + make_choices("Petrol", "Diesel", "Other"),
        validators=[DataRequired()],
    )
    fuel_quantity = SelectField(
        "Required Quantity",
        choices=make_choices("1 Litres", "5 Litres", "10 Litres", "15 Litres", "20 Litres"),
    )
    fuel_gauge = SelectField("Fuel Gauge Status", choices=make_choices("Empty", "Very Low", "Not Working", "Not Sure"))
    payment = SelectField("Payment Preference", choices=make_choices("Cash", "Card", "Online Payment"))
    upload_images = FileField(
        "Upload Images",
        validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only.")],
    )
    description = TextAreaField("Additional Information", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit Fuel Request")


class TireForm(BaseServiceForm):
    tire_location = SelectField(
        "Tire Location",
        choices=make_choices("Front Left", "Front Right", "Rear Left", "Rear Right", "Multiple Tires"),
    )
    tire_service = SelectField(
        "Type of Assistance",
        choices=make_choices("Tire Repair", "Tire Replacement", "Spare Tire Installation", "Not Sure"),
    )
    spare = SelectField("Do you have a spare tire?", choices=make_choices("Yes", "No"))
    safe = SelectField("Is the vehicle safely parked?", choices=make_choices("Yes", "No"))
    description = TextAreaField("Additional Information", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit Tire Request")


class LockoutForm(BaseServiceForm):
    lockout_type = SelectField(
        "Lockout Situation",
        choices=make_choices("Keys Locked Inside Vehicle", "Lost Keys", "Broken Key", "Key Not Working",
                             "Key Fob Problem", "Other"),
    )
    spare_key = SelectField("Do you have a spare key?", choices=make_choices("No", "Yes"))
    ownership = SelectField(
        "Vehicle Ownership",
        choices=make_choices("I am the owner", "Company Vehicle", "Rental Vehicle", "Other"),
    )
    locked = SelectField("Vehicle Locked Completely?", choices=make_choices("Yes", "No", "Not Sure"))
    description = TextAreaField("Additional Details", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit Lockout Request")


class RepairForm(BaseServiceForm):
    repair_type = SelectField(
        "Repair Type",
        choices=[("", "Select Problem")] + make_choices(
            "Engine Problem", "Battery Problem", "Overheating", "Starter Problem",
            "Alternator Problem", "Electrical Problem", "Brake Problem", "Other",
        ),
        validators=[DataRequired()],
    )
    urgency = SelectField("Urgency", choices=make_choices("Normal", "Urgent", "Emergency"))
    drivable = SelectField("Is the vehicle drivable?", choices=make_choices("Yes", "No", "Not Sure"))
    preferred_time = DateTimeLocalField("Preferred Assistance Time", format="%Y-%m-%dT%H:%M", validators=[Optional()])
    description = TextAreaField("Describe the Problem", validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField("Submit Repair Request")


class BatteryForm(BaseServiceForm):
    battery_problem = SelectField(
        "Battery Problem",
        choices=make_choices("Vehicle Will Not Start", "Battery Dead", "Weak Battery",
                             "Battery Warning Light", "Not Sure"),
    )
    description = TextAreaField("Additional Information", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit Battery Request")


# ADMIN FORMS
class AdminUserForm(FlaskForm):
    """Used by the admin panel to add/edit users. Password is optional when editing
    (leave blank to keep the current one) and required when adding (checked in the route)."""
    name = StringField("Full Name", validators=[DataRequired(), Length(max=100)])
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=120)],
                       render_kw={"autocomplete": "off"})
    phone = StringField("Phone Number", validators=[DataRequired(), Length(min=7, max=20)])
    vehicle_type = SelectField("Vehicle Type", choices=[("", "Not set")] + make_choices(*VEHICLE_TYPES),
                               validators=[Optional()])
    vehicle_number = StringField("Vehicle Number", validators=[Optional(), Length(max=30)])
    password = PasswordField("Password", validators=[Optional(), Length(min=6, max=100)],
                             render_kw={"autocomplete": "new-password",
                                        "placeholder": "Leave blank to keep the current password"})
    is_admin = BooleanField("Admin access")
    submit = SubmitField("Save User")


class AdminStatusForm(FlaskForm):
    status = SelectField("Status", choices=make_choices(*REQUEST_STATUSES), validators=[DataRequired()])
    submit = SubmitField("Update Status")
