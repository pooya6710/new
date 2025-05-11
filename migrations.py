"""
این فایل برای مهاجرت از دیتابیس SQLite به PostgreSQL استفاده می‌شود
"""
import logging
import os
from app import app, db
from models import User, Student, Reservation, Menu, Payment, Notification, DatabaseBackup, init_db

logger = logging.getLogger(__name__)

def migrate_to_postgresql():
    """
    مهاجرت داده‌ها از دیتابیس SQLite به PostgreSQL
    """
    try:
        # بررسی اینکه آیا متغیر محیطی DATABASE_URL تنظیم شده‌است
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            logger.error("متغیر محیطی DATABASE_URL تنظیم نشده است.")
            return False
        
        # بررسی اینکه آیا دیتابیس PostgreSQL است
        if not (database_url.startswith('postgres://') or database_url.startswith('postgresql://')):
            logger.error(f"دیتابیس مقصد PostgreSQL نیست: {database_url}")
            return False
        
        with app.app_context():
            # اطمینان از وجود جداول در PostgreSQL
            db.create_all()
            logger.info("جداول با موفقیت در PostgreSQL ایجاد شدند.")
            
            # بارگذاری منوی پیش‌فرض اگر خالی است
            from models import load_default_menu
            load_default_menu(db.session)
            logger.info("منوی پیش‌فرض با موفقیت بارگذاری شد.")
            
            # ایجاد کاربر مدیر اگر وجود ندارد
            from create_admin import create_admin_user
            create_admin_user()
            logger.info("کاربر مدیر بررسی شد.")
        
        logger.info("مهاجرت به PostgreSQL با موفقیت انجام شد.")
        return True
    
    except Exception as e:
        logger.error(f"خطا در مهاجرت به PostgreSQL: {str(e)}")
        return False

if __name__ == "__main__":
    # تنظیم لاگر
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                      level=logging.INFO)
    
    # اجرای مهاجرت
    result = migrate_to_postgresql()
    
    if result:
        print("مهاجرت به PostgreSQL با موفقیت انجام شد.")
    else:
        print("خطا در مهاجرت به PostgreSQL. به لاگ‌ها مراجعه کنید.")