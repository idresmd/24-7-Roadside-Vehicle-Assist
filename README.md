# RoadAssist 24/7 — Flask/Jinja Version

This project converts the supplied single-page RoadAssist HTML into real Flask routes while keeping the supplied visual styling/content as closely as possible.

## Pages/routes
- `/` — Home
- `/services` — Services
- `/about` — About
- `/contact` — Contact
- `/feedback` — Feedback
- `/login` — Login
- `/register` — Register
- `/dashboard` — Dashboard
- `/track` — Track request
- `/request-service` — Service request entry
- `/service/towing` — Vehicle Towing form
- `/service/fuel` — Fuel Delivery form
- `/service/tire` — Flat Tire form
- `/service/lockout` — Lockout Service form
- `/service/repair` — Minor Repairs form
- `/service/battery` — Battery Jump Start form

## Important
- Structured like Train2Conquer: everything lives in `main.py` (config, models, startup schema check, routes), with `forms.py` for Flask-WTF forms.
- Data is stored with **Flask-SQLAlchemy**: Supabase PostgreSQL via the `SUPABASE` env var (`NullPool`). Tables: `users`, `service_requests`, `feedback` (created automatically on startup; the `is_admin` column is added to older databases automatically). Passwords are hashed.
- Auth uses **Flask-Login**; CSRF is enforced app-wide; logout is POST-only. Set `ADMIN_EMAIL` to promote an existing user to admin.
- Forms use Flask-WTF and Bootstrap-Flask `render_form()`.
- **Login required:** every `/service/...` page needs an account; logged-out visitors are sent to login and returned afterwards. Name, phone and vehicle type/number are asked once at registration (edit them at `/profile`); service forms only ask what is specific to the breakdown.
- **Admin panel** at `/admin` (admins only): overview stats, users (add/edit/delete, reset password), service requests (search, filter, change status, delete, CSV export) and feedback (delete). Make someone an admin with `ADMIN_EMAIL` in `.env` (they must have registered first) or from Admin -> Users -> Edit.
- Demo login (only if `SEED_DEMO_USER=true` in `.env`): `admin@roadassist.com` / `admin123`.
- The original CSS references `c3.jpg`. The supplied ZIP did not contain that image, so place the original `c3.jpg` at `static/images/c3.jpg` and change the `.hero` background URL in `static/css/style.css` to `url('../images/c3.jpg')` if you want the original background image.

## Run
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then fill SECRET_KEY and SUPABASE
python main.py
```
Production: `gunicorn main:app` (see `Procfile`) with `FLASK_ENV=production`.
Then open `http://127.0.0.1:5000/`.

## Supabase: after the first run
Tables created by SQLAlchemy land in the `public` schema, which Supabase exposes through its REST API. Flask connects directly as the `postgres` role (bypasses RLS), so turn RLS on with no policies to block public API access. Run once in the Supabase SQL Editor:
```sql
alter table public.users enable row level security;
alter table public.service_requests enable row level security;
alter table public.feedback enable row level security;
```
