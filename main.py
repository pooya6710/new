import datetime
import os
import time
import jdatetime
from collections import OrderedDict
from flask import request, jsonify, render_template, redirect, url_for, flash, session, send_file
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

from app import app, db, login_manager, logger, security_logger, login_attempts, max_login_attempts, login_timeout
from zarinpal import ZarinPal
from utils import generate_inventory_report_pdf, generate_transaction_report_pdf, generate_food_usage_forecast_pdf

# حذف درگاه پرداخت زرین‌پال به درخواست کاربر
# zarinpal_gateway = ZarinPal(sandbox=True)  # استفاده از محیط تست

# Create all database tables
with app.app_context():
    # Import models to register them with SQLAlchemy
    from models import Student, Reservation, Menu, DatabaseBackup, User, Payment, InventoryItem, InventoryTransaction, FoodInventoryUsage
    db.create_all()
    
    # بارگذاری منوی پیش‌فرض (اگر وجود نداشته باشد)
    from models import load_default_menu
    load_default_menu(db.session)
    
# تابع تبدیل تاریخ میلادی به شمسی
def gregorian_to_jalali(date_obj):
    """تبدیل تاریخ میلادی به شمسی"""
    if date_obj is None:
        return None
    return jdatetime.date.fromgregorian(date=date_obj.date())

# تابع تبدیل تاریخ و زمان میلادی به شمسی
def gregorian_to_jalali_datetime(datetime_obj):
    """تبدیل تاریخ و زمان میلادی به شمسی با تنظیم ساعت به وقت ایران"""
    if datetime_obj is None:
        return None
    # اضافه کردن 3.5 ساعت (210 دقیقه) به زمان UTC برای تبدیل به وقت ایران
    iran_time = datetime_obj + datetime.timedelta(minutes=210)
    return jdatetime.datetime.fromgregorian(datetime=iran_time)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# تزیین‌کننده برای دسترسی انباردار
def warehouse_manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_warehouse_manager or current_user.is_admin):
            flash('شما دسترسی لازم برای ورود به این بخش را ندارید', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    # آمار واقعی برای صفحه اصلی
    now = datetime.datetime.now()
    
    # تعداد کل دانشجویان
    student_count = Student.query.count()
    
    # تعداد کل رزروها
    reservation_count = Reservation.query.count()
    
    # تعداد رزروهای تحویل شده
    delivered_count = Reservation.query.filter_by(delivered=1).count()
    
    # تعداد روزهای منو
    menu_days_count = Menu.query.count()
    
    # آمار وعده‌های غذایی
    breakfast_count = Reservation.query.filter_by(meal='breakfast').count()
    lunch_count = Reservation.query.filter_by(meal='lunch').count()
    dinner_count = Reservation.query.filter_by(meal='dinner').count()
    
    # آمار غذاهای محبوب
    popular_foods = db.session.query(
        Reservation.food_name, 
        db.func.count(Reservation.id).label('count')
    ).group_by(Reservation.food_name).order_by(db.func.count(Reservation.id).desc()).limit(3).all()
    
    return render_template('index.html', 
                           now=now,
                           student_count=student_count,
                           reservation_count=reservation_count,
                           delivered_count=delivered_count,
                           menu_days_count=menu_days_count,
                           breakfast_count=breakfast_count,
                           lunch_count=lunch_count,
                           dinner_count=dinner_count,
                           popular_foods=popular_foods)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        feeding_code = request.form.get('username')  # نام فیلد در فرم هنوز username است
        password = request.form.get('password')
        
        # بررسی قفل حساب کاربری
        client_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'Unknown')
        current_time = time.time()
        
        # لاگ تلاش ورود
        security_logger.info(f"Login attempt from IP: {client_ip}, Feeding Code: {feeding_code}, User-Agent: {user_agent}")
        
        # پاک کردن رکوردهای منقضی شده تلاش‌های ناموفق
        for ip in list(login_attempts.keys()):
            if current_time - login_attempts[ip]['timestamp'] > login_timeout:
                security_logger.info(f"Removing expired login attempts record for IP: {ip}")
                del login_attempts[ip]
        
        # بررسی وضعیت قفل حساب برای آدرس IP فعلی
        if client_ip in login_attempts and login_attempts[client_ip]['attempts'] >= max_login_attempts:
            # بررسی زمان قفل
            time_passed = current_time - login_attempts[client_ip]['timestamp']
            if time_passed < login_timeout:
                remaining_time = int((login_timeout - time_passed) / 60)
                security_logger.warning(f"Blocked login attempt from IP: {client_ip} - Account is locked. Attempts: {login_attempts[client_ip]['attempts']}")
                flash(f'حساب کاربری شما به دلیل تلاش‌های ناموفق قفل شده است. لطفاً {remaining_time} دقیقه دیگر امتحان کنید.', 'danger')
                return render_template('login.html')
            else:
                # زمان قفل به پایان رسیده است
                security_logger.info(f"Unlocking account for IP: {client_ip} - Lock timeout expired")
                del login_attempts[client_ip]
        
        user = User.query.filter_by(username=feeding_code).first()
        
        if user and check_password_hash(user.password, password):
            # ورود موفق - پاک کردن سابقه تلاش‌های ناموفق
            if client_ip in login_attempts:
                del login_attempts[client_ip]
                
            # ثبت ورود موفق در لاگ
            security_logger.info(f"Successful login for Feeding Code: {feeding_code} from IP: {client_ip}")
            
            login_user(user)
            flash('با موفقیت وارد شدید', 'success')
            return redirect(url_for('dashboard'))
        else:
            # ورود ناموفق - افزایش شمارنده تلاش‌های ناموفق
            if client_ip not in login_attempts:
                login_attempts[client_ip] = {'attempts': 1, 'timestamp': current_time}
                security_logger.warning(f"Failed login attempt for Feeding Code: {feeding_code} from IP: {client_ip} (Attempt 1/{max_login_attempts})")
            else:
                login_attempts[client_ip]['attempts'] += 1
                login_attempts[client_ip]['timestamp'] = current_time
                security_logger.warning(f"Failed login attempt for Feeding Code: {feeding_code} from IP: {client_ip} (Attempt {login_attempts[client_ip]['attempts']}/{max_login_attempts})")
            
            # اعلان تعداد تلاش‌های باقی‌مانده
            remaining_attempts = max_login_attempts - login_attempts[client_ip]['attempts']
            if remaining_attempts > 0:
                flash(f'کد تغذیه یا رمز عبور اشتباه است. {remaining_attempts} تلاش دیگر باقی مانده است.', 'danger')
            else:
                security_logger.warning(f"Account locked for IP: {client_ip} due to too many failed login attempts ({max_login_attempts})")
                flash(f'حساب کاربری شما به مدت {int(login_timeout/60)} دقیقه قفل شده است.', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        feeding_code = request.form.get('feeding_code')
        
        # بررسی تطابق رمز عبور
        if password != confirm_password:
            flash('رمز عبور و تکرار آن مطابقت ندارند', 'danger')
            return render_template('register.html')
        
        # بررسی اینکه کد تغذیه قبلاً ثبت نشده باشد
        existing_student = Student.query.filter_by(feeding_code=feeding_code).first()
        if existing_student:
            flash('این کد تغذیه قبلاً ثبت شده است', 'danger')
            return render_template('register.html')
        
        # بررسی اینکه کاربری با این نام کاربری قبلاً ثبت نشده باشد
        existing_user = User.query.filter_by(username=feeding_code).first()
        if existing_user:
            flash('کاربری با این کد تغذیه قبلاً ثبت شده است', 'danger')
            return render_template('register.html')
        
        # ایجاد کاربر جدید - از کد تغذیه به عنوان نام کاربری استفاده می‌کنیم
        new_user = User(username=feeding_code, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.flush()  # برای دریافت ID کاربر
        
        # ایجاد دانشجو
        new_student = Student(user_id=str(new_user.id), feeding_code=feeding_code)
        db.session.add(new_student)
        db.session.commit()
        
        # ثبت لاگ ایجاد حساب جدید
        client_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'Unknown')
        security_logger.info(f"New user registered: User ID: {new_user.id}, Feeding Code: {feeding_code}, IP: {client_ip}, User-Agent: {user_agent}")
        
        flash('ثبت نام شما با موفقیت انجام شد. اکنون می‌توانید وارد سیستم شوید', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    # ثبت لاگ خروج از سیستم
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')
    try:
        user_id = current_user.id
        username = current_user.username
        security_logger.info(f"User logged out: User ID: {user_id}, Username: {username}, IP: {client_ip}, User-Agent: {user_agent}")
    except Exception as e:
        security_logger.warning(f"Error logging logout: {str(e)}")
    
    logout_user()
    flash('با موفقیت خارج شدید', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # بررسی نقش کاربر و هدایت به داشبورد مناسب
    if current_user.is_admin:
        # کاربر مدیر است، به صفحه مدیریت منتقل می‌شود
        return redirect(url_for('admin'))
    
    if current_user.is_warehouse_manager:
        # کاربر انباردار است، به صفحه مدیریت انبار منتقل می‌شود
        return redirect(url_for('warehouse_dashboard'))
    
    # به‌روزرسانی آمار مالی و بدهی‌ها
    update_financial_statistics()
    
    # بررسی و به‌روزرسانی خودکار هفته‌ها
    update_week_schedule()
    
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('index'))
    
    # دریافت رزروهای دانشجو
    reservations = Reservation.query.filter_by(student_id=student.id).all()
    
    # محاسبه تعداد غذاهای تحویل شده
    delivered_count = Reservation.query.filter_by(student_id=student.id, delivered=1).count()
    
    # تبدیل تاریخ‌ها به شمسی
    jalali_dates = {}
    
    for reservation in reservations:
        jalali_dates[reservation.id] = gregorian_to_jalali_datetime(reservation.timestamp).strftime('%Y/%m/%d %H:%M:%S')
    
    # تاریخ فعلی به شمسی
    now_jalali = gregorian_to_jalali_datetime(datetime.datetime.now()).strftime('%Y/%m/%d')
    
    return render_template('dashboard.html', 
                           student=student, 
                           reservations=reservations, 
                           jalali_dates=jalali_dates,
                           now_jalali=now_jalali,
                           delivered_count=delivered_count)

# تابع به‌روزرسانی خودکار هفته‌ها
def update_week_schedule():
    """
    بررسی تاریخ فعلی و به‌روزرسانی خودکار هفته‌ها
    اگر هفته جاری به پایان رسیده باشد، هفته آینده به هفته جاری تبدیل شده
    و یک هفته آینده جدید ایجاد می‌شود.
    """
    try:
        # دریافت منوی هفتگی با اطمینان از تازه بودن داده‌ها
        db.session.expire_all()
        weekly_menu = Menu.query.all()
        
        if not weekly_menu or len(weekly_menu) == 0:
            print("⚠️ هیچ منویی در سیستم یافت نشد - ایجاد منوی پیش‌فرض...")
            # ایجاد منوی پیش‌فرض برای هفته جاری و آینده
            create_default_menu_structure()
            weekly_menu = Menu.query.all()
            if not weekly_menu or len(weekly_menu) == 0:
                return
        
        # تاریخ امروز
        today = datetime.datetime.now()
        current_jalali_date = jdatetime.date.fromgregorian(date=today.date())
        
        # محاسبه شنبه این هفته (روز اول هفته)
        # در تقویم شمسی، شنبه روز اول هفته (۰) است
        current_weekday = current_jalali_date.weekday()
        days_to_saturday = current_weekday  # تعداد روزهایی که باید به عقب برگردیم تا به شنبه برسیم
        
        # محاسبه شنبه این هفته
        saturday_date = current_jalali_date - jdatetime.timedelta(days=days_to_saturday)
        
        # محاسبه شنبه هفته آینده
        next_saturday_date = saturday_date + jdatetime.timedelta(days=7)
        
        # محاسبه پنجشنبه هفته جاری (آخرین روز کاری هفته)
        thursday_date = saturday_date + jdatetime.timedelta(days=5)
        
        # محاسبه جمعه هفته جاری
        friday_date = saturday_date + jdatetime.timedelta(days=6)
        
        # بررسی اینکه آیا روز پنجشنبه یا جمعه است (روزهای نزدیک به پایان هفته)
        is_end_of_week = current_jalali_date >= thursday_date
        
        # اگر امروز جمعه هفته جاری یا بعد از آن است، باید هفته‌ها به‌روزرسانی شوند
        if current_jalali_date >= friday_date:
            print(f"✓ به‌روزرسانی خودکار هفته‌ها - تاریخ فعلی: {current_jalali_date}")
            print(f"✓ هفته جاری به پایان رسیده (جمعه: {friday_date})")
            print(f"✓ هفته آینده ({next_saturday_date}) به هفته جاری تبدیل می‌شود")
            
            # اطمینان از وجود منوی هفته آینده
            ensure_next_week_menus_exist()
            
            try:
                # جلوگیری از تکرار به‌روزرسانی هفته با بررسی وجود لاگ زمان آخرین به‌روزرسانی
                last_update_log = os.path.join('logs', 'last_week_update.log')
                should_update = True
                
                # بررسی زمان آخرین به‌روزرسانی
                try:
                    if os.path.exists(last_update_log):
                        with open(last_update_log, 'r') as f:
                            last_update_text = f.read().strip()
                            if last_update_text:
                                last_update_date = jdatetime.datetime.strptime(last_update_text, '%Y-%m-%d')
                                # اگر در هفته جاری قبلاً به‌روزرسانی انجام شده، دوباره انجام نمی‌شود
                                if last_update_date.date() >= saturday_date:
                                    should_update = False
                                    print(f"⚠️ قبلاً در این هفته به‌روزرسانی انجام شده است ({last_update_text})")
                except Exception as log_error:
                    print(f"⚠️ خطا در خواندن لاگ به‌روزرسانی: {str(log_error)}")
                
                if should_update:
                    # دریافت منوی هفته آینده
                    next_week_menus = []
                    for menu_item in Menu.query.filter(Menu.day.like("%_next")).all():
                        next_week_menus.append(menu_item)
                    
                    if not next_week_menus:
                        print("⚠️ هیچ منوی هفته آینده‌ای یافت نشد - ایجاد منوی پیش‌فرض برای هفته آینده...")
                        # ایجاد منوی پیش‌فرض برای هفته آینده
                        ensure_next_week_menus_exist()
                        next_week_menus = Menu.query.filter(Menu.day.like("%_next")).all()
                    
                    # ذخیره منوی هفته آینده برای کپی کردن به هفته جاری
                    next_week_menu = {}
                    for menu_item in next_week_menus:
                        # استخراج روز بدون پسوند "_next"
                        day = menu_item.day.replace("_next", "")
                        # ذخیره داده‌های منو
                        next_week_menu[day] = menu_item.meal_data
                        # حذف منوی هفته آینده فعلی
                        db.session.delete(menu_item)
                    
                    # به‌روزرسانی منوی هفته جاری با منوی هفته آینده
                    current_week_days = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
                    for day in current_week_days:
                        day_menu = Menu.query.filter_by(day=day).first()
                        if day_menu and day in next_week_menu:
                            day_menu.meal_data = next_week_menu[day]
                            db.session.add(day_menu)
                        elif day in next_week_menu:  # اگر منوی روز در هفته جاری وجود ندارد اما در هفته آینده وجود دارد
                            # ایجاد منوی جدید برای این روز در هفته جاری
                            new_current_menu = Menu(
                                day=day,
                                meal_data=next_week_menu[day]
                            )
                            db.session.add(new_current_menu)
                    
                    # اطمینان از اینکه تمام منوهای هفته جاری وجود دارند
                    for day in current_week_days:
                        day_menu = Menu.query.filter_by(day=day).first()
                        if not day_menu:
                            # ایجاد منوی خالی برای این روز
                            empty_menu = {
                                "breakfast": [],
                                "lunch": [],
                                "dinner": []
                            }
                            new_menu = Menu(
                                day=day,
                                meal_data=empty_menu
                            )
                            db.session.add(new_menu)
                            print(f"✓ منوی خالی برای روز {day} در هفته جاری ایجاد شد")
                    
                    # ایجاد منوی هفته آینده جدید با کپی از منوی هفته جاری
                    for day in current_week_days:
                        # منوی روز در هفته جاری
                        day_menu = Menu.query.filter_by(day=day).first()
                        if day_menu:
                            # ایجاد یا به‌روزرسانی منوی هفته آینده
                            next_day = f"{day}_next"
                            next_day_menu = Menu(
                                day=next_day,
                                meal_data=day_menu.meal_data
                            )
                            db.session.add(next_day_menu)
                            print(f"✓ منوی هفته آینده برای روز {day} ایجاد شد")
                    
                    # ثبت زمان به‌روزرسانی
                    try:
                        os.makedirs('logs', exist_ok=True)
                        with open(last_update_log, 'w') as f:
                            f.write(current_jalali_date.strftime('%Y-%m-%d'))
                    except Exception as log_error:
                        print(f"⚠️ خطا در نوشتن لاگ به‌روزرسانی: {str(log_error)}")
                    
                    db.session.commit()
                    print("✓ به‌روزرسانی هفته‌ها با موفقیت انجام شد")
                
            except Exception as e:
                db.session.rollback()
                print(f"✗ خطا در به‌روزرسانی هفته‌ها: {str(e)}")
                import traceback
                print(f"جزئیات خطا: {traceback.format_exc()}")
        
        elif is_end_of_week:
            # اگر پنجشنبه هستیم، اطمینان حاصل کنیم که منوی هفته آینده وجود دارد
            ensure_next_week_menus_exist()
            print(f"✓ روز پنجشنبه هفته جاری است - اطمینان از وجود منوی هفته آینده")
            
    except Exception as e:
        print(f"✗ خطای کلی در تابع به‌روزرسانی هفته‌ها: {str(e)}")
        import traceback
        print(f"جزئیات خطا: {traceback.format_exc()}")


def ensure_next_week_menus_exist():
    """
    اطمینان از وجود منوهای هفته آینده
    این تابع بررسی می‌کند که آیا منوهای هفته آینده وجود دارند و در صورت نیاز آنها را ایجاد می‌کند
    """
    try:
        current_week_days = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
        next_week_days = [f"{day}_next" for day in current_week_days]
        
        # بررسی منوهای هفته آینده
        existing_next_week_menus = Menu.query.filter(Menu.day.like("%_next")).all()
        existing_next_days = [menu.day for menu in existing_next_week_menus]
        
        for day, next_day in zip(current_week_days, next_week_days):
            if next_day not in existing_next_days:
                # منوی این روز در هفته آینده وجود ندارد
                # بررسی منوی روز مشابه در هفته جاری
                current_day_menu = Menu.query.filter_by(day=day).first()
                
                if current_day_menu:
                    # کپی منو از هفته جاری
                    menu_data = current_day_menu.meal_data
                else:
                    # ایجاد منوی خالی پیش‌فرض
                    menu_data = {
                        "breakfast": [],
                        "lunch": [],
                        "dinner": []
                    }
                
                # ایجاد منوی هفته آینده
                new_next_menu = Menu(
                    day=next_day,
                    meal_data=menu_data
                )
                db.session.add(new_next_menu)
                print(f"✓ منوی هفته آینده برای روز {day} (با ID {next_day}) ایجاد شد")
        
        db.session.commit()
        print("✓ بررسی و ایجاد منوهای هفته آینده با موفقیت انجام شد")
        
    except Exception as e:
        db.session.rollback()
        print(f"✗ خطا در اطمینان از وجود منوهای هفته آینده: {str(e)}")
        import traceback
        print(f"جزئیات خطا: {traceback.format_exc()}")


def create_default_menu_structure():
    """
    ایجاد ساختار پیش‌فرض منو برای هفته جاری و آینده
    این تابع در صورتی که هیچ منویی در سیستم وجود نداشته باشد فراخوانی می‌شود
    """
    try:
        current_week_days = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
        
        # یک منوی پیش‌فرض با غذاهای نمونه
        default_menu_data = {
            "breakfast": [{"name": "نان و پنیر و چای", "price": 2000}],
            "lunch": [{"name": "چلو خورشت قیمه", "price": 3000}],
            "dinner": [{"name": "چلو کباب کوبیده", "price": 5000}]
        }
        
        # ایجاد منوی هفته جاری
        for day in current_week_days:
            menu = Menu.query.filter_by(day=day).first()
            if not menu:
                # برای هر روز یک منوی کمی متفاوت ایجاد می‌کنیم
                menu_data = default_menu_data.copy()
                
                # تنوع در غذاها بر اساس روز هفته
                if day == "saturday":
                    menu_data["lunch"] = [{"name": "زرشک پلو با مرغ", "price": 3000}]
                elif day == "sunday":
                    menu_data["dinner"] = [{"name": "چلو خورشت قورمه سبزی", "price": 5000}]
                elif day == "monday":
                    menu_data["lunch"] = [{"name": "عدس پلو با گوشت چرخ کرده", "price": 3000}]
                elif day == "tuesday":
                    menu_data["dinner"] = [{"name": "چلو جوجه کباب", "price": 5000}]
                elif day == "wednesday":
                    menu_data["lunch"] = [{"name": "چلو خورشت بادمجان", "price": 3000}]
                elif day == "thursday":
                    menu_data["lunch"] = [{"name": "ماکارونی با گوشت چرخ کرده", "price": 3000}]
                    menu_data["dinner"] = [{"name": "چلو کباب بختیاری", "price": 5000}]
                
                new_menu = Menu(
                    day=day,
                    meal_data=menu_data
                )
                db.session.add(new_menu)
                print(f"✓ منوی پیش‌فرض برای روز {day} هفته جاری ایجاد شد")
        
        # ایجاد منوی هفته آینده
        for day in current_week_days:
            next_day = f"{day}_next"
            menu = Menu.query.filter_by(day=next_day).first()
            if not menu:
                # برای هفته آینده منوی متفاوتی ایجاد می‌کنیم
                menu_data = default_menu_data.copy()
                
                # تنوع در غذاها بر اساس روز هفته
                if day == "saturday":
                    menu_data["lunch"] = [{"name": "چلو کباب کوبیده", "price": 3000}]
                elif day == "sunday":
                    menu_data["dinner"] = [{"name": "چلو خورشت فسنجان", "price": 5000}]
                elif day == "monday":
                    menu_data["lunch"] = [{"name": "لوبیا پلو با گوشت", "price": 3000}]
                elif day == "tuesday":
                    menu_data["dinner"] = [{"name": "چلو کباب بختیاری", "price": 5000}]
                elif day == "wednesday":
                    menu_data["lunch"] = [{"name": "چلو خورشت کرفس", "price": 3000}]
                elif day == "thursday":
                    menu_data["lunch"] = [{"name": "استامبولی پلو با گوشت", "price": 3000}]
                    menu_data["dinner"] = [{"name": "مرغ سوخاری با سیب زمینی", "price": 5000}]
                
                new_menu = Menu(
                    day=next_day,
                    meal_data=menu_data
                )
                db.session.add(new_menu)
                print(f"✓ منوی پیش‌فرض برای روز {day} هفته آینده ایجاد شد")
        
        db.session.commit()
        print("✓ ساختار پیش‌فرض منو با موفقیت ایجاد شد")
        
    except Exception as e:
        db.session.rollback()
        print(f"✗ خطا در ایجاد ساختار پیش‌فرض منو: {str(e)}")
        import traceback
        print(f"جزئیات خطا: {traceback.format_exc()}")

@app.route('/menu')
@login_required
def menu():
    # بررسی و به‌روزرسانی خودکار هفته‌ها
    update_week_schedule()
    
    # گرفتن پارامتر هفته از URL (اگر وجود داشته باشد)
    week_offset = request.args.get('week', '0')
    try:
        week_offset = int(week_offset)
    except ValueError:
        week_offset = 0
    
    # محدود کردن week_offset به مقادیر معقول (0 = هفته جاری، 1 = هفته آینده)
    if week_offset < 0:
        week_offset = 0
    elif week_offset > 1:
        week_offset = 1
    
    # دریافت منوی هفتگی بر اساس هفته انتخاب شده
    if week_offset == 1:  # هفته آینده
        # تمام منوهایی که در نام آنها "_next" وجود دارد
        weekly_menu = Menu.query.filter(Menu.day.like("%_next")).all()
        # اصلاح نام روزها برای نمایش بهتر (حذف پسوند "_next")
        for menu_item in weekly_menu:
            menu_item.display_day = menu_item.day.replace("_next", "")
    else:  # هفته جاری
        # تمام منوهایی که "_next" در نام آنها وجود ندارد
        weekly_menu = Menu.query.filter(~Menu.day.like("%_next")).all()
        # تنظیم نام نمایشی یکسان با نام واقعی
        for menu_item in weekly_menu:
            menu_item.display_day = menu_item.day
    
    # مرتب‌سازی منوی هفتگی بر اساس ترتیب روزهای هفته
    day_order = {"saturday": 0, "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6}
    weekly_menu.sort(key=lambda x: day_order.get(x.display_day, 7))
    
    # محاسبه تاریخ‌های شمسی هفته جاری یا آینده
    today = datetime.datetime.now()
    current_jalali_date = jdatetime.date.fromgregorian(date=today.date())
    
    # محاسبه شنبه این هفته (روز اول هفته)
    # در تقویم شمسی، شنبه روز اول هفته (۰) است
    current_weekday = current_jalali_date.weekday()
    days_to_saturday = current_weekday  # تعداد روزهایی که باید به عقب برگردیم تا به شنبه برسیم
    
    # محاسبه شنبه این هفته یا هفته آینده بر اساس پارامتر week_offset
    saturday_date = current_jalali_date - jdatetime.timedelta(days=days_to_saturday)
    if week_offset > 0:
        saturday_date = saturday_date + jdatetime.timedelta(days=7*week_offset)
    
    # ایجاد دیکشنری روزهای هفته همراه با تاریخ
    days_persian = {
        "saturday": "شنبه",
        "sunday": "یکشنبه",
        "monday": "دوشنبه",
        "tuesday": "سه‌شنبه",
        "wednesday": "چهارشنبه",
        "thursday": "پنج‌شنبه",
        "friday": "جمعه"
    }
    
    # لیست روزها به ترتیب
    day_keys = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
    
    # ایجاد دیکشنری منظم از روزهای هفته با تاریخ شمسی
    days = OrderedDict()
    for i, day_key in enumerate(day_keys):
        current_date = saturday_date + jdatetime.timedelta(days=i)
        formatted_date = f"{current_date.year}/{current_date.month}/{current_date.day}"
        days[day_key] = f"{days_persian[day_key]} ({formatted_date})"
    
    meals = {
        "breakfast": "صبحانه",
        "lunch": "ناهار",
        "dinner": "شام"
    }
    
    # ذخیره تاریخ‌های شمسی به صورت جداگانه برای استفاده در فرم‌ها
    day_dates = {}
    for i, day_key in enumerate(day_keys):
        current_date = saturday_date + jdatetime.timedelta(days=i)
        day_dates[day_key] = current_date.strftime("%Y/%m/%d")
    
    # دریافت اطلاعات دانشجو و رزروهای او
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    reservations = []
    if student:
        reservations = Reservation.query.filter_by(student_id=student.id).all()
    
    # ذخیره رزروهای دانشجو به صورت دیکشنری برای دسترسی سریع‌تر
    student_reservations = {}
    for res in reservations:
        key = f"{res.day}_{res.meal}"
        student_reservations[key] = res
    
    return render_template('menu.html', 
                           weekly_menu=weekly_menu, 
                           days=days, 
                           day_dates=day_dates, 
                           meals=meals,
                           week_offset=week_offset,
                           student_reservations=student_reservations)

@app.route('/reserve', methods=['POST'])
@login_required
def reserve():
    # گرفتن پارامتر هفته از URL (اگر وجود داشته باشد)
    week_offset = request.args.get('week', '0')
    try:
        week_offset = int(week_offset)
    except ValueError:
        week_offset = 0
    
    # محدود کردن week_offset به مقادیر معقول (0 = هفته جاری، 1 = هفته آینده)
    if week_offset < 0:
        week_offset = 0
    elif week_offset > 1:
        week_offset = 1
    
    day = request.form.get('day')
    meal = request.form.get('meal')
    food_name = request.form.get('food_name')
    food_price = request.form.get('food_price', 0)
    
    try:
        food_price = float(food_price)
    except (ValueError, TypeError):
        # تنظیم قیمت‌های ثابت بر اساس نوع وعده
        if meal == 'breakfast':
            food_price = 2000.0  # صبحانه
        elif meal == 'lunch':
            food_price = 3000.0  # ناهار
        elif meal == 'dinner':
            food_price = 5000.0  # شام
        else:
            food_price = 0.0
    
    if not all([day, meal, food_name]):
        flash('لطفاً تمام فیلدها را پر کنید', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('menu', week=week_offset))
        
    # بررسی و تطبیق نام روز با هفته انتخاب شده
    original_day = day  # نگهداری نام اصلی روز برای نمایش در پیام‌ها
    
    # در هفته آینده، اضافه کردن پسوند _next به روز در صورت نیاز
    if week_offset == 1:  # هفته آینده
        if "_next" not in day:
            day = f"{day}_next"
    else:  # هفته جاری
        # حذف پسوند _next در صورت وجود
        if "_next" in day:
            day = day.replace("_next", "")
    
    # بررسی اینکه رزرو قبلاً انجام نشده باشد
    existing_reservation = Reservation.query.filter_by(
        student_id=student.id, day=day, meal=meal
    ).first()
    
    if existing_reservation:
        flash(f'شما قبلاً برای {day} وعده {meal} رزرو کرده‌اید', 'warning')
        return redirect(url_for('menu', week=week_offset))
    
    # ایجاد رزرو جدید
    new_reservation = Reservation(
        student_id=student.id,
        day=day,
        meal=meal,
        food_name=food_name,
        food_price=food_price,
        delivered=0
    )
    db.session.add(new_reservation)
    db.session.commit()
    
    # به‌روزرسانی بدهی دانشجو و آمار مالی کل سیستم
    update_financial_statistics()
    
    week_type = "هفته آینده" if week_offset == 1 else "هفته جاری"
    flash(f'رزرو شما برای {day} وعده {meal} ({week_type}) با موفقیت ثبت شد', 'success')
    return redirect(url_for('dashboard'))

@app.route('/reserve_all_day', methods=['POST'])
@login_required
def reserve_all_day():
    # گرفتن پارامتر هفته از URL (اگر وجود داشته باشد)
    week_offset = request.args.get('week', '0')
    try:
        week_offset = int(week_offset)
    except ValueError:
        week_offset = 0
    
    # محدود کردن week_offset به مقادیر معقول (0 = هفته جاری، 1 = هفته آینده)
    if week_offset < 0:
        week_offset = 0
    elif week_offset > 1:
        week_offset = 1
    
    day = request.form.get('day')
    
    if not day:
        flash('روز مورد نظر مشخص نشده است', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    # دریافت منوی روز مورد نظر با توجه به هفته انتخاب شده
    if week_offset == 1:  # هفته آینده
        # بررسی اینکه آیا این روز "هفته آینده" هست یا نه
        if "_next" not in day:
            day = f"{day}_next"
    else:  # هفته جاری
        # بررسی اینکه آیا این روز بدون پسوند "_next" است
        if "_next" in day:
            day = day.replace("_next", "")
            
    # دریافت منوی روز مورد نظر
    day_menu = Menu.query.filter_by(day=day).first()
    if not day_menu:
        flash(f'منوی روز {day} یافت نشد', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    meal_data = day_menu.meal_data
    success_count = 0
    already_reserved = 0
    
    # وعده‌های غذایی
    meals = ['breakfast', 'lunch', 'dinner']
    
    for meal in meals:
        # بررسی اینکه این وعده در منو وجود داشته باشد و حداقل یک غذا داشته باشد
        if meal in meal_data and meal_data[meal] and len(meal_data[meal]) > 0:
            # بررسی رزرو قبلی
            existing_reservation = Reservation.query.filter_by(
                student_id=student.id, day=day, meal=meal
            ).first()
            
            if existing_reservation:
                already_reserved += 1
                continue
            
            # انتخاب اولین غذای هر وعده
            food_item = meal_data[meal][0]
            food_name = food_item.get('name', food_item) if isinstance(food_item, dict) else food_item
            
            # تنظیم قیمت‌های ثابت بر اساس نوع وعده
            if meal == 'breakfast':
                food_price = 2000.0  # صبحانه
            elif meal == 'lunch':
                food_price = 3000.0  # ناهار
            elif meal == 'dinner':
                food_price = 5000.0  # شام
            else:
                food_price = 0.0
            
            # ایجاد رزرو جدید
            new_reservation = Reservation(
                student_id=student.id,
                day=day,
                meal=meal,
                food_name=food_name,
                food_price=food_price,
                delivered=0
            )
            db.session.add(new_reservation)
            success_count += 1
    
    if success_count > 0:
        db.session.commit()
        
        # به‌روزرسانی آمار مالی و بدهی‌ها
        update_financial_statistics()
        
        week_type = "هفته آینده" if week_offset == 1 else "هفته جاری"
        meal_fa = 'وعده' if success_count == 1 else 'وعده'
        flash(f'{success_count} {meal_fa} غذا برای روز {day} ({week_type}) با موفقیت رزرو شد', 'success')
    else:
        week_type = "هفته آینده" if week_offset == 1 else "هفته جاری"
        if already_reserved > 0:
            flash(f'شما قبلاً تمام وعده‌های روز {day} ({week_type}) را رزرو کرده‌اید', 'warning')
        else:
            flash(f'هیچ وعده‌ای برای روز {day} ({week_type}) رزرو نشد', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/cancel_reservation/<int:reservation_id>', methods=['POST'])
@login_required
def cancel_reservation(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    
    # بررسی دسترسی و وضعیت غذا
    if not student or reservation.student_id != student.id:
        flash('شما مجوز حذف این رزرو را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # بررسی وضعیت تحویل غذا
    if reservation.delivered == 1:
        flash('امکان لغو رزرو غذای تحویل شده وجود ندارد', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # حذف رزرو
        db.session.delete(reservation)
        db.session.commit()
        
        # به‌روزرسانی آمار مالی و بدهی‌ها از طریق تابع مرکزی
        print("✓ فراخوانی تابع به‌روزرسانی آمار مالی پس از لغو رزرو انفرادی")
        update_financial_statistics()
        
        flash('رزرو با موفقیت لغو شد', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in cancel_reservation: {str(e)}")
        flash('خطا در لغو رزرو، لطفا دوباره تلاش کنید', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('شما دسترسی به پنل مدیریت را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # به‌روزرسانی بدهی همه دانشجویان و آمار مالی قبل از نمایش داشبورد مدیریت
    update_financial_statistics()
    
    # دریافت آمار برای پنل مدیریت
    student_count = Student.query.count()
    reservation_count = Reservation.query.count()
    
    # دریافت آمار انبار
    inventory_count = InventoryItem.query.count()
    low_stock_count = InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.min_quantity).count()
    delivered_count = Reservation.query.filter_by(delivered=1).count()
    pending_count = Reservation.query.filter_by(delivered=0).count()
    
    # محاسبه کل هزینه غذاهای تحویل شده
    total_delivered_price = db.session.query(db.func.sum(Reservation.food_price)).filter_by(delivered=1).scalar() or 0
    
    # محاسبه کل هزینه غذاهای منتظر تحویل
    total_pending_price = db.session.query(db.func.sum(Reservation.food_price)).filter_by(delivered=0).scalar() or 0
    
    # آمار وعده‌های غذایی
    breakfast_count = Reservation.query.filter_by(meal='breakfast').count()
    lunch_count = Reservation.query.filter_by(meal='lunch').count()
    dinner_count = Reservation.query.filter_by(meal='dinner').count()
    total_count = breakfast_count + lunch_count + dinner_count
    
    # ساخت آمار
    stats = {
        'breakfast': breakfast_count,
        'lunch': lunch_count,
        'dinner': dinner_count,
        'total': total_count
    }
    
    return render_template('admin.html', 
                           student_count=student_count,
                           reservation_count=reservation_count,
                           delivered_count=delivered_count,
                           pending_count=pending_count,
                           total_delivered_price=total_delivered_price,
                           total_pending_price=total_pending_price,
                           stats=stats)

@app.route('/admin/students')
@login_required
def admin_students():
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # به‌روزرسانی بدهی همه دانشجویان قبل از نمایش لیست با استفاده از تابع مرکزی
    update_financial_statistics()
    
    # دریافت پارامتر جستجو
    search_code = request.args.get('search_code')
    
    # بازخوانی لیست دانشجویان پس از به‌روزرسانی
    if search_code:
        # اگر کد تغذیه برای جستجو وارد شده باشد
        students = Student.query.filter(Student.feeding_code.like(f'%{search_code}%')).all()
        if not students:
            flash(f'دانشجویی با کد تغذیه مشابه {search_code} یافت نشد.', 'warning')
    else:
        # نمایش همه دانشجویان اگر جستجو نباشد
        students = Student.query.all()
    
    return render_template('admin_students.html', students=students)

@app.route('/admin/reservations')
@login_required
def admin_reservations():
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # به‌روزرسانی بدهی همه دانشجویان و آمار مالی قبل از نمایش
    update_financial_statistics()  # به‌روزرسانی آمار مالی دانشجویان
    update_reservation_prices()    # به‌روزرسانی قیمت‌های غذاها
    
    # دریافت پارامترهای فیلتر
    feeding_code = request.args.get('feeding_code')
    day_filter = request.args.get('day')
    meal_filter = request.args.get('meal')
    
    # پایه کوئری رزروها
    query = db.session.query(Reservation).join(Student)
    
    # اعمال فیلترها
    if feeding_code:
        query = query.filter(Student.feeding_code == feeding_code)
    
    if day_filter:
        query = query.filter(Reservation.day == day_filter)
        
    if meal_filter:
        query = query.filter(Reservation.meal == meal_filter)
    
    # مرتب‌سازی نتایج رزروها
    reservations = query.order_by(Reservation.day, Reservation.meal).all()
    
    # دریافت لیست تمام دانشجویان برای نمایش بدهی‌ها
    students = Student.query.all()
    
    # اطمینان از به‌روز بودن مقادیر بدهی دانشجویان
    for student in students:
        # چاپ لاگ برای اطمینان از به‌روزرسانی
        print(f"→ تأیید به‌روزرسانی: دانشجو {student.feeding_code} با بدهی {student.debt} تومان")
    
    # ترجمه نام روزها و وعده‌ها
    day_mapping = {
        "saturday": "شنبه",
        "sunday": "یکشنبه",
        "monday": "دوشنبه",
        "tuesday": "سه‌شنبه",
        "wednesday": "چهارشنبه",
        "thursday": "پنج‌شنبه",
        "friday": "جمعه"
    }
    
    meal_mapping = {
        "breakfast": "صبحانه",
        "lunch": "ناهار",
        "dinner": "شام"
    }
    
    # گروه‌بندی رزروها بر اساس روز
    days = ["saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday"]
    
    # محاسبه تعداد رزروهای تحویل داده شده و منتظر تحویل
    total_count = Reservation.query.count()
    delivered_count = Reservation.query.filter(Reservation.delivered == 1).count()
    pending_count = Reservation.query.filter(Reservation.delivered == 0).count()
    
    # محاسبه مجموع هزینه‌های رزرو شده و تحویل شده
    total_reserved_cost = sum(r.food_price for r in Reservation.query.all())
    total_delivered_cost = sum(r.food_price for r in Reservation.query.filter(Reservation.delivered == 1).all())
    
    # ارسال تمام داده‌های مورد نیاز به قالب
    return render_template('admin_reservations.html', 
                          reservations=reservations,
                          students=students,  # اضافه کردن لیست دانشجویان برای نمایش بدهی
                          days=days,
                          day_mapping=day_mapping,
                          meal_mapping=meal_mapping,
                          feeding_code=feeding_code,
                          day_filter=day_filter,
                          meal_filter=meal_filter,
                          total_count=total_count,
                          delivered_count=delivered_count,
                          pending_count=pending_count,
                          total_reserved_cost=total_reserved_cost,
                          total_delivered_cost=total_delivered_cost,
                          gregorian_to_jalali_datetime=gregorian_to_jalali_datetime)

@app.route('/admin/student/<int:student_id>/reservations')
@login_required
def admin_student_reservations(student_id):
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # به‌روزرسانی آمار مالی و بدهی‌ها
    update_financial_statistics()
    
    student = Student.query.get_or_404(student_id)
    reservations = Reservation.query.filter_by(student_id=student_id).all()
    
    return render_template('admin_student_reservations.html', 
                           student=student, 
                           reservations=reservations,
                           gregorian_to_jalali_datetime=gregorian_to_jalali_datetime)

@app.route('/admin/menu')
@login_required
def admin_menu():
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # بررسی و به‌روزرسانی خودکار هفته‌ها
    update_week_schedule()
    
    # گرفتن پارامتر هفته از URL (هفته جاری یا آینده)
    week_offset = request.args.get('week', '0')
    try:
        week_offset = int(week_offset)
    except ValueError:
        week_offset = 0
    
    # محدود کردن week_offset به مقادیر معقول
    if week_offset < 0:
        week_offset = 0
    elif week_offset > 1:
        week_offset = 1
    
    # اطمینان از وجود منوی هفته آینده
    ensure_next_week_menus_exist()
    
    # دریافت منوی هفتگی بر اساس هفته انتخاب شده
    if week_offset == 1:  # هفته آینده
        # تمام منوهایی که در نام آنها "_next" وجود دارد
        weekly_menu = Menu.query.filter(Menu.day.like("%_next")).all()
        print(f"تعداد منوهای هفته آینده: {len(weekly_menu)}")
        # برای نمایش بهتر نام روزها بدون پسوند
        for menu_item in weekly_menu:
            menu_item.display_day = menu_item.day.replace("_next", "")
    else:  # هفته جاری
        # تمام منوهایی که "_next" در نام آنها وجود ندارد
        weekly_menu = Menu.query.filter(~Menu.day.like("%_next")).all()
        print(f"تعداد منوهای هفته جاری: {len(weekly_menu)}")
        # تنظیم نام نمایشی یکسان با نام واقعی
        for menu_item in weekly_menu:
            menu_item.display_day = menu_item.day
    
    # تعریف ترتیب روزهای هفته برای مرتب‌سازی
    day_order = {"saturday": 0, "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6}
    
    # مرتب‌سازی منوی هفتگی بر اساس ترتیب روزهای هفته
    weekly_menu.sort(key=lambda x: day_order.get(x.display_day, 7))
    
    # استفاده از OrderedDict برای حفظ ترتیب روزها (شنبه در ابتدا)
    days = OrderedDict([
        ("saturday", "شنبه"),
        ("sunday", "یکشنبه"),
        ("monday", "دوشنبه"),
        ("tuesday", "سه‌شنبه"),
        ("wednesday", "چهارشنبه"),
        ("thursday", "پنج‌شنبه"),
        ("friday", "جمعه")
    ])
    meals = {
        "breakfast": "صبحانه",
        "lunch": "ناهار",
        "dinner": "شام"
    }
    
    # به‌روزرسانی آمار مالی و بدهی‌ها
    update_financial_statistics()
    
    return render_template('admin_menu.html', weekly_menu=weekly_menu, days=days, meals=meals)

@app.route('/admin/update_menu', methods=['POST'])
@login_required
def admin_update_menu():
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت و بررسی داده‌های فرم
    day = request.form.get('day')
    meal = request.form.get('meal')
    food_items_text = request.form.get('food_items')
    week_offset = request.args.get('week', '0')  # پارامتر انتخاب هفته
    
    # تعیین اینکه آیا منوی هفته آینده در حال ویرایش است
    try:
        week_offset = int(week_offset)
        is_next_week = (week_offset == 1)
    except ValueError:
        is_next_week = False
    
    # اضافه کردن پسوند "_next" اگر در حال ویرایش هفته آینده هستیم
    if is_next_week and not day.endswith('_next'):
        day = f"{day}_next"
    # برعکس: اطمینان از عدم وجود پسوند "_next" اگر در حال ویرایش هفته جاری هستیم
    elif not is_next_week and day.endswith('_next'):
        day = day.replace('_next', '')
    
    # بررسی اعتبار داده‌های ورودی
    if not day or not meal:
        flash('روز و وعده غذایی باید مشخص شوند', 'danger')
        return redirect(url_for('admin_menu'))
    
    try:
        # پردازش لیست غذاها با اضافه کردن قیمت ثابت بر اساس نوع وعده
        food_items = []
        for item in food_items_text.split('\n'):
            if item.strip():
                # تعیین قیمت بر اساس نوع وعده غذایی
                if meal == 'breakfast':
                    price = 2000  # صبحانه 2 هزار تومان
                elif meal == 'lunch':
                    price = 3000  # ناهار 3 هزار تومان
                elif meal == 'dinner':
                    price = 5000  # شام 5 هزار تومان
                else:
                    price = 0
                
                # افزودن به صورت دیکشنری با قیمت
                food_items.append({"name": item.strip(), "price": price})
        
        # محدود کردن به یک غذا برای هر وعده
        if len(food_items) > 1:
            food_items = [food_items[0]]
            
        # لاگ اطلاعات ورودی برای دیباگ
        print(f"Updating menu - Day: {day}, Meal: {meal}")
        print(f"Food items with prices: {food_items}")
        
        # دریافت منوی روز مورد نظر
        day_menu = Menu.query.filter_by(day=day).first()
        if not day_menu:
            print(f"Creating new menu for day: {day}")
            flash(f'منوی روز {day} یافت نشد - در حال ایجاد منوی جدید', 'warning')
            # ایجاد یک منوی جدید برای این روز
            day_menu = Menu(day=day, meal_data={
                "breakfast": [],
                "lunch": [],
                "dinner": []
            })
            db.session.add(day_menu)
            db.session.flush()  # برای دریافت ID جدید
            print(f"Created new menu with ID: {day_menu.id}")
        else:
            print(f"Found existing menu for day: {day}, ID: {day_menu.id}")
            print(f"Current meal_data: {day_menu.meal_data}")
        
        # تضمین اینکه meal_data یک دیکشنری معتبر است
        current_data = {}
        if day_menu.meal_data:
            if isinstance(day_menu.meal_data, dict):
                current_data = day_menu.meal_data
                print(f"meal_data is valid dictionary")
            elif isinstance(day_menu.meal_data, str):
                import json
                try:
                    current_data = json.loads(day_menu.meal_data)
                    print(f"Converted string meal_data to dictionary")
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {str(e)}")
                    current_data = {}
            else:
                print(f"Unknown meal_data type: {type(day_menu.meal_data)}")
                current_data = {}
        else:
            print("meal_data is None or empty, initializing new dictionary")
        
        # وعده‌های غذایی پیش‌فرض را اضافه می‌کنیم اگر وجود نداشته باشند
        for meal_name in ['breakfast', 'lunch', 'dinner']:
            if meal_name not in current_data:
                current_data[meal_name] = []
                print(f"Added missing meal type: {meal_name}")
        
        # به‌روزرسانی منو برای وعده مورد نظر
        print(f"Updating menu for meal: {meal} with items: {food_items}")
        current_data[meal] = food_items.copy()
        
        # بررسی و لاگ داده‌های جدید
        print(f"New meal_data structure: {current_data}")
        
        # استفاده از مقدار جدید برای بروزرسانی
        import copy
        import json
        
        # ایجاد یک کپی عمیق از داده‌ها برای اطمینان از تغییر واقعی
        new_menu_data = copy.deepcopy(current_data)
        
        # تلاش مستقیم برای ذخیره تغییرات به صورت خام SQL به‌جای ORM
        try:
            import json
            # تبدیل دیکشنری به JSON string
            meal_data_json = json.dumps(new_menu_data)
            print(f"Converting to JSON string: {meal_data_json}")
            
            # به‌روزرسانی مستقیم از طریق SQL برای اطمینان از اعمال تغییرات
            from sqlalchemy import text
            sql = text("UPDATE menu SET meal_data = :meal_data WHERE id = :id")
            db.session.execute(sql, {"meal_data": meal_data_json, "id": day_menu.id})
            db.session.commit()
            print(f"Successfully committed changes directly using SQL")
        except Exception as e:
            print(f"Error in direct SQL update: {str(e)}")
            # روش جایگزین - استفاده از ORM استاندارد
            day_menu.meal_data = new_menu_data
            db.session.add(day_menu)
            db.session.commit()
            print(f"Fallback: Successfully committed changes using ORM")
        
        # تخلیه کش SQLAlchemy
        db.session.expire_all()
        
        # تعهد به دیتابیس باید اول انجام شود
        db.session.commit()
        
        # تایید نهایی تغییرات با دریافت مجدد از دیتابیس
        updated_menu = Menu.query.get(day_menu.id)
        print(f"Verification - Updated menu data: {updated_menu.meal_data}")
        
        # تعیین پیام فلش با توجه به نوع هفته
        if is_next_week:
            flash(f'منوی {meal} روز {day.replace("_next", "")} هفته آینده با موفقیت به‌روزرسانی شد', 'success')
        else:
            flash(f'منوی {meal} روز {day} هفته جاری با موفقیت به‌روزرسانی شد', 'success')
    except Exception as e:
        db.session.rollback()
        # لاگ خطا با جزئیات بیشتر
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR updating menu: {str(e)}")
        print(f"Traceback: {error_details}")
        flash(f'خطا در به‌روزرسانی منو: {str(e)}', 'danger')
    
    # بازگشت به همان صفحه با حفظ پارامتر هفته
    return redirect(url_for('admin_menu', week=week_offset))

# تابع به‌روزرسانی قیمت‌های غذا در رزروهای موجود
def update_reservation_prices():
    """
    به‌روزرسانی قیمت‌های غذا در تمام رزروهای موجود بر اساس نوع وعده
    """
    print("✓ فراخوانی تابع به‌روزرسانی قیمت‌های غذا")
    try:
        # دریافت تمام رزروها
        reservations = Reservation.query.all()
        updated_count = 0
        
        for res in reservations:
            old_price = res.food_price
            
            # تنظیم قیمت‌های ثابت بر اساس نوع وعده
            if res.meal == 'breakfast':
                res.food_price = 2000.0  # صبحانه
            elif res.meal == 'lunch':
                res.food_price = 3000.0  # ناهار
            elif res.meal == 'dinner':
                res.food_price = 5000.0  # شام
            
            if old_price != res.food_price:
                updated_count += 1
                print(f"   ✓ به‌روزرسانی رزرو {res.id}: {res.day}, {res.meal} - قیمت قدیم: {old_price} تومان، قیمت جدید: {res.food_price} تومان")
        
        # ذخیره تغییرات
        db.session.commit()
        print(f"✓ تعداد {updated_count} رزرو با موفقیت به‌روزرسانی شد")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"✗ خطا در به‌روزرسانی قیمت‌های غذا: {e}")
        import traceback
        print(f"✗ جزئیات خطا: {traceback.format_exc()}")
        logger.error(f"خطا در به‌روزرسانی قیمت‌های غذا: {e}")
        return False

# تابع بروزرسانی کامل آمار مالی و بدهی
def update_financial_statistics():
    """
    بروزرسانی کامل آمار مالی و بدهی‌های تمام دانشجویان
    این تابع در نقاط کلیدی سیستم فراخوانی می‌شود:
    - ثبت رزرو جدید
    - لغو رزرو
    - تایید تحویل غذا
    - بازدید از پنل‌های مدیریت و گزارش‌ها
    """
    print("✓ فراخوانی تابع به‌روزرسانی آمار مالی و بدهی دانشجویان")
    
    # ابتدا قیمت‌های رزروها را به‌روز می‌کنیم
    update_reservation_prices()
    
    try:
        # محاسبه بدهی همه دانشجویان
        students = Student.query.all()
        print(f"✓ تعداد دانشجویان برای به‌روزرسانی: {len(students)}")
        
        # ریست کردن بدهی همه دانشجویان برای اطمینان از به‌روزرسانی صحیح
        for student in students:
            # ریست مقدار بدهی
            student.debt = 0
            # اعتبار حساب همچنان حفظ می‌شود
            # student.credit = 0
        db.session.flush()
        
        for student in students:
            # محاسبه بدهی کل برای هر دانشجو - فقط غذاهای تحویل شده
            student_debt = 0
            # غذاهای تحویل شده برای محاسبه بدهی
            delivered_reservations = Reservation.query.filter_by(student_id=student.id, delivered=1).all()
            
            for res in delivered_reservations:
                student_debt += res.food_price
            
            # محاسبه بدهی برای غذاهای تحویل نشده (به منظور نمایش در داشبورد)
            pending_debt = 0
            pending_reservations = Reservation.query.filter_by(student_id=student.id, delivered=0).all()
            
            print(f"✓ دانشجو: {student.feeding_code}, تعداد رزروهای تحویل نشده: {len(pending_reservations)}")
            
            for res in pending_reservations:
                pending_debt += res.food_price
                print(f"   - رزرو: {res.day}, {res.meal}, قیمت: {res.food_price} تومان")
            
            # ذخیره‌سازی بدهی در فیلد debt 
            student.debt = student_debt
            print(f"✓ بدهی نهایی دانشجو {student.feeding_code} برای غذاهای تحویل شده: {student.debt} تومان")
            print(f"✓ هزینه‌های آتی دانشجو {student.feeding_code} برای غذاهای رزرو شده: {pending_debt} تومان")
            
            # نمایش کل بدهی و هزینه‌های پیش‌رو در داشبورد به صورت جداگانه
        
        # ذخیره تغییرات و اطمینان از commit شدن آنها
        db.session.commit()
        print("✓ تمام بدهی‌ها با موفقیت به‌روزرسانی شدند")
        
        # تأیید به‌روزرسانی موفق
        updated_students = Student.query.all()
        for student in updated_students:
            if student.debt > 0:
                print(f"→ تأیید به‌روزرسانی: دانشجو {student.feeding_code} با بدهی {student.debt} تومان")
        
        return True
    except Exception as e:
        db.session.rollback()
        print(f"✗ خطا در به‌روزرسانی آمار مالی: {e}")
        import traceback
        print(f"✗ جزئیات خطا: {traceback.format_exc()}")
        logger.error(f"خطا در بروزرسانی آمار مالی: {e}")
        return False


@app.route('/admin/delivery/<int:reservation_id>', methods=['POST'])
@login_required
def admin_delivery(reservation_id):
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # استفاده از اجرای مستقیم SQL برای اطمینان از اجرای تغییرات
        try:
            from sqlalchemy import text
            sql = text("UPDATE reservations SET delivered = 1 WHERE id = :id")
            result = db.session.execute(sql, {"id": reservation_id})
            db.session.commit()
            print(f"Updated reservation directly with SQL: {result.rowcount} row(s) affected")
            
            # اگر هیچ رزروی به‌روز نشد، احتمالا ID نامعتبر است
            if result.rowcount == 0:
                flash('رزرو مورد نظر یافت نشد', 'danger')
                return redirect(request.referrer or url_for('admin_reservations'))
                
        except Exception as sql_error:
            print(f"SQL update error: {str(sql_error)}, falling back to ORM")
            # راه حل جایگزین در صورت خطا در SQL مستقیم
            reservation = Reservation.query.get_or_404(reservation_id)
            
            # بررسی وضعیت فعلی
            if reservation.delivered == 1:
                flash('این غذا قبلا تحویل داده شده است', 'warning')
                return redirect(request.referrer or url_for('admin_reservations'))
            
            # تنظیم وضعیت تحویل به "تحویل شده"
            reservation.delivered = 1
            db.session.commit()
        
        # بروزرسانی بدهی و آمار مالی کل سیستم
        if update_financial_statistics():
            flash('وضعیت تحویل غذا با موفقیت به‌روزرسانی شد', 'success')
        else:
            flash('وضعیت تحویل بروز شد، اما در بروزرسانی آمار مالی مشکلی پیش آمد', 'warning')
            
        # بازگشت به صفحه قبلی (اگر ممکن باشد)
        return redirect(request.referrer or url_for('admin_reservations'))
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"خطا در تأیید تحویل غذا: {e}")
        flash('خطا در تأیید تحویل غذا، لطفا دوباره تلاش کنید', 'danger')
        return redirect(url_for('admin_reservations'))

@app.route('/reserve_all_week', methods=['POST'])
@login_required
def reserve_all_week():
    # گرفتن پارامتر هفته از URL (اگر وجود داشته باشد)
    week_offset = request.args.get('week', '0')
    try:
        week_offset = int(week_offset)
    except ValueError:
        week_offset = 0
    
    # محدود کردن week_offset به مقادیر معقول (0 = هفته جاری، 1 = هفته آینده)
    if week_offset < 0:
        week_offset = 0
    elif week_offset > 1:
        week_offset = 1
    
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    # دریافت منوی هفتگی
    weekly_menu = Menu.query.all()
    if not weekly_menu:
        flash('منوی هفتگی یافت نشد', 'danger')
        return redirect(url_for('menu', week=week_offset))
    
    # مرتب‌سازی منوی هفتگی بر اساس ترتیب روزهای هفته
    day_order = {"saturday": 0, "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4, "thursday": 5, "friday": 6}
    weekly_menu.sort(key=lambda x: day_order.get(x.day, 7))
    
    success_count = 0
    already_reserved = 0
    
    # وعده‌های غذایی
    meals = ['breakfast', 'lunch', 'dinner']
    
    for day_menu in weekly_menu:
        for meal in meals:
            # بررسی اینکه این وعده در منو وجود داشته باشد و حداقل یک غذا داشته باشد
            if meal in day_menu.meal_data and day_menu.meal_data[meal] and len(day_menu.meal_data[meal]) > 0:
                # بررسی رزرو قبلی
                existing_reservation = Reservation.query.filter_by(
                    student_id=student.id, day=day_menu.day, meal=meal
                ).first()
                
                if existing_reservation:
                    already_reserved += 1
                    continue
                
                # انتخاب اولین غذای هر وعده
                food_item = day_menu.meal_data[meal][0]
                food_name = food_item.get('name', food_item) if isinstance(food_item, dict) else food_item
                
                # تنظیم قیمت‌های ثابت بر اساس نوع وعده
                if meal == 'breakfast':
                    food_price = 2000.0  # صبحانه
                elif meal == 'lunch':
                    food_price = 3000.0  # ناهار
                elif meal == 'dinner':
                    food_price = 5000.0  # شام
                else:
                    food_price = food_item.get('price', 0) if isinstance(food_item, dict) else 0
                
                # ایجاد رزرو جدید
                new_reservation = Reservation(
                    student_id=student.id,
                    day=day_menu.day,
                    meal=meal,
                    food_name=food_name,
                    food_price=food_price,
                    delivered=0
                )
                db.session.add(new_reservation)
                success_count += 1
    
    if success_count > 0:
        db.session.commit()
        
        # به‌روزرسانی آمار مالی و بدهی‌ها از طریق تابع مرکزی
        print("✓ فراخوانی تابع به‌روزرسانی آمار مالی پس از رزرو هفتگی")
        update_financial_statistics()
        
        week_type = "هفته آینده" if week_offset == 1 else "هفته جاری"
        meal_fa = 'وعده' if success_count == 1 else 'وعده'
        flash(f'{success_count} {meal_fa} غذا برای {week_type} با موفقیت رزرو شد', 'success')
    else:
        week_type = "هفته آینده" if week_offset == 1 else "هفته جاری"
        if already_reserved > 0:
            flash(f'شما قبلاً تمام وعده‌های {week_type} را رزرو کرده‌اید', 'warning')
        else:
            flash(f'هیچ وعده‌ای برای {week_type} رزرو نشد', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    try:
        if request.method == 'POST':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            # بررسی تطابق رمز عبور جدید
            if new_password != confirm_password:
                flash('رمز عبور جدید و تکرار آن مطابقت ندارند', 'danger')
                return redirect(url_for('settings'))
            
            # بررسی رمز عبور فعلی
            user = User.query.get(current_user.id)
            if not check_password_hash(user.password, current_password):
                flash('رمز عبور فعلی نادرست است', 'danger')
                return redirect(url_for('settings'))
            
            # به‌روزرسانی رمز عبور
            user.password = generate_password_hash(new_password)
            db.session.commit()
            
            flash('رمز عبور شما با موفقیت تغییر یافت', 'success')
            return redirect(url_for('dashboard'))
        
        # استفاده از try-except برای دیباگ
        return render_template('settings.html')
    except Exception as e:
        logger.error(f"Error in settings route: {str(e)}")
        flash('خطا در سیستم رخ داده است. لطفا دوباره تلاش کنید.', 'danger')
        return redirect(url_for('dashboard'))

# مسیرهای تعمیر و نگهداری به درخواست کاربر حذف شدند


@app.route('/cancel_all_day', methods=['POST'])
@login_required
def cancel_all_day():
    day = request.form.get('day')
    
    if not day:
        flash('روز مورد نظر مشخص نشده است', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت رزروهای روز مورد نظر
    # استفاده از OrderedDict برای حفظ ترتیب روزها (شنبه در ابتدا)
    days = OrderedDict([
        ("saturday", "شنبه"),
        ("sunday", "یکشنبه"),
        ("monday", "دوشنبه"),
        ("tuesday", "سه‌شنبه"),
        ("wednesday", "چهارشنبه"),
        ("thursday", "پنج‌شنبه"),
        ("friday", "جمعه")
    ])
    
    try:
        # دریافت رزروهای روز مورد نظر - فقط رزروهایی که تحویل نشده‌اند
        reservations = Reservation.query.filter_by(
            student_id=student.id, day=day, delivered=0
        ).all()
        
        if not reservations:
            flash(f'شما رزرو قابل لغوی برای روز {days.get(day, day)} ندارید', 'warning')
            return redirect(url_for('dashboard'))
        
        # حذف رزروها
        count = 0
        for reservation in reservations:
            db.session.delete(reservation)
            count += 1
        
        db.session.commit()
        
        # به‌روزرسانی آمار مالی و بدهی‌ها از طریق تابع مرکزی
        print("✓ فراخوانی تابع به‌روزرسانی آمار مالی پس از لغو رزرو روزانه")
        update_financial_statistics()
        
        flash(f'{count} رزرو برای روز {days.get(day, day)} با موفقیت لغو شد', 'success')
        return redirect(url_for('dashboard'))
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in cancel_all_day: {str(e)}")
        flash('خطا در لغو رزروها، لطفا دوباره تلاش کنید', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/cancel_all_week', methods=['POST'])
@login_required
def cancel_all_week():
    # دریافت اطلاعات دانشجو
    student = Student.query.filter_by(user_id=str(current_user.id)).first()
    if not student:
        flash('اطلاعات دانشجویی شما یافت نشد', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # دریافت فقط رزروهایی که تحویل نشده‌اند
        reservations = Reservation.query.filter_by(
            student_id=student.id, delivered=0
        ).all()
        
        if not reservations:
            flash('شما هیچ رزروی قابل لغو ندارید', 'warning')
            return redirect(url_for('dashboard'))
        
        # حذف رزروها
        count = 0
        for reservation in reservations:
            db.session.delete(reservation)
            count += 1
        
        db.session.commit()
        
        # به‌روزرسانی بدهی دانشجو پس از حذف رزرو
        update_financial_statistics()
        
        flash(f'{count} رزرو برای کل هفته با موفقیت لغو شد', 'success')
        return redirect(url_for('dashboard'))
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in cancel_all_week: {str(e)}")
        flash('خطا در لغو رزروها، لطفا دوباره تلاش کنید', 'danger')
        return redirect(url_for('dashboard'))

# ----- مدیریت انبار - دسترسی انباردار و مدیر -----

@app.route('/warehouse')
@login_required
@warehouse_manager_required
def warehouse_dashboard():
    """داشبورد مدیریت انبار"""
    # دریافت آمار کلی انبار
    total_items = InventoryItem.query.count()
    
    # دریافت اقلام با موجودی کم
    low_stock_items = InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.min_quantity).all()
    
    # دریافت تراکنش‌های اخیر
    recent_transactions = InventoryTransaction.query.order_by(
        InventoryTransaction.timestamp.desc()).limit(10).all()
    
    return render_template('warehouse/dashboard.html',
                        total_items=total_items,
                        low_stock_items=low_stock_items,
                        recent_transactions=recent_transactions)

@app.route('/warehouse/items')
@login_required
@warehouse_manager_required
def warehouse_items():
    """لیست اقلام انبار"""
    # دریافت لیست کامل اقلام انبار
    items = InventoryItem.query.all()
    
    return render_template('warehouse/items.html', items=items)

@app.route('/warehouse/items/add', methods=['GET', 'POST'])
@login_required
@warehouse_manager_required
def warehouse_add_item():
    """افزودن قلم جدید به انبار"""
    if request.method == 'POST':
        code = request.form.get('code')
        name = request.form.get('name')
        category = request.form.get('category')
        unit = request.form.get('unit')
        quantity = request.form.get('quantity', 0)
        min_quantity = request.form.get('min_quantity', 5)
        description = request.form.get('description')
        
        # بررسی وجود فیلدهای اجباری
        if not all([code, name, unit]):
            flash('لطفاً فیلدهای ضروری را تکمیل کنید', 'danger')
            return render_template('warehouse/add_item.html')
        
        # بررسی تکراری نبودن کد محصول
        existing_item = InventoryItem.query.filter_by(code=code).first()
        if existing_item:
            flash('کد محصول وارد شده قبلاً در سیستم ثبت شده است', 'danger')
            return render_template('warehouse/add_item.html')
        
        # تبدیل مقادیر عددی
        try:
            quantity = int(quantity)
            min_quantity = int(min_quantity)
            
            if quantity < 0 or min_quantity < 0:
                flash('مقادیر عددی باید بزرگتر یا مساوی صفر باشند', 'danger')
                return render_template('warehouse/add_item.html')
        except ValueError:
            flash('مقادیر وارد شده برای موجودی و حداقل موجودی باید عدد صحیح باشند', 'danger')
            return render_template('warehouse/add_item.html')
        
        # ایجاد آیتم جدید
        new_item = InventoryItem(
            code=code,
            name=name,
            category=category,
            unit=unit,
            quantity=quantity,
            min_quantity=min_quantity,
            description=description
        )
        
        db.session.add(new_item)
        db.session.flush()  # برای دریافت شناسه آیتم
        
        # ثبت تراکنش اولیه
        if quantity > 0:
            transaction = InventoryTransaction(
                item_id=new_item.id,
                transaction_type='add',
                quantity=quantity,
                previous_quantity=0,
                current_quantity=quantity,
                user_id=current_user.id,
                notes='موجودی اولیه'
            )
            db.session.add(transaction)
        
        db.session.commit()
        
        flash(f'قلم جدید «{name}» با موفقیت به انبار اضافه شد', 'success')
        return redirect(url_for('warehouse_items'))
    
    return render_template('warehouse/add_item.html')

@app.route('/warehouse/items/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@warehouse_manager_required
def warehouse_edit_item(item_id):
    """ویرایش قلم انبار"""
    # دریافت اطلاعات قلم
    item = InventoryItem.query.get_or_404(item_id)
    
    if request.method == 'POST':
        code = request.form.get('code')
        name = request.form.get('name')
        category = request.form.get('category')
        unit = request.form.get('unit')
        min_quantity = request.form.get('min_quantity', 5)
        description = request.form.get('description')
        
        # بررسی وجود فیلدهای اجباری
        if not all([code, name, unit]):
            flash('لطفاً فیلدهای ضروری را تکمیل کنید', 'danger')
            return render_template('warehouse/edit_item.html', item=item)
        
        # بررسی تکراری نبودن کد محصول
        existing_item = InventoryItem.query.filter_by(code=code).first()
        if existing_item and existing_item.id != item.id:
            flash('کد محصول وارد شده قبلاً در سیستم ثبت شده است', 'danger')
            return render_template('warehouse/edit_item.html', item=item)
        
        # تبدیل مقادیر عددی
        try:
            min_quantity = int(min_quantity)
            
            if min_quantity < 0:
                flash('حداقل موجودی باید بزرگتر یا مساوی صفر باشد', 'danger')
                return render_template('warehouse/edit_item.html', item=item)
        except ValueError:
            flash('مقدار وارد شده برای حداقل موجودی باید عدد صحیح باشد', 'danger')
            return render_template('warehouse/edit_item.html', item=item)
        
        # به‌روزرسانی اطلاعات قلم
        item.code = code
        item.name = name
        item.category = category
        item.unit = unit
        item.min_quantity = min_quantity
        item.description = description
        
        db.session.commit()
        
        flash(f'اطلاعات قلم «{name}» با موفقیت به‌روزرسانی شد', 'success')
        return redirect(url_for('warehouse_items'))
    
    return render_template('warehouse/edit_item.html', item=item)

@app.route('/warehouse/transactions')
@login_required
@warehouse_manager_required
def warehouse_transactions():
    """تاریخچه تراکنش‌های انبار"""
    # دریافت تراکنش‌ها
    transactions = InventoryTransaction.query.order_by(
        InventoryTransaction.timestamp.desc()).all()
    
    return render_template('warehouse/transactions.html', transactions=transactions)

@app.route('/warehouse/items/update/<int:item_id>', methods=['GET', 'POST'])
@login_required
@warehouse_manager_required
def warehouse_update_inventory(item_id):
    """به‌روزرسانی موجودی قلم انبار"""
    # دریافت اطلاعات قلم
    item = InventoryItem.query.get_or_404(item_id)
    
    if request.method == 'POST':
        transaction_type = request.form.get('transaction_type')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes')
        
        # بررسی وجود فیلدهای اجباری
        if not all([transaction_type, quantity]):
            flash('لطفاً نوع تراکنش و مقدار را مشخص کنید', 'danger')
            return render_template('warehouse/update_inventory.html', item=item)
        
        # تبدیل مقدار عددی
        try:
            quantity = int(quantity)
            
            if quantity <= 0:
                flash('مقدار باید عددی بزرگتر از صفر باشد', 'danger')
                return render_template('warehouse/update_inventory.html', item=item)
        except ValueError:
            flash('مقدار وارد شده باید عدد صحیح باشد', 'danger')
            return render_template('warehouse/update_inventory.html', item=item)
        
        # بررسی نوع تراکنش و اعمال تغییرات
        previous_quantity = item.quantity
        new_quantity = previous_quantity
        
        if transaction_type == 'add':
            # افزایش موجودی
            new_quantity = previous_quantity + quantity
        elif transaction_type == 'remove':
            # کاهش موجودی
            if quantity > previous_quantity:
                flash('مقدار برداشت نمی‌تواند بیشتر از موجودی فعلی باشد', 'danger')
                return render_template('warehouse/update_inventory.html', item=item)
            new_quantity = previous_quantity - quantity
        elif transaction_type == 'adjust':
            # تنظیم موجودی
            new_quantity = quantity
        else:
            flash('نوع تراکنش نامعتبر است', 'danger')
            return render_template('warehouse/update_inventory.html', item=item)
        
        # ثبت تراکنش
        transaction = InventoryTransaction(
            item_id=item.id,
            transaction_type=transaction_type,
            quantity=quantity,
            previous_quantity=previous_quantity,
            current_quantity=new_quantity,
            user_id=current_user.id,
            notes=notes
        )
        
        # به‌روزرسانی موجودی قلم
        item.quantity = new_quantity
        
        db.session.add(transaction)
        db.session.commit()
        
        flash(f'موجودی قلم «{item.name}» با موفقیت به‌روزرسانی شد', 'success')
        return redirect(url_for('warehouse_items'))
    
    return render_template('warehouse/update_inventory.html', item=item)

@app.route('/warehouse/food-usage')
@login_required
@warehouse_manager_required
def warehouse_food_usage():
    """مدیریت مصرف مواد غذایی"""
    # دریافت دستورات پخت غذاها
    food_usages = FoodInventoryUsage.query.all()
    
    # دریافت لیست غذاها از منوی هفتگی
    food_names = set()
    for menu in Menu.query.all():
        for meal_type, foods in menu.meal_data.items():
            for food in foods:
                food_names.add(food['name'])
    
    food_names = sorted(list(food_names))
    
    # دریافت لیست مواد اولیه
    inventory_items = InventoryItem.query.all()
    
    return render_template('warehouse/food_usage.html', 
                        food_usages=food_usages,
                        food_names=food_names,
                        inventory_items=inventory_items)

@app.route('/warehouse/food-usage/add', methods=['POST'])
@login_required
@warehouse_manager_required
def warehouse_add_food_usage():
    """افزودن دستور پخت جدید"""
    if request.method == 'POST':
        food_name = request.form.get('food_name')
        item_id = request.form.get('item_id')
        quantity_per_serving = request.form.get('quantity_per_serving')
        
        # بررسی وجود فیلدهای اجباری
        if not all([food_name, item_id, quantity_per_serving]):
            flash('لطفاً تمام فیلدها را تکمیل کنید', 'danger')
            return redirect(url_for('warehouse_food_usage'))
        
        # تبدیل مقادیر
        try:
            item_id = int(item_id)
            quantity_per_serving = float(quantity_per_serving)
            
            if quantity_per_serving <= 0:
                flash('مقدار مصرف باید عددی بزرگتر از صفر باشد', 'danger')
                return redirect(url_for('warehouse_food_usage'))
        except ValueError:
            flash('مقدار وارد شده برای مصرف هر پرس باید عدد باشد', 'danger')
            return redirect(url_for('warehouse_food_usage'))
        
        # بررسی وجود ماده اولیه
        item = InventoryItem.query.get(item_id)
        if not item:
            flash('ماده اولیه انتخاب شده در سیستم وجود ندارد', 'danger')
            return redirect(url_for('warehouse_food_usage'))
        
        # بررسی تکراری نبودن دستور پخت
        existing = FoodInventoryUsage.query.filter_by(food_name=food_name, item_id=item_id).first()
        if existing:
            flash(f'این ماده اولیه قبلاً برای غذای «{food_name}» ثبت شده است', 'danger')
            return redirect(url_for('warehouse_food_usage'))
        
        # ایجاد دستور پخت جدید
        food_usage = FoodInventoryUsage(
            food_name=food_name,
            item_id=item_id,
            quantity_per_serving=quantity_per_serving
        )
        
        db.session.add(food_usage)
        db.session.commit()
        
        flash(f'دستور پخت برای غذای «{food_name}» با موفقیت ثبت شد', 'success')
        return redirect(url_for('warehouse_food_usage'))

@app.route('/warehouse/food-usage/delete/<int:usage_id>', methods=['POST'])
@login_required
@warehouse_manager_required
def warehouse_delete_food_usage(usage_id):
    """حذف دستور پخت"""
    usage = FoodInventoryUsage.query.get_or_404(usage_id)
    
    db.session.delete(usage)
    db.session.commit()
    
    flash('دستور پخت با موفقیت حذف شد', 'success')
    return redirect(url_for('warehouse_food_usage'))

@app.route('/warehouse/forecast')
@login_required
@warehouse_manager_required
def warehouse_forecast():
    """پیش‌بینی مصرف مواد غذایی"""
    # دریافت رزروهای فعلی برای پیش‌بینی مصرف مواد اولیه
    reservations = Reservation.query.filter_by(delivered=0).all()
    
    # جمع‌آوری تعداد رزرو هر غذا
    food_counts = {}
    for reservation in reservations:
        if reservation.food_name in food_counts:
            food_counts[reservation.food_name] += 1
        else:
            food_counts[reservation.food_name] = 1
    
    # محاسبه مصرف پیش‌بینی شده مواد اولیه
    forecast_data = []
    
    for food_name, count in food_counts.items():
        # دریافت دستورات پخت این غذا
        usages = FoodInventoryUsage.query.filter_by(food_name=food_name).all()
        
        for usage in usages:
            # محاسبه مقدار مصرف کل
            total_needed = usage.quantity_per_serving * count
            
            # بررسی موجودی فعلی
            current_quantity = usage.item.quantity
            
            # تعیین وضعیت
            status = "ok"
            if current_quantity < total_needed:
                status = "critical"
            elif current_quantity < (total_needed * 1.2):  # کمتر از 20% بیشتر از نیاز
                status = "warning"
            
            forecast_data.append({
                'food_name': food_name,
                'item_name': usage.item.name,
                'item_code': usage.item.code,
                'portions': count,
                'quantity_per_serving': usage.quantity_per_serving,
                'total_needed': total_needed,
                'current_quantity': current_quantity,
                'status': status
            })
    
    return render_template('warehouse/forecast.html', forecast_data=forecast_data)

@app.route('/warehouse/reports')
@login_required
@warehouse_manager_required
def warehouse_reports():
    """گزارش‌های انبار"""
    # دریافت لیست کالاها برای فیلتر کردن
    items = InventoryItem.query.all()
    
    # دریافت دسته‌بندی‌ها برای فیلتر کردن
    categories = set()
    for item in items:
        if item.category:
            categories.add(item.category)
    
    return render_template('warehouse/reports.html', items=items, categories=sorted(list(categories)))

@app.route('/warehouse/reports/generate', methods=['POST'])
@login_required
@warehouse_manager_required
def warehouse_generate_report():
    """تولید گزارش انبار"""
    if request.method == 'POST':
        report_type = request.form.get('report_type')
        date_from = request.form.get('date_from')
        date_to = request.form.get('date_to')
        item_id = request.form.get('item_id')
        category = request.form.get('category')
        
        if report_type == 'inventory':
            # گزارش موجودی انبار
            query = InventoryItem.query
            
            # اعمال فیلترها
            if item_id and item_id != 'all':
                query = query.filter(InventoryItem.id == int(item_id))
            if category and category != 'all':
                query = query.filter(InventoryItem.category == category)
            
            items = query.all()
            
            # تولید فایل PDF
            now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"inventory_report_{now}.pdf"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            generate_inventory_report_pdf(items, filepath)
            
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif report_type == 'transactions':
            # گزارش تراکنش‌های انبار
            query = InventoryTransaction.query
            
            # اعمال فیلترها
            if date_from:
                try:
                    from_date = datetime.datetime.strptime(date_from, '%Y-%m-%d')
                    query = query.filter(InventoryTransaction.timestamp >= from_date)
                except ValueError:
                    flash('فرمت تاریخ شروع نامعتبر است', 'danger')
                    return redirect(url_for('warehouse_reports'))
            
            if date_to:
                try:
                    to_date = datetime.datetime.strptime(date_to, '%Y-%m-%d')
                    to_date = to_date.replace(hour=23, minute=59, second=59)
                    query = query.filter(InventoryTransaction.timestamp <= to_date)
                except ValueError:
                    flash('فرمت تاریخ پایان نامعتبر است', 'danger')
                    return redirect(url_for('warehouse_reports'))
            
            if item_id and item_id != 'all':
                query = query.filter(InventoryTransaction.item_id == int(item_id))
            
            transactions = query.order_by(InventoryTransaction.timestamp.desc()).all()
            
            # تولید فایل PDF
            now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"transactions_report_{now}.pdf"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            generate_transaction_report_pdf(transactions, filepath, date_from, date_to)
            
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif report_type == 'forecast':
            # گزارش پیش‌بینی مصرف مواد غذایی
            # دریافت رزروهای فعلی برای پیش‌بینی مصرف مواد اولیه
            reservations = Reservation.query.filter_by(delivered=0).all()
            
            # جمع‌آوری تعداد رزرو هر غذا
            food_counts = {}
            for reservation in reservations:
                if reservation.food_name in food_counts:
                    food_counts[reservation.food_name] += 1
                else:
                    food_counts[reservation.food_name] = 1
            
            # محاسبه مصرف پیش‌بینی شده مواد اولیه
            forecast_data = []
            
            for food_name, count in food_counts.items():
                # دریافت دستورات پخت این غذا
                usages = FoodInventoryUsage.query.filter_by(food_name=food_name).all()
                
                for usage in usages:
                    # محاسبه مقدار مصرف کل
                    total_needed = usage.quantity_per_serving * count
                    
                    # بررسی موجودی فعلی
                    current_quantity = usage.item.quantity
                    
                    # تعیین وضعیت
                    status = "ok"
                    if current_quantity < total_needed:
                        status = "critical"
                    elif current_quantity < (total_needed * 1.2):  # کمتر از 20% بیشتر از نیاز
                        status = "warning"
                    
                    forecast_data.append({
                        'food_name': food_name,
                        'item_name': usage.item.name,
                        'item_code': usage.item.code,
                        'portions': count,
                        'quantity_per_serving': usage.quantity_per_serving,
                        'total_needed': total_needed,
                        'current_quantity': current_quantity,
                        'status': status
                    })
            
            # تولید فایل PDF
            now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"forecast_report_{now}.pdf"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            generate_food_usage_forecast_pdf(forecast_data, filepath)
            
            return send_file(filepath, as_attachment=True, download_name=filename)
        
        flash('نوع گزارش نامعتبر است', 'danger')
        return redirect(url_for('warehouse_reports'))
    
    return redirect(url_for('warehouse_reports'))

# ----- روت‌های دسترسی مدیر به انبار -----

# این روت به دلیل تکراری بودن با روت دیگری در انتهای فایل به طور موقت غیرفعال شده است
# @app.route('/admin/warehouse')
# @login_required
# def admin_warehouse_old():
#     """مدیریت انبار - دسترسی مدیر"""
#     if not current_user.is_admin:
#         flash('شما دسترسی به این بخش را ندارید', 'danger')
#         return redirect(url_for('dashboard'))
#     
#     # دریافت آمار کلی انبار
#     total_items = InventoryItem.query.count()
#     low_stock_items = InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.min_quantity).all()
#     
#     return render_template('admin/warehouse.html',
#                         total_items=total_items,
#                         low_stock_items=low_stock_items)

@app.route('/admin/warehouse/create-account', methods=['GET', 'POST'])
@login_required
def admin_create_warehouse_account():
    """ایجاد حساب کاربری انباردار توسط مدیر"""
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # بررسی وجود فیلدهای اجباری
        if not all([username, password, confirm_password]):
            flash('لطفاً تمام فیلدها را تکمیل کنید', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        # بررسی تطابق رمز عبور
        if password != confirm_password:
            flash('رمز عبور و تأیید آن مطابقت ندارند', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        # بررسی تکراری نبودن نام کاربری
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('این نام کاربری قبلاً در سیستم ثبت شده است', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        # ایجاد حساب کاربری انباردار
        warehouse_user = User(
            username=username,
            password=generate_password_hash(password)
        )
        
        db.session.add(warehouse_user)
        db.session.commit()
        
        flash(f'حساب کاربری انباردار با نام کاربری «{username}» با موفقیت ایجاد شد', 'success')
        return redirect(url_for('admin_warehouse'))
    
    return render_template('admin/create_warehouse_account.html')

@app.route('/admin/users')
@login_required
def admin_users():
    """مدیریت کاربران سیستم"""
    # فقط کاربر با نقش مدیر می‌تواند به این صفحه دسترسی داشته باشد
    if not current_user.is_admin:
        flash('شما دسترسی لازم برای این صفحه را ندارید.', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت تمام کاربران از دیتابیس
    users = User.query.all()
    
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/change-role/<int:user_id>', methods=['POST'])
@login_required
def admin_change_user_role(user_id):
    """تغییر نقش کاربر"""
    # فقط کاربر با نقش مدیر می‌تواند به این صفحه دسترسی داشته باشد
    if not current_user.is_admin:
        flash('شما دسترسی لازم برای این عملیات را ندارید.', 'danger')
        return redirect(url_for('dashboard'))
    
    # بررسی درخواست
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    
    # بررسی معتبر بودن نقش
    if new_role not in ['admin', 'warehouse_manager', 'student']:
        flash('نقش انتخاب شده معتبر نیست.', 'danger')
        return redirect(url_for('admin_users'))
    
    # به‌روزرسانی نقش کاربر
    user.role = new_role
    db.session.commit()
    
    flash(f'نقش کاربر {user.username} با موفقیت به {new_role} تغییر یافت.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/create', methods=['POST'])
@login_required
def admin_create_user():
    """ایجاد کاربر جدید"""
    # فقط کاربر با نقش مدیر می‌تواند به این صفحه دسترسی داشته باشد
    if not current_user.is_admin:
        flash('شما دسترسی لازم برای این عملیات را ندارید.', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت اطلاعات کاربر جدید
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')
    
    # بررسی اطلاعات وارد شده
    if not username or not password:
        flash('نام کاربری و رمز عبور الزامی هستند.', 'danger')
        return redirect(url_for('admin_users'))
    
    # بررسی معتبر بودن نقش
    if role not in ['admin', 'warehouse_manager', 'student']:
        flash('نقش انتخاب شده معتبر نیست.', 'danger')
        return redirect(url_for('admin_users'))
    
    # بررسی تکراری نبودن نام کاربری
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash('این نام کاربری قبلاً استفاده شده است.', 'danger')
        return redirect(url_for('admin_users'))
    
    # ایجاد کاربر جدید
    hashed_password = generate_password_hash(password)
    new_user = User()
    new_user.username = username
    new_user.password = hashed_password
    new_user.role = role
    
    db.session.add(new_user)
    db.session.commit()
    
    flash(f'کاربر {username} با نقش {role} با موفقیت ایجاد شد.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/reports')
@login_required
def admin_reports():
    if not current_user.is_admin:
        flash('شما دسترسی به این بخش را ندارید', 'danger')
        return redirect(url_for('dashboard'))
    
    # به‌روزرسانی بدهی همه دانشجویان و آمار مالی قبل از نمایش گزارش‌ها
    update_financial_statistics()
    
    # جمع‌آوری آمار برای غذاهای پرطرفدار
    food_stats = db.session.query(
        Reservation.food_name, 
        db.func.count(Reservation.id).label('count')
    ).group_by(Reservation.food_name).order_by(db.func.count(Reservation.id).desc()).limit(5).all()
    
    # محاسبه درصد برای هر غذا
    total_reservations = Reservation.query.count()
    popular_foods = []
    for food_name, count in food_stats:
        percentage = (count / total_reservations * 100) if total_reservations > 0 else 0
        popular_foods.append({
            'name': food_name,
            'count': count,
            'percentage': percentage
        })
    
    # آمار رزروها بر اساس روزهای هفته
    # استفاده از OrderedDict برای حفظ ترتیب روزها (شنبه در ابتدا)
    days = OrderedDict([
        ("saturday", "شنبه"),
        ("sunday", "یکشنبه"),
        ("monday", "دوشنبه"),
        ("tuesday", "سه‌شنبه"),
        ("wednesday", "چهارشنبه"),
        ("thursday", "پنج‌شنبه"),
        ("friday", "جمعه")
    ])
    
    # مرتب‌سازی ترتیب روزهای هفته (شنبه در ابتدا)
    day_order = OrderedDict([
        ("saturday", 0),
        ("sunday", 1),
        ("monday", 2),
        ("tuesday", 3),
        ("wednesday", 4),
        ("thursday", 5),
        ("friday", 6)
    ])
    
    # آمار ترکیبی روز و وعده‌های غذایی
    day_meal_stats = db.session.query(
        Reservation.day,
        Reservation.meal,
        db.func.count(Reservation.id).label('count')
    ).group_by(Reservation.day, Reservation.meal).all()
    
    # ساختار داده برای آمار روزانه به تفکیک وعده
    daily_meal_stats = {}
    for day_name in days.keys():
        daily_meal_stats[day_name] = {
            'day_name': days[day_name],
            'breakfast': 0,
            'lunch': 0,
            'dinner': 0,
            'total': 0
        }
    
    # پر کردن آمار روزانه به تفکیک وعده
    for day, meal, count in day_meal_stats:
        if day in daily_meal_stats:
            daily_meal_stats[day][meal] = count
            daily_meal_stats[day]['total'] += count
    
    # تبدیل دیکشنری به لیست برای استفاده در تمپلیت
    daily_stats_detail = []
    for day, stats in daily_meal_stats.items():
        daily_stats_detail.append(stats)
    
    # مرتب‌سازی بر اساس ترتیب روزهای هفته
    day_name_to_key = {value: key for key, value in days.items()}
    daily_stats_detail.sort(key=lambda x: day_order.get(day_name_to_key.get(x['day_name'], ''), 7))
    
    # آمار کلی روزهای هفته برای نمودار اصلی
    day_stats = db.session.query(
        Reservation.day, 
        db.func.count(Reservation.id).label('count')
    ).group_by(Reservation.day).all()
    
    daily_stats = []
    for day, count in day_stats:
        percentage = (count / total_reservations * 100) if total_reservations > 0 else 0
        daily_stats.append({
            'day': day,
            'day_name': days.get(day, day),  # نام فارسی روز
            'count': count,
            'percentage': percentage
        })
    
    # مرتب‌سازی بر اساس ترتیب روزهای هفته
    daily_stats.sort(key=lambda x: day_order.get(x['day'], 7))
    
    # آمار وعده‌های غذایی
    meal_stats_data = db.session.query(
        Reservation.meal, 
        db.func.count(Reservation.id).label('count')
    ).group_by(Reservation.meal).all()
    
    meal_stats = []
    for meal, count in meal_stats_data:
        percentage = (count / total_reservations * 100) if total_reservations > 0 else 0
        meal_stats.append({
            'meal': meal,
            'count': count,
            'percentage': percentage
        })
    
    # آمار مالی - محاسبه هزینه‌ها
    delivered_price = db.session.query(db.func.sum(Reservation.food_price)).filter_by(delivered=1).scalar() or 0
    pending_price = db.session.query(db.func.sum(Reservation.food_price)).filter_by(delivered=0).scalar() or 0
    total_price = delivered_price + pending_price
    
    # اطلاعات آماری مالی
    financial_stats = {
        'delivered_price': delivered_price,
        'pending_price': pending_price,
        'total_price': total_price,
        'delivered_percentage': (delivered_price / total_price * 100) if total_price > 0 else 0,
        'pending_percentage': (pending_price / total_price * 100) if total_price > 0 else 0,
    }
    
    # آمار مالی به تفکیک وعده‌های غذایی
    financial_meal_stats_data = db.session.query(
        Reservation.meal,
        db.func.sum(Reservation.food_price).label('price')
    ).group_by(Reservation.meal).all()
    
    financial_meal_stats = []
    for meal, price in financial_meal_stats_data:
        percentage = (price / total_price * 100) if total_price > 0 else 0
        financial_meal_stats.append({
            'meal': meal,
            'price': price,
            'percentage': percentage
        })
    
    # آمار مالی به تفکیک روز هفته
    financial_day_stats_data = db.session.query(
        Reservation.day,
        db.func.sum(Reservation.food_price).label('price')
    ).group_by(Reservation.day).all()
    
    financial_day_stats = []
    for day, price in financial_day_stats_data:
        percentage = (price / total_price * 100) if total_price > 0 else 0
        financial_day_stats.append({
            'day': day,
            'day_name': days.get(day, day),  # نام فارسی روز
            'price': price,
            'percentage': percentage
        })
    
    # مرتب‌سازی بر اساس ترتیب روزهای هفته
    financial_day_stats.sort(key=lambda x: day_order.get(x['day'], 7))
    
    return render_template('admin_reports.html', 
                           popular_foods=popular_foods,
                           daily_stats=daily_stats,
                           daily_stats_detail=daily_stats_detail,
                           meal_stats=meal_stats,
                           financial_stats=financial_stats,
                           financial_meal_stats=financial_meal_stats,
                           financial_day_stats=financial_day_stats)


@app.route('/admin/warehouse')
@login_required
def admin_warehouse():
    """مدیریت انبار - دسترسی مدیر"""
    if not current_user.is_admin:
        flash('شما دسترسی لازم برای این صفحه را ندارید.', 'danger')
        return redirect(url_for('dashboard'))
    
    # دریافت اطلاعات کلی انبار
    total_items = db.session.query(db.func.count(InventoryItem.id)).scalar() or 0
    
    # دریافت اقلامی که موجودی آنها کم است
    low_stock_items = db.session.query(InventoryItem).filter(
        InventoryItem.quantity <= InventoryItem.min_quantity
    ).order_by(
        # اول اقلام تمام شده، بعد اقلام با موجودی کم
        (InventoryItem.quantity == 0).desc(),
        (InventoryItem.quantity / InventoryItem.min_quantity).asc()
    ).all()
    
    return render_template('admin/warehouse.html', 
                          total_items=total_items, 
                          low_stock_items=low_stock_items)


# تابع زیر به دلیل تکراری بودن با تابع دیگری در خط 2234 غیرفعال شده است
# @app.route('/admin/create-warehouse-account', methods=['GET', 'POST'])
# @login_required
# def admin_create_warehouse_account_alt():
#     """ایجاد حساب کاربری انباردار توسط مدیر"""
#     if not current_user.is_admin:
#         flash('شما دسترسی لازم برای این صفحه را ندارید.', 'danger')
#         return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # بررسی صحت اطلاعات ورودی
        if not username or not password:
            flash('نام کاربری و رمز عبور الزامی هستند.', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        if password != confirm_password:
            flash('رمز عبور و تأیید آن مطابقت ندارند.', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        # بررسی وجود کاربر با همین نام کاربری
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('این نام کاربری قبلاً در سیستم ثبت شده است.', 'danger')
            return render_template('admin/create_warehouse_account.html')
        
        # ایجاد کاربر جدید
        new_user = User(
            username=username,
            password=generate_password_hash(password),
            role='warehouse_manager'  # نقش انباردار
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'حساب کاربری انباردار با نام کاربری {username} با موفقیت ایجاد شد.', 'success')
        return redirect(url_for('admin_warehouse'))
    
    return render_template('admin/create_warehouse_account.html')


if __name__ == '__main__':
    # به‌روزرسانی اولیه قیمت‌ها و آمار مالی
    with app.app_context():
        print("✓ به‌روزرسانی اولیه قیمت‌ها و آمار مالی قبل از شروع اپلیکیشن")
        update_financial_statistics()
    
    # شروع برنامه فلسک
    app.run(host='0.0.0.0', port=5000, debug=True)
