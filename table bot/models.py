from database import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    discord_id = db.Column(db.String(80), unique=True, nullable=False)
    username = db.Column(db.String(100), nullable=False)
    discriminator = db.Column(db.String(4), nullable=True)
    avatar = db.Column(db.String(100), nullable=True)
    roles = db.Column(db.String(200), nullable=True) 
    admin_level = db.Column(db.Integer, default=0)

    admin_profile = db.relationship("AdminProfile", backref="user", uselist=False)
    
    # Явно указываем, что эти связи относятся к полю user_id в дочерних таблицах
    inactive_requests = db.relationship("InactiveRequest", 
                                        foreign_keys="InactiveRequest.user_id", 
                                        backref="user", lazy=True)
    
    meeting_skip_requests = db.relationship("MeetingSkipRequest", 
                                            foreign_keys="MeetingSkipRequest.user_id", 
                                            backref="user", lazy=True)
    
    forms = db.relationship("FormSubmission", 
                            foreign_keys="FormSubmission.user_id", 
                            backref="user", lazy=True)
    
    # Логи уже были настроены верно, оставляем
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

    def __repr__(self):
        return f"<AdminProfile of User {self.user.username}>"

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

    # Вторая связь с таблицей User (для того, кто обработал)
    processor = db.relationship("User", foreign_keys=[processed_by_id])

    def __repr__(self):
        return f"<InactiveRequest {self.id} by {self.user.username}>"

class MeetingSkipRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    processed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    processed_date = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    processor = db.relationship("User", foreign_keys=[processed_by_id])

    def __repr__(self):
        return f"<MeetingSkipRequest {self.id} by {self.user.username}>"

class FormSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="Pending") 
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    accepted_date = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    accepter = db.relationship("User", foreign_keys=[accepted_by_id])

    def __repr__(self):
        return f"<FormSubmission {self.id} by {self.user.username}>"

class LogEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) 
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False) 
    action = db.Column(db.String(255), nullable=False) 
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<LogEntry {self.id} by {self.actor.username} on {self.target_user.username}>"