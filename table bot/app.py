import os
from flask import Flask, redirect, url_for, session, render_template, request, flash
from database import db
from models import User, AdminProfile, InactiveRequest, MeetingSkipRequest, FormSubmission, LogEntry
from requests_oauthlib import OAuth2Session
from datetime import datetime
from functools import wraps

# 1. РАЗРЕШАЕМ HTTP (нужно для работы внутри туннеля и локально)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class Config:
    # Используйте постоянную строку, чтобы сессия не сбрасывалась
    SECRET_KEY = 'super_secret_key_for_dev_tunnel'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///site.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ВАШИ ДАННЫЕ ИЗ DISCORD PORTAL
    DISCORD_CLIENT_ID = '1470790152766095414'
    DISCORD_CLIENT_SECRET = 'omSY1HtF25zyQ57ki3HhN8zcX2uW2d9j'
    DISCORD_REDIRECT_URI = 'https://4dt1nkgc-5000.euw.devtunnels.ms/callback'
    
    DISCORD_AUTHORIZATION_BASE_URL = 'https://discord.com/oauth2/authorize'
    DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
    DISCORD_API_BASE_URL = 'https://discord.com/api/v10'

    # НАСТРОЙКИ COOKIE ДЛЯ DEV TUNNELS
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'None'
    SESSION_COOKIE_NAME = 'discord_session'

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Discord OAuth configuration from Config
with app.app_context():
    CLIENT_ID = app.config.get("DISCORD_CLIENT_ID")
    CLIENT_SECRET = app.config.get("DISCORD_CLIENT_SECRET")
    REDIRECT_URI = app.config.get("DISCORD_REDIRECT_URI")
    AUTHORIZATION_BASE_URL = app.config.get("DISCORD_AUTHORIZATION_BASE_URL")
    TOKEN_URL = app.config.get("DISCORD_TOKEN_URL")
    API_BASE_URL = app.config.get("DISCORD_API_BASE_URL")

if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
    print("WARNING: Discord OAuth environment variables are not set. Please set DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_REDIRECT_URI in your environment or config.py.")

# OAuth scopes for Discord
SCOPE = ["identify"]

@app.before_request
def create_db_tables():
    db.create_all()

@app.route("/")
def index():
    user_discord_data = None
    if "discord_token" in session:
        discord = OAuth2Session(CLIENT_ID, token=session["discord_token"])
        try:
            user_discord_data = discord.get(f"{API_BASE_URL}/users/@me").json()
            if user_discord_data and "code" in user_discord_data and user_discord_data["code"] == 0:
                print("Discord token invalid, clearing session.")
                session.pop("discord_token", None)
                session.pop("user_id", None)
                session.pop("username", None)
                session.pop("admin_level", None)
                user_discord_data = None
                return redirect(url_for("login"))

        except Exception as e:
            print(f"Error fetching user data: {e}")
            session.pop("discord_token", None)
            session.pop("user_id", None)
            session.pop("username", None)
            session.pop("admin_level", None)
            user_discord_data = None
            return redirect(url_for("login"))

    return render_template("index.html", user=user_discord_data)

@app.route("/login")
def login():
    discord = OAuth2Session(CLIENT_ID, scope=SCOPE, redirect_uri=REDIRECT_URI)
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session["oauth2_state"] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    # Мы убираем проверку state, так как Dev Tunnels часто теряют его в сессии
    discord = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    
    try:
        token = discord.fetch_token(
            TOKEN_URL,
            client_secret=CLIENT_SECRET,
            authorization_response=request.url.replace('http://', 'https://') # Принудительно HTTPS для туннеля
        )
    except Exception as e:
        print(f"Error fetching token: {e}")
        return f"Failed to obtain access token: {e}", 500

    session["discord_token"] = token
    user_info = discord.get(f"{API_BASE_URL}/users/@me").json()

    discord_id = user_info["id"]
    username = user_info["username"]
    # Используем .get(), чтобы не упасть, если ключа нет, и ставим "0" по умолчанию
    discriminator = user_info.get("discriminator", "0")
    avatar = user_info.get("avatar")

    user = User.query.filter_by(discord_id=discord_id).first()

    if not user:
        user = User(
            discord_id=discord_id,
            username=username,
            discriminator=discriminator, # Теперь здесь будет "0" или реальный номер
            avatar=avatar,
            admin_level=0
        )
        db.session.add(user)
    else:
        user.username = username
        user.discriminator = discriminator
        user.avatar = avatar

    db.session.commit()

    session["user_id"] = user.id
    session["username"] = user.username
    session["admin_level"] = user.admin_level

    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# --- Administration Section Routes ---

from functools import wraps

# Helper to check admin level
def admin_required(min_level):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("user_id") or session.get("admin_level", 0) < min_level:
                flash("You do not have the required administration level to access this page.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Взятие неактива (Inactive Requests)
@app.route("/inactive/apply", methods=["GET", "POST"])
def inactive_request_form():
    if not session.get("user_id"):
        flash("Please log in to submit an inactive request.", "info")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        reason = request.form.get("reason")

        if not all([start_date_str, end_date_str, reason]):
            flash("All fields are required.", "danger")
            return render_template("inactive_request_form.html", username=session.get("username"))

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
            return render_template("inactive_request_form.html", username=session.get("username"))
        
        if start_date > end_date:
            flash("Start date cannot be after end date.", "danger")
            return render_template("inactive_request_form.html", username=session.get("username"))

        new_request = InactiveRequest(
            user_id=session["user_id"],
            start_date=start_date,
            end_date=end_date,
            reason=reason
        )
        db.session.add(new_request)
        db.session.commit()
        flash("Inactive request submitted successfully!", "success")
        return redirect(url_for("index")) # Redirect to a dashboard or confirmation page

    return render_template("inactive_request_form.html", username=session.get("username"))

@app.route("/inactive/panel")
@admin_required(min_level=7)
def inactive_requests_panel():
    pending_requests = InactiveRequest.query.filter_by(status="Pending").all()
    return render_template("inactive_requests_panel.html", requests=pending_requests)

@app.route("/inactive/process/<int:request_id>/<action>")
@admin_required(min_level=7)
def process_inactive_request(request_id, action):
    inactive_req = InactiveRequest.query.get_or_404(request_id)
    if action == "approve":
        inactive_req.status = "Approved"
        flash(f"Inactive request {request_id} approved.", "success")
    elif action == "deny":
        inactive_req.status = "Denied"
        flash(f"Inactive request {request_id} denied.", "warning")
    else:
        flash("Invalid action.", "danger")
        return redirect(url_for("inactive_requests_panel"))
    
    inactive_req.processed_by_id = session["user_id"]
    inactive_req.processed_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("inactive_requests_panel"))

# Пропуск собрания (Meeting Skip)
@app.route("/meeting_skip/apply", methods=["GET", "POST"])
def meeting_skip_form():
    if not session.get("user_id"):
        flash("Please log in to submit a meeting skip request.", "info")
        return redirect(url_for("login"))

    if request.method == "POST":
        reason = request.form.get("reason")

        if not reason:
            flash("Reason is required.", "danger")
            return render_template("meeting_skip_form.html", username=session.get("username"))

        new_request = MeetingSkipRequest(
            user_id=session["user_id"],
            reason=reason
        )
        db.session.add(new_request)
        db.session.commit()
        flash("Meeting skip request submitted successfully!", "success")
        return redirect(url_for("index")) # Redirect to a dashboard or confirmation page

    return render_template("meeting_skip_form.html", username=session.get("username"))

@app.route("/meeting_skip/panel")
@admin_required(min_level=7)
def meeting_skip_panel():
    pending_requests = MeetingSkipRequest.query.filter_by(status="Pending").all()
    return render_template("meeting_skip_panel.html", requests=pending_requests)

@app.route("/meeting_skip/process/<int:request_id>/<action>")
@admin_required(min_level=7)
def process_meeting_skip_request(request_id, action):
    meeting_req = MeetingSkipRequest.query.get_or_404(request_id)
    if action == "approve":
        meeting_req.status = "Approved"
        flash(f"Meeting skip request {request_id} approved.", "success")
    elif action == "deny":
        meeting_req.status = "Denied"
        flash(f"Meeting skip request {request_id} denied.", "warning")
    else:
        flash("Invalid action.", "danger")
        return redirect(url_for("meeting_skip_panel"))
    
    meeting_req.processed_by_id = session["user_id"]
    meeting_req.processed_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("meeting_skip_panel"))

# Магазин (Shop) - Placeholder
@app.route("/shop")
def shop_page():
    return render_template("shop.html")

# Список администрации
@app.route("/admin/list")
def admin_list():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    admins = AdminProfile.query.all()
    return render_template("admin_list.html", admins=admins)

# Профиль администратора
@app.route("/admin/profile/<int:user_id>")
def admin_profile(user_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    target_user = User.query.get_or_404(user_id)
    profile = AdminProfile.query.filter_by(user_id=user_id).first()
    
    if not profile:
        # Create profile if doesn't exist (e.g., first time visiting)
        profile = AdminProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    
    logs = LogEntry.query.filter_by(target_user_id=user_id).order_by(LogEntry.timestamp.desc()).all()
    
    return render_template("admin_profile.html", target_user=target_user, profile=profile, logs=logs)

# Редактирование профиля
@app.route("/admin/profile/<int:user_id>/edit", methods=["POST"])
@admin_required(min_level=7)
def edit_profile(user_id):
    target_user = User.query.get_or_404(user_id)
    profile = AdminProfile.query.filter_by(user_id=user_id).first()
    
    changes = []
    
    # Update profile fields and track changes
    fields = [
        ('date_appointed', 'date'),
        ('last_promotion', 'date'),
        ('reason_appointed', 'text'),
        ('points', 'int'),
        ('position', 'text'),
        ('prefix', 'text')
    ]
    
    for field, type_ in fields:
        old_val = getattr(profile, field)
        new_val_str = request.form.get(field)
        
        if type_ == 'date':
            new_val = datetime.strptime(new_val_str, "%Y-%m-%d") if new_val_str else None
        elif type_ == 'int':
            new_val = int(new_val_str) if new_val_str else 0
        else:
            new_val = new_val_str
            
        if old_val != new_val:
            setattr(profile, field, new_val)
            changes.append(f"{field}: {old_val} -> {new_val}")
            
    # Update admin level separately
    old_lvl = target_user.admin_level
    new_lvl = int(request.form.get('admin_level', old_lvl))
    if old_lvl != new_lvl:
        target_user.admin_level = new_lvl
        changes.append(f"admin_level: {old_lvl} -> {new_lvl}")
        
    if changes:
        log = LogEntry(
            actor_id=session["user_id"],
            target_user_id=user_id,
            action=", ".join(changes)
        )
        db.session.add(log)
        db.session.commit()
        flash("Profile updated successfully!", "success")
    
    return redirect(url_for("admin_profile", user_id=user_id))

# --- Forms Section Routes ---

@app.route("/forms/my")
def my_forms():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    submissions = FormSubmission.query.filter_by(user_id=session["user_id"]).order_by(FormSubmission.submitted_at.desc()).all()
    
    stats = {
        "total": len(submissions),
        "accepted": len([s for s in submissions if s.status == "Accepted"]),
        "pending": len([s for s in submissions if s.status == "Pending"])
    }
    
    return render_template("my_forms.html", submissions=submissions, stats=stats)

@app.route("/forms/submit", methods=["GET", "POST"])
def submit_form():
    if not session.get("user_id"):
        return redirect(url_for("login"))
        
    if request.method == "POST":
        content = request.form.get("content")
        if not content:
            flash("Form content cannot be empty.", "danger")
            return redirect(url_for("my_forms"))
            
        new_submission = FormSubmission(
            user_id=session["user_id"],
            content=content
        )
        db.session.add(new_submission)
        db.session.commit()
        flash("Form submitted successfully!", "success")
        return redirect(url_for("my_forms"))
        
    return render_template("submit_form.html")

@app.route("/forms/list")
@admin_required(min_level=7)
def forms_list():
    submissions = FormSubmission.query.order_by(FormSubmission.submitted_at.desc()).all()
    return render_template("forms_list.html", submissions=submissions)

@app.route("/forms/process/<int:form_id>/<action>")
@admin_required(min_level=7)
def process_form(form_id, action):
    form = FormSubmission.query.get_or_404(form_id)
    if action == "accept":
        form.status = "Accepted"
        flash("Form accepted.", "success")
    elif action == "reject":
        form.status = "Rejected"
        flash("Form rejected.", "warning")
    
    form.accepted_by_id = session["user_id"]
    form.accepted_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("forms_list"))


if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Ensure tables are created when running directly
    app.run(debug=True)
