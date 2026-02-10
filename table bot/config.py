import os

class Config:
    # 2. ВАЖНО: Используйте постоянную строку, чтобы сессия не "умирала" при перезапуске сервера
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

    # 3. НАСТРОЙКИ COOKIE ДЛЯ DEV TUNNELS (чтобы не было ошибки 400)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = 'None'
    SESSION_COOKIE_NAME = 'discord_session'

