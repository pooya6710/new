# این فایل برای رفع مشکل دور circular import بین main.py و models.py ایجاد شده است
import os
import time
import logging
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Initialize logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   level=logging.DEBUG)
logger = logging.getLogger(__name__)

# تنظیم لاگر برای رویدادهای امنیتی
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)

# اضافه کردن handler برای نوشتن لاگ‌های امنیتی در فایل جداگانه
try:
    # ایجاد دایرکتوری logs اگر وجود نداشته باشد
    os.makedirs('logs', exist_ok=True)
    
    # تنظیم handler فایل برای لاگ‌های امنیتی
    security_handler = logging.FileHandler('logs/security.log')
    security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    security_logger.addHandler(security_handler)
except Exception as e:
    logger.error(f"خطا در راه‌اندازی لاگر امنیتی: {e}")
    # اگر نتوانستیم فایل لاگ را بسازیم، از لاگر اصلی استفاده می‌کنیم
    security_logger = logger

# Create base class for SQLAlchemy models
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy
db = SQLAlchemy(model_class=Base)

# Create Flask app
app = Flask(__name__)

# تنظیمات امنیتی کلید جلسه - استفاده از کلید تصادفی طولانی و پیچیده
secret_key = os.environ.get("SESSION_SECRET")
if not secret_key or secret_key == "default_secret_key":
    import secrets
    secret_key = secrets.token_hex(32)  # 256 بیت کلید تصادفی
    logger.warning('از کلید امنیتی پیش‌فرض استفاده می‌شود. برای محیط تولید، متغیر محیطی SESSION_SECRET را تنظیم کنید.')

app.secret_key = secret_key

# تنظیمات امنیتی کوکی‌ها
app.config["SESSION_COOKIE_SECURE"] = True  # فقط در HTTPS ارسال شود
app.config["SESSION_COOKIE_HTTPONLY"] = True  # غیرقابل دسترس با JavaScript
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # محافظت در برابر حملات CSRF
app.config["PERMANENT_SESSION_LIFETIME"] = 3600  # منقضی شدن جلسه بعد از 1 ساعت

# تنظیمات Content Security Policy (CSP)
app.config["CSP"] = {
    'default-src': "'self'",
    'script-src': "'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net",
    'style-src': "'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.replit.com https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/",
    'font-src': "'self' https://cdn.jsdelivr.net https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/",
    'img-src': "'self' data:",
    'connect-src': "'self'"
}

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configure database
# تنظیم آدرس دیتابیس پوستگرس برای محیط تولید
database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    # تبدیل آدرس postgres:// به postgresql:// برای سازگاری با SQLAlchemy 1.4+
    database_url = database_url.replace("postgres://", "postgresql://", 1)
elif not database_url:
    # استفاده از دیتابیس SQLite به صورت پیش‌فرض در صورت عدم وجود DATABASE_URL
    database_url = "sqlite:///university_food.db"
    
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Initialize database with app
db.init_app(app)

# Initialize Flask-Migrate for database migrations
migrate = Migrate(app, db)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'لطفاً برای دسترسی به این صفحه وارد سیستم شوید.'

# تنظیم پوشه آپلود برای گزارشات و فایل‌ها
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'reports')

# تعریف میدلور امنیتی برای افزودن هدرهای HTTP امنیتی
@app.after_request
def add_security_headers(response):
    # غیرفعال کردن MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # جلوگیری از قرار گرفتن در iframe در سایت‌های دیگر (محافظت در برابر Clickjacking)
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    
    # محافظت در برابر حملات XSS
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # تنظیم سیاست امنیتی محتوا (CSP)
    if app.config.get('CSP'):
        csp = ''
        for directive, sources in app.config['CSP'].items():
            csp += f"{directive} {sources}; "
        response.headers['Content-Security-Policy'] = csp
    
    # مدیریت اطلاعات ارجاع‌دهنده (Referrer)
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    return response

# میدلور محدودیت نرخ درخواست (Rate Limiting)
@app.before_request
def rate_limit():
    if request.method == "OPTIONS":
        # برای درخواست‌های CORS رعایت می‌کنیم
        return None
    
    # دریافت آدرس IP کلاینت با پشتیبانی از هدرهای پراکسی
    client_ip = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For') or request.remote_addr
    if ',' in client_ip:  # اگر چندین IP در X-Forwarded-For وجود داشته باشد
        client_ip = client_ip.split(',')[0].strip()
        
    current_time = time.time()
    path = request.path
    
    # بررسی اینکه مسیر حساس است یا خیر - افزایش مسیرهای حساس
    sensitive_paths = [
        '/admin', '/api/', '/login', '/register', '/logout', '/settings', 
        '/admin_', '/dashboard', '/menu', '/reserve', '/cancel_', '/password_reset'
    ]
    is_sensitive_path = any(p in path for p in sensitive_paths)
    
    # محدودیت شدیدتر برای صفحات مدیریتی
    is_admin_path = '/admin' in path
    
    # انتخاب محدودیت مناسب بر اساس نوع مسیر
    if is_admin_path:
        limit = 30  # محدودیت ویژه برای مسیرهای مدیریتی
    elif is_sensitive_path:
        limit = api_rate_limit_count  # محدودیت برای API‌ها و مسیرهای حساس
    else:
        limit = rate_limit_count  # محدودیت عمومی
    
    # بررسی رکوردهای منقضی شده و پاکسازی آنها
    for ip in list(rate_limits.keys()):
        if current_time - rate_limits[ip]['timestamp'] > rate_limit_reset:
            # نرخ محدودیت برای این IP ریست شده است
            del rate_limits[ip]
    
    # ایجاد یا به‌روزرسانی رکورد برای IP کاربر
    if client_ip not in rate_limits:
        rate_limits[client_ip] = {
            'count': 1,
            'timestamp': current_time
        }
    else:
        # اگر پنجره زمانی منقضی نشده، افزایش شمارشگر
        if current_time - rate_limits[client_ip]['timestamp'] < rate_limit_reset:
            rate_limits[client_ip]['count'] += 1
        else:
            # شروع شمارش جدید با زمان جدید
            rate_limits[client_ip] = {
                'count': 1,
                'timestamp': current_time
            }
    
    # بررسی رسیدن به محدودیت
    if rate_limits[client_ip]['count'] > limit:
        # ثبت وقوع محدودیت
        security_logger.warning(f"RATE LIMIT EXCEEDED: IP: {client_ip}, Path: {path}, Count: {rate_limits[client_ip]['count']}")
        
        # ایجاد پاسخ خطا
        remaining_time = int(rate_limit_reset - (current_time - rate_limits[client_ip]['timestamp']))
        response = jsonify({
            'error': 'تعداد درخواست‌های شما از حد مجاز بیشتر شده است. لطفاً بعداً تلاش کنید.',
            'retryAfter': remaining_time
        })
        response.status_code = 429  # Too Many Requests
        response.headers['Retry-After'] = str(remaining_time)
        return response
    
    return None

# میدلور برای ثبت درخواست‌های مشکوک و خطیر
@app.before_request
def log_suspicious_requests():
    # لیست مسیرهای حساس که باید همیشه ثبت شوند
    sensitive_paths = [
        '/admin', '/api/', '/logout', '/settings', '/admin_', 
        '/login', '/register', '/dashboard', '/menu', '/reserve',
        '/password_reset', '/cancel_', '/student_'
    ]
    
    # لیست پسوندهای مشکوک که ممکن است نشاندهنده حمله باشند
    suspicious_extensions = ['.php', '.asp', '.aspx', '.jsp', '.cgi', '.env', '.git', '.sql']
    
    # لیست عبارات خطرناک در URL یا پارامترها
    dangerous_patterns = [
        '../..', 'SELECT ', 'UNION ', 'INSERT ', 'script', '<script', 'eval(', 'onload=', 'javascript:', 'alert(', 'document.cookie', 'exec(',
        'OR 1=1', ' OR ', "'OR'", '" OR "', '--', ';--', ';', '/*', '*/', 'DROP ', 'DELETE ', 'UPDATE ', 'xp_', 'SLEEP(', 'WAITFOR DELAY'
    ]
    
    # دریافت اطلاعات درخواست
    path = request.path
    method = request.method
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')
    referrer = request.referrer or 'None'
    request_data = {}
    
    # بررسی قرار گرفتن در مسیرهای حساس
    is_sensitive = any(sensitive_path in path for sensitive_path in sensitive_paths)
    
    # بررسی پسوندهای مشکوک
    has_suspicious_ext = any(path.endswith(ext) for ext in suspicious_extensions)
    
    # بررسی الگوهای خطرناک در URL
    has_dangerous_pattern = any(pattern in path.lower() for pattern in dangerous_patterns)
    
    # بررسی پارامترهای GET
    if request.args:
        request_data['query_params'] = dict(request.args)
        # بررسی الگوهای خطرناک در پارامترهای GET
        has_dangerous_query = any(
            any(pattern in str(v).lower() for pattern in dangerous_patterns)
            for v in request.args.values()
        )
    else:
        has_dangerous_query = False
    
    # بررسی روش‌های POST, PUT, DELETE و سایر روش‌های غیر GET
    is_non_get = method != 'GET'
    
    # ثبت درخواست‌های مشکوک یا حساس
    if is_sensitive or has_suspicious_ext or has_dangerous_pattern or has_dangerous_query:
        # تعیین سطح لاگ
        if has_dangerous_pattern or has_suspicious_ext or has_dangerous_query:
            log_level = 'warning'
            message = f"SUSPICIOUS REQUEST: {method} {path}"
        else:
            log_level = 'info'
            message = f"SENSITIVE REQUEST: {method} {path}"
        
        # اضافه کردن اطلاعات بیشتر
        message += f" | IP: {client_ip} | Referrer: {referrer} | User-Agent: {user_agent}"
        
        # ثبت لاگ بر اساس سطح
        if log_level == 'warning':
            security_logger.warning(message)
        else:
            security_logger.info(message)
    
    # لاگ رویدادهای POST, PUT, DELETE برای تغییرات در سیستم
    elif is_non_get:
        security_logger.info(f"MODIFY REQUEST: {method} {path} | IP: {client_ip}")
    
    return None  # اجازه ادامه فرآیند درخواست

# تنظیمات کوکی‌های جلسه
# در حالت توسعه (development) تنظیمات امنیتی را به صورت موقت غیرفعال می‌کنیم
# فقط برای محیط توسعه - در محیط تولید این تنظیمات باید فعال باشند
app.config["SESSION_COOKIE_SECURE"] = False  # در محیط تولید به True تغییر دهید

# قفل کردن حساب بعد از تعداد مشخصی تلاش ناموفق
# دیکشنری برای نگهداری تعداد تلاش‌های ناموفق لاگین
login_attempts = {}
max_login_attempts = 5
login_timeout = 900  # در ثانیه (15 دقیقه)

# تنظیمات محدودیت نرخ درخواست‌ها (Rate Limiting)
# ذخیره تعداد درخواست‌ها برای هر IP
rate_limits = {}
# حداکثر تعداد درخواست در پنجره زمانی مشخص
rate_limit_count = 100  # تعداد درخواست مجاز در پنجره زمانی
rate_limit_reset = 60  # در ثانیه (1 دقیقه)
# محدودیت شدیدتر برای مسیرهای حساس
api_rate_limit_count = 30  # تعداد درخواست مجاز برای مسیرهای حساس در پنجره زمانی