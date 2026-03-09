from database import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(80), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=False)
    discriminator = db.Column(db.String(4), nullable=True)
    avatar = db.Column(db.String(100), nullable=True)
    admin_level = db.Column(db.Integer, default=0)

    admin_profile = db.relationship("AdminProfile", backref="user", uselist=False)
    
    # Связи для логов
    log_entries_actor = db.relationship("LogEntry", foreign_keys="LogEntry.actor_id", backref="actor", lazy=True)
    log_entries_target = db.relationship("LogEntry", foreign_keys="LogEntry.target_user_id", backref="target_user", lazy=True)

    def __repr__(self):
        return f"<User {self.username}#{self.discriminator}>"

class AdminProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    date_appointed = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_promotion = db.Column(db.DateTime, nullable=True)
    reason_appointed = db.Column(db.Text, nullable=True)
    points = db.Column(db.Integer, default=0)
    reprimands = db.Column(db.Integer, default=0)
    warnings = db.Column(db.Integer, default=0)
    position = db.Column(db.String(100), nullable=True)
    prefix = db.Column(db.String(50), nullable=True)
    discord_link = db.Column(db.String(100), nullable=True)
    telegram_link = db.Column(db.String(100), nullable=True)
    vk_link = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<AdminProfile of User {self.user.username}>"

class ShopItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    min_level = db.Column(db.Integer, default=1)  # С какого уровня админки
    purchase_limit = db.Column(db.Integer, default=0) # 0 - безлимит, >0 - лимит шт.

class InactiveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    processed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    processed_date = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # ИСПРАВЛЕНО: Добавлена связь с автором заявки
    user = db.relationship("User", foreign_keys=[user_id], backref="inactive_requests")
    # Вторая связь (кто обработал)
    processor = db.relationship("User", foreign_keys=[processed_by_id])

    def __repr__(self):
        return f"<InactiveRequest {self.id} by {self.user.username if self.user else 'Unknown'}>"

class MeetingSkipRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    processed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    processed_date = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # ИСПРАВЛЕНО: Добавлена связь с автором заявки
    user = db.relationship("User", foreign_keys=[user_id], backref="meeting_skips")
    processor = db.relationship("User", foreign_keys=[processed_by_id])

    def __repr__(self):
        return f"<MeetingSkipRequest {self.id} by {self.user.username if self.user else 'Unknown'}>"

class FormSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    accepted_date = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Оставляем вашу добавленную строку
    user = db.relationship("User", foreign_keys=[user_id], backref="submissions")
    accepter = db.relationship("User", foreign_keys=[accepted_by_id])

    def __repr__(self):
        return f"<FormSubmission {self.id} by {self.user.username if self.user else 'Unknown'}>"

class ReportSubmission(db.Model):
    """Отчёты о проделанной работе"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending")  # Pending, Approved, Rejected
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    review_date = db.Column(db.DateTime, nullable=True)
    comment = db.Column(db.Text, nullable=True)  # Комментарий при рассмотрении
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], backref="reports")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_id])

    def __repr__(self):
        return f"<ReportSubmission {self.id} by {self.user.username if self.user else 'Unknown'}>"

class LogEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) 
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True) 
    action = db.Column(db.String(255), nullable=False) 
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('shop_item.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f"<LogEntry {self.id} by {self.actor.username if self.actor else 'Unknown'}>"