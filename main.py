import csv
import gzip as _gzip
import io
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from flask import Flask, Response, flash, redirect, render_template, request, url_for
from flask_bootstrap import Bootstrap5
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.pagination import SelectPagination
from flask_wtf import CSRFProtect
from sqlalchemy import ForeignKey, Integer, String, Text, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, joinedload, mapped_column, relationship
from sqlalchemy.pool import NullPool
from werkzeug.security import check_password_hash, generate_password_hash

from forms import (
    REQUEST_STATUSES, VEHICLE_TYPES, AdminStatusForm, AdminUserForm, BatteryForm, FeedbackForm,
    FuelForm, LockoutForm, LoginForm, ProfileForm, RegisterForm, RepairForm, TireForm, TowingForm,
    TrackForm,
)

load_dotenv()

# APP CONFIGURATION
app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable is not set")
app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 7
# Cache static assets (CSS/JS/images) in the browser for a week.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 7
# Only advertise the demo login on the login page when the demo user is being seeded.
app.config["SHOW_DEMO"] = os.environ.get("SEED_DEMO_USER", "").lower() == "true"

bootstrap = Bootstrap5(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.login_view = "login"  # type: ignore
login_manager.login_message = "Please login to continue."
login_manager.login_message_category = "warning"
login_manager.init_app(app)


# Lightweight gzip compression using only the standard library (no Flask-Compress).
COMPRESSIBLE_MIMETYPES = {
    "text/html", "text/css", "text/javascript", "application/javascript",
    "application/json", "image/svg+xml",
}
MIN_COMPRESS_BYTES = 500


@app.after_request
def compress_response(response):
    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "")
    already_encoded = "Content-Encoding" in response.headers
    mimetype_ok = response.mimetype in COMPRESSIBLE_MIMETYPES
    if not accepts_gzip or already_encoded or not mimetype_ok:
        return response
    if response.direct_passthrough:
        response.direct_passthrough = False
    data = response.get_data()
    if len(data) < MIN_COMPRESS_BYTES:
        return response
    compressed = _gzip.compress(data, compresslevel=6)
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(compressed))
    response.headers.setdefault("Vary", "Accept-Encoding")
    return response


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


class Base(DeclarativeBase):
    pass


database_url = os.environ.get("SUPABASE")
if not database_url:
    raise RuntimeError("SUPABASE environment variable is not set")

app.config["SQLALCHEMY_DATABASE_URI"] = database_url

if database_url.startswith("postgresql"):
    db = SQLAlchemy(model_class=Base, engine_options={"poolclass": NullPool})
else:
    db = SQLAlchemy(model_class=Base)

db.init_app(app)

try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    # Windows has no system tz database unless the `tzdata` package is installed.
    # India has no DST, so a fixed UTC+05:30 offset is equivalent.
    IST = timezone(timedelta(hours=5, minutes=30), "IST")


def utcnow():
    return datetime.now(timezone.utc)


# DATABASE MODELS
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Asked once at registration (or on /profile) so service forms don't repeat them.
    vehicle_type: Mapped[str] = mapped_column(String(30), nullable=True)
    vehicle_number: Mapped[str] = mapped_column(String(30), nullable=True)
    is_admin: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    requests = relationship("ServiceRequest", back_populates="user", lazy=True)

    @property
    def has_vehicle_info(self):
        return bool(self.vehicle_type and self.vehicle_number)


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"
    # The primary key IS the public request ID (e.g. "RA-483920").
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(120), nullable=True)
    # Each service form has different fields, so they are stored together as JSON.
    details: Mapped[dict] = mapped_column(db.JSON, nullable=False, default=dict)
    # Received -> Dispatched -> In Progress -> Completed (or Cancelled); changed from the admin panel.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Received")
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="requests")

    @property
    def createdAt(self):
        """Same 'YYYY-MM-DD HH:MM:SS' string (IST) the templates already display."""
        created = self.created_at
        if created.tzinfo is None:  # SQLite returns naive datetimes
            created = created.replace(tzinfo=timezone.utc)
        return created.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


class Feedback(db.Model):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow, nullable=False)


# STARTUP DATABASE CHECK / LIGHTWEIGHT MIGRATION
def ensure_database_schema():
    """Create missing tables and add columns to old databases (lightweight migration)."""
    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        if "users" in inspector.get_table_names():
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            if "is_admin" not in user_columns:
                db.session.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
                db.session.commit()
            for column, ddl in (("vehicle_type", "VARCHAR(30)"), ("vehicle_number", "VARCHAR(30)")):
                if column not in user_columns:
                    db.session.execute(text(f"ALTER TABLE users ADD COLUMN {column} {ddl}"))
                    db.session.commit()
            # Optional bootstrap: promote an existing user by e-mail. Never creates
            # an account and never demotes anyone.
            admin_email = os.environ.get("ADMIN_EMAIL")
            if admin_email:
                admin_user = db.session.execute(
                    db.select(User).where(User.email == admin_email.strip().lower())
                ).scalar_one_or_none()
                if admin_user and not admin_user.is_admin:
                    admin_user.is_admin = True
                    db.session.commit()
        if "service_requests" in inspector.get_table_names():
            request_columns = {column["name"] for column in inspector.get_columns("service_requests")}
            if "status" not in request_columns:
                db.session.execute(text(
                    "ALTER TABLE service_requests ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Received'"))
                db.session.commit()
        # Optional demo account (admin@roadassist.com / admin123) for local testing only.
        if os.environ.get("SEED_DEMO_USER", "").lower() == "true":
            demo = db.session.execute(
                db.select(User).where(User.email == "admin@roadassist.com")).scalar_one_or_none()
            if not demo:
                db.session.add(User(
                    email="admin@roadassist.com",
                    name="RoadAssist Admin",
                    phone="+91 9876543210",
                    vehicle_type="Car",
                    vehicle_number="KA01AB1234",
                    password_hash=generate_password_hash("admin123"),
                    is_admin=True,
                ))
                db.session.commit()


try:
    ensure_database_schema()
except Exception as exc:
    # Do not hide the original error; make it visible in deployment logs.
    print("DATABASE STARTUP ERROR:", exc)


# AUTH / REQUEST HELPERS
SERVICE_CONFIG = {
    "towing": ("Vehicle Towing", TowingForm, "Submit Towing Request"),
    "fuel": ("Fuel Delivery", FuelForm, "Submit Fuel Request"),
    "tire": ("Flat Tire", TireForm, "Submit Tire Request"),
    "lockout": ("Lockout Service", LockoutForm, "Submit Lockout Request"),
    "repair": ("Minor Repairs", RepairForm, "Submit Repair Request"),
    "battery": ("Battery Jump Start", BatteryForm, "Submit Battery Request"),
}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def check_existing_user(email):
    if not email:
        return None
    return db.session.execute(
        db.select(User).where(User.email == email.strip().lower())).scalar_one_or_none()


def find_request_by_id(request_id):
    """Case-insensitive lookup by request ID."""
    return db.session.execute(
        db.select(ServiceRequest).where(
            db.func.upper(ServiceRequest.id) == request_id.strip().upper())
    ).scalar_one_or_none()


def generate_request_id():
    while True:
        request_id = f"RA-{secrets.randbelow(1_000_000):06d}"
        if not db.session.get(ServiceRequest, request_id):
            return request_id


def safe_next_url():
    """The ?next= page to return to after login, only if it is a local path."""
    target = request.args.get("next", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def admin_required(function):
    """Server-side admin gate. Stack under @login_required on every /admin route."""
    @wraps(function)
    def decorator_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, "is_admin", False):
            flash("You don't have access to the admin panel.", "danger")
            return redirect(url_for("home"))
        return function(*args, **kwargs)
    return decorator_function


def form_to_details(form):
    """Collect a service form's fields into a JSON-safe dict."""
    details = {}
    for field in form:
        if field.name in ("csrf_token", "submit") or field.data is None:
            continue
        if field.type == "FileField":
            continue  # uploaded images are not stored
        details[field.name] = field.data.isoformat() if hasattr(field.data, "isoformat") else field.data
    return details


# PAGES
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/services")
def services_page():
    return render_template("services.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    feedback_form = FeedbackForm()
    if feedback_form.validate_on_submit():
        db.session.add(Feedback(
            name=feedback_form.name.data.strip(),
            email=feedback_form.email.data.strip().lower(),
            category=feedback_form.category.data,
            rating=int(feedback_form.rating.data),
            feedback=feedback_form.feedback.data.strip(),
        ))
        db.session.commit()
        flash("Thank you! Feedback submitted successfully.", "success")
        return redirect(url_for("feedback"))
    feedback_items = db.session.execute(
        db.select(Feedback).order_by(Feedback.created_at.desc()).limit(50)).scalars().all()
    return render_template("feedback.html", form=feedback_form, feedback_items=feedback_items)


# LOGIN / REGISTRATION
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    login_form = LoginForm()
    if login_form.validate_on_submit():
        user = check_existing_user(login_form.email.data)
        if not user:
            # No account for this email yet -> send them to sign up (keeping ?next=).
            flash("We couldn't find an account with that email. Please sign up first.", "warning")
            return redirect(url_for("register", next=safe_next_url()))
        if check_password_hash(user.password_hash, login_form.password.data):
            login_user(user)
            flash("Login successful!", "success")
            return redirect(safe_next_url() or url_for("dashboard"))
        flash("Incorrect password. Please try again.", "danger")
    return render_template("login.html", form=login_form)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    register_form = RegisterForm()
    if register_form.validate_on_submit():
        email = register_form.email.data.strip().lower()
        if check_existing_user(email):
            flash("An account with this email already exists. Please login.", "info")
            return redirect(url_for("login", next=safe_next_url()))
        user = User(
            email=email,
            name=register_form.full_name.data.strip(),
            phone=register_form.phone.data.strip(),
            vehicle_type=register_form.vehicle_type.data,
            vehicle_number=register_form.vehicle_number.data.strip().upper(),
            password_hash=generate_password_hash(register_form.password.data),
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("An account with this email already exists. Please login.", "info")
            return redirect(url_for("login", next=safe_next_url()))
        login_user(user)
        flash("Registration successful!", "success")
        return redirect(safe_next_url() or url_for("dashboard"))
    return render_template("register.html", form=register_form)


# ACCOUNT
@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileForm(obj=current_user)
    if profile_form.validate_on_submit():
        current_user.name = profile_form.name.data.strip()
        current_user.phone = profile_form.phone.data.strip()
        current_user.vehicle_type = profile_form.vehicle_type.data
        current_user.vehicle_number = profile_form.vehicle_number.data.strip().upper()
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(safe_next_url() or url_for("dashboard"))
    return render_template("profile.html", form=profile_form)


@app.route("/dashboard")
@login_required
def dashboard():
    user_requests = db.session.execute(
        db.select(ServiceRequest)
        .where(ServiceRequest.user_id == current_user.id)
        .order_by(ServiceRequest.created_at.desc())
    ).scalars().all()
    return render_template("dashboard.html", requests=user_requests)


# SERVICE REQUESTS
@app.route("/request-service")
def request_service():
    return redirect(url_for("services_page"))


@app.route("/service/<service_key>", methods=["GET", "POST"])
@login_required
def service_request(service_key):
    if service_key not in SERVICE_CONFIG:
        return redirect(url_for("services_page"))
    if not current_user.has_vehicle_info:
        # Accounts created before vehicle details were collected at registration.
        flash("Please add your vehicle details once, then you can request help.", "warning")
        return redirect(url_for("profile", next=request.path))
    service_name, form_class, submit_label = SERVICE_CONFIG[service_key]
    service_form = form_class()
    service_form.submit.label.text = submit_label
    if service_form.validate_on_submit():
        new_request = ServiceRequest(
            id=generate_request_id(),
            service=service_name,
            user_id=current_user.id,
            email=current_user.email,
            details={
                # Taken from the account, so they are never asked again.
                "name": current_user.name,
                "phone": current_user.phone,
                "vehicle_type": current_user.vehicle_type,
                "vehicle_number": current_user.vehicle_number,
                **form_to_details(service_form),
            },
        )
        db.session.add(new_request)
        db.session.commit()
        flash(f"{service_name} request submitted successfully. Request ID: {new_request.id}", "success")
        return redirect(url_for("track_request", request_id=new_request.id))
    return render_template("service_form.html", form=service_form, service_name=service_name)


@app.route("/track", methods=["GET", "POST"])
def track_form():
    track_form_obj = TrackForm()
    result = None
    if track_form_obj.validate_on_submit():
        result = find_request_by_id(track_form_obj.request_id.data)
        if result is None:
            flash("Request ID not found. Please check the ID and try again.", "danger")
    return render_template("track.html", form=track_form_obj, result=result)


@app.route("/track/<request_id>")
def track_request(request_id):
    result = find_request_by_id(request_id)
    return render_template("track.html", form=TrackForm(request_id=request_id), result=result)


# ADMIN
# Every /admin route is protected by BOTH @login_required and @admin_required,
# so access is enforced on the server, never by hiding a link in a template.
ADMIN_PAGE_SIZE = 15


def count_admins():
    return db.session.scalar(db.select(db.func.count(User.id)).where(User.is_admin.is_(True)))


def email_taken(email, exclude_id=None):
    query = db.select(User.id).where(User.email == email)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return db.session.scalar(query) is not None


def filtered_requests_query():
    """Shared by the requests list and the CSV export (search + service + status filters)."""
    search = request.args.get("q", "").strip()
    service = request.args.get("service", "").strip()
    status = request.args.get("status", "").strip()
    query = (
        db.select(ServiceRequest)
        .outerjoin(User, ServiceRequest.user_id == User.id)
        .options(joinedload(ServiceRequest.user))
        .order_by(ServiceRequest.created_at.desc())
    )
    if search:
        like = f"%{search}%"
        query = query.where(db.or_(
            ServiceRequest.id.ilike(like), ServiceRequest.email.ilike(like),
            User.name.ilike(like), User.phone.ilike(like), User.vehicle_number.ilike(like)))
    if service:
        query = query.where(ServiceRequest.service == service)
    if status:
        query = query.where(ServiceRequest.status == status)
    return query, search, service, status


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    total_users = db.session.scalar(db.select(db.func.count(User.id)))
    total_requests = db.session.scalar(db.select(db.func.count(ServiceRequest.id)))
    total_feedback = db.session.scalar(db.select(db.func.count(Feedback.id)))
    average_rating = db.session.scalar(db.select(db.func.avg(Feedback.rating)))
    by_status = dict(db.session.execute(
        db.select(ServiceRequest.status, db.func.count(ServiceRequest.id)).group_by(ServiceRequest.status)).all())
    by_service = db.session.execute(
        db.select(ServiceRequest.service, db.func.count(ServiceRequest.id))
        .group_by(ServiceRequest.service).order_by(db.func.count(ServiceRequest.id).desc())).all()
    recent = db.session.execute(
        db.select(ServiceRequest).options(joinedload(ServiceRequest.user))
        .order_by(ServiceRequest.created_at.desc()).limit(6)).scalars().all()
    return render_template(
        "admin/dashboard.html", total_users=total_users, total_requests=total_requests,
        total_feedback=total_feedback, average_rating=average_rating,
        by_status=by_status, by_service=by_service, recent=recent, statuses=REQUEST_STATUSES)


# ADMIN: USERS
@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    search = request.args.get("q", "").strip()
    query = db.select(User).order_by(User.created_at.desc())
    if search:
        like = f"%{search}%"
        query = query.where(db.or_(
            User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like),
            User.vehicle_number.ilike(like)))
    page = db.paginate(query, page=request.args.get("page", 1, type=int),
                       per_page=ADMIN_PAGE_SIZE, error_out=False)
    return render_template("admin/users.html", page=page, search=search)


@app.route("/admin/users/<int:user_id>")
@login_required
@admin_required
def admin_user_detail(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return "User not found", 404
    user_requests = db.session.execute(
        db.select(ServiceRequest).where(ServiceRequest.user_id == user.id)
        .order_by(ServiceRequest.created_at.desc())).scalars().all()
    return render_template("admin/user_detail.html", user=user, user_requests=user_requests)


@app.route("/admin/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_new():
    form = AdminUserForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if email_taken(email):
            form.email.errors.append("A user with this email already exists.")
        elif not form.password.data:
            form.password.errors.append("A password is required for a new user.")
        else:
            user = User(
                name=form.name.data.strip(), email=email, phone=form.phone.data.strip(),
                vehicle_type=form.vehicle_type.data or None,
                vehicle_number=(form.vehicle_number.data or "").strip().upper() or None,
                password_hash=generate_password_hash(form.password.data),
                is_admin=bool(form.is_admin.data))
            db.session.add(user)
            db.session.commit()
            flash(f'User "{user.name}" added.', "success")
            return redirect(url_for("admin_users"))
    return render_template("admin/user_form.html", form=form, mode="new", user=None)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return "User not found", 404
    form = AdminUserForm(obj=user)
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        wants_admin = bool(form.is_admin.data)
        if email_taken(email, exclude_id=user.id):
            form.email.errors.append("A user with this email already exists.")
        elif user.is_admin and not wants_admin and count_admins() <= 1:
            # Never let the panel lock everyone out.
            flash("You can't remove admin access from the last remaining admin.", "danger")
        else:
            user.name = form.name.data.strip()
            user.email = email
            user.phone = form.phone.data.strip()
            user.vehicle_type = form.vehicle_type.data or None
            user.vehicle_number = (form.vehicle_number.data or "").strip().upper() or None
            user.is_admin = wants_admin
            if form.password.data:
                user.password_hash = generate_password_hash(form.password.data)
            db.session.commit()
            flash(f'User "{user.name}" updated.', "success")
            return redirect(url_for("admin_users"))
    return render_template("admin/user_form.html", form=form, mode="edit", user=user)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_user_delete(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return "User not found", 404
    if user.id == current_user.id:
        flash("You can't delete your own account from the admin panel.", "danger")
        return redirect(url_for("admin_users"))
    if user.is_admin and count_admins() <= 1:
        flash("You can't delete the last remaining admin.", "danger")
        return redirect(url_for("admin_users"))
    # Keep the service history: the requests stay, just no longer linked to a user.
    db.session.execute(db.update(ServiceRequest).where(ServiceRequest.user_id == user.id).values(user_id=None))
    name = user.name
    db.session.delete(user)
    db.session.commit()
    flash(f'User "{name}" deleted. Their service requests were kept.', "info")
    return redirect(url_for("admin_users"))


# ADMIN: SERVICE REQUESTS
@app.route("/admin/requests")
@login_required
@admin_required
def admin_requests():
    query, search, service, status = filtered_requests_query()
    page = db.paginate(query, page=request.args.get("page", 1, type=int),
                       per_page=ADMIN_PAGE_SIZE, error_out=False)
    return render_template(
        "admin/requests.html", page=page, search=search, service=service, status=status,
        statuses=REQUEST_STATUSES, services=[config[0] for config in SERVICE_CONFIG.values()])


@app.route("/admin/requests/export.csv")
@login_required
@admin_required
def admin_requests_export():
    query, _, _, _ = filtered_requests_query()
    rows = db.session.execute(query).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Request ID", "Service", "Status", "Created (IST)", "Name", "Phone", "Email",
                     "Vehicle", "Vehicle Number", "Location", "Details"])
    for item in rows:
        details = item.details or {}
        writer.writerow([
            item.id, item.service, item.status, item.createdAt, details.get("name", ""),
            details.get("phone", ""), item.email or "", details.get("vehicle_type", ""),
            details.get("vehicle_number", ""), details.get("location", ""),
            "; ".join(f"{key}={value}" for key, value in details.items()),
        ])
    return Response(buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=roadassist-requests.csv"})


@app.route("/admin/requests/<request_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_request_detail(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item:
        return "Request not found", 404
    status_form = AdminStatusForm(obj=item)
    if status_form.validate_on_submit():
        item.status = status_form.status.data
        db.session.commit()
        flash(f"{item.id} marked as {item.status}.", "success")
        return redirect(url_for("admin_request_detail", request_id=item.id))
    return render_template("admin/request_detail.html", item=item, form=status_form)


@app.route("/admin/requests/<request_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_request_delete(request_id):
    item = db.session.get(ServiceRequest, request_id)
    if not item:
        return "Request not found", 404
    db.session.delete(item)
    db.session.commit()
    flash(f"Request {request_id} deleted.", "info")
    return redirect(url_for("admin_requests"))


# ADMIN: FEEDBACK
@app.route("/admin/feedback")
@login_required
@admin_required
def admin_feedback():
    page = db.paginate(db.select(Feedback).order_by(Feedback.created_at.desc()),
                       page=request.args.get("page", 1, type=int), per_page=ADMIN_PAGE_SIZE, error_out=False)
    return render_template("admin/feedback.html", page=page)


@app.route("/admin/feedback/<int:feedback_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_feedback_delete(feedback_id):
    item = db.session.get(Feedback, feedback_id)
    if not item:
        return "Feedback not found", 404
    db.session.delete(item)
    db.session.commit()
    flash("Feedback deleted.", "info")
    return redirect(url_for("admin_feedback"))


# ERROR HANDLERS
@app.errorhandler(404)
def page_not_found(error):
    return "Page not found.", 404


@app.errorhandler(500)
def internal_server_error(error):
    db.session.rollback()
    return "Something went wrong on our side. Please try again.", 500


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_ENV") != "production")
