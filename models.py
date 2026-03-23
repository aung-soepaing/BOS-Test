from extensions import db


class Survey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vessel_name = db.Column(db.String(100))
    date = db.Column(db.Date)
    responses = db.Column(db.JSON)


class Metric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    value = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=db.func.now())


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.String(50))
    message = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=db.func.now())


class DeviceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100))
    vessel_name = db.Column(db.String(100))
    device_name = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=db.func.now())


class User2(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)


class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
