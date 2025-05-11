import json
import os
import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Text, Boolean, Float
from sqlalchemy.orm import relationship
from flask_login import UserMixin
from app import db, logger

class User(UserMixin, db.Model):
    """مدل کاربر برای احراز هویت و مدیریت دسترسی‌ها"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(256), nullable=False)
    # نقش کاربر: admin (مدیر)، warehouse_manager (انباردار)، student (دانشجو)
    role = Column(String(20), default='student', nullable=False)
    # میتوانیم بعدا این موارد را اضافه کنیم
    # email = Column(String(120), unique=True, nullable=False)
    # password_hash = Column(String(256), nullable=False)
    # is_admin = Column(Boolean, default=False)  # آیا کاربر مدیر سیستم است؟
    # created_at = Column(DateTime, default=datetime.datetime.utcnow)

    @property
    def is_admin(self):
        # کاربر با نقش admin به عنوان مدیر در نظر گرفته می‌شود
        return self.role == 'admin' or self.username == 'admin'
        
    @property
    def is_warehouse_manager(self):
        # کاربر با نقش warehouse_manager به عنوان انباردار در نظر گرفته می‌شود
        return self.role == 'warehouse_manager' or self.is_admin
    
    def __repr__(self):
        return f"<User(username='{self.username}')>"

class Student(db.Model):
    """مدل دانشجو برای ذخیره‌سازی اطلاعات کاربران"""
    __tablename__ = 'students'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), unique=True, nullable=False)  # ارتباط با کاربر
    feeding_code = Column(String(20), unique=True, nullable=False)  # کد تغذیه دانشجویی
    credit = Column(Float, default=0.0)  # اعتبار حساب دانشجو (به تومان)
    debt = Column(Float, default=0.0)  # بدهی دانشجو (به تومان)
    
    # ارتباط با رزروها
    reservations = relationship("Reservation", back_populates="student", cascade="all, delete-orphan")
    
    # ارتباط با پرداخت‌ها
    payments = relationship("Payment", back_populates="student")
    
    def __repr__(self):
        return f"<Student(user_id='{self.user_id}', feeding_code='{self.feeding_code}')>"

class Reservation(db.Model):
    """مدل رزرو برای ذخیره‌سازی رزروهای غذا"""
    __tablename__ = 'reservations'
    
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    day = Column(String(20), nullable=False)  # روز هفته
    meal = Column(String(20), nullable=False)  # وعده غذایی
    food_name = Column(String(100), nullable=False)  # نام غذا
    food_price = Column(Float, default=0.0)  # قیمت غذا (به تومان)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    delivered = Column(Integer, default=0)  # وضعیت تحویل: 0=تحویل نشده، 1=تحویل شده
    
    # ارتباط با دانشجو
    student = relationship("Student", back_populates="reservations")
    
    def __repr__(self):
        return f"<Reservation(student_id={self.student_id}, day='{self.day}', meal='{self.meal}', food_name='{self.food_name}')>"

class Menu(db.Model):
    """مدل منو برای ذخیره‌سازی منوی غذایی هفتگی"""
    __tablename__ = 'menu'
    
    id = Column(Integer, primary_key=True)
    day = Column(String(20), unique=True, nullable=False)  # روز هفته
    meal_data = Column(JSON, nullable=False)  # دیکشنری وعده‌های غذایی
    
    def __repr__(self):
        return f"<Menu(day='{self.day}')>"

class Payment(db.Model):
    """مدل پرداخت برای ذخیره‌سازی تراکنش‌های مالی"""
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    amount = Column(Float, nullable=False)  # مبلغ پرداخت به تومان
    description = Column(Text, nullable=True)  # توضیحات پرداخت
    authority = Column(String(128), nullable=True)  # شناسه ارجاع به درگاه پرداخت
    ref_id = Column(String(128), nullable=True)  # شناسه پیگیری درگاه پرداخت
    status = Column(String(20), default='pending')  # وضعیت پرداخت: pending, success, failed
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    reservation_ids = Column(Text, nullable=True)  # شناسه‌های رزروهای مرتبط با این پرداخت (به صورت comma-separated)
    
    # ارتباط با دانشجو
    student = relationship("Student", back_populates="payments")
    
    def __repr__(self):
        return f"<Payment(student_id={self.student_id}, amount={self.amount}, status='{self.status}')>"

class Notification(db.Model):
    """مدل اعلان‌ها برای اطلاع‌رسانی به کاربران"""
    __tablename__ = 'notifications'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False)  # وضعیت خوانده شدن: False=خوانده نشده، True=خوانده شده
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
    # ارتباط با کاربر
    user = relationship("User", backref=db.backref('notifications', lazy=True))
    
    def __repr__(self):
        return f"<Notification(user_id={self.user_id}, title='{self.title}', read={self.read})>"

class DatabaseBackup(db.Model):
    """مدل پشتیبان‌گیری از دیتابیس"""
    __tablename__ = 'backups'
    
    id = Column(Integer, primary_key=True)
    filename = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f"<DatabaseBackup(filename='{self.filename}', timestamp='{self.timestamp}')>"

class InventoryItem(db.Model):
    """مدل اقلام انبار"""
    __tablename__ = 'inventory_items'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)  # کد محصول
    name = Column(String(100), nullable=False)  # نام محصول
    category = Column(String(50), nullable=True)  # دسته‌بندی محصول
    unit = Column(String(20), nullable=False)  # واحد شمارش (عدد، کیلوگرم، بسته و غیره)
    quantity = Column(Integer, default=0)  # موجودی فعلی
    min_quantity = Column(Integer, default=5)  # حداقل موجودی مجاز
    description = Column(Text, nullable=True)  # توضیحات محصول
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # ارتباط با تراکنش‌ها
    transactions = db.relationship('InventoryTransaction', back_populates='item', cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<InventoryItem(code='{self.code}', name='{self.name}', quantity={self.quantity})>"
        
    @property
    def status(self):
        """وضعیت موجودی: normal (عادی), low (کم), out (ناموجود)"""
        if self.quantity <= 0:
            return "out"
        elif self.quantity <= self.min_quantity:
            return "low"
        else:
            return "normal"

class InventoryTransaction(db.Model):
    """مدل تراکنش‌های انبار"""
    __tablename__ = 'inventory_transactions'
    
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey('inventory_items.id'), nullable=False)
    transaction_type = Column(String(20), nullable=False)  # نوع تراکنش: add (افزایش), remove (کاهش), adjust (تنظیم)
    quantity = Column(Integer, nullable=False)  # مقدار تراکنش
    previous_quantity = Column(Integer, nullable=False)  # موجودی قبل از تراکنش
    current_quantity = Column(Integer, nullable=False)  # موجودی بعد از تراکنش
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)  # کاربر انجام دهنده تراکنش
    notes = Column(Text, nullable=True)  # توضیحات تراکنش
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    
    # ارتباط با محصول و کاربر
    item = db.relationship('InventoryItem', back_populates='transactions')
    user = db.relationship('User')
    
    def __repr__(self):
        return f"<InventoryTransaction(item_id={self.item_id}, type='{self.transaction_type}', quantity={self.quantity})>"

class FoodInventoryUsage(db.Model):
    """مدل ارتباطی بین غذاها و اقلام انبار (مصرف مواد اولیه)"""
    __tablename__ = 'food_inventory_usage'
    
    id = Column(Integer, primary_key=True)
    food_name = Column(String(100), nullable=False)  # نام غذا
    item_id = Column(Integer, ForeignKey('inventory_items.id'), nullable=False)  # شناسه قلم انبار
    quantity_per_serving = Column(Float, nullable=False)  # مقدار مصرف هر پرس
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # ارتباط با قلم انبار
    item = db.relationship('InventoryItem')
    
    def __repr__(self):
        return f"<FoodInventoryUsage(food_name='{self.food_name}', item_id={self.item_id}, quantity_per_serving={self.quantity_per_serving})>"

def init_db():
    """تابع راه‌اندازی اولیه دیتابیس"""
    return db.session

def load_default_menu(db_session):
    """بارگذاری منوی پیش‌فرض به دیتابیس"""
    # بررسی اینکه آیا منو قبلاً بارگذاری شده است
    if db_session.query(Menu).count() == 0:
        # استفاده از OrderedDict برای تضمین ترتیب درست روزها (شنبه در ابتدا)
        from collections import OrderedDict
        
        # منوی پیش‌فرض
        default_menu = OrderedDict([
            ("saturday", {
                "breakfast": [
                    {"name": "نان و پنیر و گردو", "price": 15000},
                    {"name": "املت", "price": 20000},
                    {"name": "نیمرو", "price": 18000}
                ],
                "lunch": [
                    {"name": "چلو کباب کوبیده", "price": 45000},
                    {"name": "قیمه", "price": 35000},
                    {"name": "قورمه سبزی", "price": 38000}
                ],
                "dinner": [
                    {"name": "ماکارونی", "price": 32000},
                    {"name": "عدس پلو", "price": 30000},
                    {"name": "کتلت", "price": 35000}
                ]
            }),
            ("sunday", {
                "breakfast": [
                    {"name": "نان و پنیر و خرما", "price": 16000},
                    {"name": "تخم مرغ آبپز", "price": 18000},
                    {"name": "حلیم", "price": 25000}
                ],
                "lunch": [
                    {"name": "زرشک پلو با مرغ", "price": 48000},
                    {"name": "خورشت بادمجان", "price": 36000},
                    {"name": "کوکو سبزی", "price": 32000}
                ],
                "dinner": [
                    {"name": "چلو کباب جوجه", "price": 50000},
                    {"name": "خوراک لوبیا", "price": 30000},
                    {"name": "استانبولی پلو", "price": 33000}
                ]
            }),
            ("monday", {
                "breakfast": [
                    {"name": "نان و کره و مربا", "price": 16000},
                    {"name": "نان و تخم مرغ", "price": 20000},
                    {"name": "شیر و غلات", "price": 22000}
                ],
                "lunch": [
                    {"name": "چلو خورشت قیمه", "price": 38000},
                    {"name": "کوبیده", "price": 45000},
                    {"name": "فسنجان", "price": 42000}
                ],
                "dinner": [
                    {"name": "خوراک مرغ", "price": 40000},
                    {"name": "کشک و بادمجان", "price": 32000},
                    {"name": "کوفته تبریزی", "price": 35000}
                ]
            }),
            ("tuesday", {
                "breakfast": [
                    {"name": "نان و پنیر و سبزی", "price": 17000},
                    {"name": "املت", "price": 20000},
                    {"name": "عدسی", "price": 22000}
                ],
                "lunch": [
                    {"name": "چلو کباب بختیاری", "price": 55000},
                    {"name": "چلو خورشت سبزی", "price": 40000},
                    {"name": "کوکو سیب زمینی", "price": 30000}
                ],
                "dinner": [
                    {"name": "الویه", "price": 35000},
                    {"name": "میرزا قاسمی", "price": 32000},
                    {"name": "حلیم بادمجان", "price": 34000}
                ]
            }),
            ("wednesday", {
                "breakfast": [
                    {"name": "نان و پنیر و گردو", "price": 15000},
                    {"name": "تخم مرغ نیمرو", "price": 18000},
                    {"name": "آش", "price": 25000}
                ],
                "lunch": [
                    {"name": "چلو جوجه کباب", "price": 50000},
                    {"name": "چلو قورمه سبزی", "price": 38000},
                    {"name": "دلمه برگ مو", "price": 36000}
                ],
                "dinner": [
                    {"name": "کتلت", "price": 35000},
                    {"name": "عدس پلو", "price": 30000},
                    {"name": "ماکارونی", "price": 32000}
                ]
            }),
            ("thursday", {
                "breakfast": [
                    {"name": "نان و مربا و کره", "price": 16000},
                    {"name": "نیمرو", "price": 18000},
                    {"name": "آش رشته", "price": 25000}
                ],
                "lunch": [
                    {"name": "چلو کباب کوبیده", "price": 45000},
                    {"name": "چلو خورشت قیمه", "price": 38000},
                    {"name": "کباب تابه ای", "price": 40000}
                ],
                "dinner": [
                    {"name": "خوراک مرغ", "price": 40000},
                    {"name": "کوکو سبزی", "price": 32000},
                    {"name": "خوراک لوبیا", "price": 30000}
                ]
            }),
            ("friday", {
                "breakfast": [
                    {"name": "نان و کره و مربا", "price": 16000},
                    {"name": "نان و پنیر", "price": 15000},
                    {"name": "آش", "price": 25000}
                ],
                "lunch": [
                    {"name": "استانبولی پلو", "price": 33000},
                    {"name": "عدس پلو", "price": 30000},
                    {"name": "کباب تابه ای", "price": 40000}
                ],
                "dinner": [
                    {"name": "چلو کباب", "price": 45000},
                    {"name": "املت", "price": 20000},
                    {"name": "سالاد الویه", "price": 35000}
                ]
            })
        ])
        
        # افزودن منوی پیش‌فرض به دیتابیس
        for day, meals in default_menu.items():
            menu_item = Menu(day=day, meal_data=meals)
            db_session.add(menu_item)
        
        db_session.commit()
        logger.info("منوی پیش‌فرض با موفقیت بارگذاری شد.")
        
        # ایجاد یک کاربر مدیر پیش‌فرض
        from werkzeug.security import generate_password_hash
        admin_exists = db_session.query(User).filter_by(username='admin').first()
        if not admin_exists:
            admin_user = User(
                username='admin',
                password=generate_password_hash('admin123')
            )
            db_session.add(admin_user)
            db_session.commit()
            logger.info("کاربر مدیر با موفقیت ایجاد شد.")

def migrate_from_json_to_db(json_file, db_session):
    """مهاجرت داده‌ها از فایل JSON به دیتابیس"""
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for user_id, user_data in data.items():
                # بررسی وجود دانشجو در دیتابیس
                student = db_session.query(Student).filter_by(user_id=user_id).first()
                if not student:
                    # ایجاد دانشجوی جدید
                    student = Student(user_id=user_id, feeding_code=user_data.get('feeding_code', ''))
                    db_session.add(student)
                    db_session.flush()  # دریافت شناسه دانشجوی جدید
                
                # افزودن رزروها
                if 'reservations' in user_data:
                    for reservation_data in user_data['reservations']:
                        # بررسی وجود رزرو مشابه
                        existing_reservation = db_session.query(Reservation).filter_by(
                            student_id=student.id,
                            day=reservation_data['day'],
                            meal=reservation_data['meal']
                        ).first()
                        
                        if not existing_reservation:
                            reservation = Reservation(
                                student_id=student.id,
                                day=reservation_data['day'],
                                meal=reservation_data['meal'],
                                food_name=reservation_data['food_name'],
                                delivered=reservation_data.get('delivered', 0)
                            )
                            db_session.add(reservation)
            
            db_session.commit()
            logger.info(f"داده‌ها از فایل {json_file} با موفقیت به دیتابیس منتقل شدند.")
            
            # تغییر نام فایل JSON پس از مهاجرت موفق
            os.rename(json_file, f"{json_file}.migrated_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"خطا در مهاجرت داده‌ها: {str(e)}")
