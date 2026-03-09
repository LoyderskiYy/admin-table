import os
from flask import Flask, redirect, url_for, session, render_template, request, flash, g
from database import db
from models import User, AdminProfile, InactiveRequest, MeetingSkipRequest, FormSubmission, LogEntry, ShopItem, Purchase, ReportSubmission
from sqlalchemy.orm import joinedload
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

    # --- ТЕХНИЧЕСКИЕ РАБОТЫ ---
    MAINTENANCE_MODE = False  # Поставьте False, чтобы включить сайт
    # --------------------------

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

# Jinja2 filter for calculating days in team
@app.template_filter('days_in_team')
def days_in_team(date):
    if not date:
        return ''
    now = datetime.now()
    if date.tzinfo:
        now = datetime.now(date.tzinfo)
    delta = now - date
    days = delta.days
    if days == 0:
        return 'сегодня'
    elif days == 1:
        return '1 день'
    elif 2 <= days <= 4:
        return f'{days} дня'
    else:
        return f'{days} дн.'

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
def setup_request():
    # 1. Создаем таблицы, если их нет
    if not hasattr(app, '_db_initialized'):
        db.create_all()
        app._db_initialized = True

    # 2. Проверка режима тех. работ
    if app.config.get("MAINTENANCE_MODE") and request.endpoint not in ('maintenance', 'static'):
        return redirect(url_for('maintenance'))

    # 3. Загружаем пользователя в глобальный объект g
    g.user = None
    if "user_id" in session:
        # Оптимизированная загрузка с профилем (современный стиль SQLAlchemy 2.0)
        g.user = db.session.get(User, session["user_id"], options=[joinedload(User.admin_profile)])
        if not g.user:
            session.clear()

@app.route("/maintenance")
def maintenance():
    # Если кто-то зашел на /maintenance, когда режим выключен — ведем на главную
    if not app.config.get("MAINTENANCE_MODE"):
        return redirect(url_for('index'))
    return render_template("techjob.html")

# Обработчик ошибки 404 - страница не найдена
@app.errorhandler(404)
def page_not_found(e):
    return render_template("error_404.html"), 404

@app.route("/")
def index():
    db_user = None
    discord_data = None
    user_logs = [] 
    
    if "discord_token" in session:
        discord = OAuth2Session(CLIENT_ID, token=session["discord_token"])
        try:
            discord_data = discord.get(f"{API_BASE_URL}/users/@me").json()
            
            if discord_data and "code" in discord_data and discord_data["code"] == 0:
                clear_user_session()
                return redirect(url_for("login"))

            # Импортируем модели
            from models import User, LogEntry 
            db_user = User.query.filter_by(discord_id=str(discord_data['id'])).first()

            if db_user:
                # Фильтруем по target_user_id (твой ID в системе)
                user_logs = LogEntry.query.filter_by(target_user_id=db_user.id)\
                                          .order_by(LogEntry.timestamp.desc())\
                                          .limit(10).all()

        except Exception as e:
            print(f"Ошибка в index: {e}")
            clear_user_session()
            return redirect(url_for("login"))

    return render_template("index.html", 
                           user=db_user, 
                           discord_user=discord_data, 
                           logs=user_logs)

def clear_user_session():
    """Очистка всех данных сессии при логауте или ошибке токена"""
    session.pop("discord_token", None)
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("admin_level", None)

@app.route("/login")
def login():
    discord = OAuth2Session(CLIENT_ID, scope=SCOPE, redirect_uri=REDIRECT_URI)
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session["oauth2_state"] = state
    return redirect(authorization_url)

@app.route("/callback")
def callback():
    discord = OAuth2Session(CLIENT_ID, redirect_uri=REDIRECT_URI)
    
    try:
        token = discord.fetch_token(
            TOKEN_URL,
            client_secret=CLIENT_SECRET,
            authorization_response=request.url.replace('http://', 'https://') 
        )
    except Exception as e:
        print(f"Error fetching token: {e}")
        return f"Failed to obtain access token: {e}", 500

    session.permanent = True  # Делаем сессию постоянной
    session["discord_token"] = token
    user_info = discord.get(f"{API_BASE_URL}/users/@me").json()

    discord_id = str(user_info["id"]) # Приводим к строке для надежности
    username = user_info["username"]
    avatar = user_info.get("avatar")

    # --- НОВАЯ ЛОГИКА ЗАЩИТЫ ---
    user = User.query.filter_by(discord_id=discord_id).first()

    if not user:
        # Если пользователя нет в БД, не пускаем его
        clear_user_session()
        flash("Доступ запрещен: Вашего Discord ID нет в белом списке системы. Обратитесь к старшей администрации.", "danger")
        return redirect(url_for("index")) 

    # Если пользователь есть, обновляем его данные из Дискорда
    user.username = username
    user.avatar = avatar
    db.session.commit()
    # ---------------------------

    # Записываем данные в сессию
    session["user_id"] = user.id
    session["username"] = user.username
    session["admin_level"] = user.admin_level
    session["avatar"] = user.avatar
    session["discord_id"] = discord_id

    flash(f"Добро пожаловать, {username}!", "success")
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
            if not g.user:
                flash("Пожалуйста, войдите в систему.", "warning")
                return redirect(url_for("login"))
            if g.user.admin_level < min_level:
                flash("У вас недостаточно прав для доступа к этой странице.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Взятие неактива (Inactive Requests)
@app.route("/inactive/apply", methods=["GET", "POST"])
def inactive_request_form():
    if not session.get("user_id"):
        flash("Пожалуйста, войдите в аккаунт.", "info")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        date_range_raw = request.form.get("date_range")
        reason = request.form.get("reason")
        is_infinite = request.form.get("is_infinite") == 'on'

        new_request = InactiveRequest(
            user_id=session["user_id"],
            reason=reason,
            status="Pending",
            submitted_at=datetime.utcnow()
        )

        if is_infinite:
            new_request.start_date = datetime.utcnow().date()
            new_request.end_date = datetime.strptime("31.12.2099", "%d.%m.%Y").date()
        else:
            try:
                # 1. Получаем строку, например "11.02.2026 15.02.2026"
                raw_val = date_range_raw.strip()
                
                # 2. Убираем любые возможные тире, которые могли проскочить
                raw_val = raw_val.replace("—", " ").replace("-", " ").replace("to", " ")
                
                # 3. Разбиваем по пробелам и фильтруем пустые элементы
                dates = [d for d in raw_val.split() if d]

                if len(dates) < 2:
                    flash("Ошибка: выберите и дату начала, и дату окончания!", "danger")
                    return render_template("inactive_request_form.html", username=session.get("username"))

                # 4. Превращаем очищенные строки в даты
                new_request.start_date = datetime.strptime(dates[0], "%d.%m.%Y").date()
                new_request.end_date = datetime.strptime(dates[1], "%d.%m.%Y").date()

            except Exception as e:
                print(f"Ошибка парсинга дат: {e}")
                flash("Не удалось распознать формат дат. Попробуйте еще раз.", "danger")
                return render_template("inactive_request_form.html", username=session.get("username"))

        db.session.add(new_request)
        db.session.commit()
        flash("Заявка успешно отправлена!", "success")
        return redirect(url_for("index"))

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
        flash(f"Заявка на неактивность {request_id} одобрена.", "success")
    elif action == "deny":
        inactive_req.status = "Denied"
        flash(f"Заявка на неактивность {request_id} отклонена.", "warning")
    else:
        flash("Неверное действие.", "danger")
        return redirect(url_for("inactive_requests_panel"))
    
    inactive_req.processed_by_id = session["user_id"]
    inactive_req.processed_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("inactive_requests_panel"))

# Пропуск собрания (Meeting Skip)
@app.route("/meeting_skip/apply", methods=["GET", "POST"])
def meeting_skip_form():
    if not session.get("user_id"):
        flash("Пожалуйста, войдите в систему, чтобы подать заявку на пропуск совещания.", "info")
        return redirect(url_for("login"))

    if request.method == "POST":
        reason = request.form.get("reason")

        if not reason:
            flash("Укажите причину.", "danger")
            return render_template("meeting_skip_form.html", username=session.get("username"))

        new_request = MeetingSkipRequest(
            user_id=session["user_id"],
            reason=reason
        )
        db.session.add(new_request)
        db.session.commit()
        flash("Заявка на пропуск совещания успешно отправлена!", "success")
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
        flash(f"Заявка на пропуск совещания {request_id} одобрена.", "success")
    elif action == "deny":
        meeting_req.status = "Denied"
        flash(f"Заявка на пропуск совещания {request_id} отклонена.", "warning")
    else:
        flash("Неверное действие.", "danger")
        return redirect(url_for("meeting_skip_panel"))
    
    meeting_req.processed_by_id = session["user_id"]
    meeting_req.processed_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("meeting_skip_panel"))

@app.route("/shop")
@admin_required(min_level=1)
def shop():
    items = ShopItem.query.all()
    user = g.user # Используем уже загруженного пользователя
    # Передаем только items и user. Рендеринг условий (уровни, лимиты) теперь в HTML.
    return render_template("shop.html", items=items, user=user)

@app.route("/shop/admin", methods=["GET", "POST"]) # Важно: добавлены оба метода
@admin_required(min_level=8)
def shop_admin():
    if request.method == "POST":
        try:
            new_item = ShopItem(
                name=request.form.get("name"),
                price=int(request.form.get("price")),
                description=request.form.get("description"),
                image_url=request.form.get("image_url"),
                min_level=int(request.form.get("min_level", 1)),
                purchase_limit=int(request.form.get("purchase_limit", 0))
            )
            db.session.add(new_item)
            db.session.commit()
            flash(f"Товар '{new_item.name}' успешно добавлен!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка при добавлении: {e}", "danger")
        return redirect(url_for("shop_admin"))

    # Если это GET запрос — просто показываем страницу
    items = ShopItem.query.all()
    return render_template("shop_admin.html", items=items)

@app.route("/shop/admin/add", methods=["POST"])
@admin_required(min_level=8)
def add_shop_item():
    try:
        new_item = ShopItem(
            name=request.form.get("name"),
            price=int(request.form.get("price")),
            description=request.form.get("description"),
            image_url=request.form.get("image_url"),
            min_level=int(request.form.get("min_level", 1)),
            purchase_limit=int(request.form.get("purchase_limit", 0))
        )
        db.session.add(new_item)
        db.session.commit()
        flash(f"Товар '{new_item.name}' добавлен в магазин!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка при добавлении: {e}", "danger")
    
    return redirect(url_for("shop_admin"))

@app.route("/shop/admin/delete/<int:item_id>")
@admin_required(min_level=8)
def delete_shop_item(item_id):
    item = ShopItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Товар удален.", "info")
    return redirect(url_for("shop_admin"))

@app.route("/shop/buy/<int:item_id>", methods=["POST"])
@admin_required(min_level=1)
def buy_item(item_id):
    item = db.session.get(ShopItem, item_id) or abort(404)
    user = g.user # Используем g.user
    
    # 1. Проверка уровня
    if user.admin_level < item.min_level:
        flash(f"Этот товар доступен только с {item.min_level} уровня.", "danger")
        return redirect(url_for("shop"))

    # 2. Проверка баллов
    if user.admin_profile.points < item.price:
        flash("Недостаточно баллов для покупки.", "danger")
        return redirect(url_for("shop"))

    # 3. НОВАЯ ЛОГИКА: Проверка лимита покупок
    if item.purchase_limit > 0:
        # Считаем, сколько раз пользователь уже купил этот товар
        times_bought = Purchase.query.filter_by(user_id=user.id, item_id=item.id).count()
        if times_bought >= item.purchase_limit:
            flash(f"Вы достигли лимита покупок для этого товара ({item.purchase_limit} шт.).", "danger")
            return redirect(url_for("shop"))

    # Выполнение покупки
    user.admin_profile.points -= item.price
    
    # Сохраняем запись о покупке в новую таблицу
    purchase = Purchase(user_id=user.id, item_id=item.id)
    db.session.add(purchase)
    
    # Логируем действие
    new_log = LogEntry(
        actor_id=user.id,
        target_user_id=user.id,
        action=f"ПОКУПКА: {item.name} за {item.price} баллов"
    )
    db.session.add(new_log)
    
    db.session.commit()
    flash(f"Вы успешно купили {item.name}!", "success")
    
    return redirect(url_for("shop"))

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
    
    target_user = db.session.get(User, user_id)
    if not target_user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin_list"))
    profile = AdminProfile.query.filter_by(user_id=user_id).first()
    
    if not profile:
        # Create profile if doesn't exist (e.g., first time visiting)
        profile = AdminProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    
    logs = LogEntry.query.filter_by(target_user_id=user_id).order_by(LogEntry.timestamp.desc()).all()
    
    # Проверяем, может ли текущий пользователь редактировать профиль
    my_id = session.get("user_id")
    my_level = session.get("admin_level", 0)
    target_level = target_user.admin_level or 0
    
    # Можно редактировать если: это свой профиль ИЛИ уровень выше цели
    can_edit = (my_id == user_id) or (my_level > target_level)
    
    return render_template("admin_profile.html", target_user=target_user, profile=profile, logs=logs, can_edit=can_edit, my_level=my_level, target_level=target_level, my_id=my_id)

@app.route("/admin/profile/<int:user_id>/edit", methods=["POST"])
@admin_required(min_level=7)
def edit_profile(user_id):
    # 1. Получаем данные того, КТО редактирует и КОГО редактируют
    my_id = session.get("user_id")
    my_level = session.get("admin_level", 0)
    
    target_user = db.session.get(User, user_id)
    if not target_user:
        flash("Пользователь не найден.", "danger")
        return redirect(url_for("admin_list"))
    profile = AdminProfile.query.filter_by(user_id=user_id).first()
    target_level = target_user.admin_level or 0

    # 2. ПРОВЕРКА ИЕРАРХИИ
    # Нельзя редактировать тех, кто равен или выше по рангу (кроме себя)
    if my_id != user_id and my_level <= target_level:
        flash("Ошибка доступа: Вы не можете редактировать администратора равного или выше вас по рангу.", "danger")
        return redirect(url_for("admin_profile", user_id=user_id))
    
    is_self_edit = (my_id == user_id)

    changes = []
    
    # Перевод названий полей для логов
    field_names_ru = {
        'date_appointed': 'Дата назначения',
        'last_promotion': 'Последнее повышение',
        'reason_appointed': 'Причина назначения',
        'points': 'Баллы',
        'reprimands': 'Выговоры',
        'warnings': 'Предупреждения',
        'position': 'Должность',
        'prefix': 'Префикс',
        'vk_link': 'Ссылка VK',
        'telegram_link': 'Ссылка Telegram',
        'level': 'Уровень'
    }
    
    # Поля для обработки (исключаем admin_level при редактировании)
    fields = [
        ('date_appointed', 'date'),
        ('last_promotion', 'date'),
        ('reason_appointed', 'text'),
        ('points', 'int'),
        ('reprimands', 'int'),
        ('warnings', 'int'),
        ('position', 'text'),
        ('prefix', 'text'),
        ('vk_link', 'url'),
        ('telegram_link', 'url')
    ]
    
    for field, type_ in fields:
        old_val = getattr(profile, field)
        new_val_raw = request.form.get(field, "").strip()
        
        if type_ == 'date':
            new_val = datetime.strptime(new_val_raw, "%Y-%m-%d") if new_val_raw else None
        elif type_ == 'int':
            new_val = int(new_val_raw) if (new_val_raw and new_val_raw.strip()) else 0
        elif type_ == 'url':
            new_val = new_val_raw
            if new_val and not new_val.startswith(('http://', 'https://')):
                new_val = 'https://' + new_val
        else:
            new_val = new_val_raw
            
        if old_val != new_val:
            setattr(profile, field, new_val)
            field_name_ru = field_names_ru.get(field, field)
            changes.append(f"{field_name_ru}: {old_val} -> {new_val}")
    
    # Автоматическое преобразование: 3 предупреждения = 1 выговор
    warnings_after = profile.warnings
    reprimands_before = profile.reprimands
    if warnings_after >= 3:
        conversions = warnings_after // 3
        profile.warnings = warnings_after % 3
        profile.reprimands = reprimands_before + conversions
        changes.append(f"Системное преобразование: {conversions} выговор(ов) из предупреждений (было {warnings_after} предупреждений)")
    
    # Обновляем уровень админа с проверкой (только при редактировании чужого профиля)
    old_lvl = target_user.admin_level
    requested_lvl = int(request.form.get('admin_level', old_lvl))
    
    # Нельзя изменять свой уровень админа при редактировании своего профиля
    if is_self_edit and requested_lvl != old_lvl:
        flash("Вы не можете изменить свой собственный уровень админа.", "danger")
        return redirect(url_for("admin_profile", user_id=user_id))
    
    # Нельзя выдать уровень выше или равный своему (только для чужого профиля)
    if not is_self_edit and requested_lvl >= my_level:
        requested_lvl = my_level - 1
        flash(f"Вы не можете установить уровень выше или равный вашему. Установлен макс. возможный: {requested_lvl}", "warning")

    if old_lvl != requested_lvl:
        target_user.admin_level = requested_lvl
        changes.append(f"{field_names_ru.get('level', 'level')}: {old_lvl} -> {requested_lvl}")
    
    # Получаем причину изменений
    change_reason = request.form.get('change_reason', '').strip()
    
    if changes:
        log_action = "Изменение профиля: " + " | ".join(changes)
        if change_reason:
            log_action += f" | Причина: {change_reason}"
        log = LogEntry(
            actor_id=my_id,
            target_user_id=user_id,
            action=log_action
        )
        db.session.add(log)
        db.session.commit()
        flash("Изменения успешно сохранены!", "success")
    
    return redirect(url_for("admin_profile", user_id=user_id))

# --- Forms Section Routes ---

@app.route("/forms/my")
def my_forms():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    # Получаем все сабмиты пользователя
    submissions = FormSubmission.query.filter_by(user_id=session["user_id"]).order_by(FormSubmission.submitted_at.desc()).all()
    
    # ИСПРАВЛЕНО: Добавлен подсчет отклоненных форм (Rejected)
    stats = {
        "total": len(submissions),
        "accepted": len([s for s in submissions if s.status == "Accepted"]),
        "pending": len([s for s in submissions if s.status == "Pending"]),
        "rejected": len([s for s in submissions if s.status == "Rejected"])  # <--- ЭТОГО НЕ ХВАТАЛО
    }
    
    return render_template("my_forms.html", submissions=submissions, stats=stats)

@app.route("/forms/submit", methods=["GET", "POST"])
def submit_form():
    if not session.get("user_id"):
        return redirect(url_for("login"))
        
    if request.method == "POST":
        content = request.form.get("content")
        if not content:
            flash("Ошибка отправки Формы.", "danger")
            return redirect(url_for("my_forms"))
            
        new_submission = FormSubmission(
            user_id=session["user_id"],
            content=content
        )
        db.session.add(new_submission)
        db.session.commit()
        flash("Форма успешно отправлена!", "success")
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
        flash("Форма принята.", "success")
    elif action == "reject":
        form.status = "Rejected"
        flash("Форма отклонена.", "warning")
    
    form.accepted_by_id = session["user_id"]
    form.accepted_date = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("forms_list"))


# --- Reports Section Routes ---

@app.route("/reports/my")
def my_reports():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    # Получаем все отчёты пользователя
    reports = ReportSubmission.query.filter_by(user_id=session["user_id"]).order_by(ReportSubmission.submitted_at.desc()).all()
    
    stats = {
        "total": len(reports),
        "approved": len([r for r in reports if r.status == "Approved"]),
        "pending": len([r for r in reports if r.status == "Pending"]),
        "rejected": len([r for r in reports if r.status == "Rejected"])
    }
    
    return render_template("my_reports.html", reports=reports, stats=stats)

@app.route("/reports/submit", methods=["GET", "POST"])
def submit_report():
    if not session.get("user_id"):
        return redirect(url_for("login"))
        
    if request.method == "POST":
        content = request.form.get("content")
        if not content:
            flash("Ошибка отправки отчёта.", "danger")
            return redirect(url_for("my_reports"))
            
        new_report = ReportSubmission(
            user_id=session["user_id"],
            content=content
        )
        db.session.add(new_report)
        db.session.commit()
        flash("Отчёт успешно отправлен!", "success")
        return redirect(url_for("my_reports"))
        
    return render_template("submit_report.html")

@app.route("/reports/list")
@admin_required(min_level=7)
def reports_list():
    reports = ReportSubmission.query.order_by(ReportSubmission.submitted_at.desc()).all()
    return render_template("reports_list.html", reports=reports)

@app.route("/reports/process/<int:report_id>/<action>", methods=["POST"])
@admin_required(min_level=7)
def process_report(report_id, action):
    report = ReportSubmission.query.get_or_404(report_id)
    comment = request.form.get("comment", "").strip()
    
    if action == "approve":
        report.status = "Approved"
        flash("Отчёт одобрен.", "success")
    elif action == "reject":
        report.status = "Rejected"
        flash("Отчёт отклонён.", "warning")
    
    report.reviewed_by_id = session["user_id"]
    report.review_date = datetime.utcnow()
    report.comment = comment if comment else None
    db.session.commit()
    return redirect(url_for("reports_list"))


@app.route("/admin/add", methods=["GET", "POST"])
@admin_required(min_level=7)
def admin_add():
    if request.method == "POST":
        discord_id = request.form.get("discord_id")
        admin_level = int(request.form.get("admin_level", 0))
        username = request.form.get("username") or f"discord_user_{discord_id}"
        
        # Сбор данных соц. сетей
        discord_link = request.form.get("discord_link")
        telegram_link = request.form.get("telegram_link")
        vk_link = request.form.get("vk_link")
        
        # Сбор остальных данных
        position = request.form.get("position")
        prefix = request.form.get("prefix")
        reason_appointed = request.form.get("reason_appointed")

        if not discord_id:
            flash("Discord ID обязателен для заполнения.", "danger")
            return render_template("admin_add.html")

        user = User.query.filter_by(discord_id=discord_id).first()
        if not user:
            user = User(
                discord_id=discord_id,
                username=username,
                discriminator="0",
                avatar=None,
                admin_level=admin_level
            )
            db.session.add(user)
            db.session.flush() 
        else:
            user.username = username
            user.admin_level = admin_level

        profile = AdminProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            profile = AdminProfile(
                user_id=user.id,
                position=position,
                prefix=prefix,
                reason_appointed=reason_appointed,
                discord_link=discord_link,    # Сохраняем Discord
                telegram_link=telegram_link,  # Сохраняем TG
                vk_link=vk_link,              # Сохраняем VK
                date_appointed=datetime.utcnow() 
            )
            db.session.add(profile)
        else:
            profile.position = position
            profile.prefix = prefix
            profile.reason_appointed = reason_appointed
            profile.discord_link = discord_link   # Обновляем ссылки
            profile.telegram_link = telegram_link
            profile.vk_link = vk_link

        db.session.commit()

        log = LogEntry(
            actor_id=session["user_id"],
            target_user_id=user.id,
            action=f"Назначение: Уровень {admin_level}, Должность: {position}"
        )
        db.session.add(log)
        db.session.commit()

        flash(f"Пользователь {username} успешно настроен.", "success")
        return redirect(url_for("admin_profile", user_id=user.id))

    return render_template("admin_add.html")

@app.route("/admin/delete/<int:user_id>", methods=["POST"])
@admin_required(min_level=9)
def delete_admin(user_id):
    my_level = session.get("admin_level", 0)
    target_user = User.query.get_or_404(user_id)
    target_level = target_user.admin_level or 0

    # Проверка: нельзя удалить себя
    if user_id == session.get("user_id"):
        flash("Вы не можете удалить свой собственный аккаунт!", "danger")
        return redirect(url_for("admin_profile", user_id=user_id))

    # Проверка: нельзя удалить того, кто выше или равен
    if my_level <= target_level:
        flash("У вас недостаточно прав, чтобы удалить администратора с этим рангом.", "danger")
        return redirect(url_for("admin_profile", user_id=user_id))

    username_before_delete = target_user.username

    try:
        # 1. Очистка зависимых данных
        LogEntry.query.filter_by(target_user_id=user_id).delete()
        InactiveRequest.query.filter_by(user_id=user_id).delete()
        MeetingSkipRequest.query.filter_by(user_id=user_id).delete()
        FormSubmission.query.filter_by(user_id=user_id).delete()

        # 2. Удаление профиля
        profile = AdminProfile.query.filter_by(user_id=user_id).first()
        if profile:
            db.session.delete(profile)
        
        # 3. Лог об удалении (без привязки к target_user_id)
        new_log = LogEntry(
            actor_id=session["user_id"],
            target_user_id=None,
            action=f"ПОЛНОЕ УДАЛЕНИЕ: {username_before_delete} (ID: {user_id})"
        )
        db.session.add(new_log)
        
        # 4. Удаление самого пользователя
        db.session.delete(target_user)
        
        db.session.commit()
        flash(f"Администратор {username_before_delete} успешно стерт из системы.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка удаления: {e}")
        flash(f"Ошибка при удалении: {str(e)}", "danger")
    
    return redirect(url_for("admin_list"))

# Ensure system admin exists on startup
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Ensure tables are created when running directly
        SYSTEM_ADMIN_DISCORD_ID = '1470790152766095414'
        sys_admin = User.query.filter_by(discord_id=SYSTEM_ADMIN_DISCORD_ID).first()
        if not sys_admin:
            sys_admin = User(
                discord_id=SYSTEM_ADMIN_DISCORD_ID,
                username='system_admin',
                discriminator='0',
                avatar=None,
                admin_level=10
            )
            db.session.add(sys_admin)
            db.session.commit()
        # Ensure admin profile exists
        if not AdminProfile.query.filter_by(user_id=sys_admin.id).first():
            profile = AdminProfile(user_id=sys_admin.id)
            db.session.add(profile)
            db.session.commit()
    app.run(debug=True)
